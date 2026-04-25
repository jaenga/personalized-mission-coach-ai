import time
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from database import (
    init_db, assign_daily_missions, _kst_today,
    get_student_by_credentials, create_chat_session,
    save_profile, fetch_profile,
    save_message, fetch_messages, delete_messages,
    get_student_mission_db, get_student_info_db,
    save_mission_result, mark_synced, cancel_last_action,
    get_user_history_db, has_checkin_today,
    find_adjusted_mission, save_mission_adjustment,
    get_last_action_type,
)
from ollama_client import generate_chat_message, generate_chat_message_stream, OLLAMA_MODEL
from prompts import build_chat_system_prompt
from rag import search_rag, preload_model
from sheets import detect_mission_status, update_mission_result, cancel_mission_result, generate_daily_status
from intent_router import classify_intent, split_multi_intent
from category_prompts import get_category_equivalency_prompt
from qwen_client import call_function, preload_qwen

# ── 펑션별 Gemma 힌트 ──────────────────────────────────────────────────────────

def _build_fn_hint(detected_function: str, fn_args: dict) -> str:
    if detected_function == "submit_mission_result":
        result_kor = {"success": "결과: 완료.", "fail": "결과: 수행 실패."}.get(fn_args.get("result_type", ""), "")
        return f"아이가 미션 결과를 제출했어. {result_kor} 자연스럽게 받아주고 기록됐다고 알려줘."
    if detected_function == "get_mission_info":
        return {
            "today": "아이가 오늘 미션 내용을 물어봤어. 오늘 미션을 친절하게 안내해줘.",
            "deadline": "아이가 제출 마감 시간을 물어봤어. 마감 시간을 안내해줘.",
            "general_rule": "아이가 앱 규칙을 물어봤어. 제출·인증·판정 규칙을 안내해줘.",
        }.get(fn_args.get("query_type", ""), "아이가 미션 정보를 물어봤어. 친절하게 안내해줘.")
    if detected_function == "request_mission_adjustment":
        return {
            "change": "아이가 다른 미션으로 바꿔달라고 했어. 요청을 접수했다고 알려줘.",
            "easier": "아이가 더 쉬운 미션을 요청했어. 요청을 접수했다고 알려줘.",
            "harder": "아이가 더 어려운 미션을 요청했어. 요청을 접수했다고 알려줘.",
        }.get(fn_args.get("adjustment_type", ""), "아이가 미션 조정을 요청했어. 요청을 접수했다고 알려줘.")
    if detected_function == "check_mission_equivalency":
        return {
            "behavior": "아이가 다른 행동으로 수행해도 되는지 물어봤어. 대체 수행 가능 여부를 안내해줘.",
            "place": "아이가 다른 장소에서 수행해도 되는지 물어봤어. 대체 수행 가능 여부를 안내해줘.",
            "time": "아이가 다른 시간에 수행해도 되는지 물어봤어. 대체 수행 가능 여부를 안내해줘.",
        }.get(fn_args.get("equivalency_type", ""), "아이가 대체 수행 가능 여부를 물어봤어. 친절하게 안내해줘.")
    if detected_function == "get_user_history":
        return {
            "weekly_summary": "아이가 이번 주 미션 기록을 조회했어. 주간 기록을 안내해줘.",
            "monthly_summary": "아이가 이번 달 미션 기록을 조회했어. 월간 기록을 안내해줘.",
        }.get(fn_args.get("query_type", ""), "아이가 미션 기록을 조회했어. 기록을 안내해줘.")
    if detected_function == "cancel_mission_action":
        return "아이가 가장 최근 행동을 취소하려고 해. 취소됐다고 자연스럽게 알려줘."
    return f"아이가 '{detected_function}' 기능을 요청했어. 자연스럽게 응답해줘."


DEADLINE_TEXT = "밤 11시 (23:00)"

# GENERAL_RULE_TEXT 예상 답변 (Q. 앱 규칙이 뭔가요?)
# A. 미션은 오늘 밤 11시까지 하면 돼요. 다 했다면 "성공", "완료", "다 했어요"처럼 말해주면 기록할 수 있어요
GENERAL_RULE_TEXT = """
[앱 전체 미션 규칙]

- 미션은 당일 밤 11시까지 제출해야 해.
- 사진이나 영상 인증 없이, 채팅으로 완료 여부를 말하면 돼.
- "성공", "완료", "다 했어요", "했어요", "끝냈어요"는 완료 제출로 볼 수 있어.
- "못 했어요", "실패했어요", "안 했어요", "까먹었어요"는 미수행/실패 보고로 볼 수 있어.
- "조금 했어요", "반만 했어요", "거의 했어요"처럼 일부만 한 경우는 성공으로 처리하지 않아.
- 미션이 너무 어렵거나 안전상 하기 힘들면, 다른 미션이나 쉬운 미션으로 바꿔 달라고 요청할 수 있어.
- 아프거나 다쳤거나 위험한 상황이면 미션보다 안전이 먼저야.

아이에게 답할 때는 위 내용을 전부 나열하지 말고, 질문과 관련된 규칙만 2~3문장으로 쉽게 설명해.
""".strip()

# ── 멀티펑션 조합 분류 ──────────────────────────────────────────────────────────
_CONFLICT_PAIRS = [
    {"submit_mission_result", "request_mission_adjustment"},
    {"request_mission_adjustment", "check_mission_equivalency"},
]
_NON_REPEATABLE = {"submit_mission_result", "cancel_mission_action", "request_mission_adjustment"}

# 🟡 순차: (먼저 실행, 나중 실행) — 순서 고정
# get_mission_info는 query_type=="today"일 때만 순차 → _classify_multi에서 args 확인
_SEQUENTIAL_PAIRS = [
    ("check_mission_equivalency", "submit_mission_result"),   # equivalency → submit
    ("submit_mission_result", "get_user_history"),            # submit → history
]

# 🔀 DB분기: cancel + (submit | adjustment) — 직전 액션에 따라 순차 or 충돌
_DB_BRANCH_PAIRS = {
    frozenset({"cancel_mission_action", "submit_mission_result"}): "submit",
    frozenset({"cancel_mission_action", "request_mission_adjustment"}): "adjustment",
}


def _classify_multi(fn_calls: list[tuple[str, dict]]) -> str:
    """멀티펑션 조합 분류. 반환값: 'conflict' | 'sequential' | 'db_branch' | 'independent'"""
    names = [fn for fn, _ in fn_calls]

    # 같은 함수 중복 호출 → 충돌
    for name in _NON_REPEATABLE:
        if names.count(name) > 1:
            return "conflict"

    name_set = set(names)

    # 충돌 쌍 검사
    if any(pair.issubset(name_set) for pair in _CONFLICT_PAIRS):
        return "conflict"

    # DB분기 검사 (cancel이 먼저 올 때만 — "취소하고 다시 ~해줘")
    # cancel이 뒤에 오면 ("제출하고 취소해줘") 충돌
    if frozenset(name_set) in _DB_BRANCH_PAIRS:
        cancel_idx = next((i for i, n in enumerate(names) if n == "cancel_mission_action"), None)
        if cancel_idx == 0:
            return "db_branch"
        return "conflict"

    # 순차 검사 (고정 쌍)
    for first, second in _SEQUENTIAL_PAIRS:
        if first in name_set and second in name_set:
            return "sequential"

    # 순차 검사 (adjustment/cancel + get_mission_info(today))
    if "get_mission_info" in name_set:
        mission_info_args = next((args for fn, args in fn_calls if fn == "get_mission_info"), {})
        if mission_info_args.get("query_type") == "today":
            if "request_mission_adjustment" in name_set or "cancel_mission_action" in name_set:
                return "sequential"

    return "independent"


_FN_LABELS = {
    "submit_mission_result": "미션 결과 제출",
    "cancel_mission_action": "이전 행동 취소",
    "request_mission_adjustment": "미션 변경",
    "check_mission_equivalency": "대체 수행 확인",
}


def _build_conflict_prompt(fn_calls: list[tuple[str, dict]]) -> str:
    names = [_FN_LABELS.get(fn, fn) for fn, _ in fn_calls]
    return (
        f"\n\n아이가 '{names[0]}'하고 '{names[1]}'을 동시에 요청했어. "
        "둘을 한꺼번에 처리할 수 없어. "
        "아이가 둘 중 어떤 걸 원하는 건지 부드럽게 되물어봐."
    )


def _is_conflict(fn_calls: list[tuple[str, dict]]) -> bool:
    """하위 호환용 — 충돌 여부만 반환."""
    return _classify_multi(fn_calls) == "conflict"


def _build_adjustment_hint(student_id: int, fn_args: dict) -> str:
    adjustment_type = fn_args.get("adjustment_type", "change")
    today = _kst_today()
    current = get_student_mission_db(student_id, today)
    if not current:
        return "아이가 미션 조정을 요청했어. 오늘 배정된 미션이 없다고 알려줘."

    new_mission = find_adjusted_mission(student_id, adjustment_type, current["mission_id"])
    if not new_mission:
        label = {"easier": "더 쉬운", "harder": "더 어려운"}.get(adjustment_type, "다른")
        return f"아이가 {label} 미션을 요청했어. 같은 카테고리에 {label} 미션이 없어. 현재 미션을 계속하도록 안내해줘."

    save_mission_adjustment(student_id, current["mission_id"], new_mission["mission_id"])

    label = {"easier": "더 쉬운", "harder": "더 어려운"}.get(adjustment_type, "다른")
    lines = [f"아이가 {label} 미션으로 변경을 요청했어. 아래 새 미션으로 바뀌었다고 알려줘.\n"]
    lines.append(f"새 미션명: {new_mission['mission_name']}")
    if new_mission.get("mission_rule"):
        lines.append(f"수행 규칙: {new_mission['mission_rule']}")
    return "\n".join(lines)


def _reorder_sequential(fn_calls: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """순차 쌍이 있으면 올바른 실행 순서로 정렬."""
    if len(fn_calls) < 2:
        return fn_calls
    ordered = list(fn_calls)

    # 고정 순차 쌍 정렬
    for first, second in _SEQUENTIAL_PAIRS:
        first_idx = next((i for i, (fn, _) in enumerate(ordered) if fn == first), None)
        second_idx = next((i for i, (fn, _) in enumerate(ordered) if fn == second), None)
        if first_idx is not None and second_idx is not None and first_idx > second_idx:
            ordered[first_idx], ordered[second_idx] = ordered[second_idx], ordered[first_idx]

    # adjustment/cancel + get_mission_info(today) 정렬
    mi_idx = next((i for i, (fn, args) in enumerate(ordered)
                    if fn == "get_mission_info" and args.get("query_type") == "today"), None)
    if mi_idx is not None:
        for priority_fn in ("request_mission_adjustment", "cancel_mission_action"):
            p_idx = next((i for i, (fn, _) in enumerate(ordered) if fn == priority_fn), None)
            if p_idx is not None and p_idx > mi_idx:
                ordered[p_idx], ordered[mi_idx] = ordered[mi_idx], ordered[p_idx]
                break

    return ordered


def _build_submit_hint(student_id: int, fn_args: dict) -> str:
    """미션 결과를 DB에 저장하고 힌트 반환."""
    result_type = fn_args.get("result_type", "")
    today = _kst_today()
    mission = get_student_mission_db(student_id, today)
    if not mission:
        return "아이가 미션 결과를 제출했어. 오늘 배정된 미션이 없다고 알려줘."

    if has_checkin_today(student_id):
        result_kor = {"success": "완료", "fail": "수행 실패"}.get(result_type, "")
        return f"아이가 미션 결과를 제출했어. 결과: {result_kor}. 오늘 이미 제출한 기록이 있어. 자연스럽게 알려줘."

    save_mission_result(
        student_id=student_id,
        mission_id=mission["mission_id"],
        status=result_type,
        detected_function="submit_mission_result",
    )
    result_kor = {"success": "결과: 완료.", "fail": "결과: 수행 실패."}.get(result_type, "")
    return f"아이가 미션 결과를 제출했어. {result_kor} 자연스럽게 받아주고 기록됐다고 알려줘."


def _build_equivalency_hint(student_id: int, fn_args: dict) -> str:
    """대체 수행 판정 힌트 — 카테고리별 판정 기준 포함."""
    today = _kst_today()
    mission = get_student_mission_db(student_id, today)
    if not mission:
        return "아이가 대체 수행 가능 여부를 물어봤어. 오늘 배정된 미션이 없다고 알려줘."

    eq_type = fn_args.get("equivalency_type", "")
    type_label = {"behavior": "다른 행동", "place": "다른 장소", "time": "다른 시간"}.get(eq_type, "대체 수행")

    category_prompt = get_category_equivalency_prompt(
        mission.get("main_category"),
        mission.get("sub_category"),
    )

    lines = [
        f"아이가 {type_label}으로 수행해도 되는지 물어봤어.",
        f"아래 미션 정보와 판정 기준을 보고, 인정 가능 여부를 판단해서 답해줘.\n",
        f"미션명: {mission.get('mission_name', '')}",
    ]
    if mission.get("mission_rule"):
        lines.append(f"수행 규칙: {mission['mission_rule']}")
    lines.append(f"\n{category_prompt}")
    return "\n".join(lines)


def _build_one_hint(student_id: int, fn: str, args: dict) -> str:
    """단일 펑션에 대한 힌트 생성."""
    if fn == "get_user_history":
        return _build_history_hint(student_id, args)
    if fn == "get_mission_info":
        return _build_mission_info_hint(student_id, args)
    if fn == "request_mission_adjustment":
        return _build_adjustment_hint(student_id, args)
    if fn == "submit_mission_result":
        return _build_submit_hint(student_id, args)
    if fn == "check_mission_equivalency":
        return _build_equivalency_hint(student_id, args)
    return _build_fn_hint(fn, args)


def _is_equivalency_submit(fn_calls: list[tuple[str, dict]]) -> bool:
    """equivalency→submit 조합인지 확인."""
    names = {fn for fn, _ in fn_calls}
    return "check_mission_equivalency" in names and "submit_mission_result" in names


_EQUIVALENCY_SUBMIT_TAG_INSTRUCTION = """
===== 필수 태그 (반드시 지켜) =====
아이가 대체 수행이 인정되면 성공으로 제출하겠다고 했어.
너의 답변 텍스트 마지막 줄에 반드시 아래 태그 중 하나를 붙여.

인정 가능 → [APPROVED]
인정 불가 → [DENIED]

예시:
"좋아, 그것도 충분히 인정돼! 성공으로 기록했어! 😊
[APPROVED]"

"아쉽지만 이번에는 조금 달라서 인정이 어려워.
[DENIED]"
=================================
""".strip()


def _build_combined_hint(student_id: int, fn_calls: list[tuple[str, dict]]) -> str:
    """멀티펑션 힌트 — 순차 쌍은 순서 보장, 나머지는 그대로 실행."""
    ordered = _reorder_sequential(fn_calls)

    # equivalency→submit: submit은 DB 저장 안 하고 태그 지시만 추가
    if _is_equivalency_submit(fn_calls):
        hints = []
        for fn, args in ordered:
            if fn == "submit_mission_result":
                continue  # submit 힌트 스킵 (DB 저장 안 함)
            hints.append(_build_one_hint(student_id, fn, args))
        hints.append(_EQUIVALENCY_SUBMIT_TAG_INSTRUCTION)
        return "\n\n".join(hints)

    hints = [_build_one_hint(student_id, fn, args) for fn, args in ordered]
    return "\n\n".join(hints)


def _build_mission_info_hint(student_id: int, fn_args: dict) -> str:
    query_type = fn_args.get("query_type", "today")

    if query_type == "deadline":
        return f"아이가 제출 마감 시간을 물어봤어. 마감은 {DEADLINE_TEXT}이야. 친절하게 안내해줘."

    if query_type == "general_rule":
        return f"아이가 앱 규칙을 물어봤어. 아래 규칙을 친절하게 안내해줘.\n\n{GENERAL_RULE_TEXT}"

    # today: DB에서 오늘 미션 정보 가져와서 안내
    today = _kst_today()
    mission = get_student_mission_db(student_id, today)
    if not mission:
        return "아이가 오늘 미션을 물어봤어. 오늘 배정된 미션이 없어. 미션이 아직 배정되지 않았다고 알려줘."

    lines = ["아이가 오늘 미션 내용을 물어봤어. 아래 정보를 바탕으로 친절하게 안내해줘.\n"]
    lines.append(f"미션명: {mission.get('mission_name', '')}")
    if mission.get("mission_rule"):
        lines.append(f"수행 규칙: {mission['mission_rule']}")
    return "\n".join(lines)


def _build_history_hint(student_id: int, fn_args: dict) -> str:
    query_type = fn_args.get("query_type", "weekly_summary")
    period_name = "이번 주" if query_type == "weekly_summary" else "이번 달"

    result = get_user_history_db(student_id, query_type)
    records = result["records"]

    if not records:
        return f"아이가 {period_name} 미션 기록을 물어봤어. 아직 기록이 전혀 없어. 아직 미션을 수행한 기록이 없다고 따뜻하게 알려줘."

    success_count = sum(1 for r in records if r["mission_result"] == "success")

    fallback_notice = ""
    if result["fallback"]:
        fallback_notice = (
            f'"{period_name} 기준으로는 아직 기록이 없어요. '
            f'{result["fallback_label"]} 기록을 함께 보여드릴게요."라고 먼저 말하고 '
        )

    return (
        f"아이가 {period_name} 미션 기록을 물어봤어. "
        f"{fallback_notice}아래 내용을 바탕으로 친절하게 알려줘.\n\n"
        f"{result['period_label']} 성공 횟수: {success_count}회"
    )

app = FastAPI(title="AI 생활습관 코치 MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    preload_model()
    preload_qwen()
    try:
        assigned = assign_daily_missions()
        if assigned:
            print(f"[startup] 오늘 미션 배정: {assigned}명")
    except Exception as e:
        print(f"[startup] 미션 배정 실패 (무시): {e}")
    try:
        today = _kst_today()
        added = generate_daily_status(today)
        if added:
            print(f"[startup] daily_status {today}: {added}명 행 추가됨")
    except Exception as e:
        print(f"[startup] daily_status 생성 실패 (무시): {e}")


# ── 학생 본인 확인 ─────────────────────────────────────────────────────────────

class VerifyRequest(BaseModel):
    student_name: str = Field(..., min_length=1)
    phone_last4:  str = Field(..., min_length=4, max_length=4, pattern=r"^\d{4}$")


@app.post("/verify-student")
def post_verify_student(body: VerifyRequest):
    student = get_student_by_credentials(body.student_name, body.phone_last4)
    if not student:
        raise HTTPException(status_code=404, detail="일치하는 학생을 찾을 수 없어요.")
    return student


# ── 프로필 저장/조회 ───────────────────────────────────────────────────────────

class ProfileRequest(BaseModel):
    session_id:   str = Field(..., min_length=1)
    student_id:   int
    student_name: str = Field(..., min_length=1)


@app.post("/profile")
def post_profile(body: ProfileRequest):
    db_session_id = create_chat_session(body.student_id)
    save_profile(body.session_id, body.student_id, body.student_name, db_session_id)
    return {"ok": True}


@app.get("/profile/{session_id}")
def get_profile(session_id: str):
    profile = fetch_profile(session_id)
    if not profile:
        raise HTTPException(status_code=404, detail="프로필 없음")
    return profile


# ── 오늘 미션 조회 ─────────────────────────────────────────────────────────────

@app.get("/mission")
def get_mission(student_id: int | None = None):
    today = _kst_today()
    if student_id:
        mission = get_student_mission_db(student_id, today)
        if mission:
            return mission
    return {
        "mission_id": None,
        "mission_name": "오늘의 미션",
        "category": "",
        "difficulty": "",
        "status": "assigned",
    }


# ── 금지어 감지 ────────────────────────────────────────────────────────────────

FORBIDDEN_WORDS = ["엄마", "아빠", "부모님", "가족", "형", "언니", "오빠", "동생", "친구", "선생님"]


def detect_violations(ai_message: str, user_input: str) -> list[str]:
    return [
        f"금지어 언급: '{w}' (사용자가 먼저 말하지 않음)"
        for w in FORBIDDEN_WORDS
        if w in ai_message and w not in user_input
    ]


# ── 배경 작업 ──────────────────────────────────────────────────────────────────

async def _cancel_sheet_bg(student_id: int, today: str):
    try:
        cancel_mission_result(student_id, today)
    except Exception as e:
        print(f"[cancel] 시트 초기화 실패: {e}")


async def _sync_sheet_bg(
    session_id: str,
    user_message: str,
    ai_message: str,
    status: str,
    detected_function: str,
):
    profile = fetch_profile(session_id)
    if not profile:
        return

    today = _kst_today()
    student_id = profile["student_id"]

    # DB에서 학생/미션 정보 가져오기
    student_info = get_student_info_db(student_id) or {}
    mission_info = get_student_mission_db(student_id, today) or {}

    mission_id = mission_info.get("mission_id")
    if not mission_id:
        print(f"[sync] mission_id 없음 — 시트 동기화 스킵 (student_id={student_id})")
        return

    # DB 저장: 힌트 빌드에서 이미 저장된 경우 스킵, 아니면 여기서 저장
    result_id = None
    if not has_checkin_today(student_id):
        result_id = save_mission_result(
            student_id=student_id,
            mission_id=mission_id,
            status=status,
            result_reason=user_message,
            detected_function=detected_function,
        )

    # 구글 시트 업데이트
    try:
        update_mission_result(
            student_id=student_id,
            today=today,
            result_reason=user_message,
            ai_response=ai_message,
            status=status,
            student_name=student_info.get("student_name", ""),
            age=student_info.get("age"),
            gender=student_info.get("gender", ""),
            location=student_info.get("location", ""),
            mission_id=mission_id,
            mission_name=mission_info.get("mission_name", ""),
            category=mission_info.get("category", ""),
            difficulty=mission_info.get("difficulty", ""),
        )
        if result_id is not None:
            mark_synced(result_id)
    except Exception:
        pass


# ── 채팅 ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:    str       = Field(..., min_length=1)
    session_id: str       = Field(..., min_length=1)
    mission:    str | None = None


@app.post("/chat")
async def post_chat(body: ChatRequest, background_tasks: BackgroundTasks):
    mission_title = body.mission or "오늘의 미션"
    is_greet = body.message == "__GREET__"

    intent = "A"
    detected_function = None
    fn_args: dict = {}
    rag_result: dict = {"chunks": [], "faqs": [], "context": ""}

    if not is_greet:
        # ── 1. Gemma4:e2b 인텐트 분류 ──────────────────────────────────────────
        intent = await classify_intent(body.message)

        # ── 2. 인텐트별 모듈 활성화 ────────────────────────────────────────────
        if intent == "B":
            # 멀티 의도 분리 → 각각 Qwen 호출
            parts = await split_multi_intent(body.message)
            fn_calls = []
            seen = set()
            for part in parts:
                calls, _ = call_function(part)
                for c in calls:
                    key = (c[0], tuple(sorted(c[1].items())))
                    if key not in seen:
                        fn_calls.append(c)
                        seen.add(key)
            detected_function = fn_calls[0][0] if fn_calls else None
            fn_args = fn_calls[0][1] if fn_calls else {}
            print(f"[Chat] B-route: calls={fn_calls}")

        elif intent == "C":
            # RAG 검색
            try:
                rag_result = search_rag(body.message)
            except Exception as e:
                print(f"[RAG] 검색 실패 (무시): {e}")

        # A, D: 추가 모듈 없음 — Gemma4 직접 응답

    # ── 3. 시스템 프롬프트 구성 ─────────────────────────────────────────────────
    system_prompt = build_chat_system_prompt(
        mission_title,
        rag_result["context"] if not is_greet else "",
    )

    if intent == "D":
        system_prompt += "\n\n아이의 말이 무슨 뜻인지 불분명해. 판단하지 말고 딱 한 문장으로 다시 물어봐."

    if intent == "B" and fn_calls:
        combo = _classify_multi(fn_calls)
        if combo == "conflict":
            system_prompt += _build_conflict_prompt(fn_calls)
        elif combo == "db_branch":
            profile = fetch_profile(body.session_id)
            if profile:
                last_action = get_last_action_type(profile["student_id"])
                name_set = frozenset(fn for fn, _ in fn_calls)
                expected = _DB_BRANCH_PAIRS.get(name_set)
                if last_action == expected:
                    cancel_last_action(profile["student_id"])
                    remaining = [(fn, args) for fn, args in fn_calls if fn != "cancel_mission_action"]
                    cancel_hint = "아이가 요청해서 직전 행동을 취소했어. "
                    rest_hint = _build_combined_hint(profile["student_id"], remaining)
                    system_prompt += f"\n\n{cancel_hint}{rest_hint}"
                else:
                    system_prompt += _build_conflict_prompt(fn_calls)
            else:
                for fn, args in fn_calls:
                    system_prompt += f"\n\n{_build_fn_hint(fn, args)}"
        else:
            profile = fetch_profile(body.session_id)
            if profile:
                system_prompt += f"\n\n{_build_combined_hint(profile['student_id'], fn_calls)}"
            else:
                for fn, args in fn_calls:
                    system_prompt += f"\n\n{_build_fn_hint(fn, args)}"

    # ── 4. history fetch → 현재 메시지 append → Ollama 호출 ─────────────────────
    history = fetch_messages(body.session_id)
    if not is_greet:
        history.append({"role": "user", "content": body.message})
    messages = history if history else [
        {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
    ]

    try:
        ai_message, call1_ms = await generate_chat_message(system_prompt, messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}")

    # ── 5. 응답 생성 후 DB 저장 (user + assistant 둘 다) ─────────────────────────
    if not is_greet:
        save_message(body.session_id, "user", body.message, detected_function)
    save_message(body.session_id, "assistant", ai_message)

    user_input = body.message if not is_greet else ""
    violations = detect_violations(ai_message, user_input)

    # ── 5. 미션 결과 동기화 ──────────────────────────────────────────────────────
    mission_status = None
    if not is_greet and intent == "B" and fn_calls and not _is_conflict(fn_calls):
        profile = fetch_profile(body.session_id)
        for fn, args in fn_calls:
            if fn == "cancel_mission_action":
                if profile:
                    today = _kst_today()
                    cancel_last_action(profile["student_id"])
                    background_tasks.add_task(_cancel_sheet_bg, profile["student_id"], today)
            elif fn == "submit_mission_result":
                mission_status = args.get("result_type") or detect_mission_status(user_input)

    if mission_status:
        background_tasks.add_task(_sync_sheet_bg, body.session_id, user_input, ai_message, mission_status, detected_function)

    sources = [
        {"type": "faq", "title": f["title"], "question": f["question"]}
        for f in rag_result["faqs"]
    ] + [
        {"type": "chunk", "title": c["title"], "intent": c["intent"]}
        for c in rag_result["chunks"]
    ]

    return {
        "response": ai_message,
        "mission_completed": mission_status is not None,
        "detected_function": detected_function,
        "sources": sources,
        "debug": {
            "intent": intent,
            "fn_args": fn_args,
            "violations": violations,
            "system_prompt": system_prompt,
            "history_turns": len(messages),
            "model": OLLAMA_MODEL,
            "timing": {"call1_ms": call1_ms},
            "rag_hits": {"chunks": len(rag_result["chunks"]), "faqs": len(rag_result["faqs"])},
        },
    }


@app.post("/chat/stream")
async def post_chat_stream(body: ChatRequest, background_tasks: BackgroundTasks):
    import json as _json

    mission_title = body.mission or "오늘의 미션"
    is_greet = body.message == "__GREET__"

    async def event_stream():
        intent = "A"
        fn_calls: list[tuple[str, dict]] = []
        detected_function = None
        fn_args: dict = {}
        rag_result: dict = {"chunks": [], "faqs": [], "context": ""}
        intent_ms = 0
        qwen_ms = 0
        rag_ms = 0
        t_total = time.perf_counter()

        if not is_greet:
            # ── Stage 1: 인텐트 분류 (user 메시지는 history fetch 후 저장) ────
            t0 = time.perf_counter()
            intent = await classify_intent(body.message)
            intent_ms = round((time.perf_counter() - t0) * 1000)

            intent_label = {"A": "일반 대화", "B": "미션 액션", "C": "정보 조회", "D": "의도 불명확"}.get(intent, intent)
            yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'intent', 'value': intent, 'label': intent_label, 'ms': intent_ms}, ensure_ascii=False)}\n\n"

            # ── Stage 2: 인텐트별 모듈 ──────────────────────────────────────────
            if intent == "B":
                t1 = time.perf_counter()
                # 멀티 의도 분리 → 각각 Qwen 호출
                parts = await split_multi_intent(body.message)
                fn_calls = []
                seen = set()
                for part in parts:
                    calls, _ = call_function(part)
                    for c in calls:
                        key = (c[0], tuple(sorted(c[1].items())))
                        if key not in seen:
                            fn_calls.append(c)
                            seen.add(key)
                detected_function = fn_calls[0][0] if fn_calls else None
                fn_args = fn_calls[0][1] if fn_calls else {}
                qwen_ms = round((time.perf_counter() - t1) * 1000)
                yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'qwen', 'calls': [[fn, args] for fn, args in fn_calls], 'ms': qwen_ms}, ensure_ascii=False)}\n\n"

            elif intent == "C":
                try:
                    t_rag = time.perf_counter()
                    rag_result = search_rag(body.message)
                    rag_ms = round((time.perf_counter() - t_rag) * 1000)
                    hits = len(rag_result["chunks"]) + len(rag_result["faqs"])
                    yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'rag', 'hits': hits, 'ms': rag_ms}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    print(f"[RAG] 검색 실패 (무시): {e}")

        # ── Stage 3: 응답 생성 시작 알림 ────────────────────────────────────
        system_prompt = build_chat_system_prompt(
            mission_title,
            rag_result["context"] if not is_greet else "",
        )
        if intent == "D":
            system_prompt += "\n\n아이의 말이 무슨 뜻인지 불분명해. 판단하지 말고 딱 한 문장으로 다시 물어봐."
        if intent == "B" and fn_calls:
            combo = _classify_multi(fn_calls)
            if combo == "conflict":
                system_prompt += _build_conflict_prompt(fn_calls)
            elif combo == "db_branch":
                profile = fetch_profile(body.session_id)
                if profile:
                    last_action = get_last_action_type(profile["student_id"])
                    name_set = frozenset(fn for fn, _ in fn_calls)
                    expected = _DB_BRANCH_PAIRS.get(name_set)
                    if last_action == expected:
                        # cancel을 DB에서 먼저 실행한 뒤 나머지 힌트 빌드
                        cancel_last_action(profile["student_id"])
                        remaining = [(fn, args) for fn, args in fn_calls if fn != "cancel_mission_action"]
                        cancel_hint = "아이가 요청해서 직전 행동을 취소했어. "
                        rest_hint = _build_combined_hint(profile["student_id"], remaining)
                        system_prompt += f"\n\n{cancel_hint}{rest_hint}"
                    else:
                        system_prompt += _build_conflict_prompt(fn_calls)
                else:
                    for fn, args in fn_calls:
                        system_prompt += f"\n\n{_build_fn_hint(fn, args)}"
            else:
                # sequential / independent
                profile = fetch_profile(body.session_id)
                if profile:
                    system_prompt += f"\n\n{_build_combined_hint(profile['student_id'], fn_calls)}"
                else:
                    for fn, args in fn_calls:
                        system_prompt += f"\n\n{_build_fn_hint(fn, args)}"

        # 이전 히스토리 fetch → 현재 user 메시지 append → DB 저장
        history = [{"role": m["role"], "content": m["content"]} for m in fetch_messages(body.session_id)]
        if not is_greet:
            history.append({"role": "user", "content": body.message})
            save_message(body.session_id, "user", body.message, None)

        messages = history if history else [
            {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
        ]

        yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'generating'}, ensure_ascii=False)}\n\n"

        # ── Stage 4: 토큰 스트리밍 ───────────────────────────────────────────
        ai_message = ""
        t_gen = time.perf_counter()
        _TAG_MARKERS = ("[APPROVED]", "[DENIED]")
        is_eq_submit = intent == "B" and fn_calls and _is_equivalency_submit(fn_calls)
        token_buf = ""
        try:
            async for token in generate_chat_message_stream(system_prompt, messages):
                ai_message += token
                if is_eq_submit:
                    # 태그가 토큰에 걸칠 수 있으니 버퍼링
                    token_buf += token
                    # 버퍼에 태그가 완성됐으면 제거하고 flush
                    for tag in _TAG_MARKERS:
                        if tag in token_buf:
                            token_buf = token_buf.replace(tag, "")
                    # 태그 시작 가능성이 없으면 flush
                    if "[" not in token_buf:
                        if token_buf:
                            yield f"data: {_json.dumps({'type': 'token', 'content': token_buf}, ensure_ascii=False)}\n\n"
                        token_buf = ""
                else:
                    yield f"data: {_json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            return
        # 버퍼에 남은 텍스트 flush (태그 제거 후)
        if token_buf:
            for tag in _TAG_MARKERS:
                token_buf = token_buf.replace(tag, "")
            if token_buf.strip():
                yield f"data: {_json.dumps({'type': 'token', 'content': token_buf}, ensure_ascii=False)}\n\n"

        gen_ms = round((time.perf_counter() - t_gen) * 1000)

        # equivalency→submit 태그 감지
        eq_approved = False
        if "[APPROVED]" in ai_message:
            eq_approved = True
            ai_message = ai_message.replace("[APPROVED]", "").strip()
            print("[eq-tag] APPROVED 감지 → 성공 저장 예정")
        elif "[DENIED]" in ai_message:
            ai_message = ai_message.replace("[DENIED]", "").strip()
            print("[eq-tag] DENIED 감지 → 저장 안 함")
        elif is_eq_submit:
            print(f"[eq-tag] 태그 없음! 응답 끝부분: ...{ai_message[-80:]}")

        total_ms = round((time.perf_counter() - t_total) * 1000)
        user_input = body.message if not is_greet else ""
        debug_payload = {
            "intent": intent,
            "fn_args": fn_args,
            "violations": detect_violations(ai_message, user_input),
            "system_prompt": system_prompt,
            "history_turns": len(messages),
            "model": OLLAMA_MODEL,
            "timing": {
                "intent_ms": intent_ms,
                "qwen_ms": qwen_ms,
                "rag_ms": rag_ms,
                "gen_ms": gen_ms,
                "total_ms": total_ms,
            },
            "rag_hits": {"chunks": len(rag_result["chunks"]), "faqs": len(rag_result["faqs"])},
        }
        yield f"data: {_json.dumps({'type': 'done', 'debug': debug_payload}, ensure_ascii=False)}\n\n"

        # ── 후처리 ───────────────────────────────────────────────────────────
        save_message(body.session_id, "assistant", ai_message)
        user_input = body.message if not is_greet else ""
        mission_status = None
        if not is_greet and intent == "B" and fn_calls:
            combo = _classify_multi(fn_calls)
            # 충돌이면 후처리 스킵
            if combo == "conflict":
                pass
            # DB분기: cancel은 힌트 빌드에서 이미 실행됨 → 시트 동기화 + submit만 처리
            elif combo == "db_branch":
                profile = fetch_profile(body.session_id)
                if profile:
                    last_action = get_last_action_type(profile["student_id"])
                    name_set = frozenset(fn for fn, _ in fn_calls)
                    expected = _DB_BRANCH_PAIRS.get(name_set)
                    if last_action == expected:
                        today = _kst_today()
                        background_tasks.add_task(_cancel_sheet_bg, profile["student_id"], today)
                        for fn_name, args in fn_calls:
                            if fn_name == "submit_mission_result":
                                mission_status = args.get("result_type") or detect_mission_status(user_input)
            else:
                # sequential / independent — 순서대로 실행
                if _is_equivalency_submit(fn_calls) and eq_approved:
                    # equivalency→submit: LLM이 인정 → DB 저장
                    mission_status = "success"
                elif _is_equivalency_submit(fn_calls):
                    # equivalency→submit: LLM이 불가 → 저장 안 함
                    pass
                else:
                    profile = fetch_profile(body.session_id)
                    ordered = _reorder_sequential(fn_calls) if combo == "sequential" else fn_calls
                    for fn_name, args in ordered:
                        if fn_name == "cancel_mission_action":
                            if profile:
                                today = _kst_today()
                                cancel_last_action(profile["student_id"])
                                background_tasks.add_task(_cancel_sheet_bg, profile["student_id"], today)
                        elif fn_name == "submit_mission_result":
                            mission_status = args.get("result_type") or detect_mission_status(user_input)
        if mission_status:
            background_tasks.add_task(_sync_sheet_bg, body.session_id, user_input, ai_message, mission_status, detected_function)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/chat/{session_id}")
def get_chat(session_id: str):
    return fetch_messages(session_id)


@app.delete("/chat/{session_id}")
def delete_chat(session_id: str):
    count = delete_messages(session_id)
    return {"ok": True, "deleted": count}


@app.post("/admin/generate-daily")
def post_generate_daily():
    try:
        today = _kst_today()
        added = generate_daily_status(today)
        return {"ok": True, "date": today, "added": added}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
