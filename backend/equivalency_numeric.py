from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from equivalency_normalizer import normalize_equivalency_text

SUPPORTED_METRICS = {"duration", "duration_each", "reps", "count", "volume", "max_duration"}

UNIT_ALIASES = {
    "분": "분",
    "초": "초",
    "시간": "분",
    "회": "회",
    "번": "회",
    "개": "회",
    "층": "층",
    "바퀴": "바퀴",
    "보": "보",
    "걸음": "보",
    "세트": "세트",
    "봉지": "봉지",
    "병": "병",
    "입": "입",
    "잔": "잔",
    "컵": "잔",
    "l": "L",
    "L": "L",
    "리터": "L",
    "ml": "L",
    "mL": "L",
    "밀리": "L",
    "미리": "L",
}

_ACCUMULATION_MARKERS = (
    "나눠서",
    "나누어서",
    "나눠",
    "나누어",
    "씩",
    "쉬었다가",
    "쉬고",
    "쉬었다",
    "쉬어",
    "오전",
    "오후",
    "아침",
    "점심",
    "저녁",
    "밤",
    "낮",
    "새벽",
    "또",
    "다시",
    "각각",
)


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: str
    raw_value: str
    raw_unit: str
    text: str

    def to_hint_dict(self) -> dict[str, str]:
        return {
            "value": _format_decimal(self.value),
            "unit": self.unit,
            "text": self.text,
        }


@dataclass(frozen=True)
class NumericComparison:
    status: str
    target_metric: str
    target_value: Decimal | None
    target_unit: str
    user_value: Decimal | None
    user_unit: str
    found_quantities: list[Quantity]

    @property
    def instruction(self) -> str:
        return _instruction(self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "target_metric": self.target_metric,
            "target_value": None if self.target_value is None else _format_decimal(self.target_value),
            "target_unit": self.target_unit,
            "user_value": None if self.user_value is None else _format_decimal(self.user_value),
            "user_unit": self.user_unit,
            "found_quantities": [quantity.to_hint_dict() for quantity in self.found_quantities],
            "instruction": self.instruction,
        }


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _convert_value(value: Decimal, unit: str) -> tuple[Decimal, str]:
    canonical = UNIT_ALIASES.get(unit, unit)
    if unit == "시간":
        return value * Decimal("60"), "분"
    if unit in {"ml", "mL", "밀리", "미리"}:
        return value / Decimal("1000"), "L"
    return value, canonical


def _format_decimal(value: Decimal) -> str:
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f")


def canonical_numeric_unit(unit: str) -> str:
    return UNIT_ALIASES.get(unit, unit)


def convert_numeric_value(value: Any, unit: str) -> tuple[float | None, str]:
    numeric_value = _to_decimal(value)
    converted_unit = canonical_numeric_unit(unit)
    if numeric_value is None:
        return None, converted_unit
    converted_value, converted_unit = _convert_value(numeric_value, unit)
    return float(converted_value), converted_unit


def _extract_quantities(text: str) -> list[Quantity]:
    quantities: list[Quantity] = []
    normalized = normalize_equivalency_text(text)
    pattern = re.compile(
        r"(\d+(?:\.\d+)?)\s*"
        r"(시간|분|초|회|번|개|층|바퀴|보|걸음|세트|봉지|병|입|잔|컵|L|l|리터|ml|mL|밀리|미리)"
    )
    for match in pattern.finditer(normalized):
        raw_value = _to_decimal(match.group(1))
        if raw_value is None:
            continue
        raw_unit = match.group(2)
        value, unit = _convert_value(raw_value, raw_unit)
        quantities.append(
            Quantity(
                value=value,
                unit=unit,
                raw_value=match.group(1),
                raw_unit=raw_unit,
                text=match.group(0),
            )
        )
    return quantities


def extract_first_numeric_quantity(text: str) -> tuple[float, str] | None:
    quantities = _extract_quantities(text)
    if not quantities:
        return None
    quantity = quantities[0]
    return float(quantity.value), quantity.unit


def extract_numeric_for_goal(
    text: str,
    target_unit: str,
    unit_aliases: dict[str, float] | None = None,
) -> float | None:
    """Return the first comparable quantity in the target unit's scale.

    `compare_numeric_target` uses canonical units for DB metadata. This helper
    keeps the older MISSION_META contract: a ml goal receives ml, a 분 goal
    receives minutes, and alias multipliers such as 잔=200 are respected.
    """
    aliases = unit_aliases or {}
    target_canonical = canonical_numeric_unit(target_unit)
    for quantity in _extract_quantities(text):
        if quantity.raw_unit in aliases:
            return float(quantity.value * Decimal(str(aliases[quantity.raw_unit])))
        if target_unit in {"ml", "mL"} and quantity.unit == "L":
            return float(quantity.value * Decimal("1000"))
        if target_canonical == quantity.unit:
            return float(quantity.value)
    return None


def _target_unit_group(metric: str, target_unit: str) -> set[str]:
    if metric in {"duration", "duration_each", "max_duration"}:
        return {"분", "초"}
    if metric in {"reps", "count"}:
        canonical = UNIT_ALIASES.get(target_unit, target_unit)
        if canonical in {"회", "층", "잔", "바퀴", "보", "세트", "봉지", "병", "입"}:
            return {canonical}
        return {canonical}
    if metric == "volume":
        return {"L"}
    return set()


def _looks_like_split_completion(text: str) -> bool:
    compact = (text or "").replace(" ", "")
    return any(marker in compact for marker in _ACCUMULATION_MARKERS) and any(
        marker in compact for marker in ("했어요", "했어", "완료", "성공", "인정", "해도", "돼", "되나요", "괜찮")
    )


def _looks_like_accumulated_quantities(text: str) -> bool:
    compact = (text or "").replace(" ", "")
    return any(marker in compact for marker in _ACCUMULATION_MARKERS)


def _split_clauses(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[.!?\n]+", text or "") if part.strip()]


def _duration_split_total_candidate(candidates: list[Quantity], quantities: list[Quantity], user_message: str) -> Quantity | None:
    if not _looks_like_accumulated_quantities(user_message):
        return None
    if len(candidates) >= 2:
        total = sum((q.value for q in candidates), Decimal("0"))
        return Quantity(
            value=total,
            unit=candidates[0].unit,
            raw_value=_format_decimal(total),
            raw_unit=candidates[0].raw_unit,
            text=" + ".join(q.text for q in candidates),
        )
    counts = [q for q in quantities if q.unit == "회"]
    if not candidates or not counts:
        return None
    duration = min(candidates, key=lambda q: q.value)
    count = max(counts, key=lambda q: q.value)
    total = duration.value * count.value
    return Quantity(
        value=total,
        unit=duration.unit,
        raw_value=_format_decimal(total),
        raw_unit=duration.raw_unit,
        text=f"{duration.text}씩 {count.text}",
    )


def _clause_quantities(text: str, unit: str) -> list[Quantity]:
    return [q for q in _extract_quantities(text) if q.unit == unit]


def _accumulated_total_candidate(candidates: list[Quantity], user_message: str) -> Quantity | None:
    if len(candidates) < 2 or not _looks_like_accumulated_quantities(user_message):
        return None
    clauses = _split_clauses(user_message)
    selected_candidates = candidates
    for clause in clauses:
        clause_candidates = _clause_quantities(clause, candidates[0].unit)
        if len(clause_candidates) >= 2 and _looks_like_accumulated_quantities(clause):
            selected_candidates = clause_candidates
            break
    total = sum((q.value for q in selected_candidates), Decimal("0"))
    return Quantity(
        value=total,
        unit=selected_candidates[0].unit,
        raw_value=_format_decimal(total),
        raw_unit=selected_candidates[0].raw_unit,
        text=" + ".join(q.text for q in selected_candidates),
    )


def _count_or_volume_total_candidate(candidates: list[Quantity], user_message: str) -> Quantity | None:
    return _accumulated_total_candidate(candidates, user_message)


def _select_count_candidate(
    candidates: list[Quantity],
    target_value: Decimal,
    user_message: str,
) -> Quantity:
    total_candidate = _count_or_volume_total_candidate(candidates, user_message)
    if total_candidate is not None:
        return total_candidate
    if _looks_like_split_completion(user_message):
        meeting = [q for q in candidates if q.value >= target_value]
        if meeting:
            return min(meeting, key=lambda q: q.value)
    return min(candidates, key=lambda q: q.value)


def _status_for(metric: str, user_value: Decimal, target_value: Decimal) -> str:
    if metric == "max_duration":
        return "meets_target" if user_value <= target_value else "above_limit"
    return "meets_target" if user_value >= target_value else "below_target"


def _instruction(status: str) -> str:
    if status == "meets_target":
        return "수치 기준은 충족했다. 다만 strict_requirements, denied_substitutes, 행동 의미가 맞는지는 계속 확인한다."
    if status == "below_target":
        return "target_value 미달이므로 decision은 절대 approved가 될 수 없다. denied 또는 clarify로 판단한다."
    if status == "above_limit":
        return "허용 최대 시간을 초과했으므로 decision은 절대 approved가 될 수 없다. denied 또는 clarify로 판단한다."
    if status == "missing_value":
        return "사용자 발화에서 비교 가능한 숫자를 찾지 못했다. 수치 조건이 필요한 미션이면 approved하지 말고 clarify를 우선한다."
    if status == "unclear":
        return "숫자는 있으나 target_unit과 직접 비교하기 어렵다. approved하지 말고 필요한 정보를 짧게 확인한다."
    return "이 metric은 서버 숫자 비교 대상이 아니다. mission_rule과 메타데이터 기준으로 판단한다."


def compare_numeric_target(user_message: str, mission: dict) -> dict[str, Any]:
    metric = str(mission.get("target_metric") or "").strip()
    target_value = _to_decimal(mission.get("target_value"))
    target_unit = str(mission.get("target_unit") or "").strip()

    if metric not in SUPPORTED_METRICS:
        return NumericComparison(
            status="not_applicable",
            target_metric=metric,
            target_value=target_value,
            target_unit=target_unit,
            user_value=None,
            user_unit="",
            found_quantities=[],
        ).to_dict()
    if target_value is None or not target_unit:
        return NumericComparison(
            status="not_applicable",
            target_metric=metric,
            target_value=target_value,
            target_unit=target_unit,
            user_value=None,
            user_unit="",
            found_quantities=[],
        ).to_dict()

    converted_target, converted_target_unit = _convert_value(target_value, target_unit)
    wanted_units = _target_unit_group(metric, converted_target_unit)
    quantities = _extract_quantities(user_message)
    candidates = [q for q in quantities if q.unit in wanted_units]

    if not quantities:
        status = "missing_value"
        user_value = None
        user_unit = ""
    elif not candidates:
        status = "unclear"
        user_value = None
        user_unit = ""
    else:
        # 보수적 선택: 잘못된 approved를 막기 위해 위반 가능성 높은 후보를 우선.
        # max_duration(한도형)은 가장 큰 값, 그 외(최소 충족형)는 가장 작은 값.
        # 예: "30분 미션인데 31분 보면" → max=31 → above_limit
        if metric == "max_duration":
            selected = _accumulated_total_candidate(candidates, user_message) or max(candidates, key=lambda q: q.value)
        elif metric == "duration":
            selected = _duration_split_total_candidate(candidates, quantities, user_message) or min(candidates, key=lambda q: q.value)
        elif metric in {"reps", "count"}:
            selected = _select_count_candidate(candidates, converted_target, user_message)
        elif metric == "volume":
            selected = _count_or_volume_total_candidate(candidates, user_message) or min(candidates, key=lambda q: q.value)
        else:
            selected = min(candidates, key=lambda q: q.value)
        user_value = selected.value
        user_unit = selected.unit
        status = _status_for(metric, user_value, converted_target)

    return NumericComparison(
        status=status,
        target_metric=metric,
        target_value=converted_target,
        target_unit=converted_target_unit,
        user_value=user_value,
        user_unit=user_unit,
        found_quantities=quantities,
    ).to_dict()


def format_numeric_comparison_hint(comparison: dict[str, Any]) -> str:
    status = comparison.get("status")
    if status == "not_applicable":
        return ""
    lines = [
        "[서버 숫자 비교 결과]",
        f"- status: {status}",
        f"- target_metric: {comparison.get('target_metric', '')}",
        f"- target: {comparison.get('target_value', '')}{comparison.get('target_unit', '')}",
    ]
    if comparison.get("user_value") is not None:
        lines.append(f"- user: {comparison.get('user_value')}{comparison.get('user_unit', '')}")
    else:
        lines.append("- user: 비교 가능한 숫자 없음")
    found = comparison.get("found_quantities") or []
    if found:
        lines.append(f"- found_quantities: {found}")
    lines.append(f"- 판단 지시: {comparison.get('instruction', '')}")
    lines.append("이 결과는 판단에서 반드시 우선한다. below_target/above_limit/missing_value이면 decision은 절대 approved가 될 수 없다.")
    return "\n".join(lines)
