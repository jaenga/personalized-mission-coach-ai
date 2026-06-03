from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from mission_meta import MISSION_META


MissionContextType = Literal["perform", "prohibit", "limit", "substitute"]

_PERFORM_METRICS = {
    "count",
    "reps",
    "duration",
    "duration_each",
    "volume",
    "meal_completion",
}


@dataclass(frozen=True)
class MissionContext:
    mission_id: int | None = None
    mission_name: str = ""
    activity_key: str = ""
    category: str = ""
    mission_type: MissionContextType = "perform"
    mission_subtype: str | None = None
    target_kw: list[str] = field(default_factory=list)
    success_kw: list[str] = field(default_factory=list)
    fail_kw: list[str] = field(default_factory=list)
    target_metric: str = ""
    target_value: str = ""
    target_unit: str = ""
    success_criteria: str = ""
    strict_requirements: str = ""
    allowed_substitutes: str = ""
    denied_substitutes: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.mission_id or self.mission_name or self.activity_key)


def build_mission_context(
    mission_row: dict[str, Any] | None,
    mission_id: int | str | None = None,
    mission_name: str = "",
) -> MissionContext:
    """Build a lightweight, read-only context object for today's mission.

    This helper does not perform routing, DB writes, or final success/fail
    judgment. It only normalizes mission metadata for later hint generation.
    """

    row = mission_row or {}
    resolved_mission_id = _coerce_int(row.get("mission_id"), mission_id)
    resolved_mission_name = _first_text(row.get("mission_name"), mission_name)
    meta = MISSION_META.get(resolved_mission_id or -1)

    target_metric = _clean_text(row.get("target_metric")).lower()
    mission_type, mission_subtype = _resolve_mission_type(target_metric, meta)

    activity_key = _clean_text(row.get("activity_key"))
    category = _first_text(row.get("category"), row.get("main_category"), row.get("sub_category"))
    target_unit = _clean_text(row.get("target_unit"))
    target_value = _clean_text(row.get("target_value"))
    success_criteria = _clean_text(row.get("success_criteria"))
    strict_requirements = _clean_text(row.get("strict_requirements"))
    allowed_substitutes = _clean_text(row.get("allowed_substitutes"))
    denied_substitutes = _clean_text(row.get("denied_substitutes"))

    target_kw = _unique_texts([
        *(meta.target_kw if meta else []),
        activity_key,
        *_keywords_from_text(resolved_mission_name),
        *_keywords_from_text(activity_key),
    ])
    success_kw = _unique_texts([
        *(meta.success_kw if meta else []),
        *_phrases_from_metadata(success_criteria),
        *_phrases_from_metadata(allowed_substitutes),
    ])
    fail_kw = _unique_texts(_phrases_from_metadata(denied_substitutes))

    return MissionContext(
        mission_id=resolved_mission_id,
        mission_name=resolved_mission_name,
        activity_key=activity_key,
        category=category,
        mission_type=mission_type,
        mission_subtype=mission_subtype,
        target_kw=target_kw,
        success_kw=success_kw,
        fail_kw=fail_kw,
        target_metric=target_metric,
        target_value=target_value,
        target_unit=target_unit,
        success_criteria=success_criteria,
        strict_requirements=strict_requirements,
        allowed_substitutes=allowed_substitutes,
        denied_substitutes=denied_substitutes,
    )


def _resolve_mission_type(target_metric: str, meta) -> tuple[MissionContextType, str | None]:
    if target_metric == "max_duration":
        return "limit", None
    if target_metric == "avoid":
        return "prohibit", None
    if target_metric == "order":
        return "perform", "order"
    if target_metric in _PERFORM_METRICS:
        subtype = target_metric if target_metric in {"duration_each", "meal_completion"} else None
        return "perform", subtype
    if meta and meta.type in {"perform", "prohibit", "limit", "substitute"}:
        return meta.type, None
    return "perform", None


def _coerce_int(*values: Any) -> int | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        compact = text.replace(" ", "")
        if compact in seen:
            continue
        seen.add(compact)
        result.append(text)
    return result


def _keywords_from_text(text: str) -> list[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", text or "")
    return [
        token
        for token in tokens
        if len(token) >= 2 and token not in {"오늘", "미션", "하기", "동안", "이상", "이하"}
    ]


def _phrases_from_metadata(text: str) -> list[str]:
    if not text:
        return []
    pieces = re.split(r"[,/]| 또는 | 혹은 | 및 ", text)
    return [
        piece.strip()
        for piece in pieces
        if len(piece.strip()) >= 2
    ]
