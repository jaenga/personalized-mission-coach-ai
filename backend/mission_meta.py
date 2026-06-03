from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from equivalency_numeric import extract_numeric_for_goal

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


def extract_numeric(text: str, goal: NumericGoal) -> float | None:
    return extract_numeric_for_goal(text, goal.unit, goal.unit_aliases)


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
        numeric=NumericGoal(50, "회", {"번": 1, "개": 1}),
        target_kw=["줄넘기", "줄넘"],
        success_kw=["뛰었", "뛰었다", "했어", "했다", "함", "완료"],
    ),
    25: MissionMeta(
        type="perform",
        numeric=NumericGoal(10, "분"),
        target_kw=["계단", "오르", "내리", "오르내리", "걷"],
        success_kw=["올랐", "올라갔", "내려갔", "오르내렸", "걸었", "했어", "했다", "함"],
    ),
    29: MissionMeta(
        type="perform",
        numeric=NumericGoal(25, "번", {"회": 1, "개": 1}),
        target_kw=["버피", "버피테스트", "버피 테스트"],
        success_kw=["했어", "했다", "함", "완료", "끝냈"],
    ),
    38: MissionMeta(
        type="perform",
        numeric=NumericGoal(12, "분"),
        target_kw=["스트레칭", "몸풀", "몸 풀", "체조", "늘리"],
        success_kw=["했어", "했다", "함", "완료", "늘렸"],
    ),
    43: MissionMeta(
        type="perform",
        numeric=NumericGoal(10, "분"),
        target_kw=["춤", "춤추", "춤추기", "발레", "댄스", "에어로빅", "율동", "무용"],
        success_kw=["췄", "췄어", "췄다", "췄음", "했어", "했다"],
    ),
    51: MissionMeta(
        type="perform",
        target_kw=["밥", "아침밥", "아침", "먹"],
        success_kw=["먹었", "먹었어", "먹음"],
    ),
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
            {"L": 1000, "l": 1000, "리터": 1000, "잔": 200, "컵": 200},
        ),
        target_kw=["물", "잔", "컵", "마시", "먹"],
        success_kw=["마셨어", "마셨", "마심", "먹었"],
    ),
    87: MissionMeta(
        type="prohibit",
        target_kw=["과자", "스낵", "쿠키", "초코", "젤리", "사탕", "간식"],
    ),
    96: MissionMeta(
        type="perform",
        numeric=NumericGoal(1, "회", {"번": 1, "개": 1, "입": 1, "조각": 1}),
        target_kw=["과일", "사과", "바나나", "귤", "딸기", "포도", "키위", "수박", "복숭아", "오렌지", "망고"],
        success_kw=["먹었", "먹었어", "먹음", "먹었다", "먹었음"],
    ),
    112: MissionMeta(
        type="perform",
        numeric=NumericGoal(3, "분"),
        target_kw=["양치", "치아", "칫솔", "치약", "이", "이빨"],
        success_kw=["닦았", "닦음", "양치했", "양치함", "양치했어", "했다"],
    ),
    153: MissionMeta(
        type="perform",
        numeric=NumericGoal(10, "분"),
        target_kw=["방", "정리", "책상", "치우", "청소", "깨끗"],
        success_kw=["정리했", "치웠", "청소했", "깨끗", "했어", "했다", "함"],
    ),
    159: MissionMeta(
        type="perform",
        target_kw=["숙제", "공부", "과제", "게임", "겜", "유튜브", "영상", "폰"],
        success_kw=["끝냈", "끝났", "먼저", "마쳤", "다 했", "완료", "하고 게임"],
    ),
    168: MissionMeta(
        type="limit",
        numeric=NumericGoal(30, "분"),
        target_kw=["유튜브", "유튭", "유투브", "영상", "쇼츠", "숏츠", "릴스", "동영상", "화면"],
    ),
    192: MissionMeta(
        type="prohibit",
        target_kw=["화면", "핸드폰", "휴대폰", "폰", "TV", "티비", "유튜브", "유튭", "유투브", "영상", "쇼츠", "숏츠", "릴스", "게임", "겜"],
    ),
}
