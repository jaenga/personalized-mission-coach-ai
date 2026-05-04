from __future__ import annotations

import json
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from database import (
    get_pending_action,
    increment_pending_retry,
    resolve_pending,
)
from executor import ExecResults, SubmitStatus, execute_submit
from ollama_client import generate_json_message


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
    "그냥바꿔줘",
    "바꿔줘",
}

PENDING_CLASSIFY_SYSTEM_PROMPT = """이전 질문에 대한 아이의 답변이야.
긍정이면 yes, 부정이면 no, 애매하면 ambiguous로 분류해.

출력은 JSON만:
{"result":"yes|no|ambiguous"}
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


def _compact(text: str) -> str:
    return (text or "").replace(" ", "").strip()


async def classify_pending_reply(user_message: str, action_type: str | None = None) -> str:
    text = _compact(user_message)
    if text in POSITIVE_EXACT:
        return "yes"
    if text in NEGATIVE_EXACT:
        return "no"

    try:
        raw = await generate_json_message(
            PENDING_CLASSIFY_SYSTEM_PROMPT,
            f"action_type: {action_type or ''}\n답변: {user_message}",
            timeout=8.0,
        )
        data = json.loads(raw)
    except Exception as e:
        print(f"[Pending] classify fallback ambiguous error={type(e).__name__}: {e!r}")
        return "ambiguous"

    result = data.get("result")
    if result in {"yes", "no", "ambiguous"}:
        return result
    print(f"[Pending] classify invalid raw={raw[:120]!r}")
    return "ambiguous"


def _submit_args_from_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("fn_args", "submit_args", "args"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def _sync_user_message_from_payload(payload: dict, fallback: str) -> str:
    if not isinstance(payload, dict):
        return fallback
    value = payload.get("original_user_message") or payload.get("user_message")
    return value if isinstance(value, str) and value.strip() else fallback


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


async def handle_pending_action(student_id: int | None, user_message: str) -> PendingOutcome | None:
    if not student_id:
        return None

    pending = await run_in_threadpool(get_pending_action, student_id)
    if not pending:
        return None

    pending_id = pending["id"]
    action_type = pending["action_type"]
    payload = pending.get("payload") or {}
    retry_count = pending.get("retry_count") or 0
    decision = await classify_pending_reply(user_message, action_type)
    exec_results = ExecResults()
    print(f"[Pending] action={action_type} decision={decision} retry={retry_count}")

    if decision == "yes":
        if action_type == "submit_confirmation":
            submit_args = _submit_args_from_payload(payload)
            exec_results.submit = await run_in_threadpool(execute_submit, student_id, submit_args)
            await run_in_threadpool(resolve_pending, pending_id, "accepted")
            result_status = exec_results.submit.status.value
            return PendingOutcome(
                action_type=action_type,
                decision=decision,
                status="accepted",
                message_hint=_submit_hint(result_status, exec_results.submit.result_type),
                pending_id=pending_id,
                exec_results=exec_results,
                sync_user_message=_sync_user_message_from_payload(payload, user_message),
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

    if decision == "no":
        await run_in_threadpool(resolve_pending, pending_id, "rejected")
        if action_type == "submit_confirmation":
            hint = "아이가 확인 질문에 부정으로 답했어. 미션 결과를 기록하지 않았고, 나중에 다시 알려달라고 짧게 말해줘."
        elif action_type == "mission_dislike_confirm":
            hint = "아이가 기존 미션을 오늘 해보자는 제안을 거절했어. 아직 미션은 바꾸지 않았으니 바뀌었다고 말하지 말고, 다른 미션으로 바꿔보자고 짧게 말해줘."
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
            hint = "아이가 두 번 넘게 애매하게 답해서 미션 싫음 확인을 취소했어. 아직 미션은 바꾸지 않았다고 짧게 말하고, 원하면 다시 바꿔달라고 하게 해줘."
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
    if action_type == "submit_confirmation":
        hint = "아이가 미션 성공 여부 확인에 애매하게 답했어. 성공한 건지 못 한 건지 다시 한 번 짧게 물어봐."
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
