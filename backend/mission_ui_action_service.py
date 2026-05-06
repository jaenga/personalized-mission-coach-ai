from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from database import (
    fetch_profile,
    get_pending_mission_ui_action,
    resolve_mission_ui_action,
    save_mission_change_log,
    save_mission_ui_action,
    upsert_user_memory,
)
from executor import ExecResults, execute_adjustment
from ollama_client import generate_chat_message
from response_builder import build_action_ack

_DISLIKE_RESPONSE_PROMPT = """너는 토미라는 토마토 캐릭터야.
아이와 친구처럼 반말로 말해.
2문장 이내로 짧게 말해.

[상황]
{hint}

자연스럽게 한마디 해줘.
"""


def _dislike_confirm_hint(mission_name: str, mission_rule: str) -> str:
    return (
        f"아이가 미션 '{mission_name}'이 재미없다고 했어. "
        f"미션 규칙: {mission_rule} "
        "이 미션의 좋은 점이나 재밌는 점을 1문장으로 먼저 말해주고, "
        "그래도 오늘 딱 한 번만 도전해볼지 짧게 물어봐. 강요하지 말고 친구처럼 부드럽게."
    )


async def _generate_dislike_response(mission_name: str, mission_rule: str) -> str:
    hint = _dislike_confirm_hint(mission_name, mission_rule)
    fallback = "그래도 오늘 딱 한 번만 해볼래? 아니면 다른 미션으로 바꿔줄까?"
    try:
        message, _ = await generate_chat_message(
            _DISLIKE_RESPONSE_PROMPT.format(hint=hint),
            [{"role": "user", "content": "이 상황에 맞게 짧게 답해줘."}],
        )
        message = " ".join((message or "").split())
        if not message or len(message) > 120:
            return fallback
        return message
    except Exception as e:
        print(f"[UiAction] dislike response generation failed: {type(e).__name__}: {e}")
        return fallback


MISSION_CHANGE_REASON_BUTTONS = [
    {"value": "too_easy", "label": "너무 쉬워"},
    {"value": "too_hard", "label": "너무 어려워"},
    {"value": "dislike", "label": "재미없어 / 싫어"},
    {"value": "cant_do", "label": "할 수 없는 상황이야"},
    {"value": "just_change", "label": "그냥 다른 거 하고 싶어"},
]

MISSION_DISLIKE_CONFIRM_BUTTONS = [
    {"value": "try_today", "label": "그래 도전해볼게!"},
    {"value": "change", "label": "다른 미션으로 바꿔줘"},
]

def rebuild_ui_action_payload(active_ui: dict) -> dict:
    """DB row를 받아 action_type에 맞는 버튼 목록을 재조합해 ui_action payload를 반환한다."""
    action_type = active_ui.get("action_type", "")
    action_id = active_ui.get("action_id", "")
    if action_type == "mission_change_reason":
        return {"action_id": action_id, "type": action_type, "lock_chat": True, "buttons": MISSION_CHANGE_REASON_BUTTONS}
    if action_type == "mission_dislike_confirm":
        return {"action_id": action_id, "type": action_type, "lock_chat": True, "buttons": MISSION_DISLIKE_CONFIRM_BUTTONS}
    payload = active_ui.get("payload") if isinstance(active_ui.get("payload"), dict) else {}
    return {"action_id": action_id, "type": action_type, "lock_chat": False, "buttons": [], "payload": payload}


UI_ACTION_ALLOWED_VALUES = {
    "mission_change_reason": {button["value"] for button in MISSION_CHANGE_REASON_BUTTONS},
    "mission_dislike_confirm": {button["value"] for button in MISSION_DISLIKE_CONFIRM_BUTTONS},
}


@dataclass
class UiActionResolveResult:
    ok: bool
    status: str
    action: dict | None = None
    reason: str = ""


def _ui_action_payload(row: dict, buttons: list[dict], lock_chat: bool) -> dict:
    return {
        "action_id": row["action_id"],
        "type": row["action_type"],
        "lock_chat": lock_chat,
        "buttons": buttons,
    }


async def create_mission_change_reason_action(
    student_id: int,
    session_id: str,
    payload: dict,
) -> dict:
    row = await run_in_threadpool(
        save_mission_ui_action,
        student_id,
        session_id,
        "mission_change_reason",
        payload,
        "pending",
    )
    return _ui_action_payload(row, MISSION_CHANGE_REASON_BUTTONS, lock_chat=True)


async def create_mission_dislike_confirm_action(
    student_id: int,
    session_id: str,
    payload: dict,
) -> dict:
    row = await run_in_threadpool(
        save_mission_ui_action,
        student_id,
        session_id,
        "mission_dislike_confirm",
        payload,
        "pending",
    )
    return _ui_action_payload(row, MISSION_DISLIKE_CONFIRM_BUTTONS, lock_chat=True)


async def create_replacement_mission_input_action(
    student_id: int,
    session_id: str,
    payload: dict,
) -> dict:
    payload = {**payload, "retry_count": int(payload.get("retry_count") or 0)}
    row = await run_in_threadpool(
        save_mission_ui_action,
        student_id,
        session_id,
        "awaiting_replacement_mission",
        payload,
        "pending_input",
    )
    return {
        "action_id": row["action_id"],
        "type": row["action_type"],
        "lock_chat": False,
        "buttons": [],
        "payload": row.get("payload") if isinstance(row.get("payload"), dict) else payload,
    }


async def get_active_ui_action(student_id: int | None, session_id: str) -> dict | None:
    if not student_id:
        return None
    return await run_in_threadpool(get_pending_mission_ui_action, student_id, session_id)


async def validate_and_resolve_ui_action(
    student_id: int | None,
    session_id: str,
    action_id: str,
    value: str,
) -> UiActionResolveResult:
    if not student_id:
        return UiActionResolveResult(ok=False, status="rejected", reason="missing_student")

    active = await get_active_ui_action(student_id, session_id)
    if not active:
        return UiActionResolveResult(ok=False, status="expired", reason="no_active_action")
    if active.get("action_id") != action_id:
        return UiActionResolveResult(ok=False, status="rejected", reason="action_mismatch")

    action_type = active.get("action_type")
    allowed_values = UI_ACTION_ALLOWED_VALUES.get(action_type)
    if not allowed_values or value not in allowed_values:
        return UiActionResolveResult(ok=False, status="rejected", action=active, reason="invalid_value")

    resolved = await run_in_threadpool(
        resolve_mission_ui_action,
        action_id,
        student_id,
        session_id,
        "resolved",
    )
    if not resolved:
        return UiActionResolveResult(ok=False, status="expired", action=active, reason="not_pending")
    if resolved.get("status") != "resolved":
        return UiActionResolveResult(ok=False, status=resolved.get("status", "expired"), action=resolved, reason="expired")
    return UiActionResolveResult(ok=True, status="resolved", action=resolved)


def _action_payload(action: dict | None) -> dict:
    if not action:
        return {}
    payload = action.get("payload")
    return payload if isinstance(payload, dict) else {}


async def _execute_adjustment_response(student_id: int, adjustment_type: str) -> tuple[str, ExecResults]:
    exec_results = ExecResults()
    exec_results.adjustment = await run_in_threadpool(
        execute_adjustment,
        student_id,
        {"adjustment_type": adjustment_type},
    )
    ack = build_action_ack(exec_results)
    if ack:
        return ack.message, exec_results
    return "미션을 바꾸는 중 문제가 있었어. 잠시 후 다시 시도해줘.", exec_results


async def _log_change_reason(student_id: int, action: dict | None, reason_type: str) -> dict | None:
    payload = _action_payload(action)
    mission_id = payload.get("mission_id")
    if not mission_id:
        return None
    try:
        return await run_in_threadpool(save_mission_change_log, student_id, mission_id, reason_type)
    except Exception as e:
        print(f"[UiAction] mission change log failed: {type(e).__name__}: {e}")
    return None


async def _save_reason_memory(student_id: int, payload: dict, reason_type: str, log_row: dict | None = None) -> dict | None:
    activity_key = payload.get("activity_key") or (log_row or {}).get("activity_key")
    if not activity_key:
        return None

    if reason_type == "too_hard":
        memory_type = "difficulty"
        polarity = None
    elif reason_type == "dislike":
        memory_type = "preference"
        polarity = -1
    else:
        return None

    try:
        return await run_in_threadpool(upsert_user_memory, student_id, activity_key, memory_type, polarity)
    except Exception as e:
        print(f"[UiAction] memory upsert failed reason={reason_type}: {type(e).__name__}: {e}")
    return None


async def resolve_mission_ui_action_request(action_id: str, session_id: str, value: str) -> dict:
    profile = await run_in_threadpool(fetch_profile, session_id)
    if not profile:
        raise HTTPException(status_code=404, detail="프로필 없음")

    student_id = profile["student_id"]
    resolved = await validate_and_resolve_ui_action(student_id, session_id, action_id, value)
    if not resolved.ok:
        status_code = 410 if resolved.status == "expired" else 409
        raise HTTPException(
            status_code=status_code,
            detail={
                "status": resolved.status,
                "reason": resolved.reason,
            },
        )

    action = resolved.action or {}
    action_type = action.get("action_type")
    payload = _action_payload(action)

    if action_type == "mission_change_reason":
        if value == "too_hard":
            log_row = await _log_change_reason(student_id, action, "too_hard")
            memory = await _save_reason_memory(student_id, payload, "too_hard", log_row)
            response, exec_results = await _execute_adjustment_response(student_id, "easier")
            return {
                "response": response,
                "mission_completed": False,
                "ui_action": None,
                "debug": {
                    "intent": "MISSION_UI_ACTION",
                    "ui_action_type": action_type,
                    "ui_action_value": value,
                    "adjustment_status": exec_results.adjustment.status.value if exec_results.adjustment else None,
                    "memory_saved": bool(memory),
                },
            }

        if value == "too_easy":
            await _log_change_reason(student_id, action, "too_easy")
            response, exec_results = await _execute_adjustment_response(student_id, "harder")
            return {
                "response": response,
                "mission_completed": False,
                "ui_action": None,
                "debug": {
                    "intent": "MISSION_UI_ACTION",
                    "ui_action_type": action_type,
                    "ui_action_value": value,
                    "adjustment_status": exec_results.adjustment.status.value if exec_results.adjustment else None,
                },
            }

        if value == "just_change":
            await _log_change_reason(student_id, action, "just_change")
            response, exec_results = await _execute_adjustment_response(student_id, "change")
            return {
                "response": response,
                "mission_completed": False,
                "ui_action": None,
                "debug": {
                    "intent": "MISSION_UI_ACTION",
                    "ui_action_type": action_type,
                    "ui_action_value": value,
                    "adjustment_status": exec_results.adjustment.status.value if exec_results.adjustment else None,
                },
            }

        if value == "dislike":
            log_row = await _log_change_reason(student_id, action, "dislike")
            memory = await _save_reason_memory(student_id, payload, "dislike", log_row)
            ui_action = await create_mission_dislike_confirm_action(student_id, session_id, payload)
            response = await _generate_dislike_response(
                payload.get("mission_name", "오늘 미션"),
                payload.get("mission_rule", ""),
            )
            return {
                "response": response,
                "mission_completed": False,
                "ui_action": ui_action,
                "debug": {
                    "intent": "MISSION_UI_ACTION",
                    "ui_action_type": action_type,
                    "ui_action_value": value,
                    "next_ui_action_type": "mission_dislike_confirm",
                    "memory_saved": bool(memory),
                },
            }

        if value == "cant_do":
            await _log_change_reason(student_id, action, "cant_do")
            next_payload = {
                **payload,
                "source_reason": "cant_do",
            }
            ui_action = await create_replacement_mission_input_action(student_id, session_id, next_payload)
            return {
                "response": "그럼 어떤 미션으로 바꿔줄까? 하고 싶은 미션이나 조건을 말해줘.",
                "mission_completed": False,
                "ui_action": ui_action,
                "debug": {
                    "intent": "MISSION_UI_ACTION",
                    "ui_action_type": action_type,
                    "ui_action_value": value,
                    "next_ui_action_type": "awaiting_replacement_mission",
                },
            }

    if action_type == "mission_dislike_confirm":
        if value == "try_today":
            return {
                "response": "좋아, 오늘은 딱 한 번만 같이 해보자!",
                "mission_completed": False,
                "ui_action": None,
                "debug": {
                    "intent": "MISSION_UI_ACTION",
                    "ui_action_type": action_type,
                    "ui_action_value": value,
                },
            }

        if value == "change":
            response, exec_results = await _execute_adjustment_response(student_id, "change")
            return {
                "response": response,
                "mission_completed": False,
                "ui_action": None,
                "debug": {
                    "intent": "MISSION_UI_ACTION",
                    "ui_action_type": action_type,
                    "ui_action_value": value,
                    "adjustment_status": exec_results.adjustment.status.value if exec_results.adjustment else None,
                },
            }

    raise HTTPException(
        status_code=409,
        detail={
            "status": "rejected",
            "reason": "unsupported_action",
        },
    )
