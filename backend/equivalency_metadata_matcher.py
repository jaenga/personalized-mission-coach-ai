from __future__ import annotations

import re
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


def _has_negation_or_condition(user_message: str) -> bool:
    return bool(_NEGATION_OR_CONDITION_RE.search(user_message or ""))


# "대신 / 말고 / 대체" 뒤가 사용자가 실제로 묻는 대체 후보다.
# 미션 설명 부분("점심 먹고 10분 걷기")이 매처에 노이즈로 들어가는 걸 막기 위해
# 키워드 뒤 phrase만 추출해 매처에 전달한다.
_REPLACEMENT_SPLIT_RE = re.compile(r"(?:대신에?|말고|대체로?)\s*")


def _extract_replacement_phrase(user_message: str) -> str:
    """사용자가 실제로 대체하려는 행동/음료/장소 부분만 추출.

    '대신/말고/대체' 키워드가 있으면 마지막 키워드 뒤 phrase 반환,
    없으면 원본 그대로 반환.
    """
    if not user_message:
        return ""
    matches = list(_REPLACEMENT_SPLIT_RE.finditer(user_message))
    if not matches:
        return user_message
    tail = user_message[matches[-1].end():].strip()
    return tail or user_message


def _norm_text(text: str) -> str:
    normalized = normalize_equivalency_text(text or "").lower()
    normalized = re.sub(r"\s+", "", normalized)
    for src, dst in _ALIASES.items():
        normalized = normalized.replace(src.lower(), dst.lower())
    return normalized


def _tokens(text: str) -> set[str]:
    raw = normalize_equivalency_text(text or "").lower()
    tokens = set()
    for token in _TOKEN_RE.findall(raw):
        token = re.sub(
            r"(먹어도|마셔도|들어도|봐도|해도|하고|듣고|먹기|마시기|보기|하기|했어|했니|하면|하는|으로|이랑|랑|와|과|로|만|를|을|은|는|이|가|도)$",
            "",
            token,
        )
        mapped = _ALIASES.get(token, token)
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


def apply_metadata_decision_override(
    judgment: dict,
    user_message: str,
    mission: dict | None,
) -> dict:
    if not mission:
        return judgment

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
