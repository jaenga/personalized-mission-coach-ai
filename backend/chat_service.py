import asyncio
import json as _json
import random
import re
import time

from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from database import (
    _kst_today,
    fetch_messages,
    fetch_profile,
    find_mission_by_user_text,
    find_similar_mission_by_user_text,
    get_pending_mission_suggestion,
    get_student_info_db,
    get_student_mission_db,
    has_checkin_today,
    mark_synced,
    resolve_pending_mission_suggestion,
    save_mission_adjustment,
    save_message,
    save_pending_mission_suggestion,
)
from executor import AdjustmentStatus, CancelStatus, ExecResults, execute_submit
from ollama_client import OLLAMA_MODEL, generate_chat_message, generate_chat_message_stream
from qwen_client import detect_history_call, detect_submit_report_call
from pipeline import (
    classify_multi,
    is_equivalency_submit,
    step_build_hints,
    step_classify,
    step_execute,
    step_extract_functions,
)
from normalizer import normalize_b_input
from prompts import CLARIFY_HINT_DEFAULT, CLARIFY_HINT_MAP
from rag import search_rag
from response_builder import ResponseMode, build_action_ack, build_conflict_ack
from schemas import ChatRequest
from sheets import cancel_mission_result, update_mission_result

_FAKE_STREAM_CHARS = 4
_FAKE_STREAM_DELAY_SEC = 0.1
_CLARIFY_TEMPLATE_REASONS = {
    "numeric",
    "numeric_no_count",
    "numeric_ambiguous",
    "negation_verb",
    "difficulty",
}


def _clarify_template(reason: str, user_message: str, mission_title: str) -> str | None:
    if reason not in _CLARIFY_TEMPLATE_REASONS:
        return None
    if reason == "numeric_no_count":
        return "몇 개나 몇 분 했는지 알려줄래? 예를 들어, '3개 했어', '10분 했어'처럼 말해주면 돼! ☺️"
    if reason == "numeric_ambiguous":
        return "목표까지 조금 남았어! 더 해볼래, 아니면 여기까지 기록할까? 💪"
    if reason == "numeric":
        if re.search(r"봤|봄|시청|유튜브|유튭|유투브|영상|쇼츠|릴스", user_message):
            return "무엇을 몇 분 봤는지 조금 더 자세히 알려줄 수 있을까?"
        return "어떤 걸 몇 분이나 몇 개 했는지 조금 더 자세히 알려줄래? 😃"
    if reason == "negation_verb":
        if "엘리베이터" in user_message or "엘레베이터" in user_message or "엘베" in user_message:
            return "엘리베이터는 안 탔구나! 잘했어 👏 그럼 계단을 이용하여 올라가기도 실천했을까? 😆"
        return "오늘 미션 기준으로 성공인지 같이 확인해볼까?"
    if reason == "difficulty":
        return "조금 어렵게 느껴졌구나. 쉬운 미션으로 바꿔줄까? 아니면 오늘 미션으로 계속 기록할래? 🧐"
    return None


def _sse(payload: dict) -> str:
    return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"


def _chunk_template_response(text: str, chunk_size: int = _FAKE_STREAM_CHARS) -> list[str]:
    """서버 템플릿 응답을 프론트 스트리밍처럼 보이도록 작은 조각으로 나눈다."""
    if not text:
        return []
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


async def _fake_stream_template_response(text: str):
    for chunk in _chunk_template_response(text):
        yield _sse({"type": "token", "content": chunk})
        await asyncio.sleep(_FAKE_STREAM_DELAY_SEC)


def _needs_history_for_action(fn_calls: list[tuple[str, dict]]) -> bool:
    return any(fn == "submit_mission_result" for fn, _ in fn_calls)


def _save_message_safe(
    session_id: str,
    role: str,
    content: str,
    detected_function: str | None = None,
) -> int:
    try:
        return save_message(session_id, role, content, detected_function)
    except Exception as e:
        print(f"[Chat] message save failed role={role} error={type(e).__name__}: {e}")
        return 0


def _short(text: str | None, limit: int = 90) -> str:
    if not text:
        return ""
    one_line = " ".join(str(text).split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "..."


def _fn_label(fn: str, args: dict | None = None) -> str:
    args = args or {}
    if fn == "submit_mission_result":
        return f"submit({args.get('result_type', '?')})"
    if fn == "request_mission_adjustment":
        return f"adjust({args.get('adjustment_type', '?')})"
    if fn == "cancel_mission_action":
        return "cancel"
    if fn == "get_mission_info":
        query_type = args.get("query_type", "?")
        target_date = args.get("target_date")
        if target_date:
            return f"mission_info({query_type}/{target_date})"
        return f"mission_info({query_type})"
    if fn == "get_user_history":
        return f"history({args.get('query_type', '?')})"
    if fn == "check_mission_equivalency":
        return f"equiv({args.get('equivalency_type', '?')})"
    return fn


def _fn_list(fn_calls: list[tuple[str, dict]]) -> str:
    return ", ".join(_fn_label(fn, args) for fn, args in fn_calls) or "-"


def _has_cancel_call(fn_calls: list[tuple[str, dict]]) -> bool:
    return any(fn == "cancel_mission_action" for fn, _ in fn_calls)


def should_force_mission_adjustment(message: str) -> bool:
    text = (message or "").replace(" ", "")
    if _MISSION_CHANGE_NEGATION_RE.search(text):
        return False
    if _CANCEL_NEGATION_RE.search(message or ""):
        return False
    if _CANCEL_REQUEST_RE.search(text):
        return False
    change_words = [
        "미션바꿔",
        "미션변경",
        "바꿔줘",
        "바꿔줄래",
        "변경해줘",
        "바꾸고싶어",
    ]
    return any(word in text for word in change_words)


_MISSION_CHANGE_NEGATION_RE = re.compile(r"바꾸지마|바꾸지말|변경하지마|변경하지말|바꾸면안|변경하면안")
_CANCEL_NEGATION_RE = re.compile(r"(?:취소|되돌|되돌려|철회)\s*하지\s*(?:마|말|말아|마라)")
_CANCEL_REQUEST_RE = re.compile(r"취소|되돌|되돌려|철회|원래대로")


def is_accepting_mission_suggestion(message: str) -> bool:
    text = (message or "").replace(" ", "").strip()

    reject_words = ["아니", "싫어", "말고", "다른", "취소"]
    if any(word in text for word in reject_words):
        return False

    accept_exact_words = [
        "응",
        "좋아",
        "그래",
        "ㅇㅇ",
        "네",
        "맞아",
        "그걸로",
        "그걸로해줘",
        "그미션으로해줘",
        "어좋아",
        "음좋아",
        "아좋아",
        "오좋아",
        "어응",
        "응좋아",
        "그래좋아",
        "엉",
        "엉좋아",
        "엉해줘",
        "응해줘",
        "좋아해줘",
        "그래해줘",
        "그거해줘",
        "그걸로바꿔줘",
        "어해봐",
        "어바꿔줘",
        "어그걸로",
        "어그걸로해줘",
        "응해봐",
        "그래해봐",
        "좋아해봐",
        "그걸로해봐",
        "그걸로바꿔",
    ]

    return text in accept_exact_words


def _is_meaningless_mission_candidate(candidate: str | None) -> bool:
    if not candidate:
        return True

    compact = candidate.replace(" ", "").strip()
    if len(compact) < 2:
        return True

    generic_words = {
        "어", "으", "음", "아", "오",
        "다른", "다른거", "다른것", "새", "새로운",
        "그거", "그걸", "그걸로", "이거", "이걸", "이걸로",
    }

    return compact in generic_words


def extract_mission_candidate_text(user_message: str) -> str | None:
    """
    미션 변경 요청에서 원하는 미션 후보 텍스트를 추출한다.
    "으로", "로" 같은 전치사를 기준으로 텍스트를 분리한다.
    """
    if not user_message:
        return None

    text = user_message.strip()
    compact_text = text.replace(" ", "")

    generic_change_requests = {
        "다른미션으로바꿔줘",
        "새로운미션으로바꿔줘",
        "새미션으로바꿔줘",
        "다른걸로바꿔줘",
        "다른거로바꿔줘",
        "다른것으로바꿔줘",
    }
    if compact_text in generic_change_requests:
        return None

    # 전치사 기준으로 분리
    prepositions = ["으로 바꿔", "로 바꿔", "으로 변경", "로 변경", "으로", "로"]
    for prep in prepositions:
        if prep in text:
            parts = text.split(prep, 1)
            if parts[0].strip():
                candidate = parts[0].strip()
                # 불필요한 단어 제거
                remove_words = [
                    "그럼", "나", "좀", "해줘", "하는", "거야", "다른", "새로운", "새", "또", "다시", "한번", "미션",
                ]
                for word in remove_words:
                    candidate = candidate.replace(word, " ").strip()
                candidate = " ".join(candidate.split())
                if candidate and not _is_meaningless_mission_candidate(candidate):
                    return candidate
                if candidate and _is_meaningless_mission_candidate(candidate):
                    return None

    # 변경 키워드 기준으로도 시도
    change_keywords = ["미션바꿔", "미션변경", "바꿔줘", "바꿔줄래", "변경해줘", "바꾸고싶어"]
    for keyword in change_keywords:
        if keyword in text:
            parts = text.split(keyword, 1)
            candidate = ""
            if parts[0].strip():
                candidate = parts[0].strip()
            elif len(parts) > 1 and parts[1].strip():
                candidate = parts[1].strip()

            remove_words = [
                "그럼", "나", "좀", "해줘", "하는", "거야", "으로", "로", "다른", "새로운", "새", "또", "다시", "한번", "미션",
            ]
            for word in remove_words:
                candidate = candidate.replace(word, " ").strip()
            candidate = " ".join(candidate.split())
            if candidate and not _is_meaningless_mission_candidate(candidate):
                return candidate
            if candidate and _is_meaningless_mission_candidate(candidate):
                return None

    return None


def _response_mode_label(action_ack, eq_submit: bool) -> str:
    if action_ack:
        return action_ack.mode.value
    if eq_submit:
        return "equivalency"
    return "gemma"


def _strip_leading_ack(text: str, ack_message: str) -> str:
    """Gemma가 서버 확정 안내문을 반복하면 앞부분에서 제거한다."""
    if not text or not ack_message:
        return text

    stripped = text.lstrip()
    candidates = {
        ack_message,
        ack_message.rstrip(" ✅❌🔄↩️⚠️"),
    }
    for candidate in sorted(candidates, key=len, reverse=True):
        if candidate and stripped.startswith(candidate):
            stripped = stripped[len(candidate):].lstrip()
            if stripped.startswith(("\n", ".", "!", "！")):
                stripped = stripped[1:].lstrip()
            print(f"[Response] stripped repeated prefix={_short(candidate)!r}")
            return stripped
    return text


def _gemma_user_message(original_message: str, exec_results: ExecResults | None) -> str:
    """DB 실행 후 Gemma가 원문 요청보다 실행 결과에 집중하도록 user message를 보정한다."""
    if exec_results and exec_results.adjustment and exec_results.adjustment.status is AdjustmentStatus.CHANGED:
        result = exec_results.adjustment
        return "\n".join([
            "방금 미션 변경이 완료됐어.",
            "이전 미션에 대해 짧게 받아주고, 새 미션을 앞으로 할 미션으로 설명해줘.",
            f"이전 미션: {result.old_mission_name or ''}",
            f"새 미션: {result.new_mission_name or ''}",
        ])
    return original_message


def _prepare_mission_change_guard(student_id: int | None, user_message: str, fn_calls: list[tuple[str, dict]]) -> tuple[dict | None, list[tuple[str, dict]]]:
    guard_result = None
    if not student_id or not user_message:
        return guard_result, fn_calls
    if _has_cancel_call(fn_calls):
        return guard_result, fn_calls

    pending = get_pending_mission_suggestion(student_id)
    if pending and is_accepting_mission_suggestion(user_message):
        current_mission = get_student_mission_db(student_id)
        if current_mission:
            if has_checkin_today(student_id):
                guard_result = {
                    "type": "already_submitted",
                    "message": "오늘 미션 결과를 이미 저장해서 지금은 미션을 바꿀 수 없어. 바꾸고 싶으면 먼저 방금 기록을 취소해줘!",
                }
                return guard_result, []
            save_mission_adjustment(
                student_id=student_id,
                old_mission_id=current_mission["mission_id"],
                new_mission_id=pending["suggested_mission_id"],
            )
            resolve_pending_mission_suggestion(pending["suggestion_id"], status="accepted")
            guard_result = {
                "type": "adjustment_saved",
                "mission_id": pending["suggested_mission_id"],
                "mission_name": pending["mission_name"],
                "message": f'좋아! 오늘 미션을 "{pending["mission_name"]}"로 바꿨어.',
            }
            return guard_result, []

    if should_force_mission_adjustment(user_message):
        print("[Guard] force request_mission_adjustment because user asked to change mission")
        fn_calls = [call for call in fn_calls if call[0] != "submit_mission_result"]

        # 후보 텍스트 추출
        candidate_text = extract_mission_candidate_text(user_message)
        if not candidate_text:
            # 후보 텍스트 없음: generic 변경으로
            fn_calls = [
                ("request_mission_adjustment", {
                    "adjustment_type": "change",
                    "requested_text": user_message,
                })
            ]
            return guard_result, fn_calls

        # 후보 텍스트 있음: 정확 매칭 시도
        exact_mission = find_mission_by_user_text(candidate_text)
        if exact_mission:
            current_mission = get_student_mission_db(student_id)
            if current_mission:
                if has_checkin_today(student_id):
                    guard_result = {
                        "type": "already_submitted",
                        "message": "오늘 미션 결과를 이미 저장해서 지금은 미션을 바꿀 수 없어. 바꾸고 싶으면 먼저 방금 기록을 취소해줘!",
                    }
                    return guard_result, []
                save_mission_adjustment(
                    student_id=student_id,
                    old_mission_id=current_mission["mission_id"],
                    new_mission_id=exact_mission["mission_id"],
                )
                guard_result = {
                    "type": "adjustment_saved",
                    "mission_id": exact_mission["mission_id"],
                    "mission_name": exact_mission["mission_name"],
                    "message": f'좋아! 오늘 미션을 "{exact_mission["mission_name"]}"로 바꿨어.',
                }
                return guard_result, []

        # 정확 미션 없음: 유사 매칭 시도
        similar_mission = find_similar_mission_by_user_text(candidate_text)
        if similar_mission:
            save_pending_mission_suggestion(
                student_id=student_id,
                suggested_mission_id=similar_mission["mission_id"],
                source_text=user_message,
            )
            guard_result = {
                "type": "suggestion",
                "mission_id": similar_mission["mission_id"],
                "mission_name": similar_mission["mission_name"],
                "message": f'비슷한 미션으로 "{similar_mission["mission_name"]}"가 있어! 이 미션으로 바꿔볼까?',
            }
            return guard_result, []

        # 유사 미션도 없음: 찾지 못했음 안내
        guard_result = {
            "type": "not_found",
            "message": f'아직 "{candidate_text}"에 맞는 미션은 찾지 못했어. 다른 미션으로 바꾸고 싶으면 "다른 미션으로 바꿔줘"라고 말해줘!',
        }
        return guard_result, []

    return guard_result, fn_calls


# ── 가드: AI/캐릭터 정체성 질문 전처리 ────────────────────────────────────────
_AI_IDENTITY_QUESTION_RE = re.compile(
    r"("
    r"(?:너|넌|토미|너\s*혹시|너\s*사실|너\s*진짜)?[\s\S]{0,8}"
    r"(?:AI|ai|인공지능|챗봇|챗지피티|ChatGPT|GPT|gpt|Gemma|gemma|젬마\s*4?|젬마|구글|딥마인드|"
    r"봇|로봇|프로그램|모델|언어\s*모델|대규모\s*언어\s*모델|LLM|llm)"
    r"[\s\S]{0,8}(?:야|이야|임|이냐|냐|지|맞지|잖아|아니야|아니지|맞아|인가|이니|아님)?"
    r"|"
    r"(?:너|넌|토미)?[\s\S]{0,8}"
    r"(?:사람|인간|생명|살아있|현실에 있|실제)"
    r"[\s\S]{0,8}(?:야|이야|임|이냐|냐|지|맞지|잖아|아니야|아니지|맞아|인가|이니|아님)?"
    r"|"
    r"(?:너|넌|너는|토미|토마토)[\s\S]{0,8}"
    r"(?:누구|뭐야|정체|이름)"
    r"|"
    r"(?:토미|토마토)[\s\S]{0,8}"
    r"(?:AI|ai|인공지능|챗봇|Gemma|gemma|젬마\s*4?|젬마|구글|딥마인드|사람|진짜|정체|뭐야|누구)"
    r"|"
    r"(?:토미|토마토)[\s\S]{0,12}"
    r"(?:말해|살아|몸|왜|어떻게)"
    r")",
    re.IGNORECASE,
)
_AI_IDENTITY_RESPONSES = [
    "나는 토미야! 같이 건강 습관 만들어가는 토마토 친구야 🍅 오늘 미션 얘기해볼까?",
    "나는 토미야! 건강 습관을 같이 만들어가는 친구야 🍅 오늘 미션도 같이 해보자!",
    "토미라고 불러줘! 네 건강 습관을 옆에서 응원하는 토마토 친구야 🍅",
    "나는 토미야! 너랑 미션도 이야기하고 건강 습관도 같이 챙기는 친구야 🍅",
    "나는 토미! 오늘도 네 건강 습관을 같이 응원해주는 친구야 🍅",
]


def _identity_response() -> str:
    return random.choice(_AI_IDENTITY_RESPONSES)


_AI_OUTPUT_RE = re.compile(
    r"인공지능|AI\s*(?:야|이야|이에요|입니다|예요|모델)|챗봇|언어\s*모델|대규모\s*언어\s*모델|LLM|GPT|Gemma|gemma|젬마|구글|딥마인드",
    re.IGNORECASE,
)
_OFFTOPIC_RE = re.compile(
    r"주식|코인|비트코인|이더리움|암호화폐|선물\s*거래",
    re.IGNORECASE,
)
_OFFTOPIC_RESPONSE = "그 얘기도 재밌지만, 나는 건강 습관이랑 오늘 미션 얘기를 더 잘 도와줄 수 있어 🍅 오늘 미션 이야기 해볼까?"


def _filter_ai_response(text: str) -> str:
    """응답 중 AI 정체성 노출 문장을 토미 자기소개 문장으로 교체."""
    if not _AI_OUTPUT_RE.search(text):
        return text
    sentences = re.split(r"(?<=[.!?~\n])\s*", text)
    filtered: list[str] = []
    replaced = False
    for s in sentences:
        if s.strip() and _AI_OUTPUT_RE.search(s):
            if not replaced:
                filtered.append("나는 토미야! 같이 건강 습관 만들어가는 토마토 친구야 🍅")
                replaced = True
        else:
            filtered.append(s)
    result = " ".join(s for s in filtered if s.strip())
    if replaced:
        print("[Guard] AI output filtered")
    return result or text


FORBIDDEN_WORDS = ["엄마", "아빠", "부모님", "가족", "형", "언니", "오빠", "동생", "친구", "선생님"]


def detect_violations(ai_message: str, user_input: str) -> list[str]:
    return [
        f"금지어 언급: '{w}' (사용자가 먼저 말하지 않음)"
        for w in FORBIDDEN_WORDS
        if w in ai_message and w not in user_input
    ]


def _cancel_sheet_bg(student_id: int, today: str):
    try:
        cancel_mission_result(student_id, today)
    except Exception as e:
        print(f"[cancel] 시트 초기화 실패: {e}")


def _sync_sheet_bg(
    session_id: str,
    user_message: str,
    ai_message: str,
    status: str,
    checkin_id: int | None = None,
):
    """구글 시트 동기화. DB 저장은 executor가 이미 처리했으므로 여기서는 시트만"""
    profile = fetch_profile(session_id)
    if not profile:
        return

    today = _kst_today()
    student_id = profile["student_id"]
    student_info = get_student_info_db(student_id) or {}
    mission_info = get_student_mission_db(student_id, today) or {}
    mission_id = mission_info.get("mission_id")
    if not mission_id:
        print(f"[sync] mission_id 없음 - 시트 동기화 스킵 (student_id={student_id})")
        return

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
        if checkin_id is not None:
            mark_synced(checkin_id)
    except Exception:
        pass


def _finalize_equivalency_response(
    ai_message: str,
    student_id: int | None,
    pending_submit_args: dict | None,
    exec_results: ExecResults,
) -> str:
    """[APPROVED]/[DENIED] 태그 제거 후, 실제 저장 결과를 응답에 반영."""
    if "[APPROVED]" in ai_message:
        ai_message = ai_message.replace("[APPROVED]", "").strip()
        if student_id and pending_submit_args:
            submit_result = execute_submit(student_id, pending_submit_args)
            exec_results.submit = submit_result
            ack = build_action_ack(exec_results)
            if not ack:
                return ai_message
            return f"{ai_message}\n{ack.message}".strip()
        return ai_message

    if "[DENIED]" in ai_message:
        return ai_message.replace("[DENIED]", "").strip()

    return ai_message


def _prepend_db_action_ack(ai_message: str, exec_results: ExecResults | None) -> str:
    ack = build_action_ack(exec_results)
    if ack and ack.message and not ai_message.startswith(ack.message):
        ai_message = _strip_leading_ack(ai_message, ack.message)
        print(f"[Response] prefix={_short(ack.message)!r}")
        return f"{ack.message}\n{ai_message}".strip()
    return ai_message


async def process_chat(body: ChatRequest, background_tasks: BackgroundTasks):
    mission_title = body.mission or "오늘의 미션"
    is_greet = body.message == "__GREET__"
    print(f"\n[Chat] <- {_short(body.message)!r} session={body.session_id[:8]}")

    if not is_greet and _AI_IDENTITY_QUESTION_RE.search(body.message):
        print("[Guard] AI identity question detected -> fixed response")
        identity_message = _identity_response()
        await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", identity_message)
        return {
            "response": identity_message,
            "mission_completed": False,
            "detected_function": None,
            "sources": [],
            "debug": {"intent": "IDENTITY_GUARD", "timing": {}},
        }

    if not is_greet and _OFFTOPIC_RE.search(body.message):
        print("[Guard] off-topic detected -> fixed response")
        await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", _OFFTOPIC_RESPONSE)
        return {
            "response": _OFFTOPIC_RESPONSE,
            "mission_completed": False,
            "detected_function": None,
            "sources": [],
            "debug": {"intent": "OFFTOPIC_GUARD", "timing": {}},
        }

    profile = await run_in_threadpool(fetch_profile, body.session_id)
    student_id = profile["student_id"] if profile else None
    student_name = profile.get("student_name", "") if profile else ""
    mission_id = None
    if student_id:
        mission_row = await run_in_threadpool(get_student_mission_db, student_id, _kst_today())
        if mission_row:
            mission_id = mission_row.get("mission_id")
            mission_title = mission_row.get("mission_name") or mission_title

    intent = "A"
    fn_calls: list[tuple[str, dict]] = []
    detected_function = None
    fn_args: dict = {}
    rag_result: dict = {"chunks": [], "faqs": [], "context": ""}
    intent_ms = 0
    qwen_ms = 0
    clarify_hint_override = ""
    clarify_reason = ""

    if not is_greet:
        if _CANCEL_NEGATION_RE.search(body.message):
            cancel_negation_message = "알겠어, 취소하지 않을게!"
            print("[Guard] cancel negation detected -> fixed response")
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", cancel_negation_message)
            return {
                "response": cancel_negation_message,
                "mission_completed": False,
                "detected_function": None,
                "sources": [],
                "debug": {"intent": "CANCEL_NEGATION_GUARD", "timing": {}},
            }
        intent, intent_ms = await step_classify(body.message, mission_title)
        if intent == "B" and "취소" in body.message:
            norm = normalize_b_input(body.message, mission_title, mission_id)
            if norm.should_clarify:
                intent = "D"
                clarify_reason = norm.reason
                clarify_hint_override = CLARIFY_HINT_MAP.get(norm.reason, CLARIFY_HINT_DEFAULT)
                print(f"[Route] B -> D clarify ({norm.reason or 'default'})")
            elif "취소" in norm.message:
                fn_calls, qwen_ms = await step_extract_functions(norm.message)
                detected_function = fn_calls[0][0] if fn_calls else None
                fn_args = fn_calls[0][1] if fn_calls else {}

        submit_report_call = None if fn_calls else detect_submit_report_call(body.message)
        history_call = None if submit_report_call or fn_calls else detect_history_call(body.message)
        if submit_report_call:
            intent = "B"
            fn_calls = [submit_report_call]
            detected_function = submit_report_call[0]
            fn_args = submit_report_call[1]
            print("[Route] submit report forced to submit_mission_result")
        elif history_call:
            intent = "B"
            fn_calls = [history_call]
            detected_function = history_call[0]
            fn_args = history_call[1]
            print("[Route] history query forced to get_user_history")

        if intent == "B" and not fn_calls:
            norm = normalize_b_input(body.message, mission_title, mission_id)
            if norm.should_clarify:
                intent = "D"
                clarify_reason = norm.reason
                clarify_hint_override = CLARIFY_HINT_MAP.get(norm.reason, CLARIFY_HINT_DEFAULT)
                print(f"[Route] B -> D clarify ({norm.reason or 'default'})")
            else:
                fn_calls, qwen_ms = await step_extract_functions(norm.message)
                detected_function = fn_calls[0][0] if fn_calls else None
                fn_args = fn_calls[0][1] if fn_calls else {}
        if intent == "C":
            try:
                rag_result = await run_in_threadpool(search_rag, body.message)
            except Exception as e:
                print(f"[RAG] 검색 실패 (무시): {e}")

    clarify_response = _clarify_template(clarify_reason, body.message, mission_title)
    if clarify_response:
        print(f"[Clarify] template reason={clarify_reason} response={_short(clarify_response)!r}")
        if not is_greet:
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, detected_function)
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", clarify_response)
        return {
            "response": clarify_response,
            "mission_completed": False,
            "detected_function": None,
            "sources": [],
            "debug": {
                "intent": intent,
                "clarify_reason": clarify_reason,
                "clarify_template": True,
                "fn_args": fn_args,
                "violations": detect_violations(clarify_response, body.message),
                "system_prompt": "",
                "history_turns": 0,
                "model": OLLAMA_MODEL,
                "timing": {"intent_ms": intent_ms, "qwen_ms": qwen_ms, "llm_ms": 0},
                "rag_hits": {"chunks": 0, "faqs": 0},
            },
        }

    combo = classify_multi(fn_calls) if fn_calls else None
    if _MISSION_CHANGE_NEGATION_RE.search((body.message or "").replace(" ", "")):
        fn_calls = [call for call in fn_calls if call[0] != "request_mission_adjustment"]
        combo = classify_multi(fn_calls) if fn_calls else None
    mission_change_guard_result, fn_calls = _prepare_mission_change_guard(student_id, body.message, fn_calls)

    # Recompute combo because the guard may have changed fn_calls.
    combo = classify_multi(fn_calls) if fn_calls else None
    if mission_change_guard_result and not fn_calls:
        detected_function = "request_mission_adjustment"
        fn_args = {"adjustment_type": "change", "requested_text": body.message}
    elif not _has_cancel_call(fn_calls) and should_force_mission_adjustment(body.message):
        detected_function = "request_mission_adjustment"
    print(f"[Route] student={student_id or '-'} combo={combo or '-'} calls={_fn_list(fn_calls)}")
    exec_results = ExecResults()
    pending_submit_args = None

    if student_id and fn_calls:
        exec_results, fn_calls, pending_submit_args, combo = await run_in_threadpool(
            step_execute,
            student_id,
            fn_calls,
            combo,
        )
    elif fn_calls:
        print("[DB] skipped: missing student_id")
    if combo == "conflict":
        detected_function = None

    system_prompt = await run_in_threadpool(
        step_build_hints,
        student_id=student_id,
        fn_calls=fn_calls,
        exec_results=exec_results,
        combo=combo,
        mission_title=mission_title,
        rag_context=rag_result["context"],
        intent=intent,
        is_greet=is_greet,
        clarify_hint_override=clarify_hint_override,
        student_name=student_name,
        user_message=body.message,
    )
    print(f"[Prompt] function_results={'Y' if '[기능 실행 결과]' in system_prompt else 'N'}")

    gemma_user_message = _gemma_user_message(body.message, exec_results)
    if not is_greet and fn_calls and not _needs_history_for_action(fn_calls):
        messages = [{"role": "user", "content": gemma_user_message}]
    else:
        history = await run_in_threadpool(fetch_messages, body.session_id)
        if not is_greet:
            history.append({"role": "user", "content": gemma_user_message})
        messages = history if history else [
            {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
        ]

    eq_submit = is_equivalency_submit(fn_calls) if fn_calls else False
    action_ack = build_conflict_ack() if combo == "conflict" else (None if eq_submit else build_action_ack(exec_results))
    llm_only = ""
    call1_ms = 0
    if mission_change_guard_result and not fn_calls:
        ai_message = mission_change_guard_result["message"]
        llm_only = ai_message
        print(f"[Guard] direct response={_short(ai_message)!r}")
    elif action_ack and action_ack.mode is ResponseMode.SERVER_ONLY:
        ai_message = action_ack.message
    else:
        try:
            ai_message, call1_ms = await generate_chat_message(system_prompt, messages)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}")

        if eq_submit:
            ai_message = await run_in_threadpool(
                _finalize_equivalency_response,
                ai_message,
                student_id,
                pending_submit_args,
                exec_results,
            )

        ai_message = _filter_ai_response(ai_message)
        llm_only = ai_message
        if not eq_submit and action_ack and action_ack.mode is ResponseMode.PREFIX_WITH_GEMMA:
            ai_message = _prepend_db_action_ack(ai_message, exec_results)
    print(f"[Chat] -> mode={_response_mode_label(action_ack, eq_submit)} response={_short(ai_message)!r}")

    if not is_greet:
        await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, detected_function)
    await run_in_threadpool(_save_message_safe, body.session_id, "assistant", llm_only or ai_message)

    user_input = body.message if not is_greet else ""
    violations = detect_violations(ai_message, user_input)

    mission_status = None
    if exec_results and exec_results.submit and exec_results.submit.status.value == "saved":
        mission_status = exec_results.submit.result_type
    if (
        exec_results
        and exec_results.cancel
        and exec_results.cancel.status is CancelStatus.CANCELLED_SUBMIT
    ):
        today = _kst_today()
        background_tasks.add_task(_cancel_sheet_bg, student_id, today)

    if mission_status:
        checkin_id = exec_results.submit.checkin_id if exec_results and exec_results.submit else None
        background_tasks.add_task(_sync_sheet_bg, body.session_id, user_input, ai_message, mission_status, checkin_id)

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
            "clarify_reason": clarify_reason,
            "fn_args": fn_args,
            "violations": violations,
            "system_prompt": system_prompt,
            "history_turns": len(messages),
            "model": OLLAMA_MODEL,
            "timing": {"intent_ms": intent_ms, "qwen_ms": qwen_ms, "llm_ms": call1_ms},
            "rag_hits": {"chunks": len(rag_result["chunks"]), "faqs": len(rag_result["faqs"])},
        },
    }


async def process_chat_stream(body: ChatRequest, background_tasks: BackgroundTasks):
    mission_title = body.mission or "오늘의 미션"
    is_greet = body.message == "__GREET__"
    print(f"\n[Stream] <- {_short(body.message)!r} session={body.session_id[:8]}")

    async def event_stream():
        if not is_greet and _AI_IDENTITY_QUESTION_RE.search(body.message):
            print("[Guard] AI identity question detected -> fixed response (stream)")
            identity_message = _identity_response()
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", identity_message)
            async for event in _fake_stream_template_response(identity_message):
                yield event
            yield _sse({"type": "done", "debug": {"intent": "IDENTITY_GUARD", "timing": {}}})
            return

        if not is_greet and _OFFTOPIC_RE.search(body.message):
            print("[Guard] off-topic detected -> fixed response (stream)")
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", _OFFTOPIC_RESPONSE)
            async for event in _fake_stream_template_response(_OFFTOPIC_RESPONSE):
                yield event
            yield _sse({"type": "done", "debug": {"intent": "OFFTOPIC_GUARD", "timing": {}}})
            return

        current_mission_title = mission_title
        profile = await run_in_threadpool(fetch_profile, body.session_id)
        student_id = profile["student_id"] if profile else None
        student_name = profile.get("student_name", "") if profile else ""
        mission_id = None
        if student_id:
            mission_row = await run_in_threadpool(get_student_mission_db, student_id, _kst_today())
            if mission_row:
                mission_id = mission_row.get("mission_id")
                current_mission_title = mission_row.get("mission_name") or current_mission_title

        intent = "A"
        fn_calls: list[tuple[str, dict]] = []
        detected_function = None
        fn_args: dict = {}
        rag_result: dict = {"chunks": [], "faqs": [], "context": ""}
        intent_ms = 0
        qwen_ms = 0
        rag_ms = 0
        t_total = time.perf_counter()
        clarify_hint_override = ""
        clarify_reason = ""

        if not is_greet:
            if _CANCEL_NEGATION_RE.search(body.message):
                print("[Guard] cancel negation detected -> fixed response (stream)")
                cancel_negation_message = "알겠어, 취소하지 않을게!"
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", cancel_negation_message)
                async for event in _fake_stream_template_response(cancel_negation_message):
                    yield event
                yield _sse({"type": "done", "debug": {"intent": "CANCEL_NEGATION_GUARD", "timing": {}}})
                return
            intent, intent_ms = await step_classify(body.message, current_mission_title)
            if intent == "B" and "취소" in body.message:
                norm = normalize_b_input(body.message, current_mission_title, mission_id)
                if norm.should_clarify:
                    intent = "D"
                    clarify_reason = norm.reason
                    clarify_hint_override = CLARIFY_HINT_MAP.get(norm.reason, CLARIFY_HINT_DEFAULT)
                    print(f"[Route] B -> D clarify ({norm.reason or 'default'})")
                elif "취소" in norm.message:
                    fn_calls, qwen_ms = await step_extract_functions(norm.message)
                    detected_function = fn_calls[0][0] if fn_calls else None
                    fn_args = fn_calls[0][1] if fn_calls else {}

            submit_report_call = None if fn_calls else detect_submit_report_call(body.message)
            history_call = None if submit_report_call or fn_calls else detect_history_call(body.message)
            if submit_report_call:
                intent = "B"
                fn_calls = [submit_report_call]
                detected_function = submit_report_call[0]
                fn_args = submit_report_call[1]
                print("[Route] submit report forced to submit_mission_result")
            elif history_call:
                intent = "B"
                fn_calls = [history_call]
                detected_function = history_call[0]
                fn_args = history_call[1]
                print("[Route] history query forced to get_user_history")
            intent_label = {"A": "일반 대화", "B": "미션 액션", "C": "정보 조회", "D": "의도 불명확"}.get(intent, intent)
            yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'intent', 'value': intent, 'label': intent_label, 'ms': intent_ms}, ensure_ascii=False)}\n\n"

            if fn_calls:
                qwen_ms = 0
                yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'qwen', 'calls': [[fn, args] for fn, args in fn_calls], 'ms': qwen_ms}, ensure_ascii=False)}\n\n"
            elif intent == "B":
                norm = normalize_b_input(body.message, current_mission_title, mission_id)
                if norm.should_clarify:
                    intent = "D"
                    clarify_reason = norm.reason
                    clarify_hint_override = CLARIFY_HINT_MAP.get(norm.reason, CLARIFY_HINT_DEFAULT)
                    print(f"[Route] B -> D clarify ({norm.reason or 'default'})")
                else:
                    fn_calls, qwen_ms = await step_extract_functions(norm.message)
                    detected_function = fn_calls[0][0] if fn_calls else None
                    fn_args = fn_calls[0][1] if fn_calls else {}
                    yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'qwen', 'calls': [[fn, args] for fn, args in fn_calls], 'ms': qwen_ms}, ensure_ascii=False)}\n\n"
            if intent == "C":
                try:
                    t_rag = time.perf_counter()
                    rag_result = await run_in_threadpool(search_rag, body.message)
                    rag_ms = round((time.perf_counter() - t_rag) * 1000)
                    hits = len(rag_result["chunks"]) + len(rag_result["faqs"])
                    yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'rag', 'hits': hits, 'ms': rag_ms}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    print(f"[RAG] 검색 실패 (무시): {e}")

        clarify_response = _clarify_template(clarify_reason, body.message, current_mission_title)
        if clarify_response:
            print(f"[Clarify] template reason={clarify_reason} response={_short(clarify_response)!r}")
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, detected_function)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", clarify_response)
            async for event in _fake_stream_template_response(clarify_response):
                yield event
            total_ms = round((time.perf_counter() - t_total) * 1000)
            yield _sse({
                "type": "done",
                "debug": {
                    "intent": intent,
                    "clarify_reason": clarify_reason,
                    "clarify_template": True,
                    "fn_args": fn_args,
                    "violations": detect_violations(clarify_response, body.message),
                    "system_prompt": "",
                    "history_turns": 0,
                    "model": OLLAMA_MODEL,
                    "timing": {
                        "intent_ms": intent_ms,
                        "qwen_ms": qwen_ms,
                        "rag_ms": rag_ms,
                        "gen_ms": 0,
                        "total_ms": total_ms,
                    },
                    "rag_hits": {"chunks": 0, "faqs": 0},
                },
            })
            return

        combo = classify_multi(fn_calls) if fn_calls else None
        if _MISSION_CHANGE_NEGATION_RE.search((body.message or "").replace(" ", "")):
            fn_calls = [call for call in fn_calls if call[0] != "request_mission_adjustment"]
            combo = classify_multi(fn_calls) if fn_calls else None
        mission_change_guard_result, fn_calls = _prepare_mission_change_guard(student_id, body.message, fn_calls)

        # Recompute combo because the guard may have changed fn_calls.
        combo = classify_multi(fn_calls) if fn_calls else None
        if mission_change_guard_result and not fn_calls:
            detected_function = "request_mission_adjustment"
            fn_args = {"adjustment_type": "change", "requested_text": body.message}
        elif not _has_cancel_call(fn_calls) and should_force_mission_adjustment(body.message):
            detected_function = "request_mission_adjustment"
        print(f"[Route] student={student_id or '-'} combo={combo or '-'} calls={_fn_list(fn_calls)}")
        exec_results = ExecResults()
        pending_submit_args = None

        if student_id and fn_calls:
            exec_results, fn_calls, pending_submit_args, combo = await run_in_threadpool(
                step_execute,
                student_id,
                fn_calls,
                combo,
            )
        elif fn_calls:
            print("[DB] skipped: missing student_id")
        if combo == "conflict":
            detected_function = None

        system_prompt = await run_in_threadpool(
            step_build_hints,
            student_id=student_id,
            fn_calls=fn_calls,
            exec_results=exec_results,
            combo=combo,
            mission_title=current_mission_title,
            rag_context=rag_result["context"],
            intent=intent,
            is_greet=is_greet,
            clarify_hint_override=clarify_hint_override,
            student_name=student_name,
            user_message=body.message,
        )
        print(f"[Prompt] function_results={'Y' if '[기능 실행 결과]' in system_prompt else 'N'}")

        gemma_user_message = _gemma_user_message(body.message, exec_results)
        if not is_greet and fn_calls and not _needs_history_for_action(fn_calls):
            messages = [{"role": "user", "content": gemma_user_message}]
        else:
            fetched_history = await run_in_threadpool(fetch_messages, body.session_id)
            history = [{"role": m["role"], "content": m["content"]} for m in fetched_history]
            if not is_greet:
                history.append({"role": "user", "content": gemma_user_message})
            messages = history if history else [
                {"role": "user", "content": f"안녕! 오늘 미션 '{current_mission_title}'을 소개하고 응원해 줘."}
            ]

        yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'generating'}, ensure_ascii=False)}\n\n"

        t_gen = time.perf_counter()
        tag_markers = ("[APPROVED]", "[DENIED]")
        eq_submit = is_equivalency_submit(fn_calls) if fn_calls else False
        action_ack = build_conflict_ack() if combo == "conflict" else (None if eq_submit else build_action_ack(exec_results))
        server_prefix = (
            action_ack.message
            if action_ack and action_ack.mode is ResponseMode.PREFIX_WITH_GEMMA
            else ""
        )
        ai_message = ""
        llm_message = ""
        prefix_buffer_mode = bool(server_prefix) and not eq_submit

        if mission_change_guard_result and not fn_calls:
            ai_message = mission_change_guard_result["message"]
            async for event in _fake_stream_template_response(ai_message):
                yield event
        elif action_ack and action_ack.mode is ResponseMode.SERVER_ONLY:
            ai_message = action_ack.message
            async for event in _fake_stream_template_response(ai_message):
                yield event
        else:
            if server_prefix:
                print(f"[Response] prefix={_short(server_prefix)!r}")
                ai_message = f"{server_prefix}\n"
                async for event in _fake_stream_template_response(ai_message):
                    yield event

            token_buf = ""
            lookahead_limit = len(server_prefix) + 10 if server_prefix else 0
            lookahead_buf = ""
            prefix_echo_handled = not prefix_buffer_mode
            try:
                async for token in generate_chat_message_stream(system_prompt, messages):
                    llm_message += token

                    if not prefix_echo_handled:
                        lookahead_buf += token
                        if len(lookahead_buf) >= lookahead_limit:
                            cleaned = _strip_leading_ack(lookahead_buf, server_prefix)
                            prefix_echo_handled = True
                            ai_message += cleaned
                            if cleaned.strip():
                                yield f"data: {_json.dumps({'type': 'token', 'content': cleaned}, ensure_ascii=False)}\n\n"
                        continue

                    ai_message += token
                    if eq_submit:
                        token_buf += token
                        for tag in tag_markers:
                            if tag in token_buf:
                                token_buf = token_buf.replace(tag, "")
                        if "[" not in token_buf:
                            if token_buf:
                                yield f"data: {_json.dumps({'type': 'token', 'content': token_buf}, ensure_ascii=False)}\n\n"
                            token_buf = ""
                    else:
                        yield f"data: {_json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {_json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
                return
            if not prefix_echo_handled and lookahead_buf:
                cleaned = _strip_leading_ack(lookahead_buf, server_prefix)
                ai_message += cleaned
                if cleaned.strip():
                    yield f"data: {_json.dumps({'type': 'token', 'content': cleaned}, ensure_ascii=False)}\n\n"
            elif token_buf:
                for tag in tag_markers:
                    token_buf = token_buf.replace(tag, "")
                if token_buf.strip():
                    yield f"data: {_json.dumps({'type': 'token', 'content': token_buf}, ensure_ascii=False)}\n\n"

        gen_ms = round((time.perf_counter() - t_gen) * 1000)

        if "[APPROVED]" in llm_message:
            print("[Equiv] approved")
        elif "[DENIED]" in llm_message:
            print("[Equiv] denied")
        elif eq_submit:
            print(f"[Equiv] missing tag tail={_short(llm_message[-80:])!r}")

        if eq_submit:
            visible_before_finalize = (
                llm_message.replace("[APPROVED]", "").replace("[DENIED]", "").strip()
            )
            finalized_message = await run_in_threadpool(
                _finalize_equivalency_response,
                llm_message,
                student_id,
                pending_submit_args,
                exec_results,
            )
            if finalized_message.startswith(visible_before_finalize):
                finalize_suffix = finalized_message[len(visible_before_finalize):]
                if finalize_suffix.strip():
                    async for event in _fake_stream_template_response(finalize_suffix):
                        yield event
            ai_message = finalized_message
        print(f"[Stream] -> mode={_response_mode_label(action_ack, eq_submit)} response={_short(ai_message)!r}")

        total_ms = round((time.perf_counter() - t_total) * 1000)
        user_input = body.message if not is_greet else ""
        debug_payload = {
            "intent": intent,
            "clarify_reason": clarify_reason,
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
        if exec_results.submit:
            debug_payload["submit_result"] = {
                "status": exec_results.submit.status.value,
                "result_type": exec_results.submit.result_type,
                "db_changed": exec_results.submit.db_changed,
            }
        if not is_greet:
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, detected_function)
        llm_save = _filter_ai_response(
            llm_message.replace("[APPROVED]", "").replace("[DENIED]", "").strip()
        )
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", llm_save or ai_message)

        yield f"data: {_json.dumps({'type': 'done', 'debug': debug_payload}, ensure_ascii=False)}\n\n"
        mission_status = None
        if exec_results.submit and exec_results.submit.status.value == "saved":
            mission_status = exec_results.submit.result_type
        if exec_results.cancel and exec_results.cancel.status is CancelStatus.CANCELLED_SUBMIT:
            today = _kst_today()
            background_tasks.add_task(_cancel_sheet_bg, student_id, today)
        if mission_status:
            checkin_id = exec_results.submit.checkin_id if exec_results.submit else None
            background_tasks.add_task(_sync_sheet_bg, body.session_id, user_input, ai_message, mission_status, checkin_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
