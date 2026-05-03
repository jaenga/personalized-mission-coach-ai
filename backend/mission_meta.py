from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

MissionType = Literal["perform", "prohibit", "limit", "substitute"]


@dataclass
class NumericGoal:
    threshold: float
    unit: str
    unit_aliases: dict[str, float] = field(default_factory=dict)


@dataclass
class MissionMeta:
    type: MissionType
    numeric: Optional[NumericGoal] = None
    target_kw: list[str] = field(default_factory=list)
    success_kw: list[str] = field(default_factory=list)


MISSION_META: dict[int, MissionMeta] = {
    2: MissionMeta(type="perform"),
    12: MissionMeta(
        type="substitute",
        target_kw=["엘리베이터", "승강기"],
        success_kw=["계단"],
    ),
    16: MissionMeta(type="perform", numeric=NumericGoal(50, "회")),
    25: MissionMeta(type="perform", numeric=NumericGoal(10, "분")),
    29: MissionMeta(type="perform", numeric=NumericGoal(25, "번")),
    38: MissionMeta(type="perform", numeric=NumericGoal(12, "분")),
    43: MissionMeta(type="perform", numeric=NumericGoal(10, "분")),
    51: MissionMeta(type="perform"),
    62: MissionMeta(type="perform"),
    67: MissionMeta(type="perform"),
    71: MissionMeta(
        type="perform",
        numeric=NumericGoal(
            1000,
            "ml",
            {"L": 1000, "l": 1000, "리터": 1000, "잔": 200},
        ),
    ),
    87: MissionMeta(type="prohibit", target_kw=["과자"]),
    96: MissionMeta(type="perform"),
    112: MissionMeta(type="perform"),
    153: MissionMeta(type="perform", numeric=NumericGoal(10, "분")),
    159: MissionMeta(type="perform"),
    168: MissionMeta(
        type="limit",
        numeric=NumericGoal(30, "분"),
        target_kw=["유튜브", "영상", "쇼츠"],
    ),
    192: MissionMeta(
        type="prohibit",
        target_kw=["화면", "핸드폰", "폰", "TV", "유튜브", "영상"],
    ),
}
