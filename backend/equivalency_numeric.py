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
    "잔": "잔",
    "컵": "잔",
    "l": "L",
    "L": "L",
    "리터": "L",
    "ml": "L",
    "mL": "L",
    "밀리": "L",
}


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
    if unit in {"ml", "mL", "밀리"}:
        return value / Decimal("1000"), "L"
    return value, canonical


def _format_decimal(value: Decimal) -> str:
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f")


def _extract_quantities(text: str) -> list[Quantity]:
    quantities: list[Quantity] = []
    normalized = normalize_equivalency_text(text)
    pattern = re.compile(r"(\d+(?:\.\d+)?)\s*(시간|분|초|회|번|개|층|잔|컵|L|l|리터|ml|mL|밀리)")
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


def _target_unit_group(metric: str, target_unit: str) -> set[str]:
    if metric in {"duration", "duration_each", "max_duration"}:
        return {"분", "초"}
    if metric in {"reps", "count"}:
        canonical = UNIT_ALIASES.get(target_unit, target_unit)
        if canonical == "회":
            return {"회"}
        if canonical == "층":
            return {"층"}
        if canonical == "잔":
            return {"잔"}
        return {canonical}
    if metric == "volume":
        return {"L"}
    return set()


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
            selected = max(candidates, key=lambda q: q.value)
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
