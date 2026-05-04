"""
Hint Builder — 실행 결과를 LLM 시스템 프롬프트용 텍스트로 변환
원칙: DB write 절대 안 함! DB read는 읽기 전용 힌트에서만
"""
from __future__ import annotations

from database import _kst_today, get_student_mission_db, get_user_history_db, resolve_mission_query_date
from category_prompts import get_category_equivalency_prompt
from executor import (
    SubmitStatus, SubmitResult,
    AdjustmentStatus, AdjustmentResult,
    CancelStatus, CancelResult,
    ExecResults,
)


# ── 상수 ─────────────────────────────────────────────────────────────────────

DEADLINE_TEXT = "밤 11시 (23:00)"

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

_FN_LABELS = {
    "submit_mission_result": "미션 결과 제출",
    "cancel_mission_action": "이전 행동 취소",
    "request_mission_adjustment": "미션 변경",
    "check_mission_equivalency": "대체 수행 확인",
}

EQUIVALENCY_SUBMIT_TAG_INSTRUCTION = """
===== 필수 태그 (반드시 지켜) =====
아이가 대체 수행이 인정되면 성공으로 제출하겠다고 했어.
너의 답변 텍스트 마지막 줄에 반드시 아래 태그 중 하나를 붙여.

중요:
- 아직 기록이 완료된 것은 아니야. "기록했어", "저장됐어"처럼 이미 저장된 것처럼 말하지 마.
- 인정 가능/불가 판단만 먼저 알려줘.

인정 가능 → [APPROVED]
인정 불가 → [DENIED]

예시:
"좋아, 그것도 충분히 인정될 수 있어! 😊
[APPROVED]"

"아쉽지만 이번에는 조금 달라서 인정이 어려워.
[DENIED]"
=================================
""".strip()


# ── 실행 결과 기반 힌트 (DB 접근 없음) ───────────────────────────────────────

def build_submit_hint(result: SubmitResult) -> str:
    result_kor = {"success": "완료", "fail": "수행 실패"}.get(result.result_type or "", "")
    if result.status is SubmitStatus.SAVED:
        if result.result_type == "success":
            return f"아이가 미션을 성공했어. 짧게 칭찬해줘."
        return f"아이가 미션 결과를 제출했어. 결과: {result_kor}. 따뜻하게 받아줘."
    if result.status is SubmitStatus.ALREADY_SUBMITTED:
        return "아이가 미션 결과를 다시 제출하려 했어. 짧게 응원 한 마디만 해줘."
    if result.status is SubmitStatus.NO_MISSION:
        return "아이가 미션 결과를 제출했어. 오늘 배정된 미션이 없다고 알려줘."
    # DB_ERROR
    return "아이가 미션 결과를 제출했는데 기록 중 문제가 생겼어. 잠시 후 다시 시도해달라고 안내해줘."


def build_adjustment_hint(result: AdjustmentResult) -> str:
    label = {"easier": "더 쉬운", "harder": "더 어려운"}.get(result.adjustment_type or "", "다른")
    if result.status is AdjustmentStatus.CHANGED:
        empathy = {
            "easier": "이전 미션이 조금 어려웠을 수 있다는 점을 한 문장으로 짧게 받아준다.",
            "harder": "아이가 조금 더 도전해보고 싶은 마음을 한 문장으로 짧게 받아준다.",
            "change": "아이가 다른 미션으로 해보고 싶은 마음을 한 문장으로 짧게 받아준다.",
        }.get(result.adjustment_type or "", "아이가 다른 미션으로 해보고 싶은 마음을 한 문장으로 짧게 받아준다.")
        lines = [
            "[미션 변경 완료 후 설명]",
            '서버가 이미 "미션을 바꿔뒀어!"라고 안내했다.',
            "아래 정보를 이전 미션과 새 미션으로 정확히 구분해서 답한다.",
            "이전 미션을 성공했다고 말하지 않는다.",
            "이전 미션 수행 여부를 추측하지 않는다.",
            "새 미션명과 새 미션 규칙만 안내한다.",
            "아래 [새 미션]에 없는 미션명은 절대 만들지 않는다.",
            f"변경 유형: {result.adjustment_type or 'change'} ({label} 미션)",
            "",
            "[이전 미션]",
            f"미션명: {result.old_mission_name or ''}",
        ]
        if result.old_mission_rule:
            lines.append(f"규칙: {result.old_mission_rule}")
        lines.extend([
            "",
            "[새 미션]",
            f"미션명: {result.new_mission_name or ''}",
        ])
        if result.new_mission_rule:
            lines.append(f"규칙: {result.new_mission_rule}")
        lines.extend([
            "",
            "응답 순서:",
            f"1. {empathy}",
            "2. 새 미션명을 말한다.",
            "3. 새 미션 규칙을 아이가 이해하기 쉽게 1~2문장으로 설명한다.",
            "",
            "금지 예시:",
            "- 이전 미션을 잘했다/해냈다/성공했다처럼 말하지 않는다.",
            "- 이전 미션을 수행한 것처럼 칭찬하지 않는다.",
        ])
        return "\n".join(lines)
    if result.status is AdjustmentStatus.ALREADY_SUBMITTED:
        return "아이가 미션 변경을 요청했어. 짧게 공감해줘."
    if result.status is AdjustmentStatus.NO_ALTERNATIVE:
        return f"아이가 {label} 미션을 요청했어. 같은 카테고리에 {label} 미션이 없어. 현재 미션을 계속하도록 안내해줘."
    if result.status is AdjustmentStatus.NO_MISSION:
        return "아이가 미션 조정을 요청했어. 오늘 배정된 미션이 없다고 알려줘."
    # DB_ERROR
    return "아이가 미션 변경을 요청했는데 처리 중 문제가 생겼어. 잠시 후 다시 시도해달라고 안내해줘."


def build_cancel_hint(result: CancelResult) -> str:
    if result.status is CancelStatus.CANCELLED_SUBMIT:
        return "아이가 미션 제출 기록을 취소했어. 무엇을 취소했는지 짧게 알려줘."
    if result.status is CancelStatus.CANCELLED_ADJUSTMENT:
        return "아이가 미션 변경을 취소했어. 원래 미션으로 돌아간 상황이야. 무엇을 취소했는지 짧게 알려줘."
    if result.status is CancelStatus.NOTHING_TO_CANCEL:
        requested = result.cancel_type or "latest"
        if requested == "submit":
            return "아이가 제출 취소를 요청했지만 취소할 제출 기록이 없어. 그 사실만 짧게 알려줘."
        if requested == "adjustment":
            return "아이가 미션 변경 취소를 요청했지만 취소할 미션 변경이 없어. 그 사실만 짧게 알려줘."
        return "아이가 취소를 요청했지만 취소할 최근 작업이 없어. 그 사실만 짧게 알려줘."
    # DB_ERROR
    return "아이가 취소를 요청했는데 처리 중 문제가 생겼어. 잠시 후 다시 시도해달라고 안내해줘."


# ── 읽기 전용 힌트 (DB SELECT만, write 없음) ─────────────────────────────────

def build_equivalency_hint(student_id: int, fn_args: dict) -> str:
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


def build_mission_info_hint(student_id: int, fn_args: dict) -> str:
    query_type = fn_args.get("query_type", "today")

    if query_type == "deadline":
        return f"아이가 제출 마감 시간을 물어봤어. 마감은 {DEADLINE_TEXT}이야. 친절하게 안내해줘."
    if query_type == "general_rule":
        return f"아이가 앱 규칙을 물어봤어. 아래 규칙을 친절하게 안내해줘.\n\n{GENERAL_RULE_TEXT}"

    target_date = fn_args.get("target_date", "today")
    mission_date = resolve_mission_query_date(target_date)
    date_label = {
        "today": "오늘",
        "yesterday": "어제",
        "day_before_yesterday": "그저께",
    }.get(target_date, mission_date)

    mission = get_student_mission_db(student_id, mission_date)
    if not mission:
        return (
            f"아이가 {date_label} 배정 미션을 물어봤어.\n"
            f"DB 조회 결과: {date_label} 배정된 미션이 없음.\n"
            "반드시 아래 의미로만 답해.\n"
            f"- {date_label} 배정된 미션은 없다고 말한다.\n"
            "- 시스템 문제, 오류, 잠깐 문제가 생겼다는 식으로 말하지 않는다.\n"
            "- 아이가 다시 알려줘야 한다고 말하지 않는다.\n"
            "- 아이에게 부드럽고 짧게 안내한다.\n"
            "응답 예시:\n"
            f"{date_label} 배정된 미션은 아직 없었어."
        )

    lines = [
        f"아이가 {date_label} 미션 내용을 물어봤어. 아래 정보를 바탕으로 친절하게 안내해줘.\n",
        f"날짜: {date_label}",
    ]
    lines.append(f"미션명: {mission.get('mission_name', '')}")
    if mission.get("mission_rule"):
        lines.append(f"수행 규칙: {mission['mission_rule']}")
    return "\n".join(lines)


def _normalize_history_args(fn_args: dict) -> dict:
    fn_args = fn_args or {}
    query_type = fn_args.get("query_type") or "weekly_summary"
    target_period = fn_args.get("target_period")
    target_date = fn_args.get("target_date")
    target_month = fn_args.get("target_month")

    if query_type in ("today", "오늘"):
        query_type = "daily_summary"
        target_date = target_date or "today"
    elif query_type in ("yesterday", "어제"):
        query_type = "daily_summary"
        target_date = target_date or "yesterday"
    elif query_type in ("day_before_yesterday", "그저께"):
        query_type = "daily_summary"
        target_date = target_date or "day_before_yesterday"
    elif query_type in ("last_week_summary", "지난주"):
        query_type = "weekly_summary"
        target_period = target_period or "last_week"
    elif query_type in ("last_month_summary", "지난달"):
        query_type = "monthly_summary"
        target_period = target_period or "last_month"
    elif query_type in ("month_summary", "월간"):
        query_type = "monthly_summary"

    if target_date and query_type not in ("daily_summary",):
        query_type = "daily_summary"
    if target_month and query_type not in ("monthly_summary",):
        query_type = "monthly_summary"

    return {
        "query_type": query_type,
        "target_period": target_period,
        "target_date": target_date,
        "target_month": target_month,
    }


def build_history_hint(student_id: int, fn_args: dict) -> str:
    args = _normalize_history_args(fn_args)
    query_type = args["query_type"]
    period_name = {
        "daily_summary": "하루",
        "weekly_summary": "주간",
        "monthly_summary": "월간",
    }.get(query_type, "미션")

    result = get_user_history_db(
        student_id,
        query_type,
        target_period=args.get("target_period"),
        target_date=args.get("target_date"),
        target_month=args.get("target_month"),
    )

    if result.get("need_clarification"):
        return f"아이가 미션 기록을 물어봤어. {result['clarification_message']}"

    records = result["records"]
    if not records:
        return (
            f"아이가 {result['period_label']} 미션 기록을 물어봤어. "
            "해당 기간에는 제출된 미션 기록이 없다고 따뜻하게 알려줘."
        )

    success_count = sum(1 for r in records if r["mission_result"] in ("success", "completed"))
    fail_count = len(records) - success_count

    fallback_notice = ""
    if result.get("fallback"):
        fallback_notice = (
            f'"{period_name} 기준으로는 아직 기록이 없어요. '
            f'{result["fallback_label"]} 기록을 함께 보여드릴게요."라고 먼저 말하고 '
        )

    record_lines = []
    for r in records:
        status = "성공" if r["mission_result"] in ("success", "completed") else "실패"
        record_lines.append(f"- {r['checkin_date']}: {r['mission_name']} / {status}")

    return (
        f"아이가 {result['period_label']} 미션 기록을 물어봤어. "
        f"{fallback_notice}아래 내용을 바탕으로 친절하게 알려줘.\n\n"
        f"{result['period_label']} 성공 횟수: {success_count}회\n"
        f"{result['period_label']} 실패 횟수: {fail_count}회\n"
        + "\n".join(record_lines)
    )


# ── 정적 텍스트 힌트 ─────────────────────────────────────────────────────────

def build_fn_hint(detected_function: str, fn_args: dict) -> str:
    """프로필 없을 때 폴백용 제네릭 힌트."""
    if detected_function == "submit_mission_result":
        result_kor = {"success": "결과: 완료.", "fail": "결과: 수행 실패."}.get(fn_args.get("result_type", ""), "")
        return (
            f"아이가 미션 결과를 제출했어. {result_kor} 자연스럽게 받아줘.\n"
            "중요: DB 실행 결과가 없으므로 기록됐다고 말하지 마. "
            "절대로 '미션을 바꿨어', '변경했어' 같은 표현을 쓰지 마."
        )
    if detected_function == "get_mission_info":
        return {
            "today": "아이가 오늘 미션 내용을 물어봤어. 오늘 미션을 친절하게 안내해줘.",
            "deadline": "아이가 제출 마감 시간을 물어봤어. 마감 시간을 안내해줘.",
            "general_rule": "아이가 앱 규칙을 물어봤어. 제출·인증·판정 규칙을 안내해줘.",
        }.get(fn_args.get("query_type", ""), "아이가 미션 정보를 물어봤어. 친절하게 안내해줘.")
    if detected_function == "request_mission_adjustment":
        adjustment_hint = {
            "change": "아이가 다른 미션으로 바꿔달라고 했어. 요청을 접수했다고 알려줘.",
            "easier": "아이가 더 쉬운 미션을 요청했어. 요청을 접수했다고 알려줘.",
            "harder": "아이가 더 어려운 미션을 요청했어. 요청을 접수했다고 알려줘.",
        }.get(fn_args.get("adjustment_type", ""), "아이가 미션 조정을 요청했어. 요청을 접수했다고 알려줘.")
        return f"{adjustment_hint}\n중요: DB 실행 결과가 없으므로 미션이 바뀌었다고 말하지 마."
    if detected_function == "check_mission_equivalency":
        return {
            "behavior": "아이가 다른 행동으로 수행해도 되는지 물어봤어. 대체 수행 가능 여부를 안내해줘.",
            "place": "아이가 다른 장소에서 수행해도 되는지 물어봤어. 대체 수행 가능 여부를 안내해줘.",
            "time": "아이가 다른 시간에 수행해도 되는지 물어봤어. 대체 수행 가능 여부를 안내해줘.",
        }.get(fn_args.get("equivalency_type", ""), "아이가 대체 수행 가능 여부를 물어봤어. 친절하게 안내해줘.")
    if detected_function == "get_user_history":
        return {
            "daily_summary": "아이가 하루 미션 기록을 조회했어. 일간 기록을 안내해줘.",
            "weekly_summary": "아이가 이번 주 미션 기록을 조회했어. 주간 기록을 안내해줘.",
            "monthly_summary": "아이가 이번 달 미션 기록을 조회했어. 월간 기록을 안내해줘.",
        }.get(fn_args.get("query_type", ""), "아이가 미션 기록을 조회했어. 기록을 안내해줘.")
    if detected_function == "cancel_mission_action":
        return (
            "아이가 가장 최근 행동을 취소하려고 해. 자연스럽게 받아줘.\n"
            "중요: DB 실행 결과가 없으므로 취소됐다고 말하지 마."
        )
    return f"아이가 '{detected_function}' 기능을 요청했어. 자연스럽게 응답해줘."


def build_conflict_prompt(fn_calls: list[tuple[str, dict]]) -> str:
    names = [_FN_LABELS.get(fn, fn) for fn, _ in fn_calls]
    return (
        f"\n\n아이가 '{names[0]}'하고 '{names[1]}'을 동시에 요청했어. "
        "둘을 한꺼번에 처리할 수 없어. "
        "아이가 둘 중 어떤 걸 원하는 건지 부드럽게 되물어봐."
    )


# ── 오케스트레이션 ───────────────────────────────────────────────────────────

def build_one_hint(student_id: int, fn: str, args: dict, exec_results: ExecResults | None = None) -> str:
    """단일 펑션 힌트. submit/adjustment/cancel은 exec_results 필수."""
    if fn == "submit_mission_result" and exec_results and exec_results.submit:
        return build_submit_hint(exec_results.submit)
    if fn == "request_mission_adjustment" and exec_results and exec_results.adjustment:
        return build_adjustment_hint(exec_results.adjustment)
    if fn == "cancel_mission_action" and exec_results and exec_results.cancel:
        return build_cancel_hint(exec_results.cancel)
    # 읽기 전용 힌트
    if fn == "get_user_history":
        return build_history_hint(student_id, args)
    if fn == "get_mission_info":
        return build_mission_info_hint(student_id, args)
    if fn == "check_mission_equivalency":
        return build_equivalency_hint(student_id, args)
    return build_fn_hint(fn, args)
