from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from equivalency_numeric import compare_numeric_target


class ReasonCode(str, Enum):
    APPROVED_SPLIT_COMPLETION = "approved_split_completion"
    APPROVED_SPLIT_DURATION = "approved_split_duration"
    DENIED_MAX_DURATION_EXCEEDED = "denied_max_duration_exceeded"
    DENIED_VIDEO_SUBSTITUTE = "denied_video_substitute"
    DENIED_SUBSTITUTE = "denied_substitute"


class ResponseHintKind(str, Enum):
    SPLIT_COMPLETION_APPROVED = "split_completion_approved"
    SPLIT_DURATION_APPROVED = "split_duration_approved"
    MAX_DURATION_EXCEEDED = "max_duration_exceeded"
    VIDEO_SUBSTITUTE_DENIED = "video_substitute_denied"
    DENIED_SUBSTITUTE = "denied_substitute"


_VIDEO_PLATFORM_LABELS = (
    ("틱톡", "틱톡"),
    ("릴스", "릴스"),
    ("쇼츠", "쇼츠"),
    ("유튜브", "유튜브"),
    ("유튭", "유튜브"),
    ("유투브", "유튜브"),
    ("넷플릭스", "넷플릭스"),
    ("ott", "OTT"),
    ("tv", "TV"),
    ("티비", "TV"),
)


def _mentioned_video_platform(*texts: str) -> str | None:
    haystack = " ".join(texts).lower()
    for keyword, label in _VIDEO_PLATFORM_LABELS:
        if keyword in haystack:
            return label
    return None


def _coerce_reason_code(value: Any) -> ReasonCode | None:
    if isinstance(value, ReasonCode):
        return value
    if not value:
        return None
    try:
        return ReasonCode(str(value))
    except ValueError:
        return None


def _coerce_hint_kind(value: Any) -> ResponseHintKind | None:
    if isinstance(value, ResponseHintKind):
        return value
    if not value:
        return None
    try:
        return ResponseHintKind(str(value))
    except ValueError:
        return None


def attach_response_hint(
    judgment: Mapping[str, Any] | dict[str, Any] | None,
    user_message: str,
    mission: Mapping[str, Any] | None,
) -> dict[str, Any]:
    updated = dict(judgment or {})
    if not mission:
        return updated

    decision = str(updated.get("decision") or "").strip().lower()
    metadata_override = updated.get("metadata_override") or {}
    numeric = compare_numeric_target(user_message, dict(mission))
    reason_code = _coerce_reason_code(updated.get("reason_code"))
    hint = {
        "mission_name": mission.get("mission_name"),
        "target_metric": mission.get("target_metric"),
        "target_value": mission.get("target_value"),
        "target_unit": mission.get("target_unit"),
        "numeric_status": numeric.get("status"),
        "user_value": numeric.get("user_value"),
        "user_unit": numeric.get("user_unit"),
        "kind": _coerce_hint_kind((updated.get("response_hint") or {}).get("kind")),
    }

    if decision == "denied":
        if metadata_override.get("source") == "denied_substitutes":
            platform = _mentioned_video_platform(
                user_message,
                str(metadata_override.get("matched") or ""),
                str(updated.get("reason") or ""),
                str(updated.get("reply") or ""),
            )
            if platform:
                reason_code = ReasonCode.DENIED_VIDEO_SUBSTITUTE
                hint["kind"] = ResponseHintKind.VIDEO_SUBSTITUTE_DENIED
                hint["platform"] = platform
            else:
                reason_code = ReasonCode.DENIED_SUBSTITUTE
                hint["kind"] = ResponseHintKind.DENIED_SUBSTITUTE
                hint["matched"] = metadata_override.get("matched")
        elif numeric.get("status") == "above_limit" and str(mission.get("target_metric") or "").strip() == "max_duration":
            reason_code = ReasonCode.DENIED_MAX_DURATION_EXCEEDED
            hint["kind"] = ResponseHintKind.MAX_DURATION_EXCEEDED

    if decision == "approved":
        if "split_completion_override" in updated:
            reason_code = ReasonCode.APPROVED_SPLIT_COMPLETION
            hint["kind"] = ResponseHintKind.SPLIT_COMPLETION_APPROVED
        elif "duration_split_override" in updated:
            reason_code = ReasonCode.APPROVED_SPLIT_DURATION
            hint["kind"] = ResponseHintKind.SPLIT_DURATION_APPROVED

    if reason_code is not None:
        updated["reason_code"] = reason_code
    updated["response_hint"] = hint
    return updated


def build_fallback_reply(judgment: Mapping[str, Any] | dict[str, Any] | None) -> str:
    data = dict(judgment or {})
    decision = str(data.get("decision") or "").strip().lower()
    reply = str(data.get("reply") or "").strip()
    reason = str(data.get("reason") or "").strip()
    hint = data.get("response_hint") or {}
    reason_code = _coerce_reason_code(data.get("reason_code"))
    kind = _coerce_hint_kind(hint.get("kind"))

    if decision == "approved":
        return reply or "응, 그것도 괜찮아 🙂"
    if decision == "clarify":
        question = data.get("clarify_question")
        return str(question).strip() if question else "무엇을 얼마나 했는지 조금만 더 알려줄래 🙂"

    if reason_code is ReasonCode.DENIED_MAX_DURATION_EXCEEDED or kind is ResponseHintKind.MAX_DURATION_EXCEEDED:
        target_value = hint.get("target_value") or "기준"
        target_unit = hint.get("target_unit") or ""
        user_value = hint.get("user_value")
        user_unit = hint.get("user_unit") or target_unit
        if user_value is not None:
            return f"아쉽지만, 총 시간이 {target_value}{target_unit}을 넘었어, 지금처럼 보면 총 {user_value}{user_unit}이라 이번엔 인정이 어려워 😢"
        return f"아쉽지만, 총 시간이 {target_value}{target_unit}을 넘어서 이번엔 인정이 어려워 😢"
    if reason_code is ReasonCode.DENIED_VIDEO_SUBSTITUTE or kind is ResponseHintKind.VIDEO_SUBSTITUTE_DENIED:
        platform = hint.get("platform") or "그 영상"
        return f"유튜브를 안 본 건 좋지만, {platform}도 영상 시청이라 30분 제한 취지에 포함돼서 이번엔 인정이 어려워 📱"
    if reason_code is ReasonCode.DENIED_SUBSTITUTE or kind is ResponseHintKind.DENIED_SUBSTITUTE:
        matched = hint.get("matched")
        if matched:
            return f"아쉽지만 {matched}는 이번 미션에서 인정되는 대체 행동은 아니야 😢"

    if reply:
        return reply
    if reason:
        return f"아쉽지만 {reason} 😢"
    return "아쉽지만,그건 이번 미션 기준으로는 인정이 어려워 😢"
