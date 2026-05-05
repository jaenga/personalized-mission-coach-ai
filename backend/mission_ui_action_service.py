from __future__ import annotations

from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from database import (
    get_pending_mission_ui_action,
    resolve_mission_ui_action,
    save_mission_ui_action,
)


MISSION_CHANGE_REASON_BUTTONS = [
    {"value": "too_hard", "label": "너무 어려워"},
    {"value": "too_easy", "label": "너무 쉬워"},
    {"value": "dislike", "label": "재미없어"},
    {"value": "cant_do", "label": "할 수 없는 상황이야"},
    {"value": "just_change", "label": "그냥 바꿀래"},
]

MISSION_DISLIKE_CONFIRM_BUTTONS = [
    {"value": "try_today", "label": "오늘 한 번 해볼래"},
    {"value": "change", "label": "다른 미션으로 바꿀래"},
]

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
