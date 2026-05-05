from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from database import (
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
from mission_ui_action_service import create_mission_dislike_confirm_action
from ollama_client import generate_json_message


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
    "그래",
    "좋아",
    "맞아",
    "그걸로",
    "해줘",
}

NEGATIVE_EXACT = {
    "아니",
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
        "args": {**_submit_args_from_payload(payload), "result_type": "failure"},
    }


async def _execute_confirmation_branch(
    student_id: int,
    branch: dict,
) -> ExecResults:
    exec_results = ExecResults()
    fn = branch.get("fn")
    args = branch.get("args") if isinstance(branch.get("args"), dict) else {}
    if fn not in CONFIRMATION_ACTION_FNS:
        print(f"[Pending] confirmation skipped unknown fn={fn!r}")
        return exec_results

    if fn == "submit_mission_result":
        exec_results.submit = await run_in_threadpool(execute_submit, student_id, args)
    elif fn == "cancel_mission_action":
        exec_results.cancel = await run_in_threadpool(execute_cancel, student_id, args)
    elif fn == "request_mission_adjustment":
        exec_results.adjustment = await run_in_threadpool(execute_adjustment, student_id, args)
    return exec_results


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

    reason = _classify_change_reason_by_keyword(user_message)

    if reason is None:
        if retry_count >= 2:
            reason = "just_change"
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
            "reason_type": "dislike",
            "original_user_message": user_message,
        }
        ui_action = await create_mission_dislike_confirm_action(student_id, session_id, dislike_payload)
        if mission_id:
            try:
                await run_in_threadpool(save_mission_change_log, student_id, mission_id, "dislike")
            except Exception as e:
                print(f"[ChangeReason] log failed: {e!r}")
        return PendingOutcome(
            action_type="mission_change_reason",
            decision="dislike",
            status="chained_dislike",
            message_hint=_MISSION_DISLIKE_PENDING_HINT,
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

    if action_type == "mission_change_reason":
        print(f"[Pending] action={action_type} retry={retry_count}")
        return await _handle_mission_change_reason(
            student_id, session_id, pending_id, payload, retry_count, user_message
        )

    decision = await classify_pending_reply(user_message, action_type)
    exec_results = ExecResults()
    print(f"[Pending] action={action_type} decision={decision} retry={retry_count}")

    if decision == "yes":
        if action_type in {"submit_confirmation", "natural_language_confirmation"}:
            branch = _confirmation_branch(payload, decision)
            exec_results = await _execute_confirmation_branch(student_id, branch)
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
        await run_in_threadpool(resolve_pending, pending_id, "rejected")
        if action_type in {"submit_confirmation", "natural_language_confirmation"}:
            branch = _confirmation_branch(payload, decision)
            exec_results = await _execute_confirmation_branch(student_id, branch)
            hint = _confirmation_hint(branch, decision, exec_results)
        elif action_type == "mission_dislike_confirm":
            exec_results = await _execute_dislike_fallback_change(student_id)
            hint = _adjustment_hint(exec_results)
        else:
            hint = "아이가 이전 확인 질문에 부정으로 답했어. 짧게 알겠다고 말해줘."
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
