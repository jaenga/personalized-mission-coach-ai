"""서버가 확정적으로 보여줄 응답 조각 생성."""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from executor import (
    AdjustmentStatus,
    CancelStatus,
    ExecResults,
    ExecutorActionType,
    SubmitStatus,
)

_ADJUSTMENT_ALREADY_SUBMITTED_MSG = "오늘 이미 미션 결과를 제출했어! 제출 후에는 미션을 바꿀 수 없어."
_CONFLICT_MSG = "성공으로 기록할지, 아니면 최근 기록을 취소할지 헷갈렸어! 어떻게 할지 알려줄래? 😊"
_ALREADY_SUBMITTED_ACKS = [
    "오늘은 이미 제출한 기록이 있어! 최근에 한 행동을 취소하고 다시 할까? 😁",
    "오늘 미션 결과는 이미 기록돼 있어! 최근 기록을 취소하고 다시 진행할래? 😊",
    "이미 오늘 기록이 남아 있어! 다시 제출하려면 최근 기록을 취소해야 해. 😋",
    "오늘은 제출이 완료된 상태야! 최근 행동을 취소하고 다시 할 수 있어 😆",
    "이미 제출한 기록이 있어! 취소하고 다시 진행해볼래? 😀",
]
_SUCCESS_RECORDED_ACKS = [
    "성공으로 기록해뒀어! 👍 ✅",
    "미션 성공 기록 완료! ✅",
    "오늘 미션 성공으로 저장했어! ☺️ ✅",
    "좋아, 성공으로 기록했어! 👌 ✅",
]
_FAIL_RECORDED_ACKS = [
    "알겠어, 실패로 기록해뒀어! 😭 ✅",
    "미션 실패 기록 완료! ✅",
    "오늘 미션은 실패로 저장했어!🥲 ✅",
    "실패로 기록했어! ✅",
]
_MISSION_CHANGED_ACKS = {
    "change": [
        "미션을 새롭게 바꿔뒀어! 🔄",
        "새 미션으로 바꿔뒀어! 🔄",
        "좋아, 새로운 미션으로 변경 완료! 🔄",
        "요청한 대로 새로운 미션으로 바꿨어! 🔄",
        "오늘 미션을 새로 바꿔뒀어! 🔄",
    ],
    "easier": [
        "조금 더 쉬운 미션으로 바꿔뒀어! 🔄",
        "쉬운 미션으로 바꿔뒀어! 🔄",
        "부담이 덜한 미션으로 바꿨어! 🔄",
        "좋아, 더 쉬운 미션으로 변경 완료! 🔄",
        "오늘 미션을 조금 쉽게 바꿔뒀어! 🔄",
    ],
    "harder": [
        "조금 더 어려운 미션으로 바꿔뒀어! 🔄",
        "도전 미션으로 바꿔뒀어! 🔄",
        "더 도전할 수 있는 미션으로 바꿨어! 🔄",
        "좋아, 더 어려운 미션으로 변경 완료! 🔄",
        "오늘 미션을 조금 더 도전적으로 바꿔뒀어! 🔄",
    ],
}
_ACTION_CANCELLED_ACKS = [
    "취소해뒀어! ↩️",
    "방금 기록을 취소했어! ↩️",
    "좋아, 취소 완료했어! ↩️",
    "최근 작업을 되돌려뒀어! ↩️",
    "요청한 대로 취소했어! ↩️",
]


class ResponseMode(str, Enum):
    SERVER_ONLY = "server_only"
    PREFIX_WITH_GEMMA = "prefix_with_gemma"


@dataclass(frozen=True)
class ActionAck:
    message: str
    mode: ResponseMode


def build_action_ack(exec_results: ExecResults | None) -> ActionAck | None:
    """DB 실행 결과를 사용자 안내문과 응답 생성 모드로 변환한다."""
    if not exec_results:
        return None

    if exec_results.submit:
        result = exec_results.submit

        if result.db_changed and result.action is ExecutorActionType.SUCCESS_RECORDED:
            return ActionAck(random.choice(_SUCCESS_RECORDED_ACKS), ResponseMode.PREFIX_WITH_GEMMA)

        if result.db_changed and result.action is ExecutorActionType.FAIL_RECORDED:
            return ActionAck(random.choice(_FAIL_RECORDED_ACKS), ResponseMode.PREFIX_WITH_GEMMA)

        if result.status == SubmitStatus.ALREADY_SUBMITTED:
            return ActionAck(
                random.choice(_ALREADY_SUBMITTED_ACKS),
                ResponseMode.SERVER_ONLY,
            )

        if result.status == SubmitStatus.NO_MISSION:
            return ActionAck("오늘은 아직 할 수 있는 미션이 없어! 잠시만 기다려줘~ 😊", ResponseMode.SERVER_ONLY)

        if result.status == SubmitStatus.DB_ERROR:
            return ActionAck("방금 기록을 저장하지 못했어! ⚠️", ResponseMode.SERVER_ONLY)

    if exec_results.adjustment:
        result = exec_results.adjustment

        if result.db_changed and result.action is ExecutorActionType.MISSION_CHANGED:
            acks = _MISSION_CHANGED_ACKS.get(
                result.adjustment_type or "change",
                _MISSION_CHANGED_ACKS["change"],
            )
            return ActionAck(random.choice(acks), ResponseMode.PREFIX_WITH_GEMMA)

        if result.status == AdjustmentStatus.ALREADY_SUBMITTED:
            return ActionAck(_ADJUSTMENT_ALREADY_SUBMITTED_MSG, ResponseMode.SERVER_ONLY)

        if result.status == AdjustmentStatus.NO_ALTERNATIVE:
            return ActionAck("지금은 바꿀 수 있는 다른 미션이 없어!", ResponseMode.SERVER_ONLY)

        if result.status == AdjustmentStatus.NO_MISSION:
            return ActionAck("오늘은 바꿀 미션이 없어!", ResponseMode.SERVER_ONLY)

        if result.status == AdjustmentStatus.DB_ERROR:
            return ActionAck("미션 바꾸기를 실패했어! ⚠️", ResponseMode.SERVER_ONLY)

    if exec_results.cancel:
        result = exec_results.cancel

        if result.db_changed and result.action is ExecutorActionType.ACTION_CANCELLED:
            return ActionAck(random.choice(_ACTION_CANCELLED_ACKS), ResponseMode.SERVER_ONLY)

        if result.status == CancelStatus.NOTHING_TO_CANCEL:
            return ActionAck("지금은 취소할 내용이 없어! 다시 한 번 확인해볼래?", ResponseMode.SERVER_ONLY)

        if result.status == CancelStatus.DB_ERROR:
            return ActionAck("취소하기를 실패했어! ⚠️", ResponseMode.SERVER_ONLY)

    return None


def build_conflict_ack() -> ActionAck:
    """서로 충돌하는 기능 요청은 LLM 없이 고정 안내한다."""
    return ActionAck(_CONFLICT_MSG, ResponseMode.SERVER_ONLY)


def build_action_ack_prefix(exec_results: ExecResults | None) -> str | None:
    """기존 호출부 호환용: 안내문만 반환한다."""
    ack = build_action_ack(exec_results)
    return ack.message if ack else None
