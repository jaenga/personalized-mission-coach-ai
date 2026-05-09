from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from activity_keys import VALID_ACTIVITY_KEYS, normalize_activity_key
from ollama_client import generate_json_message


MAX_TITLE_LENGTH = 48
VALID_MAIN_CATEGORIES = {"digital_detox", "healthy_routine", "nutrition", "physical_activity"}
VALID_SUB_CATEGORIES = {
    "active_play",
    "daily_habit",
    "exercise",
    "game",
    "healthy_food",
    "hygiene",
    "meal",
    "morning",
    "screen_free_time",
    "screen_time",
    "sleep",
    "snack",
    "stretching",
    "video",
    "walking",
    "water",
}
VALID_LOCATIONS = {"anywhere", "indoor", "outdoor", "school"}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}
REWARD_XP_BY_DIFFICULTY = {"easy": 5, "medium": 10, "hard": 12}

REQUIRED_RULE_SECTIONS = ("[미션 설명]", "[수행 방법]", "[주의 사항 및 규칙]")
SPECIFICITY_RE = re.compile(
    r"((\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(초|회|세트|분|잔|가지|번|쪽|걸음)|"
    r"(오늘 하루|자기 전|잠들기 전|기상 후|아침에|점심에|저녁에|식사 중|식사 전|식사 후|외출 후|화장실 후|등교 전|하교 후))"
)
UNSAFE_PATTERNS = re.compile(
    r"(무리한|무리해서|통증.*참|아파도|굶|굶기|금식|약|영양제|처방|진단|치료|의료|"
    r"체중\s*감량|살\s*빼|다이어트|위험한|차도|도로|밤늦|늦은 밤|혼자 밖|"
    r"부적절|벌칙|벌로|몰래)"
)


GENERATION_SYSTEM_PROMPT = """너는 어린이/학생용 건강 습관 미션을 만드는 코치야.
반드시 JSON 객체 하나만 출력해. 설명 문장, 마크다운, 코드블록은 출력하지 마.

출력 JSON 형식:
{
  "mission_name": "valid_activity_keys 중 선택한 활동으로 만든 구체적인 미션명",
  "main_category": "allowed_enums.main_category 중 하나",
  "sub_category": "allowed_enums.sub_category 중 하나",
  "mission_location": "allowed_enums.mission_location 중 하나",
  "difficulty": "allowed_enums.difficulty 중 하나",
  "reward_xp": 5,
  "activity_key": "valid_activity_keys 중 하나",
  "mission_group": null,
  "mission_rule": "[미션 설명] ...\n\n[수행 방법] ...\n\n[주의 사항 및 규칙] ..."
}

규칙:
- mission_name은 12~20자 정도의 짧은 명령형 제목으로 써.
- mission_name에는 성공 기준을 포함해.
- "미션"이라는 단어를 붙이지 마.
- 같은 말을 반복하지 마. 예: "물 마시기 2리터 마시기" 금지, "물 3잔 마시기"처럼 써.
- activity_key를 그대로 제목으로 쓰지 말고, 수량/상황을 붙여 구체화해.
- activity_key는 반드시 user payload의 valid_activity_keys 목록 중 하나만 선택해. 새 키워드를 만들지 마.
- activity_key는 반드시 valid_activity_keys 배열 안의 값 중 하나를 그대로 복사해.
- valid_activity_keys에 없는 activity_key를 쓰면 실패야.
- valid_activity_keys가 1개라면 반드시 그 1개 activity_key만 사용한다.
- 예시 JSON의 값을 복사하지 말고, user payload의 valid_activity_keys를 기준으로 생성한다.
- activity_key는 mission_name과 mission_rule의 실제 활동 내용과 반드시 일치해야 해.
- 선택한 activity_key와 다른 활동을 mission_name이나 mission_rule에 쓰면 안 돼.
- activity_key가 "X"이면 mission_name/rule에도 X 활동이 들어가야 해.
- restricted_activity_keys와 avoid_activity_keys에 해당하는 활동은 절대 만들지 마.
- restriction_terms와 직접 충돌하는 단어가 들어가면 안 돼.
- main_category, sub_category, mission_location, difficulty는 허용 enum만 사용해.
- main_category는 반드시 digital_detox, healthy_routine, nutrition, physical_activity 중 하나만 써.
- main_category와 sub_category도 선택한 activity_key의 의미와 맞아야 해.
- user payload의 activity_generation_guides가 있으면 해당 activity_key의 default_meta와 generation_guide를 우선 반영해.
- default_meta가 있으면 main_category, sub_category, mission_location은 그 값을 그대로 사용해.
- generation_guide는 생성 품질 기준이야. 미션명, 수량, 장소, 안전 조건을 만들 때 반드시 참고해.
- mission_rule은 반드시 [미션 설명], [수행 방법], [주의 사항 및 규칙] 3단 구조를 포함해.
- mission_rule의 각 섹션은 1문장만 써.
- 전체 mission_rule은 180자 이내로 써.
- JSON 문자열이 끊기지 않도록 짧게 작성해.
- 성공 기준이 구체적이어야 해. 횟수, 시간, 양, 또는 상황 중 하나 이상을 mission_name이나 mission_rule에 넣어.
- 성공 기준의 수량은 "세 번"처럼 한글 숫자가 아니라 "3번", "1가지", "5분"처럼 숫자로 써.
- 오늘 하루 안에 끝낼 수 있는 1일 미션으로 써. "매일", "꾸준히", "앞으로" 같은 장기 반복 표현은 쓰지 마.
- 어린이 말투에 맞게 "하세요", "섭취" 같은 딱딱한 표현보다 "먹어보기", "해보기"처럼 쉽게 써.
- mission_rule에는 "~하세요", "~해주세요", "~합니다", "~해야 합니다", "섭취"를 쓰지 마.
- "~해보기", "~먹기", "~마시기", "~씻기"처럼 어린이가 보기 쉬운 표현으로 써.
- mission_group은 같은 활동의 유사 미션을 묶을 때만 사용해.
- 명확한 그룹이 없으면 null로 둬.
- 새로운 그룹명을 억지로 만들지 마.
- 금지: 무리한 운동, 통증 참기, 굶기, 약/영양제/의료 조언, 체중 감량 강요, 위험한 장소, 밤늦은 야외활동, 2리터처럼 많은 양의 물, 아이에게 부적절한 표현.
"""


class GeneratedMissionModel(BaseModel):
    mission_name: str = Field(..., min_length=1, max_length=MAX_TITLE_LENGTH)
    main_category: str
    sub_category: str
    mission_location: str
    difficulty: str
    reward_xp: int
    activity_key: str
    mission_group: str | None = Field(default=None, max_length=80)
    mission_rule: str = Field(..., min_length=20)

    @field_validator("mission_name", mode="before")
    @classmethod
    def _clean_title_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split())

    @field_validator("mission_group", mode="before")
    @classmethod
    def _clean_optional_group(cls, value: Any) -> str | None:
        text = " ".join(str(value or "").split())
        return text or None

    @field_validator("main_category")
    @classmethod
    def _validate_main_category(cls, value: str) -> str:
        if value not in VALID_MAIN_CATEGORIES:
            raise ValueError("invalid main_category")
        return value

    @field_validator("sub_category")
    @classmethod
    def _validate_sub_category(cls, value: str) -> str:
        if value not in VALID_SUB_CATEGORIES:
            raise ValueError("invalid sub_category")
        return value

    @field_validator("mission_location")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        if value not in VALID_LOCATIONS:
            raise ValueError("invalid mission_location")
        return value

    @field_validator("difficulty")
    @classmethod
    def _validate_difficulty(cls, value: str) -> str:
        value = (value or "").strip().lower()
        if value not in VALID_DIFFICULTIES:
            raise ValueError("invalid difficulty")
        return value

    @field_validator("activity_key")
    @classmethod
    def _validate_activity_key(cls, value: str) -> str:
        key = normalize_activity_key(value)
        if not key or key not in VALID_ACTIVITY_KEYS:
            raise ValueError("invalid activity_key")
        return key

    @field_validator("mission_rule")
    @classmethod
    def _validate_rule_sections(cls, value: str) -> str:
        rule = str(value or "").strip()
        if not all(section in rule for section in REQUIRED_RULE_SECTIONS):
            raise ValueError("mission_rule must include required sections")
        return rule

    @model_validator(mode="after")
    def _normalize_reward(self) -> "GeneratedMissionModel":
        self.reward_xp = REWARD_XP_BY_DIFFICULTY[self.difficulty]
        return self


def _valid_unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        key = normalize_activity_key(value if isinstance(value, str) else None)
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _normalize_difficulty(value: str | None, fallback: str = "medium") -> str:
    text = (value or "").strip().lower()
    if text == "normal":
        text = "medium"
    if text in VALID_DIFFICULTIES:
        return text
    return fallback if fallback in VALID_DIFFICULTIES else "medium"


def _clean_title(value: str | None) -> str:
    title = " ".join((value or "").split())
    if len(title) > MAX_TITLE_LENGTH:
        title = title[:MAX_TITLE_LENGTH].rstrip()
    return title


def _is_safe_text(*values: str | None) -> bool:
    text = " ".join(value or "" for value in values)
    return not UNSAFE_PATTERNS.search(text)


def _has_specific_success_criteria(*values: str | None) -> bool:
    text = " ".join(value or "" for value in values)
    return bool(SPECIFICITY_RE.search(text))


KOREAN_NUMBER_VALUES = {
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
QUANTITY_RE = re.compile(
    r"(\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(초|회|세트|분|잔|가지|번|쪽|걸음)"
)


def _quantity_value(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    return KOREAN_NUMBER_VALUES.get(value)


def _has_quantity_conflict(mission_name: str, mission_rule: str) -> bool:
    quantities_by_unit: dict[str, set[int]] = {}
    for value, unit in QUANTITY_RE.findall(f"{mission_name} {mission_rule}"):
        normalized = _quantity_value(value)
        if normalized is None:
            continue
        quantities_by_unit.setdefault(unit, set()).add(normalized)
    return any(len(values) > 1 for values in quantities_by_unit.values())


ACTIVITY_DEFAULT_META: dict[str, dict[str, str]] = {
    "걷기": {"main_category": "physical_activity", "sub_category": "walking", "mission_location": "anywhere"},
    "걸음수 채우기": {"main_category": "physical_activity", "sub_category": "walking", "mission_location": "anywhere"},
    "계단 이용하기": {"main_category": "physical_activity", "sub_category": "walking", "mission_location": "anywhere"},
    "줄넘기": {"main_category": "physical_activity", "sub_category": "exercise", "mission_location": "outdoor"},
    "스쿼트": {"main_category": "physical_activity", "sub_category": "exercise", "mission_location": "indoor"},
    "버피테스트": {"main_category": "physical_activity", "sub_category": "exercise", "mission_location": "indoor"},
    "팔굽혀펴기": {"main_category": "physical_activity", "sub_category": "exercise", "mission_location": "indoor"},
    "팔벌려뛰기": {"main_category": "physical_activity", "sub_category": "exercise", "mission_location": "indoor"},
    "플랭크": {"main_category": "physical_activity", "sub_category": "exercise", "mission_location": "indoor"},
    "벽 밀기": {"main_category": "physical_activity", "sub_category": "exercise", "mission_location": "indoor"},
    "제자리 달리기": {"main_category": "physical_activity", "sub_category": "exercise", "mission_location": "indoor"},
    "자유 운동": {"main_category": "physical_activity", "sub_category": "exercise", "mission_location": "anywhere"},
    "스트레칭": {"main_category": "physical_activity", "sub_category": "stretching", "mission_location": "indoor"},
    "활동 놀이": {"main_category": "physical_activity", "sub_category": "active_play", "mission_location": "anywhere"},
    "야외 놀이": {"main_category": "physical_activity", "sub_category": "active_play", "mission_location": "outdoor"},
    "자전거 타기": {"main_category": "physical_activity", "sub_category": "active_play", "mission_location": "outdoor"},
    "물 마시기": {"main_category": "healthy_routine", "sub_category": "water", "mission_location": "anywhere"},
    "아침 식사": {"main_category": "nutrition", "sub_category": "meal", "mission_location": "anywhere"},
    "규칙적 식사": {"main_category": "nutrition", "sub_category": "meal", "mission_location": "anywhere"},
    "균형 식단": {"main_category": "nutrition", "sub_category": "meal", "mission_location": "anywhere"},
    "천천히 먹기": {"main_category": "nutrition", "sub_category": "meal", "mission_location": "anywhere"},
    "과식 방지": {"main_category": "nutrition", "sub_category": "meal", "mission_location": "anywhere"},
    "야식 금지": {"main_category": "nutrition", "sub_category": "meal", "mission_location": "indoor"},
    "식사 집중": {"main_category": "nutrition", "sub_category": "meal", "mission_location": "anywhere"},
    "식사 위생": {"main_category": "healthy_routine", "sub_category": "hygiene", "mission_location": "anywhere"},
    "간식 줄이기": {"main_category": "nutrition", "sub_category": "snack", "mission_location": "anywhere"},
    "건강 간식 선택": {"main_category": "nutrition", "sub_category": "snack", "mission_location": "anywhere"},
    "과일 먹기": {"main_category": "nutrition", "sub_category": "healthy_food", "mission_location": "anywhere"},
    "채소 먹기": {"main_category": "nutrition", "sub_category": "healthy_food", "mission_location": "anywhere"},
    "우유 마시기": {"main_category": "nutrition", "sub_category": "healthy_food", "mission_location": "anywhere"},
    "가공식품 줄이기": {"main_category": "nutrition", "sub_category": "healthy_food", "mission_location": "anywhere"},
    "건강 음료 선택": {"main_category": "nutrition", "sub_category": "healthy_food", "mission_location": "anywhere"},
    "취침 시간 지키기": {"main_category": "healthy_routine", "sub_category": "sleep", "mission_location": "indoor"},
    "취침 전 루틴": {"main_category": "healthy_routine", "sub_category": "sleep", "mission_location": "indoor"},
    "기상 시간 지키기": {"main_category": "healthy_routine", "sub_category": "morning", "mission_location": "indoor"},
    "기상 후 루틴": {"main_category": "healthy_routine", "sub_category": "morning", "mission_location": "indoor"},
    "손 씻기": {"main_category": "healthy_routine", "sub_category": "hygiene", "mission_location": "anywhere"},
    "양치하기": {"main_category": "healthy_routine", "sub_category": "hygiene", "mission_location": "indoor"},
    "위생 관리": {"main_category": "healthy_routine", "sub_category": "hygiene", "mission_location": "anywhere"},
    "독서": {"main_category": "healthy_routine", "sub_category": "daily_habit", "mission_location": "indoor"},
    "공부 집중": {"main_category": "healthy_routine", "sub_category": "daily_habit", "mission_location": "indoor"},
    "계획 세우기": {"main_category": "healthy_routine", "sub_category": "daily_habit", "mission_location": "anywhere"},
    "정리 정돈": {"main_category": "healthy_routine", "sub_category": "daily_habit", "mission_location": "indoor"},
    "게임 시간 줄이기": {"main_category": "digital_detox", "sub_category": "game", "mission_location": "anywhere"},
    "영상 시청 줄이기": {"main_category": "digital_detox", "sub_category": "video", "mission_location": "anywhere"},
    "숏폼 줄이기": {"main_category": "digital_detox", "sub_category": "video", "mission_location": "anywhere"},
    "스마트폰 절제": {"main_category": "digital_detox", "sub_category": "screen_time", "mission_location": "anywhere"},
    "화면 없는 시간": {"main_category": "digital_detox", "sub_category": "screen_free_time", "mission_location": "anywhere"},
}


ACTIVITY_GENERATION_GUIDES: dict[str, str] = {
    "걷기": "걷는 활동이 핵심이다. 5~20분 또는 500~3000걸음처럼 가벼운 기준을 쓰고, 위험한 도로나 밤늦은 야외활동은 피한다.",
    "걸음수 채우기": "걸음 수를 채우는 활동이 핵심이다. 500~3000걸음 정도의 가벼운 기준을 쓰고, 무리한 걸음 수를 요구하지 않는다.",
    "계단 이용하기": "엘리베이터 대신 계단을 안전하게 이용하는 활동이다. 1~3층, 1~3번처럼 짧은 기준을 쓰고 뛰어오르기는 시키지 않는다.",
    "줄넘기": "줄넘기 동작 자체가 핵심이다. 20~80회 또는 3~5분 정도로 쓰고, 넘어지지 않게 안전한 장소를 포함한다.",
    "스쿼트": "스쿼트 동작 자체가 핵심이다. 5~20회 정도로 쓰고, 자세와 무릎 통증 주의 문구를 포함한다.",
    "버피테스트": "강도가 높은 운동이다. 어린이에게는 3~8회 정도로 아주 가볍게 쓰고, 무리하거나 숨이 차면 쉬어도 된다고 쓴다.",
    "팔굽혀펴기": "팔굽혀펴기 동작 자체가 핵심이다. 3~10회 정도로 쓰고, 무릎을 대는 쉬운 방식도 허용한다.",
    "팔벌려뛰기": "팔벌려뛰기 동작 자체가 핵심이다. 10~30회 정도로 쓰고, 주변 공간을 확보하게 한다.",
    "플랭크": "버티는 시간이 핵심이다. 10~30초 정도로 쓰고, 허리 통증을 참지 않도록 한다.",
    "벽 밀기": "벽을 안전하게 밀며 힘을 주는 활동이다. 10~30초 또는 3~5번 정도로 쓰고, 미끄럽지 않은 곳을 고른다.",
    "제자리 달리기": "제자리에서 움직이는 활동이다. 1~5분 정도로 쓰고, 층간소음이나 미끄러움을 주의한다.",
    "자유 운동": "몸을 움직이는 활동이면 된다. 5~15분 정도로 쓰고, 아이가 고를 수 있는 안전한 실내/실외 활동으로 표현한다.",
    "스트레칭": "몸을 부드럽게 늘리는 활동이다. 3~7분 정도로 쓰고, 반동을 주거나 아픈 자세를 참게 하지 않는다.",
    "활동 놀이": "몸을 실제로 움직이는 놀이가 핵심이다. 5~15분 정도로 쓰고, 앉아서 하는 게임/영상 시청과 섞지 않는다.",
    "야외 놀이": "밖에서 안전하게 움직이는 놀이가 핵심이다. 5~15분 정도로 쓰고, 날씨와 장소 안전을 고려한다.",
    "자전거 타기": "자전거를 안전하게 타는 활동이다. 5~15분 정도로 쓰고, 보호장비와 안전한 장소를 포함한다.",
    "물 마시기": "맹물 기준으로 쓴다. 1~4잔 또는 하루 2~3번 나눠 마시기 정도로 쓰고, 1L/1.5L/2L/1000ml/2000ml처럼 큰 양은 쓰지 않는다.",
    "아침 식사": "아침을 거르지 않는 것이 핵심이다. 한 끼를 먹는 기준으로 쓰고, 과자나 단 음료로 대신하게 하지 않는다.",
    "규칙적 식사": "정해진 끼니를 챙기는 것이 핵심이다. 오늘 한 끼 또는 세 끼 중 특정 시점을 정해 짧게 수행하게 한다.",
    "균형 식단": "여러 음식군을 골고루 먹는 것이 핵심이다. 밥/반찬/채소/단백질처럼 쉬운 표현을 쓰고 과한 식단 관리를 시키지 않는다.",
    "천천히 먹기": "먹는 속도 조절이 핵심이다. 한 끼 동안 10~20번 씹기, 10분 이상 천천히 먹기처럼 식사 중 기준을 쓴다.",
    "과식 방지": "배부름을 느끼며 멈추는 것이 핵심이다. 한 끼에서 천천히 먹기, 배부르면 멈추기처럼 가볍게 쓴다.",
    "야식 금지": "늦은 시간 음식 섭취를 피하는 것이 핵심이다. 잠들기 전 1~2시간 간식 피하기처럼 짧은 1일 기준을 쓴다.",
    "식사 집중": "식사 중 화면/딴짓을 줄이는 것이 핵심이다. 한 끼 동안 화면 보지 않기처럼 상황 기준을 쓴다.",
    "식사 위생": "먹기 전 위생 행동이 핵심이다. 식사 전 손 씻기, 식탁 정리처럼 한 가지 행동으로 구체화한다.",
    "간식 줄이기": "간식 횟수나 양을 줄이는 것이 핵심이다. 오늘 단 간식 1번 줄이기처럼 가볍게 쓰고 굶기처럼 쓰지 않는다.",
    "건강 간식 선택": "간식을 먹는다면 건강한 선택을 하는 것이 핵심이다. 과일/무가당 요거트/견과류처럼 쉬운 선택으로 쓰되 특정 음식 강요는 피한다.",
    "과일 먹기": "생과일을 먹는 것이 핵심이다. 1~2가지 또는 작은 접시 1번 정도로 쓰고, 주스나 가공식품으로 대체하지 않는다.",
    "채소 먹기": "채소를 먹는 것이 핵심이다. 1~2가지 또는 반찬 1~2번 정도로 쓰고, 튀김이나 가공식품과 섞지 않는다.",
    "우유 마시기": "흰 우유 기준으로 쓴다. 1잔 정도로 가볍게 쓰고, 알레르기나 싫어함이 있으면 무리하게 강요하지 않는다.",
    "가공식품 줄이기": "인스턴트/가공식품을 줄이는 것이 핵심이다. 오늘 한 번 덜 먹기처럼 쓰고, 굶기나 벌칙처럼 표현하지 않는다.",
    "건강 음료 선택": "단 음료 대신 물/흰 우유/무가당 차를 고르는 것이 핵심이다. 음료 1번 바꾸기처럼 가볍게 쓴다.",
    "취침 시간 지키기": "정해진 시간에 잠자리에 드는 것이 핵심이다. 너무 늦은 시간은 피하고, 잠들기 전 준비 행동을 포함해도 된다.",
    "취침 전 루틴": "잠들기 전 준비 행동이 핵심이다. 양치, 화면 치우기, 방 정리처럼 1~2가지 행동으로 쓴다.",
    "기상 시간 지키기": "정해진 시간에 일어나는 것이 핵심이다. 오늘 아침 또는 내일 아침처럼 시점을 분명히 하고, 무리한 기상 시간을 요구하지 않는다.",
    "기상 후 루틴": "일어난 뒤 바로 하는 짧은 행동이 핵심이다. 물 한 잔, 이불 정리, 세수처럼 한 가지 행동으로 쓴다.",
    "손 씻기": "비누와 흐르는 물로 씻는 것이 핵심이다. 식사 전/외출 후/화장실 후/30초처럼 상황이나 기준을 mission_name에 포함한다.",
    "양치하기": "실제 양치가 핵심이다. 아침/저녁/식사 후처럼 시점을 넣고, 물로 입 헹구기만으로 대체하지 않는다.",
    "위생 관리": "하나의 구체적인 위생 행동을 수행하는 것이 핵심이다. 손 씻기, 양치, 세수, 컵 씻기처럼 행동을 명확히 쓴다.",
    "독서": "책 읽는 행동이 핵심이다. 5~15분 또는 3~10쪽 정도로 쓰고, 화면 영상 시청과 섞지 않는다.",
    "공부 집중": "정해진 시간 동안 공부에 집중하는 것이 핵심이다. 10~30분 정도로 쓰고, 휴대폰을 멀리 두기 같은 조건을 붙일 수 있다.",
    "계획 세우기": "오늘 할 일을 정리하는 것이 핵심이다. 할 일 2~3개 쓰기처럼 짧은 기준을 쓴다.",
    "정리 정돈": "특정 공간을 정리하는 것이 핵심이다. 책상/가방/침대 주변 1곳처럼 범위를 좁혀 쓴다.",
    "게임 시간 줄이기": "게임 시간을 줄이는 것이 핵심이다. 오늘 10~30분 줄이기 또는 게임 전 할 일 1개 끝내기처럼 쓴다.",
    "영상 시청 줄이기": "영상 시청 시간을 줄이는 것이 핵심이다. 유튜브/쇼츠/TV를 10~30분 줄이기처럼 쓰고 다른 화면 활동으로 대체하지 않는다.",
    "숏폼 줄이기": "쇼츠/릴스/틱톡 같은 짧은 영상을 줄이는 것이 핵심이다. 자기 전 15분 안 보기 또는 오늘 10분 줄이기처럼 쓴다.",
    "스마트폰 절제": "휴대폰 사용 습관 조절이 핵심이다. 식사 중 안 보기, 공부할 때 멀리 두기처럼 상황 기준을 쓴다.",
    "화면 없는 시간": "정해진 시간 동안 모든 화면 기기를 보지 않는 것이 핵심이다. 10~30분 정도로 쓰고 휴대폰만 피하고 TV를 보는 식은 허용하지 않는다.",
}


FORMAL_STYLE_RE = re.compile(r"(하세요|해주세요|합니다|해야 합니다|섭취|목표로 합니다|기르세요)")
WATER_TOO_MUCH_RE = re.compile(
    r"(1\s*리터|1\.5\s*리터|2\s*리터|1\s*L|1\.5\s*L|2\s*L|1000\s*ml|1500\s*ml|2000\s*ml)",
    re.IGNORECASE,
)


def _coerce_activity_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """LLM이 activity_key는 맞췄지만 카테고리 enum을 헷갈린 경우 안전한 기본값으로 보정한다."""
    data = dict(raw)
    key = normalize_activity_key(data.get("activity_key"))
    defaults = ACTIVITY_DEFAULT_META.get(key or "")
    if defaults:
        data.update(defaults)
    return data


def _generation_guides_for_keys(activity_keys: list[str]) -> dict[str, dict[str, Any]]:
    guides: dict[str, dict[str, Any]] = {}
    for key in activity_keys:
        normalized = normalize_activity_key(key)
        if not normalized:
            continue
        guide: dict[str, Any] = {}
        meta = ACTIVITY_DEFAULT_META.get(normalized)
        if meta:
            guide["default_meta"] = meta
        rule = ACTIVITY_GENERATION_GUIDES.get(normalized)
        if rule:
            guide["generation_guide"] = rule
        if guide:
            guides[normalized] = guide
    return guides


def _has_formal_style(*values: str | None) -> bool:
    text = " ".join(value or "" for value in values)
    return bool(FORMAL_STYLE_RE.search(text))


def _has_too_much_water(activity_key: str, *values: str | None) -> bool:
    if normalize_activity_key(activity_key) != "물 마시기":
        return False
    text = " ".join(value or "" for value in values)
    return bool(WATER_TOO_MUCH_RE.search(text))


ACTIVITY_CONTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "가공식품 줄이기": ("가공식품", "인스턴트", "라면", "햄", "소시지"),
    "간식 줄이기": ("간식", "과자", "군것질"),
    "건강 간식 선택": ("건강간식", "견과", "과일", "요거트"),
    "건강 음료 선택": ("건강음료", "음료", "물", "우유"),
    "걷기": ("걷", "걸음", "산책"),
    "걸음수 채우기": ("걸음", "걷", "산책"),
    "게임 시간 줄이기": ("게임",),
    "계단 이용하기": ("계단",),
    "계획 세우기": ("계획", "목표", "할일"),
    "공부 집중": ("공부", "집중", "숙제"),
    "과식 방지": ("과식", "천천히", "배부르"),
    "과일 먹기": ("과일", "사과", "바나나", "귤", "딸기", "포도"),
    "규칙적 식사": ("규칙", "식사", "끼니"),
    "균형 식단": ("균형", "식단", "골고루"),
    "기상 시간 지키기": ("기상", "일어나", "아침"),
    "기상 후 루틴": ("기상", "일어난", "아침루틴"),
    "독서": ("독서", "책", "읽"),
    "물 마시기": ("물", "마시"),
    "버피테스트": ("버피",),
    "벽 밀기": ("벽밀", "벽을밀", "벽 밀"),
    "손 씻기": ("손씻", "손을씻", "손 씻"),
    "숏폼 줄이기": ("숏폼", "릴스", "쇼츠"),
    "스마트폰 절제": ("스마트폰", "휴대폰", "폰", "화면"),
    "스쿼트": ("스쿼트",),
    "스트레칭": ("스트레칭", "늘리", "몸풀", "이완"),
    "식사 위생": ("식사위생", "손씻", "식탁", "위생"),
    "식사 집중": ("식사", "밥", "집중"),
    "아침 식사": ("아침식사", "아침밥", "아침"),
    "야식 금지": ("야식", "밤에먹", "늦게먹"),
    "야외 놀이": ("야외", "밖", "놀이터", "놀이"),
    "양치하기": ("양치", "이를닦", "치약"),
    "영상 시청 줄이기": ("영상", "유튜브", "시청"),
    "우유 마시기": ("우유",),
    "위생 관리": ("위생", "깨끗", "씻"),
    "자유 운동": ("운동", "움직", "활동"),
    "자전거 타기": ("자전거",),
    "정리 정돈": ("정리", "정돈", "치우"),
    "제자리 달리기": ("제자리달리", "달리"),
    "줄넘기": ("줄넘기",),
    "채소 먹기": ("채소", "야채", "나물", "샐러드", "당근", "오이"),
    "천천히 먹기": ("천천히", "꼭꼭", "씹"),
    "취침 시간 지키기": ("취침", "잠들기", "자기전", "수면"),
    "취침 전 루틴": ("취침", "잠들기", "자기전", "수면"),
    "팔굽혀펴기": ("팔굽혀", "푸시업"),
    "팔벌려뛰기": ("팔벌려뛰",),
    "플랭크": ("플랭크",),
    "화면 없는 시간": ("화면", "스크린", "스마트폰", "휴대폰"),
    "활동 놀이": ("놀이", "활동", "움직"),
}


def _compact_content_text(*values: str | None) -> str:
    return "".join(" ".join(value or "" for value in values).split()).lower()


def _activity_key_matches_content(activity_key: str, mission_name: str, mission_rule: str) -> bool:
    key = normalize_activity_key(activity_key)
    if not key:
        return False

    content = _compact_content_text(mission_name, mission_rule)
    keywords = ACTIVITY_CONTENT_KEYWORDS.get(key)
    if keywords:
        return any(_compact_content_text(keyword) in content for keyword in keywords)

    tokens = [
        token
        for token in re.split(r"[\s/_-]+", key)
        if len(token.strip()) >= 2
    ]
    return any(_compact_content_text(token) in content for token in tokens)


def _conflicts_with_restriction_terms(mission: dict[str, Any], restriction_terms: list[str]) -> bool:
    text = f"{mission.get('mission_name') or ''} {mission.get('mission_rule') or ''}".lower()
    stopwords = {
        "못",
        "안",
        "먹어",
        "먹기",
        "마셔",
        "오늘",
        "어려움",
        "어려워",
        "알레르기",
        "제한",
        "금지",
        "못해",
        "못함",
        "피해",
    }
    for term in restriction_terms or []:
        compact = str(term or "").strip().lower()
        if compact and len(compact) >= 2 and compact in text:
            return True
        for token in re.split(r"[\s,./]+", compact):
            token = token.strip()
            if len(token) >= 2 and token not in stopwords and token in text:
                return True
    return False


def _allowed_activity_keys(profile: dict[str, Any]) -> list[str]:
    restricted = set(_valid_unique(profile.get("restricted_activity_keys", [])))
    avoid = set(_valid_unique(profile.get("avoid_activity_keys", [])))
    allowed_keys = [
        key
        for key in _valid_unique(profile.get("candidate_activity_keys", []))
        if key in VALID_ACTIVITY_KEYS and key not in restricted and key not in avoid
    ]
    if allowed_keys:
        return allowed_keys
    return [
        key
        for key in sorted(VALID_ACTIVITY_KEYS)
        if key not in restricted and key not in avoid
    ]


def validate_generated_mission_with_reason(
    raw: dict[str, Any],
    profile: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate a real-time LLM mission and return actionable retry reasons."""
    reasons: list[str] = []
    if not isinstance(raw, dict):
        return None, ["출력이 JSON 객체가 아님"]

    try:
        raw = _coerce_activity_metadata(raw)
        mission = GeneratedMissionModel.model_validate(raw).model_dump()
    except ValidationError as exc:
        reasons.append(f"필드 검증 실패: {exc.errors()[:2]}")
        return None, reasons

    activity_key = mission["activity_key"]
    restricted = set(_valid_unique(profile.get("restricted_activity_keys", [])))
    avoid = set(_valid_unique(profile.get("avoid_activity_keys", [])))
    if activity_key in restricted:
        reasons.append(f"restricted_activity_keys에 포함된 activity_key 사용: {activity_key}")
    if activity_key in avoid:
        reasons.append(f"avoid_activity_keys에 포함된 activity_key 사용: {activity_key}")

    allowed = set(_allowed_activity_keys(profile))
    if allowed and activity_key not in allowed:
        reasons.append(f"valid_activity_keys 밖의 activity_key 사용: {activity_key}")

    if not _activity_key_matches_content(activity_key, mission["mission_name"], mission["mission_rule"]):
        reasons.append("activity_key와 mission_name/mission_rule의 실제 활동 내용이 일치하지 않음")
    if _conflicts_with_restriction_terms(mission, profile.get("restriction_terms", [])):
        reasons.append("restriction_terms와 충돌하는 내용 포함")
    if not _is_safe_text(mission["mission_name"], mission["mission_rule"]):
        reasons.append("안전하지 않은 표현 또는 금지 표현 포함")
    if not _has_specific_success_criteria(mission["mission_name"], mission["mission_rule"]):
        reasons.append("성공 기준이 구체적이지 않음. 횟수, 시간, 양, 상황 중 하나가 필요함")
    if _has_quantity_conflict(mission["mission_name"], mission["mission_rule"]):
        reasons.append("mission_name과 mission_rule 안에서 같은 단위의 수량 기준이 서로 다름")
    if _has_too_much_water(activity_key, mission["mission_name"], mission["mission_rule"]):
        reasons.append("물 마시기 미션의 양이 너무 많음. 1~4잔처럼 어린이에게 부담 없는 양이 필요함")
    if _has_formal_style(mission["mission_name"], mission["mission_rule"]):
        print("[MissionGenerator] formal style warning")

    if reasons:
        print(f"[MissionGenerator] validation rejected reasons={reasons}")
        if "activity_key와 mission_name/mission_rule의 실제 활동 내용이 일치하지 않음" in reasons:
            print(f"[MissionGenerator] activity/content mismatch activity_key={activity_key}")
        if any(reason.startswith("valid_activity_keys 밖의 activity_key 사용") for reason in reasons):
            print(f"[MissionGenerator] activity_key not allowed by profile activity_key={activity_key}")
        return None, reasons

    return mission, []


def validate_generated_mission(raw: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
    """Validate a real-time LLM mission before it can be inserted into missions."""
    mission, _ = validate_generated_mission_with_reason(raw, profile)
    return mission


def _prompt_payload(profile: dict[str, Any], previous_errors: list[str] | None = None) -> str:
    allowed_keys = _allowed_activity_keys(profile)
    payload = {
        "student_id": profile.get("student_id"),
        "valid_activity_keys": allowed_keys,
        "all_valid_activity_keys": sorted(VALID_ACTIVITY_KEYS),
        "candidate_activity_keys": profile.get("candidate_activity_keys", []),
        "avoid_activity_keys": profile.get("avoid_activity_keys", []),
        "restricted_activity_keys": profile.get("restricted_activity_keys", []),
        "restriction_terms": profile.get("restriction_terms", []),
        "difficulty_hint": _normalize_difficulty(profile.get("difficulty_hint")),
        "activity_generation_guides": _generation_guides_for_keys(allowed_keys),
        "allowed_enums": {
            "main_category": sorted(VALID_MAIN_CATEGORIES),
            "sub_category": sorted(VALID_SUB_CATEGORIES),
            "mission_location": sorted(VALID_LOCATIONS),
            "difficulty": sorted(VALID_DIFFICULTIES),
        },
    }
    if previous_errors:
        payload["previous_generation_errors"] = previous_errors
        payload["retry_instruction"] = (
            "이전 생성은 위 사유로 실패했다. 같은 실수를 반복하지 말고, "
            "실패 사유를 모두 고쳐서 새 JSON을 생성해."
        )
    return json.dumps(payload, ensure_ascii=False)


def _extract_json_object_text(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and start < end:
        return text[start : end + 1]
    return text


def _loads_json_object(raw_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        parsed = json.loads(_extract_json_object_text(raw_text))
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("expected JSON object", str(parsed), 0)
    return parsed


async def generate_realtime_personalized_mission(
    profile: dict[str, Any],
    *,
    max_attempts: int = 2,
    timeout: float = 80.0,
) -> dict[str, Any] | None:
    """Ask Gemma4 for one assignable mission. Returns None so callers can use DB recommendation fallback."""
    previous_errors: list[str] = []

    for attempt in range(max(1, min(max_attempts, 3))):
        try:
            raw_text = await generate_json_message(
                GENERATION_SYSTEM_PROMPT,
                _prompt_payload(profile, previous_errors),
                timeout=timeout,
            )
            print("[MissionGenerator] raw_text:", raw_text[:1000])
            try:
                parsed = _loads_json_object(raw_text)
            except json.JSONDecodeError as exc:
                previous_errors = [f"JSON 파싱 실패: {exc}"]
                print(f"[MissionGenerator] JSON decode failed: {exc}")
                print("[MissionGenerator] raw_text_on_error:", raw_text[:1000])
                continue
            validated, reasons = validate_generated_mission_with_reason(parsed, profile)
            if validated:
                return validated
            previous_errors = reasons or ["검증 실패"]
            print(
                f"[MissionGenerator] generated mission rejected "
                f"attempt={attempt + 1} reasons={previous_errors}"
            )
        except Exception as exc:
            previous_errors = [f"생성 중 예외 발생: {type(exc).__name__}: {exc}"]
            print(f"[MissionGenerator] realtime generation failed attempt={attempt + 1}: {type(exc).__name__}: {exc}")
    return None


def validate_generated_mission_draft(raw: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
    """Compatibility validator for background draft generation."""
    if not isinstance(raw, dict):
        return None

    if raw.get("mission_name"):
        realtime = validate_generated_mission(raw, profile)
        if realtime:
            return {
                "mission_title": realtime["mission_name"],
                "mission_description": realtime["mission_rule"],
                "activity_keys": [realtime["activity_key"]],
                "difficulty": realtime["difficulty"],
                "generation_reason": "실시간 생성 포맷을 draft 포맷으로 변환",
            }

    title = _clean_title(raw.get("mission_title"))
    description = " ".join(str(raw.get("mission_description") or "").split())
    reason = " ".join(str(raw.get("generation_reason") or "").split())
    fallback_difficulty = _normalize_difficulty(profile.get("difficulty_hint"))
    difficulty = _normalize_difficulty(raw.get("difficulty"), fallback_difficulty)

    activity_keys = _valid_unique(raw.get("activity_keys") if isinstance(raw.get("activity_keys"), list) else [])
    restricted = set(_valid_unique(profile.get("restricted_activity_keys", [])))
    avoid = set(_valid_unique(profile.get("avoid_activity_keys", [])))

    if not title or not activity_keys:
        return None
    if restricted.intersection(activity_keys):
        return None
    if avoid.intersection(activity_keys):
        return None
    if not _is_safe_text(title, description):
        return None

    return {
        "mission_title": title,
        "mission_description": description or f"{activity_keys[0]} 활동을 오늘 가볍게 실천해 보기",
        "activity_keys": activity_keys,
        "difficulty": difficulty,
        "generation_reason": reason or "개인화 후보 활동을 바탕으로 만든 draft 미션",
    }


def generate_fallback_mission(profile: dict[str, Any], variant: int = 0) -> dict[str, Any]:
    restricted = set(_valid_unique(profile.get("restricted_activity_keys", [])))
    avoid = set(_valid_unique(profile.get("avoid_activity_keys", [])))
    candidates = [
        key
        for key in _valid_unique(profile.get("candidate_activity_keys", []))
        if key not in restricted and key not in avoid
    ]
    if not candidates:
        candidates = [
            key
            for key in _valid_unique(profile.get("preferred_activity_keys", []))
            if key not in restricted and key not in avoid
        ]
    if not candidates:
        raise ValueError("no safe activity_key candidates")

    activity_key = candidates[variant % len(candidates)]
    difficulty = _normalize_difficulty(profile.get("difficulty_hint"))
    if difficulty == "hard":
        title = f"{activity_key} 조금 더 도전해서 해보기"
        description = f"오늘은 {activity_key} 활동을 평소보다 조금 더 집중해서 실천해 보는 미션"
    elif difficulty == "easy":
        title = f"{activity_key} 아주 가볍게 해보기"
        description = f"부담 없이 {activity_key} 활동을 짧게 실천해 보는 미션"
    else:
        title = f"{activity_key} 오늘 한 번 실천하기"
        description = f"오늘 생활 속에서 {activity_key} 활동을 한 번 실천해 보는 미션"

    return {
        "mission_title": _clean_title(title),
        "mission_description": description,
        "activity_keys": [activity_key],
        "difficulty": difficulty,
        "generation_reason": "LLM 결과를 쓰지 않고 안전한 rule-based fallback으로 생성",
    }


async def generate_personalized_mission_draft(
    profile: dict[str, Any],
    *,
    use_llm: bool = True,
    variant: int = 0,
    timeout: float = 80.0,
) -> dict[str, Any]:
    if use_llm:
        try:
            raw_text = await generate_json_message(
                GENERATION_SYSTEM_PROMPT,
                _prompt_payload(profile),
                timeout=timeout,
            )
            print("[MissionGenerator] raw_text:", raw_text[:1000])
            parsed = json.loads(raw_text)
            validated = validate_generated_mission_draft(parsed, profile)
            if validated:
                return validated
        except Exception as exc:
            print(f"[MissionGenerator] LLM draft failed: {type(exc).__name__}: {exc}")

    return generate_fallback_mission(profile, variant=variant)


def generate_personalized_mission_draft_sync(
    profile: dict[str, Any],
    *,
    use_llm: bool = True,
    variant: int = 0,
    timeout: float = 80.0,
) -> dict[str, Any]:
    return asyncio.run(
        generate_personalized_mission_draft(profile, use_llm=use_llm, variant=variant, timeout=timeout)
    )
