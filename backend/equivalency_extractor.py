"""
사용자 발화에서 명시된 장소/시간/수치/시점 정보를 추출해
judge LLM이 빠뜨리지 않도록 명시적 컨텍스트로 제공한다.

판단 흐름:
1. 사용자 발화 → extract_user_facts → {location, duration, quantity, timing}
2. format_user_facts_hint → "[사용자 발화 분석 결과]" 텍스트 블록
3. build_equivalency_judge_prompt가 이 블록을 judge 시스템 프롬프트에 주입
4. judge가 "이미 답한 정보"를 clarify로 다시 묻지 않게 됨
"""
from __future__ import annotations

import re

# "미션인데 학교에서" → "학교"만 추출되게 한다.
_LOCATION_RE = re.compile(r"([가-힣A-Za-z]{2,})\s*(?:에서|에)\b")
# 지속 시간 (시간/분/초)
_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(시간|분|초)")
# 수량/볼륨
_QUANTITY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(회|번|개|층|잔|컵|L|l|리터|ml|mL|kg|g)")

_TIMING_KEYWORDS = (
    "아침", "점심", "저녁",
    "기상 후", "기상하자마자", "기상 직후",
    "잠들기 전", "잠들기 직전", "자기 전",
    "식사 전", "식사 후", "식사 직전", "식사 직후",
    "밥 먹기 전", "밥 먹기 후", "밥 먹은 뒤", "밥 먹고",
    "외출 전", "외출하기 전",
    "낮", "밤", "오전", "오후", "하루 동안", "오늘", "지금",
)

# 장소로 잘못 잡히기 쉬운 일반 명사 제외
_LOCATION_STOPWORDS = {
    "미션", "오늘", "내일", "어제", "어디", "거기", "여기", "저기",
    "사진", "영상", "이거", "저거", "그거", "이번", "다음",
    "처음", "마지막", "조금", "잠시", "잠깐", "한번", "두번",
}


def extract_user_facts(user_message: str) -> dict[str, list[str]]:
    """사용자 발화에서 명시된 정보 추출."""
    facts: dict[str, list[str]] = {}
    text = user_message or ""
    if not text:
        return facts

    durations = _DURATION_RE.findall(text)
    if durations:
        facts["duration"] = [f"{v}{u}" for v, u in durations]

    quantities = _QUANTITY_RE.findall(text)
    if quantities:
        facts["quantity"] = [f"{v}{u}" for v, u in quantities]

    timings = [kw for kw in _TIMING_KEYWORDS if kw in text]
    if timings:
        facts["timing"] = timings

    raw_locations = _LOCATION_RE.findall(text)
    locations: list[str] = []
    seen: set[str] = set()
    for loc in raw_locations:
        cleaned = loc.strip()
        if not cleaned or len(cleaned) < 2:
            continue
        if cleaned in _LOCATION_STOPWORDS:
            continue
        # 시점 키워드("아침에", "잠들기 전에")가 장소로 오인되는 것을 막는다
        if any(cleaned == tk or cleaned.endswith(tk) for tk in _TIMING_KEYWORDS):
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        locations.append(cleaned)
    if locations:
        facts["location"] = locations

    return facts


def format_user_facts_hint(facts: dict[str, list[str]]) -> str:
    """추출한 facts를 judge 프롬프트용 텍스트 블록으로 변환. facts가 비면 빈 문자열."""
    if not facts:
        return ""

    label_map = [
        ("location", "장소"),
        ("duration", "지속 시간"),
        ("quantity", "수량"),
        ("timing", "시점"),
    ]
    lines = ["[사용자 발화 분석 결과]"]
    for key, label in label_map:
        values = facts.get(key)
        if values:
            lines.append(f"- {label}: {', '.join(values)}")

    lines.append(
        "위 정보는 사용자가 발화에서 이미 명시한 것이다. "
        "같은 정보를 clarify_question에서 다시 묻지 마라. "
        "이 정보로 곧장 approved/denied를 판정할 수 있으면 clarify 대신 그것을 사용해라."
    )
    return "\n".join(lines)
