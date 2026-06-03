from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Literal

from starlette.concurrency import run_in_threadpool

from database import (
    get_student_mission_db,
    get_pending_action,
    increment_pending_retry,
    resolve_pending,
    save_mission_change_log,
    upsert_user_memory,
)
from executor import (
    AdjustmentStatus,
    ExecResults,
    SubmitStatus,
    execute_adjustment,
    execute_cancel,
    execute_submit,
)
from equivalency_numeric import convert_numeric_value, extract_first_numeric_quantity
from mission_meta import MISSION_META, MissionMeta
from mission_ui_action_service import create_mission_change_method_action, create_mission_dislike_confirm_action
from ollama_client import generate_json_message
from submit_validator import (
    SubmitValidationResult,
    build_submit_validation_response,
    is_smalltalk,
    validate_submit_candidate,
)


DISLIKE_CLASSIFY_TIMEOUT_SEC = float(os.getenv("DISLIKE_CLASSIFY_TIMEOUT_SEC", "15"))
CONFIRMATION_ACTION_FNS = {
    "submit_mission_result",
    "cancel_mission_action",
    "request_mission_adjustment",
}

POSITIVE_EXACT = {
    "응",
    "ㅇ",
    "ㅇㅇ",
    "응응",
    "어",
    "엉",
    "네",
    "넹",
    "넵",
    "예",
    "예스",
    "ㅇㅋ",
    "오케이",
    "그래",
    "좋아",
    "맞아",
    "그걸로",
    "해줘",
}

NEGATIVE_EXACT = {
    "아니",
    "아니요",
    "아뇨",
    "아냐",
    "ㄴ",
    "ㄴㄴ",
    "아님",
    "싫어",
    "취소",
    "말고",
    "다른거",
    "다른거줘",
    "다른걸로",
    "다른거할래",
    "다른걸로할래",
    "그냥바꿔줘",
    "바꿔줘",
}

MISSION_DISLIKE_NEGATIVE_RE = re.compile(r"다른\s*거|다른\s*걸|딴\s*거|딴\s*걸|바꿔|변경")
CONFIRMATION_POSITIVE_RE = re.compile(
    r"(그렇게|그걸로|진행|처리|기록)\s*해줘|"
    r"(응|ㅇㅇ|네|그래|좋아).{0,12}(진행|처리|기록|취소)\s*해줘"
)
CONFIRMATION_NEGATIVE_RE = re.compile(
    r"(하지\s*마|하지마|안\s*할래|안할래|괜찮아|"
    r"취소\s*하지\s*마|취소하지마|기록\s*하지\s*마|기록하지마)"
)

NUMERIC_PARTIAL_RECORD_RE = re.compile(
    r"(여기|이만큼|이\s*정도|이정도)\s*(까지|까지만|만)|"
    r"오늘은\s*여기\s*(까지|까지만)|"
    r"(기록|저장|처리).{0,8}(해줘|ㄱㄱ|고고|진행|하자)?|"
    r"(실패|못\s*했|못했).{0,8}(기록|저장|처리|해줘)|"
    r"(그걸로|그렇게|일단|그냥).{0,8}(기록|저장|처리)|"
    r"그만.{0,8}(기록|저장|처리|할래)|"
    r"여기\s*까지\s*ㄱㄱ|기록\s*ㄱㄱ"
)
NUMERIC_PARTIAL_CONTINUE_RE = re.compile(
    r"더|마저|나중|이따|조금\s*더|좀\s*더|목표\s*까지|채우고|"
    r"기록\s*하지\s*마|기록하지마|저장\s*하지\s*마|저장하지마|"
    r"아직.{0,6}(기록|저장).{0,4}(하지\s*마|하지마)|"
    r"(걷고|하고|해보고|해\s*보고).{0,8}(올게|올께|올래)"
)
NUMERIC_PARTIAL_STATUS_QUESTION_RE = re.compile(
    r"(?:그럼|그러면|이거|이건|그거|지금|현재)?.{0,8}"
    r"(?:미션\s*)?(?:실패|부족|못\s*한|못한).{0,10}"
    r"(?:인가|이야|야|맞|거야|건가|돼|됨|될까|되나|되나요|인가요)"
)
PARTIAL_DIFFICULTY_RECORD_RE = re.compile(
    r"(오늘\s*미션|오늘미션|현재\s*미션|현재미션|이\s*미션|이미션|그걸로|그대로|원래\s*미션|원래미션|"
    r"기록|저장|처리|여기\s*까지|여기까지).{0,12}(기록|저장|처리|해줘|해주라|할래|할게|ㄱㄱ)?"
)
PARTIAL_DIFFICULTY_CHANGE_RE = re.compile(
    r"(쉬운|쉽게|더\s*쉬|더쉬|바꿔|바꾸|변경|교체|다른\s*미션|다른미션|다른\s*거|다른거)"
)
TIME_CONFIRM_RE = re.compile(r"오늘|방금|지금|오늘\s*한|오늘이야|오늘\s*맞|방금\s*했")
TIME_NOT_TODAY_RE = re.compile(r"어제|그저께|엊그제|지난|저번|예전|오늘\s*아니|오늘아니")
REPEATED_CLARIFY_CANCEL_MESSAGE = "기록하려면 오늘 미션을 어떻게 했는지 한 문장으로 다시 말해줘!"

PENDING_CLASSIFY_SYSTEM_PROMPT = """이전 질문에 대한 아이의 답변이야.
긍정이면 yes, 부정이면 no, 애매하면 ambiguous로 분류해.

긍정 예시:
- 응, 좋아, 그래
- 그렇게 해줘
- 진행해줘
- 취소해줘 (이전 질문이 취소 여부를 확인한 경우)
- 기록해줘 (이전 질문이 기록 여부를 확인한 경우)

부정 예시:
- 아니, 하지 마, 괜찮아
- 취소하지 마
- 기록하지 마

출력은 JSON만:
{"result":"yes|no|ambiguous"}
"""

DISLIKE_SIGNAL_RE = re.compile(
    r"싫어|싫다|싫음|재미없어|재미\s*없어|재미없다|재미없음|귀찮아|별로|별로야|하기\s*싫어|하기싫어|하고\s*싶지\s*않아|하고싶지않아"
)

MISSION_DISLIKE_CLASSIFY_SYSTEM_PROMPT = """오늘 미션에 대한 아이의 발화인지 판단해.

true:
- 아이가 오늘 미션을 싫어함
- 재미없어함
- 하기 싫어함
- 귀찮아함
- 별로라고 말함

false:
- 다른 사람 이야기
- 일반 질문
- 예시 문장
- 오늘 미션과 관련 없는 활동 이야기
- 미션을 싫어한다는 뜻이 애매함

주의:
- 띄어쓰기나 가벼운 오타가 있어도 오늘 미션명이 발화에 포함되어 있고 싫어/재미없어/하기 싫어라는 뜻이면 true
- "줄넘기가싫어", "줄넘기 싫어"처럼 붙여 쓴 표현도 true

출력은 JSON만:
{"is_dislike":true|false}
"""


@dataclass
class PendingOutcome:
    action_type: str
    decision: str
    status: str
    message_hint: str
    pending_id: int
    exec_results: ExecResults
    sync_user_message: str | None = None
    skip_memory: bool = True
    ui_action: dict | None = None
    should_reroute: bool = False


def _compact(text: str) -> str:
    return (text or "").replace(" ", "").strip()


def _loads_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


async def classify_pending_reply(user_message: str, action_type: str | None = None) -> str:
    text = _compact(user_message)
    if is_smalltalk(user_message):
        return "ambiguous"
    if action_type in {"submit_confirmation", "natural_language_confirmation"}:
        if CONFIRMATION_NEGATIVE_RE.search(user_message or ""):
            return "no"
        if CONFIRMATION_POSITIVE_RE.search(user_message or ""):
            return "yes"
    if text in POSITIVE_EXACT:
        return "yes"
    if text in NEGATIVE_EXACT:
        return "no"
    if action_type == "mission_dislike_confirm" and has_dislike_signal(user_message):
        return "no"
    if action_type == "mission_dislike_confirm" and MISSION_DISLIKE_NEGATIVE_RE.search(user_message or ""):
        return "no"

    try:
        raw = await generate_json_message(
            PENDING_CLASSIFY_SYSTEM_PROMPT,
            f"action_type: {action_type or ''}\n답변: {user_message}",
            timeout=8.0,
        )
        data = _loads_json_object(raw)
    except Exception as e:
        print(f"[Pending] classify fallback ambiguous error={type(e).__name__}: {e!r}")
        return "ambiguous"

    result = data.get("result")
    if result in {"yes", "no", "ambiguous"}:
        return result
    print(f"[Pending] classify invalid raw={raw[:120]!r}")
    return "ambiguous"


def has_dislike_signal(user_message: str) -> bool:
    return bool(DISLIKE_SIGNAL_RE.search(user_message or ""))


async def classify_mission_dislike(user_message: str, mission_name: str) -> bool:
    if not mission_name or not has_dislike_signal(user_message):
        return False

    raw = ""
    compact_mission = _compact(mission_name)
    compact_message = _compact(user_message)
    mission_related = bool(compact_mission and compact_mission in compact_message)
    try:
        raw = await generate_json_message(
            MISSION_DISLIKE_CLASSIFY_SYSTEM_PROMPT,
            "\n".join([
                f"오늘 미션: {mission_name}",
                f"아이 발화: {user_message}",
                f"공백 제거 오늘 미션: {compact_mission}",
                f"공백 제거 아이 발화: {compact_message}",
                f"공백 제거 기준 미션명 포함 여부: {mission_related}",
            ]),
            timeout=DISLIKE_CLASSIFY_TIMEOUT_SEC,
        )
        data = _loads_json_object(raw)
    except Exception as e:
        print(
            "[Dislike] classify skipped "
            f"error={type(e).__name__}: {e!r} raw={raw[:120]!r}"
        )
        return False

    result = data.get("is_dislike")
    if isinstance(result, bool):
        print(f"[Dislike] classified is_dislike={result} raw={raw[:120]!r}")
        return result
    print(f"[Dislike] invalid raw={raw[:120]!r}")
    return False


def _submit_args_from_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("fn_args", "submit_args", "args"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def _confirmation_branch(payload: dict, decision: str) -> dict:
    if not isinstance(payload, dict):
        return {}
    key = "on_yes" if decision == "yes" else "on_no"
    branch = payload.get(key)
    if isinstance(branch, dict):
        return branch

    # Backward compatibility for pending rows created as submit_confirmation.
    if decision == "yes":
        return {
            "fn": "submit_mission_result",
            "args": _submit_args_from_payload(payload),
        }
    return {
        "fn": "submit_mission_result",
        "args": {**_submit_args_from_payload(payload), "result_type": "fail"},
    }


async def _execute_confirmation_branch(
    student_id: int,
    branch: dict,
    payload: dict,
    user_message: str,
) -> tuple[ExecResults, SubmitValidationResult | None]:
    exec_results = ExecResults()
    validation = None
    fn = branch.get("fn")
    args = branch.get("args") if isinstance(branch.get("args"), dict) else {}
    if fn not in CONFIRMATION_ACTION_FNS:
        print(f"[Pending] confirmation skipped unknown fn={fn!r}")
        return exec_results, validation

    if fn == "submit_mission_result":
        original_message = _sync_user_message_from_payload(payload, user_message)
        mission_id = payload.get("mission_id")
        try:
            mission_id = int(mission_id) if mission_id not in (None, "") else None
        except (TypeError, ValueError):
            mission_id = None
        mission_name = str(payload.get("mission_name") or "")
        mission_row = await run_in_threadpool(get_student_mission_db, student_id)
        validation = validate_submit_candidate(
            user_message=original_message,
            mission_name=mission_name,
            mission_id=mission_id,
            qwen_args=args,
            mission_metadata=mission_row,
        )
        print(
            "[Pending.Validator.submit] "
            f"action={validation.action} "
            f"result={validation.result_type or '-'} "
            f"reason={validation.reason or '-'}"
        )
        if not validation.should_execute:
            return exec_results, validation
        exec_results.submit = await run_in_threadpool(
            execute_submit,
            student_id,
            {**args, "result_type": validation.result_type},
        )
    elif fn == "cancel_mission_action":
        exec_results.cancel = await run_in_threadpool(execute_cancel, student_id, args)
    elif fn == "request_mission_adjustment":
        exec_results.adjustment = await run_in_threadpool(execute_adjustment, student_id, args)
    return exec_results, validation


def _confirmation_hint(branch: dict, decision: str, exec_results: ExecResults) -> str:
    fn = branch.get("fn")
    explicit_hint = branch.get("message_hint")
    if isinstance(explicit_hint, str) and explicit_hint.strip():
        return explicit_hint

    if fn == "submit_mission_result":
        if exec_results.submit:
            if decision == "yes":
                return _submit_hint(exec_results.submit.status.value, exec_results.submit.result_type)
            return _submit_failure_hint(exec_results.submit.status.value)
        return "아이의 확인 답변에 따라 기록하려 했지만 문제가 있었어. 잠시 후 다시 시도해달라고 짧게 말해줘."

    if fn == "request_mission_adjustment":
        return _adjustment_hint(exec_results)

    if fn == "cancel_mission_action":
        if exec_results.cancel:
            status = exec_results.cancel.status.value
            if status == "cancelled_submit":
                return "아이가 확인 질문에 긍정으로 답해서 방금 미션 기록을 취소했어. 짧게 알려줘."
            if status == "cancelled_adjustment":
                return "아이가 확인 질문에 긍정으로 답해서 방금 미션 변경을 취소했어. 짧게 알려줘."
            if status == "nothing_to_cancel":
                return "취소할 최근 미션 행동이 없었어. 그 사실만 짧게 알려줘."
        return "취소 처리 중 문제가 있었어. 잠시 후 다시 시도해달라고 짧게 말해줘."

    if decision == "yes":
        return "아이가 이전 확인 질문에 긍정으로 답했어. 짧게 알겠다고 말해줘."
    return "아이가 이전 확인 질문에 부정으로 답했어. 짧게 알겠다고 말해줘."


def _sync_user_message_from_payload(payload: dict, fallback: str) -> str:
    if not isinstance(payload, dict):
        return fallback
    value = payload.get("original_user_message") or payload.get("user_message")
    return value if isinstance(value, str) and value.strip() else fallback


def _mission_context_from_payload(payload: dict, mission_row: dict | None = None) -> tuple[str, int | None]:
    mission_id = payload.get("mission_id") if isinstance(payload, dict) else None
    try:
        mission_id = int(mission_id) if mission_id not in (None, "") else None
    except (TypeError, ValueError):
        mission_id = None

    mission_name = str(payload.get("mission_name") or "") if isinstance(payload, dict) else ""
    if mission_row:
        mission_name = mission_name or str(mission_row.get("mission_name") or "")
        if mission_id is None:
            row_mission_id = mission_row.get("mission_id")
            try:
                mission_id = int(row_mission_id) if row_mission_id not in (None, "") else None
            except (TypeError, ValueError):
                mission_id = None

    return mission_name, mission_id


def _direct_pending_decision(user_message: str) -> str | None:
    text = _compact(user_message)
    if text in POSITIVE_EXACT:
        return "yes"
    if text in NEGATIVE_EXACT:
        return "no"
    return None


def _prohibit_confirmation_message(meta: MissionMeta, decision: str) -> str:
    target = next((keyword for keyword in meta.target_kw if keyword), "금지한 것")
    if decision == "yes":
        return f"{target} 안 먹었어요"
    return f"{target} 먹었어요"


async def _cancel_repeated_clarify(
    pending_id: int,
    exec_results: ExecResults | None = None,
) -> PendingOutcome:
    await run_in_threadpool(resolve_pending, pending_id, "cancelled")
    return PendingOutcome(
        action_type="natural_language_confirmation",
        decision="clarify_cancelled",
        status="cancelled",
        message_hint=f"'{REPEATED_CLARIFY_CANCEL_MESSAGE}'",
        pending_id=pending_id,
        exec_results=exec_results or ExecResults(),
    )


def _submit_failure_hint(result_status: str) -> str:
    if result_status == SubmitStatus.SAVED.value:
        return "아이가 확인 질문에 부정으로 답해서 오늘 미션을 실패로 기록했어. 짧게 따뜻하게 받아줘."
    if result_status == SubmitStatus.ALREADY_SUBMITTED.value:
        return "아이가 확인 질문에 부정으로 답했지만 오늘 미션 결과가 이미 저장되어 있었어. 이미 저장됐다고 짧게 알려줘."
    if result_status == SubmitStatus.NO_MISSION.value:
        return "아이가 확인 질문에 부정으로 답했지만 오늘 배정된 미션이 없어. 그 사실만 짧게 알려줘."
    return "아이가 확인 질문에 부정으로 답했지만 기록 저장에 문제가 있었어. 잠시 후 다시 시도해달라고 짧게 말해줘."


def _submit_hint(result_status: str, result_type: str | None = None) -> str:
    if result_status == SubmitStatus.SAVED.value:
        if result_type == "success":
            return "아이가 확인 질문에 긍정으로 답해서 오늘 미션을 성공으로 기록했어. 짧게 칭찬해줘."
        return "아이가 확인 질문에 긍정으로 답해서 오늘 미션을 실패로 기록했어. 짧게 따뜻하게 받아줘."
    if result_status == SubmitStatus.ALREADY_SUBMITTED.value:
        return "아이가 확인 질문에 긍정으로 답했지만 오늘 미션 결과가 이미 저장되어 있었어. 이미 저장됐다고 짧게 알려줘."
    if result_status == SubmitStatus.NO_MISSION.value:
        return "아이가 확인 질문에 긍정으로 답했지만 오늘 배정된 미션이 없어. 그 사실만 짧게 알려줘."
    return "아이가 확인 질문에 긍정으로 답했지만 기록 저장에 문제가 있었어. 잠시 후 다시 시도해달라고 짧게 말해줘."


def _adjustment_hint(exec_results: ExecResults) -> str:
    adjustment = exec_results.adjustment
    result_status = adjustment.status.value if adjustment else "db_error"
    if result_status == AdjustmentStatus.CHANGED.value:
        return "\n".join([
            "아이가 기존 미션을 오늘 해보자는 제안을 거절해서 다른 미션으로 바꿨어.",
            "이전 미션에 대해 짧게 공감하고 새 미션을 알려줘.",
            f"이전 미션: {adjustment.old_mission_name or ''}",
            f"새 미션: {adjustment.new_mission_name or ''}",
        ])
    if result_status == AdjustmentStatus.ALREADY_SUBMITTED.value:
        return "아이가 기존 미션을 거절했지만 오늘 미션 결과가 이미 저장되어 있어서 바꿀 수 없어. 먼저 기록을 취소해야 한다고 짧게 말해줘."
    if result_status == AdjustmentStatus.NO_MISSION.value:
        return "아이가 기존 미션을 거절했지만 오늘 배정된 미션이 없어. 그 사실만 짧게 알려줘."
    if result_status == AdjustmentStatus.NO_ALTERNATIVE.value:
        return "아이가 기존 미션을 거절했지만 지금 바꿀 수 있는 다른 미션이 없어. 오늘은 현재 미션으로 가야 한다고 짧게 말해줘."
    return "아이가 기존 미션을 거절했지만 미션 변경 중 문제가 있었어. 잠시 후 다시 시도해달라고 짧게 말해줘."


_TOO_EASY_RE = re.compile(r"쉬워|쉽다|너무\s*쉬|쉬운|시시해|시시함")
_TOO_HARD_RE = re.compile(r"어려워|어렵|힘들어|힘들다|못하겠|어려움")
_CANT_DO_RE = re.compile(r"못\s*해|못함|안\s*돼|안돼|할\s*수\s*없|할수없|오늘\s*못|상황이")

_MC_ESCAPE_KEEP_RE = re.compile(
    r"안\s*바꿀|안\s*바꿔(?!\s*도)|별로\s*안\s*바꾸|그냥\s*둬|그냥\s*지금\s*미션|원래\s*미션\s*할|오늘\s*미션\s*할|지금\s*미션\s*할|안\s*해도\s*돼"
)
_MC_ESCAPE_FAIL_RE = re.compile(
    r"실패(?!\s*[는은])|못\s*했|못\s*함|안\s*했|안\s*함|까먹고\s*못|까먹어서\s*못|까먹었어|패스"
)
_MC_ESCAPE_SUCCESS_RE = re.compile(
    r"성공으로\s*기록|다\s*했|완료했|끝냈"
)


def classify_mission_change_escape(user_message: str) -> Literal["keep", "fail", "success"] | None:
    """미션 변경 pending 중 탈출 의도 감지. None이면 기존 변경 로직 진행."""
    text = user_message or ""
    if _MC_ESCAPE_KEEP_RE.search(text):
        return "keep"
    if _MC_ESCAPE_FAIL_RE.search(text):
        return "fail"
    if _MC_ESCAPE_SUCCESS_RE.search(text):
        return "success"
    return None


_PENDING_ROUTE_OUT_RE = re.compile(
    r"(?:미션\s*(?:바꿔|바꾸|변경|교체)|다른\s*.+미션|새\s*미션)"
    r"|(?:오늘|지금|현재|내)\s*미션[\s\S]{0,12}(?:뭐|알려|어떻게|확인)"
    r"|(?:미션\s*)?(?:성공|실패|완료)(?:했|했다고|으로\s*기록)"
    r"|(?:취소|되돌려|원래대로)"
    r"|(?:뭐야|뭔데|어떻게\s*하|방법|뜻|얼마나\s*걸)"
)


_PENDING_ESCAPE_CANCEL_RE = re.compile(
    r"(?:"
    r"(?:성공|실패|완료|제출|기록|미션\s*변경|바꾼\s*거|바뀐\s*거|이전\s*미션).{0,12}"
    r"(?:취소|되돌려|원래대로|무효|없던\s*걸로)"
    r"|(?:취소|되돌려|원래대로|무효|없던\s*걸로).{0,12}"
    r"(?:성공|실패|완료|제출|기록|미션\s*변경|바꾼\s*거|바뀐\s*거|이전\s*미션)?"
    r"|바꾸지\s*마|변경하지\s*마|그대로\s*할래|원래\s*꺼로|원래\s*걸로"
    r")"
)
_PENDING_ESCAPE_NEW_INTENT_RE = re.compile(
    r"(?:미션\s*(?:바꿔|바꾸|변경|교체)|다른\s*.+미션|새\s*미션|추천해\s*줘)"
    r"|(?:오늘|지금|현재|내)\s*미션[\s\S]{0,12}(?:뭐|알려|어떻게|확인)"
    r"|(?:미션[\s\S]{0,12}(?:바뀐|변경됐|변경\s*된|바꾼\s*거|바뀐\s*거))"
    r"|(?:뭐야|뭔데|어떻게\s*하|방법|뜻|얼마나\s*걸)"
)
_PENDING_EXPLICIT_SUBMIT_RE = re.compile(
    r"(?:"
    r"(?:성공|실패|완료)(?:했|했다고|으로\s*기록|로\s*기록|처리|로\s*해|으로\s*해)"
    r"|(?:다\s*했|완료했|끝냈|해냈)(?:어|음|다)?"
    r"|(?:못\s*했|못\s*함|안\s*했|안\s*함|까먹|실패로\s*해|실패로\s*기록)"
    r")"
)
_AMBIGUOUS_SHORT_REPLY_RE = re.compile(
    r"^(음+|어+|아+|그냥|몰라|모르겠어|잘\s*모르겠어|아무튼|일단|글쎄|글쎄다|흠+|응\?*)$"
)
_ACTION_ANSWER_HINT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(분|초|시간|회|번|개|잔|컵|ml|mL|L|리터|바퀴|봉지|입|세트|보|걸음)"
    r"|(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|반)\s*(분|초|시간|회|번|개|잔|컵|바퀴|봉지|입|세트|보|걸음)"
    r"|했어|했어요|완료|끝냈|다\s*했|먹었|마셨|걸었|봤|씻었|탔|올라갔|줄였|안\s*했|못\s*했"
)


def _looks_like_pending_answer(
    user_message: str,
    action_type: str | None = None,
    clarify_reason: str | None = None,
) -> bool:
    text = (user_message or "").strip()
    compact = _compact(text)
    if not text:
        return False

    if _AMBIGUOUS_SHORT_REPLY_RE.search(text) or _AMBIGUOUS_SHORT_REPLY_RE.search(compact):
        return False
    if compact in POSITIVE_EXACT or compact in NEGATIVE_EXACT:
        return True
    if _extract_equivalency_numeric_reply(text):
        return True
    if _ACTION_ANSWER_HINT_RE.search(text):
        return True
    if action_type == "mission_change_reason" and len(compact) >= 2:
        return True
    if clarify_reason:
        return len(compact) >= 4 and not is_smalltalk(text)
    return False


def classify_pending_message(
    user_message: str,
    action_type: str | None = None,
    payload: dict | None = None,
) -> Literal[
    "escape_cancel",
    "escape_new_intent",
    "explicit_submit",
    "pending_answer",
    "unclear_repeat",
]:
    """pending 상태의 최신 발화를 먼저 분류한다.

    우선순위는 취소/새 의도/명확한 제출/기존 pending 답변/불명확 반복이다.
    """
    text = (user_message or "").strip()
    if not text:
        return "unclear_repeat"

    # "성공 기록 취소해줘"처럼 제출 표현과 취소 표현이 섞이면 취소/새 의도가 우선이다.
    if _PENDING_ESCAPE_CANCEL_RE.search(text):
        return "escape_cancel"
    if _PENDING_ESCAPE_NEW_INTENT_RE.search(text):
        return "escape_new_intent"
    if _PENDING_EXPLICIT_SUBMIT_RE.search(text):
        return "explicit_submit"

    payload = payload or {}
    clarify_reason = payload.get("clarify_reason") if isinstance(payload, dict) else None
    if _looks_like_pending_answer(text, action_type, clarify_reason):
        return "pending_answer"
    return "unclear_repeat"


def _pending_reroute_outcome(
    pending_id: int,
    action_type: str,
    decision: str,
) -> PendingOutcome:
    return PendingOutcome(
        action_type=action_type,
        decision=decision,
        status="cancelled",
        message_hint="",
        pending_id=pending_id,
        exec_results=ExecResults(),
        should_reroute=True,
    )


def _should_route_out_of_pending(action_type: str, payload: dict, user_message: str) -> bool:
    if action_type == "mission_change_reason":
        return False
    text = (user_message or "").strip()
    if not text or text in POSITIVE_EXACT or text in NEGATIVE_EXACT:
        return False
    if _extract_equivalency_numeric_reply(text):
        return False
    return bool(_PENDING_ROUTE_OUT_RE.search(text))


def _mission_quantity_detail_question(mission_name: str, mission_id: int | None) -> str:
    meta = MISSION_META.get(mission_id or -1)
    goal = meta.numeric if meta else None
    title = (mission_name or "오늘 미션").strip()
    if not goal:
        return "오늘 미션을 어떤 행동으로 얼마나 했는지 한 문장으로 말해줘!"

    unit = goal.unit
    if unit in {"분", "초", "시간"}:
        return f"오늘 미션 기준으로 몇 {unit} 했는지 한 문장으로 말해줘!"
    if unit in {"회", "번"}:
        return "오늘 미션 기준으로 몇 번 했는지 한 문장으로 말해줘!"
    if unit in {"ml", "L", "리터", "잔", "컵"}:
        return "오늘 미션 기준으로 얼마나 마셨는지 한 문장으로 말해줘!"
    if unit in {"바퀴", "봉지", "개", "입", "세트", "보", "걸음"}:
        return f"오늘 미션 기준으로 몇 {unit}인지 한 문장으로 말해줘!"
    return f"{title}을 얼마나 했는지 한 문장으로 말해줘!"


_CHANGE_REASON_CLASSIFY_SYSTEM_PROMPT = """아이가 미션을 바꾸고 싶은 이유를 말했어.
아래 5가지 중 가장 가까운 이유 1개를 골라줘.

too_easy: 미션이 너무 쉬움
too_hard: 미션이 너무 어렵거나 힘듦
dislike: 미션이 싫거나 재미없음
cant_do: 오늘은 상황상 할 수 없음
just_change: 그냥 다른 걸 하고 싶음

출력은 JSON만:
{"reason":"too_easy|too_hard|dislike|cant_do|just_change"}
"""

_CHANGE_REASON_TIMEOUT_SEC = float(os.getenv("CHANGE_REASON_CLASSIFY_TIMEOUT_SEC", "10"))


def _classify_change_reason_by_keyword(user_message: str) -> str | None:
    if _TOO_HARD_RE.search(user_message or ""):
        return "too_hard"
    if _TOO_EASY_RE.search(user_message or ""):
        return "too_easy"
    if _CANT_DO_RE.search(user_message or ""):
        return "cant_do"
    if has_dislike_signal(user_message):
        return "dislike"
    return None


async def _classify_change_reason(user_message: str) -> str:
    reason = _classify_change_reason_by_keyword(user_message)
    if reason:
        return reason
    try:
        raw = await generate_json_message(
            _CHANGE_REASON_CLASSIFY_SYSTEM_PROMPT,
            f"아이 발화: {user_message}",
            timeout=_CHANGE_REASON_TIMEOUT_SEC,
        )
        data = _loads_json_object(raw)
        result = data.get("reason", "")
        if result in {"too_easy", "too_hard", "dislike", "cant_do", "just_change"}:
            return result
    except Exception as e:
        print(f"[ChangeReason] classify failed: {type(e).__name__}: {e!r}")
    return "just_change"


_CHANGE_REASON_HINTS = {
    "too_easy": "아이가 미션이 너무 쉽다고 해서 조금 더 어려운 미션으로 바꿔줬어. 짧게 알려줘.",
    "too_hard": "아이가 미션이 너무 어렵다고 해서 더 쉬운 미션으로 바꿔줬어. 짧게 공감하고 새 미션을 알려줘.",
    "cant_do": "아이가 오늘은 상황상 미션을 할 수 없다고 해서 다른 미션으로 바꿔줬어. 짧게 알려줘.",
    "just_change": "아이가 다른 미션을 원해서 바꿔줬어. 새 미션을 짧게 알려줘.",
}

_MISSION_DISLIKE_PENDING_HINT = (
    "아이가 오늘 미션을 싫어하거나 재미없어한다고 말했어. "
    "아직 미션은 바꾸지 않았어. 그래도 오늘 딱 한 번만 해볼지 짧게 물어봐."
)


async def _handle_mission_change_reason(
    student_id: int,
    session_id: str,
    pending_id: int,
    payload: dict,
    retry_count: int,
    user_message: str,
) -> PendingOutcome:
    mission_id = payload.get("mission_id")
    activity_key = payload.get("activity_key")
    exec_results = ExecResults()

    # ── 탈출 의도 먼저 검사 ──────────────────────────────────────────
    escape = classify_mission_change_escape(user_message)
    if escape == "keep":
        await run_in_threadpool(resolve_pending, pending_id, "cancelled")
        return PendingOutcome(
            action_type="mission_change_reason",
            decision="escaped_keep",
            status="cancelled",
            message_hint="아이가 미션 변경을 취소했어. '좋아, 지금 미션 그대로 할게!' 라고 짧게 말해줘.",
            pending_id=pending_id,
            exec_results=exec_results,
        )
    if escape == "success":
        await run_in_threadpool(resolve_pending, pending_id, "cancelled")
        return PendingOutcome(
            action_type="mission_change_reason",
            decision="ambiguous",
            status="cancelled",
            message_hint=(
                "아이가 미션 변경 중 성공 기록 의사를 말했지만 수행 내용이 부족해. "
                "'오늘 미션을 어떻게 했는지 한 번만 더 알려줘!'라고 짧게 물어봐. DB는 건드리지 마."
            ),
            pending_id=pending_id,
            exec_results=exec_results,
        )
    if escape == "fail":
        exec_results.submit = await run_in_threadpool(
            execute_submit, student_id, {"result_type": "fail"}
        )
        if exec_results.submit.status is SubmitStatus.SAVED:
            await run_in_threadpool(resolve_pending, pending_id, "cancelled")
        return PendingOutcome(
            action_type="mission_change_reason",
            decision="escaped_fail",
            status="escaped",
            message_hint=_submit_failure_hint(exec_results.submit.status.value),
            pending_id=pending_id,
            exec_results=exec_results,
        )
    # ─────────────────────────────────────────────────────────────────

    reason = _classify_change_reason_by_keyword(user_message)

    if reason is None:
        if retry_count >= 2:
            await run_in_threadpool(resolve_pending, pending_id, "cancelled")
            return PendingOutcome(
                action_type="mission_change_reason",
                decision="overflow_clarify",
                status="cancelled",
                message_hint=(
                    "아이가 뭘 원하는지 계속 잘 모르겠어. "
                    "'미션 바꿀 거야? 아니면 오늘 미션 성공/실패로 기록할 거야?' "
                    "라고 한 번만 짧게 물어봐."
                ),
                pending_id=pending_id,
                exec_results=ExecResults(),
            )
        else:
            updated = await run_in_threadpool(increment_pending_retry, pending_id)
            retry_after = updated.get("retry_count") if updated else retry_count + 1
            print(f"[ChangeReason] unrecognized retry={retry_after}")
            return PendingOutcome(
                action_type="mission_change_reason",
                decision="ambiguous",
                status=f"retry_{retry_after}",
                message_hint="아이가 왜 바꾸고 싶은지 아직 잘 모르겠어. 너무 쉬운지, 어려운지, 싫은지, 다른 걸 하고 싶은지 다시 한 번 짧게 물어봐.",
                pending_id=pending_id,
                exec_results=exec_results,
            )

    if reason is None:
        reason = await _classify_change_reason(user_message)

    print(f"[ChangeReason] reason={reason}")

    if reason == "dislike":
        await run_in_threadpool(resolve_pending, pending_id, "accepted")
        dislike_payload = {
            "mission_id": mission_id,
            "mission_name": payload.get("mission_name", ""),
            "mission_rule": payload.get("mission_rule", ""),
            "activity_key": activity_key,
            "reason_type": "dislike",
            "original_user_message": user_message,
        }
        ui_action = await create_mission_dislike_confirm_action(student_id, session_id, dislike_payload)
        if mission_id:
            try:
                await run_in_threadpool(save_mission_change_log, student_id, mission_id, "dislike")
            except Exception as e:
                print(f"[ChangeReason] log failed: {e!r}")
        if activity_key:
            try:
                await run_in_threadpool(upsert_user_memory, student_id, activity_key, "preference", -1)
            except Exception as e:
                print(f"[ChangeReason] dislike memory upsert failed: {e!r}")
        return PendingOutcome(
            action_type="mission_change_reason",
            decision="dislike",
            status="chained_dislike",
            message_hint=_MISSION_DISLIKE_PENDING_HINT,
            pending_id=pending_id,
            exec_results=exec_results,
            ui_action=ui_action,
        )

    if reason == "just_change":
        await run_in_threadpool(resolve_pending, pending_id, "accepted")
        method_payload = {
            "mission_id": mission_id,
            "mission_name": payload.get("mission_name", ""),
            "mission_rule": payload.get("mission_rule", ""),
            "activity_key": activity_key,
            "reason_type": "just_change",
            "source_reason": "just_change",
            "original_user_message": user_message,
        }
        ui_action = await create_mission_change_method_action(student_id, session_id, method_payload)
        return PendingOutcome(
            action_type="mission_change_reason",
            decision="just_change",
            status="chained_method",
            message_hint="어떤 방식으로 바꿔볼까?",
            pending_id=pending_id,
            exec_results=exec_results,
            ui_action=ui_action,
        )

    adjustment_type_map = {"too_easy": "harder", "too_hard": "easier"}
    adjustment_type = adjustment_type_map.get(reason, "change")
    exec_results.adjustment = await run_in_threadpool(
        execute_adjustment, student_id, {"adjustment_type": adjustment_type}
    )

    if reason == "too_hard" and activity_key:
        try:
            await run_in_threadpool(upsert_user_memory, student_id, activity_key, "difficulty")
        except Exception as e:
            print(f"[ChangeReason] memory upsert failed: {e!r}")

    if mission_id:
        try:
            await run_in_threadpool(save_mission_change_log, student_id, mission_id, reason)
        except Exception as e:
            print(f"[ChangeReason] log failed: {e!r}")

    await run_in_threadpool(resolve_pending, pending_id, "accepted")
    hint = _CHANGE_REASON_HINTS.get(reason) or _adjustment_hint(exec_results)
    return PendingOutcome(
        action_type="mission_change_reason",
        decision=reason,
        status="accepted",
        message_hint=hint,
        pending_id=pending_id,
        exec_results=exec_results,
    )


async def _execute_dislike_fallback_change(student_id: int) -> ExecResults:
    exec_results = ExecResults()
    exec_results.adjustment = await run_in_threadpool(
        execute_adjustment,
        student_id,
        {"adjustment_type": "change"},
    )
    return exec_results


def _classify_numeric_partial_reply(user_message: str) -> str:
    text = user_message or ""
    compact = _compact(text)
    if not compact:
        return "ambiguous"
    if NUMERIC_PARTIAL_STATUS_QUESTION_RE.search(text) or NUMERIC_PARTIAL_STATUS_QUESTION_RE.search(compact):
        return "status_question"
    if NUMERIC_PARTIAL_CONTINUE_RE.search(text) or NUMERIC_PARTIAL_CONTINUE_RE.search(compact):
        return "continue"
    if NUMERIC_PARTIAL_RECORD_RE.search(text) or NUMERIC_PARTIAL_RECORD_RE.search(compact):
        return "record_now"
    return "ambiguous"


def _classify_partial_difficulty_reply(user_message: str) -> str:
    text = user_message or ""
    compact = _compact(text)
    if not compact:
        return "ambiguous"
    if PARTIAL_DIFFICULTY_CHANGE_RE.search(text) or PARTIAL_DIFFICULTY_CHANGE_RE.search(compact):
        return "change_easier"
    if PARTIAL_DIFFICULTY_RECORD_RE.search(text) or PARTIAL_DIFFICULTY_RECORD_RE.search(compact):
        return "record_current"
    return "ambiguous"


def _extract_equivalency_numeric_reply(user_message: str) -> tuple[float, str] | None:
    return extract_first_numeric_quantity(user_message)


async def _handle_numeric_partial_confirmation(
    student_id: int,
    pending_id: int,
    payload: dict,
    retry_count: int,
    user_message: str,
) -> PendingOutcome:
    decision = _classify_numeric_partial_reply(user_message)
    exec_results = ExecResults()
    print(f"[Pending.numeric] decision={decision} retry={retry_count}")

    if decision == "record_now":
        choice = (payload.get("choices") or {}).get("record_now") or {}
        args = choice.get("args") if isinstance(choice.get("args"), dict) else {"result_type": "fail"}
        exec_results.submit = await run_in_threadpool(
            execute_submit,
            student_id,
            {**args, "result_type": "fail"},
        )
        await run_in_threadpool(resolve_pending, pending_id, "accepted")
        return PendingOutcome(
            action_type="natural_language_confirmation",
            decision=decision,
            status="accepted",
            message_hint=_numeric_record_hint(exec_results.submit.status.value),
            pending_id=pending_id,
            exec_results=exec_results,
            sync_user_message=_sync_user_message_from_payload(payload, user_message),
        )

    if decision == "continue":
        await run_in_threadpool(resolve_pending, pending_id, "cancelled")
        return PendingOutcome(
            action_type="natural_language_confirmation",
            decision=decision,
            status="cancelled",
            message_hint="아이가 아직 기록하지 않고 목표까지 더 해보겠다고 답했어. 짧게 응원해줘.",
            pending_id=pending_id,
            exec_results=exec_results,
        )

    if decision == "status_question":
        if retry_count >= 2:
            return await _cancel_repeated_clarify(pending_id, exec_results)
        updated = await run_in_threadpool(increment_pending_retry, pending_id)
        retry_after_update = updated.get("retry_count") if updated else retry_count + 1
        return PendingOutcome(
            action_type="natural_language_confirmation",
            decision="numeric_status_question",
            status=f"retry_{retry_after_update}",
            message_hint="'응, 지금 기준으로는 부족해. 여기까지 실패로 기록할까?'",
            pending_id=pending_id,
            exec_results=exec_results,
        )

    if retry_count >= 2:
        return await _cancel_repeated_clarify(pending_id, exec_results)

    next_retry = retry_count + 1
    updated = await run_in_threadpool(increment_pending_retry, pending_id)
    retry_after_update = updated.get("retry_count") if updated else next_retry
    return PendingOutcome(
        action_type="natural_language_confirmation",
        decision=decision,
        status=f"retry_{retry_after_update}",
        message_hint="아이가 여기까지 기록할지 더 해볼지 애매하게 답했어. DB는 건드리지 말고 '기록할지, 더 해볼지 한 번만 골라줘!'라고 짧게 다시 물어봐.",
        pending_id=pending_id,
        exec_results=exec_results,
    )


async def _handle_partial_difficulty_confirmation(
    student_id: int,
    pending_id: int,
    payload: dict,
    retry_count: int,
    user_message: str,
) -> PendingOutcome:
    decision = _classify_partial_difficulty_reply(user_message)
    exec_results = ExecResults()
    print(f"[Pending.partial_difficulty] decision={decision} retry={retry_count}")

    if decision == "record_current":
        choice = (payload.get("choices") or {}).get("record_current") or {}
        args = choice.get("args") if isinstance(choice.get("args"), dict) else {"result_type": "fail"}
        exec_results.submit = await run_in_threadpool(
            execute_submit,
            student_id,
            {**args, "result_type": "fail"},
        )
        await run_in_threadpool(resolve_pending, pending_id, "accepted")
        return PendingOutcome(
            action_type="natural_language_confirmation",
            decision=decision,
            status="accepted",
            message_hint=_partial_record_hint(exec_results.submit.status.value),
            pending_id=pending_id,
            exec_results=exec_results,
            sync_user_message=_sync_user_message_from_payload(payload, user_message),
        )

    if decision == "change_easier":
        choice = (payload.get("choices") or {}).get("change_easier") or {}
        args = choice.get("args") if isinstance(choice.get("args"), dict) else {"adjustment_type": "easier"}
        exec_results.adjustment = await run_in_threadpool(
            execute_adjustment,
            student_id,
            {**args, "adjustment_type": "easier"},
        )
        await run_in_threadpool(resolve_pending, pending_id, "accepted")
        return PendingOutcome(
            action_type="natural_language_confirmation",
            decision=decision,
            status="accepted",
            message_hint=_adjustment_hint(exec_results),
            pending_id=pending_id,
            exec_results=exec_results,
        )

    if retry_count >= 2:
        return await _cancel_repeated_clarify(pending_id, exec_results)

    next_retry = retry_count + 1
    updated = await run_in_threadpool(increment_pending_retry, pending_id)
    retry_after_update = updated.get("retry_count") if updated else next_retry
    return PendingOutcome(
        action_type="natural_language_confirmation",
        decision="ambiguous",
        status=f"retry_{retry_after_update}",
        message_hint="아이가 쉬운 미션으로 바꿀지 오늘 미션으로 기록할지 애매하게 답했어. DB는 건드리지 말고 '쉬운 미션으로 바꿀지, 오늘 미션으로 기록할지 한 번만 골라줘!'라고 다시 물어봐.",
        pending_id=pending_id,
        exec_results=exec_results,
    )


async def _handle_clarify_negation_confirmation(
    student_id: int,
    pending_id: int,
    payload: dict,
    user_message: str,
) -> PendingOutcome | None:
    mission_row = await run_in_threadpool(get_student_mission_db, student_id)
    mission_name, mission_id = _mission_context_from_payload(payload, mission_row)
    meta = MISSION_META.get(mission_id) if mission_id else None
    direct_decision = _direct_pending_decision(user_message)
    if meta and meta.type == "prohibit" and direct_decision in {"yes", "no"}:
        result_type = "success" if direct_decision == "yes" else "fail"
        candidate_message = _prohibit_confirmation_message(meta, direct_decision)
        current_payload = {
            **payload,
            "mission_id": mission_id,
            "mission_name": mission_name,
            "original_user_message": candidate_message,
            "user_message": candidate_message,
        }
        branch = {"fn": "submit_mission_result", "args": {"result_type": result_type}}
        exec_results, validation = await _execute_confirmation_branch(
            student_id,
            branch,
            current_payload,
            user_message,
        )
        if not (validation and validation.should_execute):
            return None
        await run_in_threadpool(resolve_pending, pending_id, "accepted")
        return PendingOutcome(
            action_type="natural_language_confirmation",
            decision=f"clarify_negation_prohibit_{direct_decision}",
            status="accepted",
            message_hint=_submit_hint(
                exec_results.submit.status.value if exec_results.submit else SubmitStatus.DB_ERROR.value,
                result_type,
            ),
            pending_id=pending_id,
            exec_results=exec_results,
            sync_user_message=candidate_message,
        )

    current_payload = {
        **payload,
        "original_user_message": user_message,
        "user_message": user_message,
    }
    original_message = _sync_user_message_from_payload(current_payload, user_message)
    current_validation = validate_submit_candidate(
        user_message=user_message,
        mission_name=mission_name,
        mission_id=mission_id,
        qwen_args={},
        mission_metadata=mission_row,
    )
    if not (current_validation.should_execute and current_validation.result_type == "fail"):
        return None
    branch = {"fn": "submit_mission_result", "args": {"result_type": "fail"}}
    exec_results, validation = await _execute_confirmation_branch(
        student_id,
        branch,
        current_payload,
        user_message,
    )
    if not (validation and validation.should_execute and validation.result_type == "fail"):
        return None
    await run_in_threadpool(resolve_pending, pending_id, "cancelled")
    return PendingOutcome(
        action_type="natural_language_confirmation",
        decision="clarify_negation_fail",
        status="cancelled",
        message_hint=_submit_failure_hint(exec_results.submit.status.value if exec_results.submit else SubmitStatus.DB_ERROR.value),
        pending_id=pending_id,
        exec_results=exec_results,
        sync_user_message=original_message,
    )


async def _execute_time_confirmation_submit(
    student_id: int,
    pending_id: int,
    payload: dict,
    user_message: str,
    candidate_message: str,
    result_type: str,
    decision: str,
) -> PendingOutcome:
    exec_results = ExecResults()
    current_payload = {
        **payload,
        "original_user_message": candidate_message,
        "user_message": candidate_message,
    }
    branch = {"fn": "submit_mission_result", "args": {"result_type": result_type}}
    exec_results, validation = await _execute_confirmation_branch(
        student_id,
        branch,
        current_payload,
        user_message,
    )
    if not (validation and validation.should_execute):
        updated = await run_in_threadpool(increment_pending_retry, pending_id)
        retry_after_update = updated.get("retry_count") if updated else 1
        return PendingOutcome(
            action_type="natural_language_confirmation",
            decision="time_ambiguous",
            status=f"retry_{retry_after_update}",
            message_hint="'오늘 한 건지, 다른 날 한 건지만 알려줘!'",
            pending_id=pending_id,
            exec_results=exec_results,
        )
    await run_in_threadpool(resolve_pending, pending_id, "accepted")
    return PendingOutcome(
        action_type="natural_language_confirmation",
        decision=decision,
        status="accepted",
        message_hint=_submit_hint(
            exec_results.submit.status.value if exec_results.submit else SubmitStatus.DB_ERROR.value,
            validation.result_type,
        ),
        pending_id=pending_id,
        exec_results=exec_results,
        sync_user_message=candidate_message,
    )


async def _handle_clarify_time_ambiguous_confirmation(
    student_id: int,
    pending_id: int,
    payload: dict,
    retry_count: int,
    user_message: str,
) -> PendingOutcome:
    exec_results = ExecResults()
    original_message = _sync_user_message_from_payload(payload, "")
    mission_row = await run_in_threadpool(get_student_mission_db, student_id)
    mission_name, mission_id = _mission_context_from_payload(payload, mission_row)

    print(f"[Pending.time] retry={retry_count} original={bool(original_message)}")

    if TIME_NOT_TODAY_RE.search(user_message or ""):
        await run_in_threadpool(resolve_pending, pending_id, "cancelled")
        return PendingOutcome(
            action_type="natural_language_confirmation",
            decision="time_not_today",
            status="cancelled",
            message_hint="'오늘 미션만 기록할 수 있어!'",
            pending_id=pending_id,
            exec_results=exec_results,
        )

    current_validation = validate_submit_candidate(
        user_message=user_message,
        mission_name=mission_name,
        mission_id=mission_id,
        qwen_args={},
        mission_metadata=mission_row,
    )
    if current_validation.should_execute and current_validation.result_type:
        return await _execute_time_confirmation_submit(
            student_id,
            pending_id,
            {**payload, "mission_name": mission_name, "mission_id": mission_id},
            user_message,
            user_message,
            current_validation.result_type,
            "time_current_submit",
        )

    if original_message and TIME_CONFIRM_RE.search(user_message or ""):
        merged_message = f"오늘 {original_message}"
        merged_validation = validate_submit_candidate(
            user_message=merged_message,
            mission_name=mission_name,
            mission_id=mission_id,
            qwen_args={},
            mission_metadata=mission_row,
        )
        if merged_validation.should_execute and merged_validation.result_type:
            return await _execute_time_confirmation_submit(
                student_id,
                pending_id,
                {**payload, "mission_name": mission_name, "mission_id": mission_id},
                user_message,
                merged_message,
                merged_validation.result_type,
                "time_confirmed_submit",
            )

    if retry_count >= 2:
        return await _cancel_repeated_clarify(pending_id, exec_results)

    updated = await run_in_threadpool(increment_pending_retry, pending_id)
    retry_after_update = updated.get("retry_count") if updated else retry_count + 1
    return PendingOutcome(
        action_type="natural_language_confirmation",
        decision="time_ambiguous",
        status=f"retry_{retry_after_update}",
        message_hint="'오늘 한 건지, 다른 날 한 건지만 알려줘!'",
        pending_id=pending_id,
        exec_results=exec_results,
    )


async def _handle_clarify_partial_confirmation(
    student_id: int,
    pending_id: int,
    payload: dict,
    retry_count: int,
    user_message: str,
) -> PendingOutcome:
    exec_results = ExecResults()
    mission_row = await run_in_threadpool(get_student_mission_db, student_id)
    mission_name, mission_id = _mission_context_from_payload(payload, mission_row)

    candidates = [user_message]
    original_message = _sync_user_message_from_payload(payload, "")
    if original_message:
        candidates.append(original_message)

    for candidate in candidates:
        validation = validate_submit_candidate(
            user_message=candidate,
            mission_name=mission_name,
            mission_id=mission_id,
            qwen_args={},
            mission_metadata=mission_row,
        )
        if validation.should_execute and validation.result_type:
            return await _execute_time_confirmation_submit(
                student_id,
                pending_id,
                {**payload, "mission_name": mission_name, "mission_id": mission_id},
                user_message,
                candidate,
                validation.result_type,
                "partial_resolved_submit",
            )

    return await _retry_reason_specific_clarify(
        pending_id,
        retry_count,
        _mission_quantity_detail_question(mission_name, mission_id),
        "numeric_detail_ambiguous",
    )


async def _retry_reason_specific_clarify(
    pending_id: int,
    retry_count: int,
    question: str,
    decision: str,
) -> PendingOutcome:
    exec_results = ExecResults()
    if retry_count >= 2:
        return await _cancel_repeated_clarify(pending_id, exec_results)
    updated = await run_in_threadpool(increment_pending_retry, pending_id)
    retry_after_update = updated.get("retry_count") if updated else retry_count + 1
    return PendingOutcome(
        action_type="natural_language_confirmation",
        decision=decision,
        status=f"retry_{retry_after_update}",
        message_hint=f"'{question}'",
        pending_id=pending_id,
        exec_results=exec_results,
    )


async def _handle_equivalency_clarify_confirmation(
    student_id: int,
    pending_id: int,
    payload: dict,
    retry_count: int,
    user_message: str,
) -> PendingOutcome:
    exec_results = ExecResults()
    parsed = _extract_equivalency_numeric_reply(user_message)
    target_value = payload.get("target_value")
    target_unit = str(payload.get("target_unit") or "").strip()
    question = str(payload.get("clarify_question") or "").strip()
    threshold, normalized_target_unit = convert_numeric_value(target_value, target_unit)

    print(f"[Pending.equivalency] parsed={parsed} target={target_value}{target_unit} retry={retry_count}")

    if parsed and threshold is not None:
        value, unit = parsed
        if normalized_target_unit and unit != normalized_target_unit:
            return await _retry_equivalency_clarify(
                pending_id,
                retry_count,
                exec_results,
                question,
                "unit_mismatch",
            )
        result_type = "success" if value >= threshold else "fail"
        exec_results.submit = await run_in_threadpool(
            execute_submit,
            student_id,
            {"result_type": result_type},
        )
        await run_in_threadpool(resolve_pending, pending_id, "accepted")
        return PendingOutcome(
            action_type="natural_language_confirmation",
            decision=f"equivalency_{result_type}",
            status="accepted",
            message_hint=_equivalency_submit_hint(exec_results.submit.status.value, result_type),
            pending_id=pending_id,
            exec_results=exec_results,
            sync_user_message=_sync_user_message_from_payload(payload, user_message),
        )

    return await _retry_equivalency_clarify(
        pending_id,
        retry_count,
        exec_results,
        question,
        "ambiguous",
    )


async def _retry_equivalency_clarify(
    pending_id: int,
    retry_count: int,
    exec_results: ExecResults,
    question: str,
    reason: str,
) -> PendingOutcome:
    if retry_count >= 2:
        return await _cancel_repeated_clarify(pending_id, exec_results)

    next_retry = retry_count + 1
    updated = await run_in_threadpool(increment_pending_retry, pending_id)
    retry_after_update = updated.get("retry_count") if updated else next_retry
    retry_question = question or "오늘 미션 기준으로 어떤 행동을 얼마나 했는지 한 문장으로 말해줘!"
    return PendingOutcome(
        action_type="natural_language_confirmation",
        decision="ambiguous",
        status=f"retry_{retry_after_update}",
        message_hint=f"아이가 동치판정 확인 질문에 애매하게 답했어. DB는 건드리지 말고 '{retry_question}'라고 다시 물어봐. reason={reason}",
        pending_id=pending_id,
        exec_results=exec_results,
    )


def _numeric_record_hint(result_status: str) -> str:
    if result_status == SubmitStatus.SAVED.value:
        return "아이가 여기까지 기록하겠다고 답해서 오늘 미션을 실패로 기록했어. 짧게 따뜻하게 받아줘."
    if result_status == SubmitStatus.ALREADY_SUBMITTED.value:
        return "아이가 여기까지 기록하겠다고 답했지만 오늘 미션 결과가 이미 저장되어 있었어. 이미 저장됐다고 짧게 알려줘."
    if result_status == SubmitStatus.NO_MISSION.value:
        return "아이가 여기까지 기록하겠다고 답했지만 오늘 배정된 미션이 없어. 그 사실만 짧게 알려줘."
    return "아이가 여기까지 기록하겠다고 답했지만 기록 저장에 문제가 있었어. 잠시 후 다시 시도해달라고 짧게 말해줘."


def _partial_record_hint(result_status: str) -> str:
    if result_status == SubmitStatus.SAVED.value:
        return "아이가 힘들지만 오늘 미션으로 기록하겠다고 답해서 실패로 기록했어. 짧게 따뜻하게 받아줘."
    if result_status == SubmitStatus.ALREADY_SUBMITTED.value:
        return "아이가 오늘 미션으로 기록하겠다고 답했지만 오늘 미션 결과가 이미 저장되어 있었어. 이미 저장됐다고 짧게 알려줘."
    if result_status == SubmitStatus.NO_MISSION.value:
        return "아이가 오늘 미션으로 기록하겠다고 답했지만 오늘 배정된 미션이 없어. 그 사실만 짧게 알려줘."
    return "아이가 오늘 미션으로 기록하겠다고 답했지만 기록 저장에 문제가 있었어. 잠시 후 다시 시도해달라고 짧게 말해줘."


def _equivalency_submit_hint(result_status: str, result_type: str) -> str:
    if result_status == SubmitStatus.SAVED.value:
        if result_type == "success":
            return "아이가 추가로 기준 충족 정보를 답해서 오늘 미션을 성공으로 기록했어. 짧게 칭찬해줘."
        return "아이가 추가로 기준 미달 정보를 답해서 오늘 미션을 실패로 기록했어. 짧게 따뜻하게 받아줘."
    if result_status == SubmitStatus.ALREADY_SUBMITTED.value:
        return "아이가 추가 정보를 답했지만 오늘 미션 결과가 이미 저장되어 있었어. 이미 저장됐다고 짧게 알려줘."
    if result_status == SubmitStatus.NO_MISSION.value:
        return "아이가 추가 정보를 답했지만 오늘 배정된 미션이 없어. 그 사실만 짧게 알려줘."
    return "아이가 추가 정보를 답했지만 기록 저장에 문제가 있었어. 잠시 후 다시 시도해달라고 짧게 말해줘."


async def handle_pending_action(student_id: int | None, user_message: str, session_id: str = "") -> PendingOutcome | None:
    if not student_id:
        return None

    pending = await run_in_threadpool(get_pending_action, student_id)
    if not pending:
        return None

    pending_id = pending["id"]
    action_type = pending["action_type"]
    payload = pending.get("payload") or {}
    retry_count = pending.get("retry_count") or 0

    pending_message_type = classify_pending_message(user_message, action_type, payload)
    if pending_message_type in {"escape_cancel", "escape_new_intent", "explicit_submit"}:
        await run_in_threadpool(resolve_pending, pending_id, "cancelled")
        print(
            "[Pending] route-out "
            f"type={pending_message_type} action={action_type} retry={retry_count} "
            f"message={user_message[:40]!r}"
        )
        return _pending_reroute_outcome(pending_id, action_type, pending_message_type)

    if action_type == "mission_change_reason":
        print(f"[Pending] action={action_type} retry={retry_count}")
        return await _handle_mission_change_reason(
            student_id, session_id, pending_id, payload, retry_count, user_message
        )

    if action_type == "natural_language_confirmation" and payload.get("clarify_reason") == "numeric_ambiguous":
        return await _handle_numeric_partial_confirmation(
            student_id,
            pending_id,
            payload,
            retry_count,
            user_message,
        )

    if action_type == "natural_language_confirmation" and payload.get("clarify_reason") == "equivalency_clarify":
        return await _handle_equivalency_clarify_confirmation(
            student_id,
            pending_id,
            payload,
            retry_count,
            user_message,
        )

    if action_type == "natural_language_confirmation" and payload.get("clarify_reason") == "partial_progress_difficulty":
        return await _handle_partial_difficulty_confirmation(
            student_id,
            pending_id,
            payload,
            retry_count,
            user_message,
        )

    if action_type == "natural_language_confirmation" and payload.get("clarify_reason") == "clarify_time_ambiguous":
        return await _handle_clarify_time_ambiguous_confirmation(
            student_id,
            pending_id,
            payload,
            retry_count,
            user_message,
        )

    if action_type == "natural_language_confirmation" and payload.get("clarify_reason") == "clarify_negation":
        negation_outcome = await _handle_clarify_negation_confirmation(
            student_id,
            pending_id,
            payload,
            user_message,
        )
        if negation_outcome:
            return negation_outcome
        return await _retry_reason_specific_clarify(
            pending_id,
            retry_count,
            "한 건지 못 한 건지만 알려줘!",
            "negation_ambiguous",
        )

    if action_type == "natural_language_confirmation" and payload.get("clarify_reason") == "clarify_partial":
        return await _handle_clarify_partial_confirmation(
            student_id,
            pending_id,
            payload,
            retry_count,
            user_message,
        )

    decision = await classify_pending_reply(user_message, action_type)
    exec_results = ExecResults()
    print(f"[Pending] action={action_type} decision={decision} retry={retry_count}")

    if decision == "yes":
        if action_type in {"submit_confirmation", "natural_language_confirmation"}:
            branch = _confirmation_branch(payload, decision)
            exec_results, validation = await _execute_confirmation_branch(
                student_id,
                branch,
                payload,
                user_message,
            )
            if validation and not validation.should_execute:
                if retry_count >= 2:
                    return await _cancel_repeated_clarify(pending_id, exec_results)
                updated = await run_in_threadpool(increment_pending_retry, pending_id)
                retry_after_update = updated.get("retry_count") if updated else retry_count + 1
                mission_name = str(payload.get("mission_name") or "")
                return PendingOutcome(
                    action_type=action_type,
                    decision="ambiguous",
                    status=f"validator_blocked_retry_{retry_after_update}",
                    message_hint=build_submit_validation_response(validation, mission_name),
                    pending_id=pending_id,
                    exec_results=exec_results,
                )
            await run_in_threadpool(resolve_pending, pending_id, "accepted")
            return PendingOutcome(
                action_type=action_type,
                decision=decision,
                status="accepted",
                message_hint=_confirmation_hint(branch, decision, exec_results),
                pending_id=pending_id,
                exec_results=exec_results,
                sync_user_message=_sync_user_message_from_payload(payload, user_message),
            )

        if action_type == "mission_dislike_confirm":
            await run_in_threadpool(resolve_pending, pending_id, "accepted")
            return PendingOutcome(
                action_type=action_type,
                decision=decision,
                status="accepted",
                message_hint="아이가 그래도 오늘은 기존 미션을 한 번 해보겠다고 답했어. 짧게 응원해줘.",
                pending_id=pending_id,
                exec_results=exec_results,
            )

        await run_in_threadpool(resolve_pending, pending_id, "cancelled")
        return PendingOutcome(
            action_type=action_type,
            decision=decision,
            status="cancelled",
            message_hint="아직 이어서 처리할 수 없는 확인 흐름이야. 다시 한 번 처음부터 말해달라고 짧게 안내해줘.",
            pending_id=pending_id,
            exec_results=exec_results,
        )

    if decision == "no":
        if action_type in {"submit_confirmation", "natural_language_confirmation"}:
            branch = _confirmation_branch(payload, decision)
            exec_results, validation = await _execute_confirmation_branch(
                student_id,
                branch,
                payload,
                user_message,
            )
            if validation and not validation.should_execute:
                if retry_count >= 2:
                    return await _cancel_repeated_clarify(pending_id, exec_results)
                updated = await run_in_threadpool(increment_pending_retry, pending_id)
                retry_after_update = updated.get("retry_count") if updated else retry_count + 1
                mission_name = str(payload.get("mission_name") or "")
                return PendingOutcome(
                    action_type=action_type,
                    decision="ambiguous",
                    status=f"validator_blocked_retry_{retry_after_update}",
                    message_hint=build_submit_validation_response(validation, mission_name),
                    pending_id=pending_id,
                    exec_results=exec_results,
                )
            hint = _confirmation_hint(branch, decision, exec_results)
        elif action_type == "mission_dislike_confirm":
            await run_in_threadpool(resolve_pending, pending_id, "rejected")
            exec_results = await _execute_dislike_fallback_change(student_id)
            hint = _adjustment_hint(exec_results)
        else:
            await run_in_threadpool(resolve_pending, pending_id, "rejected")
            hint = "아이가 이전 확인 질문에 부정으로 답했어. 짧게 알겠다고 말해줘."
        if action_type in {"submit_confirmation", "natural_language_confirmation"}:
            await run_in_threadpool(resolve_pending, pending_id, "rejected")
        return PendingOutcome(
            action_type=action_type,
            decision=decision,
            status="rejected",
            message_hint=hint,
            pending_id=pending_id,
            exec_results=exec_results,
        )

    next_retry = retry_count + 1
    if next_retry > 2:
        await run_in_threadpool(resolve_pending, pending_id, "cancelled")
        if action_type == "mission_dislike_confirm":
            exec_results = await _execute_dislike_fallback_change(student_id)
            hint = _adjustment_hint(exec_results)
        else:
            hint = "아이가 두 번 넘게 애매하게 답해서 이전 확인을 취소했어. 다시 필요하면 알려달라고 짧게 말해줘."
        return PendingOutcome(
            action_type=action_type,
            decision=decision,
            status="cancelled",
            message_hint=hint,
            pending_id=pending_id,
            exec_results=exec_results,
        )

    updated = await run_in_threadpool(increment_pending_retry, pending_id)
    retry_after_update = updated.get("retry_count") if updated else next_retry
    if action_type in {"submit_confirmation", "natural_language_confirmation"}:
        hint = "아이가 이전 확인 질문에 애매하게 답했어. 진행할지 말지 다시 한 번 짧게 물어봐."
    elif action_type == "mission_dislike_confirm":
        hint = "아이가 기존 미션을 오늘 한 번 해볼지 애매하게 답했어. 해볼지 다른 걸로 바꿀지 다시 한 번 짧게 물어봐."
    else:
        hint = "아이가 이전 확인 질문에 애매하게 답했어. 다시 한 번 짧게 확인해줘."

    return PendingOutcome(
        action_type=action_type,
        decision=decision,
        status=f"retry_{retry_after_update}",
        message_hint=hint,
        pending_id=pending_id,
        exec_results=exec_results,
    )
