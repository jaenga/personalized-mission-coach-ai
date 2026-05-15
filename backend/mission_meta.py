from __future__ import annotations

import re
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


_NUMBER_KO = {
    "한": 1,
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
}


def extract_numeric(text: str, goal: NumericGoal) -> float | None:
    unit_map = {
        "회": "회",
        "번": "회",
        "개": "회",
        "분": "분",
        "시간": "분",
        "초": "초",
        "ml": "ml",
        "mL": "ml",
        "L": "ml",
        "l": "ml",
        "리터": "ml",
        "잔": "ml",
        "컵": "ml",
    }
    goal_unit = unit_map.get(goal.unit, goal.unit)
    pattern = re.compile(
        r"(\d+(?:\.\d+)?|" + "|".join(_NUMBER_KO.keys()) + r")\s*"
        r"(분|초|시간|회|번|개|잔|컵|L|l|ml|mL|리터)"
    )
    for match in pattern.finditer(text or ""):
        raw_num, raw_unit = match.group(1), match.group(2)
        if unit_map.get(raw_unit, raw_unit) != goal_unit:
            continue

        val = float(_NUMBER_KO.get(raw_num, raw_num))
        if raw_unit == "시간":
            val *= 60
        elif raw_unit in goal.unit_aliases:
            val *= goal.unit_aliases[raw_unit]
        return val
    return None


MISSION_META: dict[int, MissionMeta] = {
    2: MissionMeta(
        type="perform",
        numeric=NumericGoal(10, "분"),
        target_kw=["걷", "걸었", "산책", "점심"],
        success_kw=["걸었", "산책했"],
    ),
    12: MissionMeta(
        type="substitute",
        target_kw=["엘리베이터", "엘레베이터", "엘베", "승강기"],
        success_kw=["계단", "계단실", "올라갔", "이용했"],
    ),
    16: MissionMeta(
        type="perform",
        numeric=NumericGoal(50, "회"),
        target_kw=["줄넘기", "줄넘"],
        success_kw=["뛰었"],
    ),
    25: MissionMeta(type="perform", numeric=NumericGoal(10, "분")),
    29: MissionMeta(type="perform", numeric=NumericGoal(25, "번")),
    38: MissionMeta(type="perform", numeric=NumericGoal(12, "분")),
    43: MissionMeta(type="perform", numeric=NumericGoal(10, "분")),
    51: MissionMeta(type="perform"),
    62: MissionMeta(
        type="perform",
        numeric=NumericGoal(30, "초"),
        target_kw=["손", "손씻", "손 씻", "비누"],
        success_kw=["씻었", "씻음", "씻었어"],
    ),
    67: MissionMeta(
        type="perform",
        numeric=NumericGoal(200, "ml", {"잔": 200, "컵": 200}),
        target_kw=["물", "잔", "컵"],
        success_kw=["마셨어", "마셨", "마심"],
    ),
    71: MissionMeta(
        type="perform",
        numeric=NumericGoal(
            1000,
            "ml",
            {"L": 1000, "l": 1000, "리터": 1000, "잔": 200},
        ),
    ),
    87: MissionMeta(
        type="prohibit",
        target_kw=["과자", "스낵", "쿠키"],
    ),
    96: MissionMeta(
        type="perform",
        numeric=NumericGoal(1, "회", {"번": 1, "개": 1}),
        target_kw=["과일", "사과", "바나나", "귤", "딸기", "포도"],
        success_kw=["먹었", "먹었어", "먹음"],
    ),
    112: MissionMeta(
        type="perform",
        numeric=NumericGoal(3, "분"),
        target_kw=["양치", "치아", "칫솔", "치약", "이"],
        success_kw=["닦았", "양치했", "양치함"],
    ),
    153: MissionMeta(type="perform", numeric=NumericGoal(10, "분")),
    159: MissionMeta(
        type="perform",
        target_kw=["숙제", "공부", "과제"],
        success_kw=["끝냈", "끝났", "먼저", "마쳤"],
    ),
    168: MissionMeta(
        type="limit",
        numeric=NumericGoal(30, "분"),
        target_kw=["유튜브", "유튭", "유투브", "영상", "쇼츠", "릴스"],
    ),
    192: MissionMeta(
        type="prohibit",
        target_kw=["화면", "핸드폰", "폰", "TV", "유튜브", "유튭", "유투브", "영상", "쇼츠", "릴스"],
    ),
}
