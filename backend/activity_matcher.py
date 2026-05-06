from __future__ import annotations

import json
import re
from collections.abc import Callable

from activity_keys import ACTIVITY_KEY_ALIASES, VALID_ACTIVITY_KEYS, normalize_activity_key


def _compact(value: str | None) -> str:
    return "".join((value or "").split()).lower()


def _unique_valid(keys: list[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for key in keys:
        normalized = normalize_activity_key(key)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


ACTIVITY_KEY_GROUPS: dict[str, list[str]] = {
    "indoor": [
        "물 마시기",
        "채소 먹기",
        "과일 먹기",
        "우유 마시기",
        "건강 간식 선택",
        "건강 음료 선택",
        "간식 줄이기",
        "가공식품 줄이기",
        "과식 방지",
        "규칙적 식사",
        "균형 식단",
        "천천히 먹기",
        "아침 식사",
        "야식 금지",
        "손 씻기",
        "양치하기",
        "위생 관리",
        "식사 위생",
        "식사 집중",
        "독서",
        "공부 집중",
        "계획 세우기",
        "정리 정돈",
        "기상 시간 지키기",
        "기상 후 루틴",
        "취침 시간 지키기",
        "취침 전 루틴",
        "스마트폰 절제",
        "영상 시청 줄이기",
        "숏폼 줄이기",
        "게임 시간 줄이기",
        "화면 없는 시간",
        "벽 밀기",
        "스쿼트",
        "스트레칭",
        "제자리 달리기",
        "버피테스트",
        "팔굽혀펴기",
        "팔벌려뛰기",
        "플랭크",
    ],
    "exercise": [
        "걷기",
        "걸음수 채우기",
        "계단 이용하기",
        "버피테스트",
        "벽 밀기",
        "스쿼트",
        "스트레칭",
        "야외 놀이",
        "자유 운동",
        "자전거 타기",
        "제자리 달리기",
        "줄넘기",
        "팔굽혀펴기",
        "팔벌려뛰기",
        "플랭크",
        "활동 놀이",
    ],
    "outdoor": [
        "걷기",
        "걸음수 채우기",
        "야외 놀이",
        "자유 운동",
        "자전거 타기",
        "줄넘기",
        "활동 놀이",
    ],
}


GROUP_ALIASES: list[tuple[tuple[str, ...], str]] = [
    (("실내", "집에서", "방에서", "안에서"), "indoor"),
    (("운동", "몸움직", "몸 움직", "체력"), "exercise"),
    (("야외", "밖에서", "밖에", "바깥", "산책"), "outdoor"),
]


NEGATED_OUTDOOR_RE = re.compile(
    r"(밖|야외|바깥|산책)[\s\S]{0,8}(못|안\s*돼|안돼|어려|힘들|싫|불가|안\s*할|안할)"
    r"|"
    r"(못|안\s*돼|안돼|어려|힘들|싫|불가)[\s\S]{0,8}(밖|야외|바깥|산책)"
)


def parse_llm_activity_keys(raw_response: str | dict | None) -> list[str]:
    """Validate LLM fallback output and discard hallucinated keys."""
    if raw_response is None:
        return []
    try:
        payload = raw_response if isinstance(raw_response, dict) else json.loads(str(raw_response))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    values = payload.get("activity_keys") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return []
    return _unique_valid([value if isinstance(value, str) else None for value in values])


def _rule_based_activity_keys(text: str) -> list[str]:
    compact_text = _compact(text)
    if not compact_text:
        return []

    matches: list[tuple[int, int, str]] = []
    negated_outdoor = bool(NEGATED_OUTDOOR_RE.search(text or ""))
    if negated_outdoor:
        matches.extend((0, idx, key) for idx, key in enumerate(ACTIVITY_KEY_GROUPS["indoor"]))

    for key in sorted(VALID_ACTIVITY_KEYS, key=len, reverse=True):
        compact_key = _compact(key)
        idx = compact_text.find(compact_key)
        if compact_key and idx >= 0:
            matches.append((idx, 0, key))

    for order, (alias, key) in enumerate(ACTIVITY_KEY_ALIASES.items(), start=1):
        if negated_outdoor and alias in {"밖", "야외", "산책"}:
            continue
        compact_alias = _compact(alias)
        idx = compact_text.find(compact_alias)
        if compact_alias and idx >= 0:
            matches.append((idx, order, key))

    for aliases, group_name in GROUP_ALIASES:
        if negated_outdoor and group_name == "outdoor":
            continue
        for alias in aliases:
            idx = compact_text.find(_compact(alias))
            if idx >= 0:
                matches.extend((idx, order, key) for order, key in enumerate(ACTIVITY_KEY_GROUPS[group_name], start=1))
                break

    matches.sort(key=lambda item: (item[0], item[1]))
    return _unique_valid([key for _, _, key in matches])


def match_activity_keys(
    text: str,
    llm_fallback: Callable[[str, list[str]], str | dict | None] | None = None,
) -> list[str]:
    """Match user text to allowed activity_keys. Rule-based matching always runs first."""
    rule_based = _rule_based_activity_keys(text)
    if rule_based:
        return rule_based

    if not llm_fallback:
        return []

    try:
        return parse_llm_activity_keys(llm_fallback(text, sorted(VALID_ACTIVITY_KEYS)))
    except Exception as e:
        print(f"[ActivityMatcher] llm fallback failed: {type(e).__name__}: {e}")
        return []


def normalize_activity_request(text: str) -> list[str]:
    return match_activity_keys(text)


DIRECT_CHANGE_RE = re.compile(r"미션|바꿔|바꾸|변경|다른|걸로|거로")


def is_direct_condition_change_request(text: str) -> bool:
    if not text or not DIRECT_CHANGE_RE.search(text):
        return False
    return bool(match_activity_keys(text))


def select_replacement_mission(
    student_id: int,
    current_mission_id: int,
    activity_keys: list[str],
) -> dict | None:
    keys = _unique_valid(activity_keys)
    if not student_id or not current_mission_id or not keys:
        return None

    try:
        from database import get_conn, get_relevant_user_memories

        memories = get_relevant_user_memories(student_id)
        restricted_keys = {
            normalized
            for memory in memories
            if memory.get("type") == "restriction"
            for normalized in [normalize_activity_key(memory.get("subject"))]
            if normalized
        }
        preferred_keys = [key for key in keys if key not in restricted_keys]

        selected = _select_replacement_mission_from_db(get_conn, current_mission_id, preferred_keys)
        if selected:
            return selected
        if preferred_keys != keys:
            return _select_replacement_mission_from_db(get_conn, current_mission_id, keys)
    except Exception as e:
        print(f"[ActivityMatcher] replacement select failed: {type(e).__name__}: {e}")
    return None


def _select_replacement_mission_from_db(
    get_conn: Callable,
    current_mission_id: int,
    activity_keys: list[str],
) -> dict | None:
    if not activity_keys:
        return None

    order_case = "CASE " + " ".join(
        f"WHEN activity_key = %s THEN {idx}"
        for idx, _ in enumerate(activity_keys)
    ) + " ELSE 999 END"
    params = [current_mission_id, activity_keys, *activity_keys]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT mission_id, mission_name, mission_rule, activity_key,
                       difficulty, main_category, mission_location
                FROM missions
                WHERE is_active = TRUE
                  AND mission_id != %s
                  AND activity_key = ANY(%s)
                ORDER BY {order_case}, RANDOM()
                LIMIT 1
                """,
                params,
            )
            row = cur.fetchone()

    if not row:
        return None
    columns = [
        "mission_id",
        "mission_name",
        "mission_rule",
        "activity_key",
        "difficulty",
        "main_category",
        "mission_location",
    ]
    return dict(zip(columns, row))
