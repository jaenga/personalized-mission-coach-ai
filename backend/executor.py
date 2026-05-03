"""
Executor — DB write 전담 모듈.
각 함수는 dataclass 결과를 반환하며, hint builder가 텍스트로 변환한다.
"""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass

from database import (
    _kst_today,
    get_student_mission_db,
    has_checkin_today,
    save_mission_result,
    find_adjusted_mission,
    save_mission_adjustment,
    cancel_last_action,
)


# ── Enum + Dataclass ─────────────────────────────────────────────────────────

class SubmitStatus(Enum):
    SAVED = "saved"
    ALREADY_SUBMITTED = "already_submitted"
    NO_MISSION = "no_mission"
    DB_ERROR = "db_error"


class ExecutorActionType(str, Enum):
    SUCCESS_RECORDED = "success_recorded"
    FAIL_RECORDED = "fail_recorded"
    MISSION_CHANGED = "mission_changed"
    ACTION_CANCELLED = "action_cancelled"


@dataclass
class SubmitResult:
    status: SubmitStatus
    mission_name: str | None = None
    result_type: str | None = None
    checkin_id: int | None = None
    error: str | None = None
    db_changed: bool = False
    action: ExecutorActionType | None = None


class AdjustmentStatus(Enum):
    CHANGED = "changed"
    ALREADY_SUBMITTED = "already_submitted"
    NO_MISSION = "no_mission"
    NO_ALTERNATIVE = "no_alternative"
    DB_ERROR = "db_error"


@dataclass
class AdjustmentResult:
    status: AdjustmentStatus
    adjustment_type: str | None = None
    old_mission_name: str | None = None
    old_mission_rule: str | None = None
    new_mission_name: str | None = None
    new_mission_rule: str | None = None
    error: str | None = None
    db_changed: bool = False
    action: ExecutorActionType | None = None


class CancelStatus(Enum):
    CANCELLED_SUBMIT = "cancelled_submit"
    CANCELLED_ADJUSTMENT = "cancelled_adjustment"
    NOTHING_TO_CANCEL = "nothing_to_cancel"
    DB_ERROR = "db_error"


@dataclass
class CancelResult:
    status: CancelStatus
    error: str | None = None
    db_changed: bool = False
    action: ExecutorActionType | None = None


@dataclass
class ExecResults:
    """executor 실행 결과 묶음. hint_builder에서 exec_results.submit 등으로 접근."""
    submit: SubmitResult | None = None
    adjustment: AdjustmentResult | None = None
    cancel: CancelResult | None = None


# ── Executor 함수 ────────────────────────────────────────────────────────────

def _status_label(result: object) -> str:
    status = getattr(getattr(result, "status", None), "value", getattr(result, "status", None))
    action = getattr(getattr(result, "action", None), "value", None)
    changed = getattr(result, "db_changed", False)
    detail = (
        getattr(result, "result_type", None)
        or getattr(result, "adjustment_type", None)
        or getattr(result, "new_mission_name", None)
    )
    pieces = [str(status)]
    if detail:
        pieces.append(str(detail))
    pieces.append(f"db={'Y' if changed else 'N'}")
    if action:
        pieces.append(str(action))
    error = getattr(result, "error", None)
    if error:
        pieces.append(f"error={str(error)[:60]}")
    return " / ".join(pieces)


def execute_submit(student_id: int, fn_args: dict) -> SubmitResult:
    """미션 결과 DB 저장. has_checkin_today 체크 포함."""
    result_type = fn_args.get("result_type", "")
    try:
        today = _kst_today()
        mission = get_student_mission_db(student_id, today)
        if not mission:
            result = SubmitResult(status=SubmitStatus.NO_MISSION, result_type=result_type)
            print(f"[DB.submit] {_status_label(result)}")
            return result

        if has_checkin_today(student_id):
            result = SubmitResult(
                status=SubmitStatus.ALREADY_SUBMITTED,
                mission_name=mission.get("mission_name"),
                result_type=result_type,
            )
            print(f"[DB.submit] {_status_label(result)}")
            return result

        checkin_id = save_mission_result(
            student_id=student_id,
            mission_id=mission["mission_id"],
            status=result_type,
            detected_function="submit_mission_result",
        )
        if checkin_id is None:
            result = SubmitResult(
                status=SubmitStatus.ALREADY_SUBMITTED,
                mission_name=mission.get("mission_name"),
                result_type=result_type,
            )
            print(f"[DB.submit] {_status_label(result)}")
            return result

        result = SubmitResult(
            status=SubmitStatus.SAVED,
            mission_name=mission.get("mission_name"),
            result_type=result_type,
            checkin_id=checkin_id,
            db_changed=True,
            action=(
                ExecutorActionType.SUCCESS_RECORDED
                if result_type == "success"
                else ExecutorActionType.FAIL_RECORDED
            ),
        )
        print(f"[DB.submit] {_status_label(result)}")
        return result
    except Exception as e:
        result = SubmitResult(status=SubmitStatus.DB_ERROR, result_type=result_type, error=str(e))
        print(f"[DB.submit] {_status_label(result)}")
        return result


def execute_adjustment(student_id: int, fn_args: dict) -> AdjustmentResult:
    """미션 변경 DB 저장."""
    adjustment_type = fn_args.get("adjustment_type", "change")
    try:
        today = _kst_today()
        current = get_student_mission_db(student_id, today)
        if not current:
            result = AdjustmentResult(status=AdjustmentStatus.NO_MISSION, adjustment_type=adjustment_type)
            print(f"[DB.adjust] {_status_label(result)}")
            return result

        if has_checkin_today(student_id):
            result = AdjustmentResult(status=AdjustmentStatus.ALREADY_SUBMITTED, adjustment_type=adjustment_type)
            print(f"[DB.adjust] {_status_label(result)}")
            return result

        new_mission = find_adjusted_mission(student_id, adjustment_type, current["mission_id"])
        if not new_mission:
            result = AdjustmentResult(status=AdjustmentStatus.NO_ALTERNATIVE, adjustment_type=adjustment_type)
            print(f"[DB.adjust] {_status_label(result)}")
            return result

        save_mission_adjustment(student_id, current["mission_id"], new_mission["mission_id"])
        result = AdjustmentResult(
            status=AdjustmentStatus.CHANGED,
            adjustment_type=adjustment_type,
            old_mission_name=current.get("mission_name"),
            old_mission_rule=current.get("mission_rule"),
            new_mission_name=new_mission.get("mission_name"),
            new_mission_rule=new_mission.get("mission_rule"),
            db_changed=True,
            action=ExecutorActionType.MISSION_CHANGED,
        )
        print(f"[DB.adjust] {_status_label(result)}")
        return result
    except Exception as e:
        result = AdjustmentResult(status=AdjustmentStatus.DB_ERROR, adjustment_type=adjustment_type, error=str(e))
        print(f"[DB.adjust] {_status_label(result)}")
        return result


def execute_cancel(student_id: int) -> CancelResult:
    """직전 행동 취소."""
    try:
        cancel_type = cancel_last_action(student_id)
        if cancel_type == "submit":
            result = CancelResult(
                status=CancelStatus.CANCELLED_SUBMIT,
                db_changed=True,
                action=ExecutorActionType.ACTION_CANCELLED,
            )
            print(f"[DB.cancel] type=submit / {_status_label(result)}")
            return result
        elif cancel_type == "adjustment":
            result = CancelResult(
                status=CancelStatus.CANCELLED_ADJUSTMENT,
                db_changed=True,
                action=ExecutorActionType.ACTION_CANCELLED,
            )
            print(f"[DB.cancel] type=adjustment / {_status_label(result)}")
            return result
        else:
            result = CancelResult(status=CancelStatus.NOTHING_TO_CANCEL)
            print(f"[DB.cancel] type=none / {_status_label(result)}")
            return result
    except Exception as e:
        result = CancelResult(status=CancelStatus.DB_ERROR, error=str(e))
        print(f"[DB.cancel] {_status_label(result)}")
        return result
