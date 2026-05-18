from __future__ import annotations

import re

KOREAN_NUMBER_WORDS = {
    "영": 0,
    "한": 1,
    "하나": 1,
    "일": 1,
    "두": 2,
    "둘": 2,
    "이": 2,
    "세": 3,
    "셋": 3,
    "삼": 3,
    "네": 4,
    "넷": 4,
    "사": 4,
    "다섯": 5,
    "오": 5,
    "여섯": 6,
    "육": 6,
    "일곱": 7,
    "칠": 7,
    "여덟": 8,
    "팔": 8,
    "아홉": 9,
    "구": 9,
    "열": 10,
    "스무": 20,
    "스물": 20,
    "서른": 30,
    "삼십": 30,
}


def _word_to_number(word: str) -> int | None:
    text = (word or "").replace(" ", "")
    if text in KOREAN_NUMBER_WORDS:
        return KOREAN_NUMBER_WORDS[text]
    for tens in ("스물", "스무", "서른", "삼십"):
        if text.startswith(tens):
            rest = text[len(tens):]
            value = KOREAN_NUMBER_WORDS[tens]
            if not rest:
                return value
            if rest in KOREAN_NUMBER_WORDS:
                return value + KOREAN_NUMBER_WORDS[rest]
    return None


def normalize_equivalency_text(text: str) -> str:
    """Normalize quantity/unit expressions only. This never decides success."""
    normalized = text or ""

    normalized = re.sub(r"500\s*(?:ml|밀리)\s*(?:두|2)\s*병", "1L", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"1000\s*(?:ml|밀리)", "1L", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"(\d+(?:\.\d+)?)\s*ml\b",
        lambda m: f"{float(m.group(1)) / 1000:g}L",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"(\d+(?:\.\d+)?)\s*(?:리터|l)\b", r"\1L", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"종이컵\s*(?:약\s*)?(?:6|여섯)\s*(?:잔|컵)", "약 1L", normalized)
    normalized = re.sub(r"일반\s*컵\s*(?:약\s*)?(?:5|다섯)\s*(?:잔|컵)", "약 1L", normalized)

    for unit in ("분", "회", "번", "잔", "컵", "층"):
        words = "|".join(map(re.escape, sorted(KOREAN_NUMBER_WORDS, key=len, reverse=True)))
        pattern = re.compile(rf"({words})\s*{unit}")
        normalized = pattern.sub(lambda m: f"{_word_to_number(m.group(1)) or m.group(1)}{unit}", normalized)

    normalized = normalized.replace("한 리터", "1L")
    normalized = normalized.replace("한리터", "1L")
    normalized = normalized.replace("일 리터", "1L")
    normalized = normalized.replace("일리터", "1L")
    normalized = normalized.replace("삼십분", "30분")
    normalized = normalized.replace("서른 분", "30분")
    normalized = normalized.replace("서른분", "30분")
    return normalized
