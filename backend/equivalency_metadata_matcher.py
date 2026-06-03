from __future__ import annotations

import re
from enum import Enum
from typing import Any

from equivalency_numeric import compare_numeric_target
from equivalency_normalizer import normalize_equivalency_text


_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")
_SPLIT_RE = re.compile(r"[,，/]|(?:\s+또는\s+)|(?:\s+혹은\s+)")
_STOPWORDS = {
    "하기",
    "해도",
    "인정",
    "가능",
    "대신",
    "이상",
    "이하",
    "미만",
    "동안",
    "정도",
    "사용",
    "이용",
    "중심",
    "직접",
    "실제",
    "오늘",
    "하루",
    "동안",
}
_ALIASES = {
    "산책": "걷기",
    "걷기": "걷기",
    "걸어": "걷기",
    "걸음": "걷기",
    "달려": "달리기",
    "달려도": "달리기",
    "달리기": "달리기",
    "달리면": "달리기",
    "달리고": "달리기",
    "뛰기": "달리기",
    "뛰어": "달리기",
    "뛰어도": "달리기",
    "뛰면": "달리기",
    "릴스": "릴스",
    "쇼츠": "쇼츠",
    "유튜브": "유튜브",
    "유튭": "유튜브",
    "음악": "음악",
    "노래": "음악",
    "팝송": "음악",
    "클래식": "음악",
    "케이팝": "음악",
    "kpop": "음악",
    "아이돌": "음악",
    "아이돌노래": "음악",
    "아이돌음악": "음악",
    "듣기": "듣기",
    "듣": "듣기",
    "듣고": "듣기",
    "들어": "듣기",
    "들었": "듣기",
    "들었어": "듣기",
    "들었어요": "듣기",
    "틀": "듣기",
    "틀어": "듣기",
    "틀고": "듣기",
    "틀었": "듣기",
    "틀었어": "듣기",
    "틀었어요": "듣기",
    "준비": "준비",
    "준비하": "준비",
    "요거트": "요거트",
    "요구르트": "요거트",
    "빵": "빵",
    "과일": "과일",
    "보리차": "보리차",
    "커피": "커피",
    "가글": "가글",
    "물티슈": "물티슈",
    "에스컬레이터": "에스컬레이터",
    "엘리베이터": "엘리베이터",
    "엘베": "엘리베이터",
    "스텝박스": "스텝박스",
}

_NEGATION_OR_CONDITION_RE = re.compile(
    r"(없으면|없어서|없는데|없으니|없을\s*때|"
    r"아니면|아니라|"
    r"하지\s*않|"
    r"안\s*[가-힣]|"
    r"못\s*[가-힣])"
)
_STAIR_RE = re.compile(r"계단")
_ELEVATOR_OR_ESCALATOR_USED_RE = re.compile(
    r"(엘리베이터|엘레베이터|엘베|승강기|에스컬레이터|에스컬).{0,8}"
    r"(탔|탔다|탔어|탐|타버|타고\s*말|타고말|이용|사용|써버)"
)
_ELEVATOR_OR_ESCALATOR_AVOID_RE = re.compile(
    r"(엘리베이터|엘레베이터|엘베|승강기|에스컬레이터|에스컬).{0,8}(안\s*탔|안탔|안\s*타고|안타고|안\s*이용|안이용|대신|말고)"
)
_SCREEN_AVOID_NEGATION_RE = re.compile(
    r"(?:영상|휴대폰\s*영상|화면|TV|티비|유튜브|쇼츠).{0,8}(?:안\s*봤|안봤|안\s*보|안보)"
)
_MUSIC_ONLY_RE = re.compile(r"(?:음악|노래|팝송|클래식|케이팝|kpop|아이돌).{0,12}(?:듣|들었|들으|틀)")

_MUSIC_TOKENS = {"음악", "노래", "팝송", "클래식", "케이팝", "kpop", "아이돌", "아이돌노래", "아이돌음악"}
_LISTEN_PREFIXES = ("듣", "들었", "들어", "틀", "틀어", "틀었")
_PREPARE_PREFIXES = ("준비",)


def _has_negation_or_condition(user_message: str) -> bool:
    return bool(_NEGATION_OR_CONDITION_RE.search(user_message or ""))


# "대신 / 말고 / 대체" 뒤가 사용자가 실제로 묻는 대체 후보다.
# 미션 설명 부분("점심 먹고 10분 걷기")이 매처에 노이즈로 들어가는 걸 막기 위해
# 키워드 뒤 phrase만 추출해 매처에 전달한다.
_REPLACEMENT_SPLIT_RE = re.compile(r"(?:대신에?|말고|대체로?)\s*")
_REPORT_QUESTION_TAIL_RE = re.compile(
    r"(?:미션\s*)?(?:성공|실패|인정|괜찮|돼|되나요|맞아|맞나요|맞나)(?:인가요?|이야|임)?\??$"
)


class TimeWindow(str, Enum):
    BEFORE_EXIT = "before_exit"


TIME_CONDITION_TO_WINDOW: dict[str, TimeWindow] = {
    "외출 전까지": TimeWindow.BEFORE_EXIT,
}

POST_EXIT_CONTEXT_KEYWORDS = (
    "버스",
    "지하철",
    "택시",
    "전철",
    "등교길",
    "학교 가는 길",
    "가는 길",
    "길에서",
    "밖에서",
    "밖에 나와",
    "이미 나와",
    "외출 후",
)


def _extract_replacement_phrase(user_message: str) -> str:
    """사용자가 실제로 대체하려는 행동/음료/장소 부분만 추출.

    '대신/말고/대체' 키워드가 있으면 마지막 키워드 뒤 phrase 반환,
    없으면 원본 그대로 반환.
    """
    if not user_message:
        return ""
    matches = list(_REPLACEMENT_SPLIT_RE.finditer(user_message))
    if not matches:
        return _REPORT_QUESTION_TAIL_RE.sub("", user_message).strip() or user_message
    tail = user_message[matches[-1].end():].strip()
    tail = _REPORT_QUESTION_TAIL_RE.sub("", tail).strip()
    return tail or user_message


def _parse_time_window(mission: dict | None) -> TimeWindow | None:
    if not mission:
        return None
    time_condition = str(mission.get("time_condition") or "").strip()
    for marker, window in TIME_CONDITION_TO_WINDOW.items():
        if marker in time_condition:
            return window
    return None


def _contains_post_exit_context(user_message: str) -> bool:
    compact = normalize_equivalency_text(user_message or "")
    return any(keyword in compact for keyword in POST_EXIT_CONTEXT_KEYWORDS)


def _norm_text(text: str) -> str:
    normalized = normalize_equivalency_text(text or "").lower()
    normalized = re.sub(r"\([^)]*\)", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    for src, dst in _ALIASES.items():
        normalized = normalized.replace(src.lower(), dst.lower())
    return normalized


def _map_token(token: str) -> str:
    token = token.strip().lower()
    if not token:
        return ""
    if token in _MUSIC_TOKENS:
        return "음악"
    if token.startswith(_LISTEN_PREFIXES):
        return "듣기"
    if token.startswith(_PREPARE_PREFIXES):
        return "준비"
    return _ALIASES.get(token, token)


def _tokens(text: str) -> set[str]:
    raw = normalize_equivalency_text(text or "").lower()
    raw = re.sub(r"\([^)]*\)", "", raw)
    tokens = set()
    for token in _TOKEN_RE.findall(raw):
        token = re.sub(
            r"(먹어도|마셔도|들어도|봐도|해도|하고|먹기|마시기|보기|하기|했어요|했어|했니|하면서|하면|하는|으로|이랑|랑|와|과|로|만|를|을|은|는|이|가|도)$",
            "",
            token,
        )
        mapped = _map_token(token)
        if len(mapped) <= 1 or mapped in _STOPWORDS:
            continue
        tokens.add(mapped)
    return tokens


def _items(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in _SPLIT_RE.split(text) if part.strip()]


def _matches_item(
    user_message: str,
    item: str,
    *,
    allow_numeric_fuzzy: bool = False,
    require_all_tokens: bool = False,
) -> bool:
    user_norm = _norm_text(user_message)
    item_norm = _norm_text(item)
    if item_norm and item_norm in user_norm:
        return True
    if re.search(r"\d", item_norm) and not allow_numeric_fuzzy:
        return False

    item_tokens = _tokens(item)
    user_tokens = _tokens(user_message)
    if not item_tokens or not user_tokens:
        return False

    meaningful = item_tokens & user_tokens
    if not meaningful:
        return False
    if require_all_tokens:
        return item_tokens <= user_tokens

    return True


def _find_match(
    user_message: str,
    metadata_text: Any,
    *,
    allow_numeric_fuzzy: bool = False,
    require_all_tokens: bool = False,
) -> str | None:
    for item in _items(metadata_text):
        if _matches_item(
            user_message,
            item,
            allow_numeric_fuzzy=allow_numeric_fuzzy,
            require_all_tokens=require_all_tokens,
        ):
            return item
    return None


def _find_screen_free_audio_allowed_match(user_message: str, metadata_text: Any) -> str | None:
    if not (_SCREEN_AVOID_NEGATION_RE.search(user_message or "") and _MUSIC_ONLY_RE.search(user_message or "")):
        return None
    metadata_raw = normalize_equivalency_text(str(metadata_text or "")).lower()
    if not any(word in metadata_raw for word in ("음악 듣기", "노래 듣기", "팝송 듣기", "케이팝", "클래식 듣기", "아이돌 음악")):
        return None
    for item in _items(metadata_text):
        item_text = normalize_equivalency_text(item or "").lower()
        if any(word in item_text for word in ("음악", "노래", "팝송", "케이팝", "kpop", "클래식", "아이돌")):
            return item
    return None


def _with_override(judgment: dict, decision: str, reason: str, matched: str, source: str) -> dict:
    updated = dict(judgment or {})
    previous = updated.get("decision")
    updated["decision"] = decision
    updated["approved"] = decision == "approved"
    updated["need_clarification"] = decision == "clarify"
    updated["reason"] = reason
    if decision != "clarify":
        updated["clarify_question"] = None
    updated["metadata_override"] = {
        "source": source,
        "matched": matched,
        "previous_decision": previous,
        "decision": decision,
    }
    return updated


def _outside_time_window_override(
    judgment: dict,
    user_message: str,
    mission: dict | None,
) -> dict | None:
    time_window = _parse_time_window(mission)
    if time_window is not TimeWindow.BEFORE_EXIT:
        return None
    if not _contains_post_exit_context(user_message):
        return None
    updated = _with_override(
        judgment,
        "approved",
        "reported behavior happened after the mission time window ended",
        "outside_time_window_after_exit",
        "time_condition",
    )
    updated["reply"] = "이미 외출한 뒤라면, 이번 미션 시간에는 안 들어가 🙂"
    return updated


def apply_metadata_decision_override(
    judgment: dict,
    user_message: str,
    mission: dict | None,
) -> dict:
    if not mission:
        return judgment

    time_override = _outside_time_window_override(judgment, user_message, mission)
    if time_override is not None:
        return time_override

    if str(mission.get("target_metric") or "").strip().lower() == "order":
        return judgment

    effective_message = _extract_replacement_phrase(user_message)

    skip_denied = _has_negation_or_condition(user_message)

    denied_match = (
        None
        if skip_denied
        else _find_match(effective_message, mission.get("denied_substitutes"), require_all_tokens=True)
    )
    if denied_match:
        return _with_override(
            judgment,
            "denied",
            f"DB denied_substitutes match: {denied_match}",
            denied_match,
            "denied_substitutes",
        )

    allowed_match = _find_match(
        effective_message,
        mission.get("allowed_substitutes"),
        allow_numeric_fuzzy=True,
        require_all_tokens=True,
    )
    if not allowed_match and str(mission.get("target_metric") or "").strip().lower() == "avoid":
        allowed_match = _find_screen_free_audio_allowed_match(
            effective_message,
            mission.get("allowed_substitutes"),
        )
    if not allowed_match and str(mission.get("target_metric") or "").strip().lower() == "avoid":
        allowed_match = _find_match(
            effective_message,
            mission.get("allowed_substitutes"),
            allow_numeric_fuzzy=True,
            require_all_tokens=False,
        )
    if not allowed_match:
        return judgment

    numeric = compare_numeric_target(user_message, mission)
    numeric_status = numeric.get("status")
    if numeric_status in {"below_target", "above_limit", "missing_value", "unclear"}:
        updated = dict(judgment or {})
        updated["metadata_override"] = {
            "source": "allowed_substitutes",
            "matched": allowed_match,
            "previous_decision": updated.get("decision"),
            "decision": "kept",
            "numeric_status": numeric_status,
            "reason": "allowed match found but numeric status is not safe for approval",
        }
        return updated

    if numeric_status in {"meets_target", "not_applicable"}:
        return _with_override(
            judgment,
            "approved",
            f"DB allowed_substitutes match: {allowed_match}",
            allowed_match,
            "allowed_substitutes",
        )

    return judgment
