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


@dataclass
class SubmitResult:
    status: SubmitStatus
    mission_name: str | None = None
    result_type: str | None = None
    checkin_id: int | None = None
    error: str | None = None


class AdjustmentStatus(Enum):
    CHANGED = "changed"
    NO_MISSION = "no_mission"
    NO_ALTERNATIVE = "no_alternative"
    DB_ERROR = "db_error"


@dataclass
class AdjustmentResult:
    status: AdjustmentStatus
    adjustment_type: str | None = None
    new_mission_name: str | None = None
    new_mission_rule: str | None = None
    error: str | None = None


class CancelStatus(Enum):
    CANCELLED_SUBMIT = "cancelled_submit"
    CANCELLED_ADJUSTMENT = "cancelled_adjustment"
    NOTHING_TO_CANCEL = "nothing_to_cancel"
    DB_ERROR = "db_error"


@dataclass
class CancelResult:
    status: CancelStatus
    error: str | None = None


@dataclass
class ExecResults:
    """executor 실행 결과 묶음. hint_builder에서 exec_results.submit 등으로 접근."""
    submit: SubmitResult | None = None
    adjustment: AdjustmentResult | None = None
    cancel: CancelResult | None = None


# ── Executor 함수 ────────────────────────────────────────────────────────────

def execute_submit(student_id: int, fn_args: dict) -> SubmitResult:
    """미션 결과 DB 저장. has_checkin_today 체크 포함."""
    result_type = fn_args.get("result_type", "")
    try:
        today = _kst_today()
        mission = get_student_mission_db(student_id, today)
        if not mission:
            return SubmitResult(status=SubmitStatus.NO_MISSION, result_type=result_type)

        if has_checkin_today(student_id):
            return SubmitResult(
                status=SubmitStatus.ALREADY_SUBMITTED,
                mission_name=mission.get("mission_name"),
                result_type=result_type,
            )

        checkin_id = save_mission_result(
            student_id=student_id,
            mission_id=mission["mission_id"],
            status=result_type,
            detected_function="submit_mission_result",
        )
        return SubmitResult(
            status=SubmitStatus.SAVED,
            mission_name=mission.get("mission_name"),
            result_type=result_type,
            checkin_id=checkin_id,
        )
    except Exception as e:
        return SubmitResult(status=SubmitStatus.DB_ERROR, result_type=result_type, error=str(e))


def execute_adjustment(student_id: int, fn_args: dict) -> AdjustmentResult:
    """미션 변경 DB 저장."""
    adjustment_type = fn_args.get("adjustment_type", "change")
    try:
        today = _kst_today()
        current = get_student_mission_db(student_id, today)
        if not current:
            return AdjustmentResult(status=AdjustmentStatus.NO_MISSION, adjustment_type=adjustment_type)

        new_mission = find_adjusted_mission(student_id, adjustment_type, current["mission_id"])
        if not new_mission:
            return AdjustmentResult(status=AdjustmentStatus.NO_ALTERNATIVE, adjustment_type=adjustment_type)

        save_mission_adjustment(student_id, current["mission_id"], new_mission["mission_id"])
        return AdjustmentResult(
            status=AdjustmentStatus.CHANGED,
            adjustment_type=adjustment_type,
            new_mission_name=new_mission.get("mission_name"),
            new_mission_rule=new_mission.get("mission_rule"),
        )
    except Exception as e:
        return AdjustmentResult(status=AdjustmentStatus.DB_ERROR, adjustment_type=adjustment_type, error=str(e))


def execute_cancel(student_id: int) -> CancelResult:
    """직전 행동 취소."""
    try:
        cancel_type = cancel_last_action(student_id)
        if cancel_type == "submit":
            return CancelResult(status=CancelStatus.CANCELLED_SUBMIT)
        elif cancel_type == "adjustment":
            return CancelResult(status=CancelStatus.CANCELLED_ADJUSTMENT)
        else:
            return CancelResult(status=CancelStatus.NOTHING_TO_CANCEL)
    except Exception as e:
        return CancelResult(status=CancelStatus.DB_ERROR, error=str(e))
