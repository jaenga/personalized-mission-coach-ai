from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from mission_context import MissionContext


Relatedness = Literal["high", "medium", "low"]
ResponseHintLevel = Literal["none", "light", "strong"]
PossibleBKind = Literal[
    "mission_help",
    "equivalency",
    "submit",
    "difficulty",
    "dislike",
    "cancel",
]

_STOPWORDS = {
    "오늘",
    "미션",
    "하기",
    "동안",
    "이상",
    "이하",
    "한",
    "두",
    "세",
    "네",
    "번",
    "분",
    "회",
    "개",
    "잔",
    "컵",
}

_HEALTH_INFO_RE = re.compile(
    r"왜|효과|좋은\s*이유|몸에\s*좋|건강에\s*좋|영양소|부작용|키\s*크|살\s*빠"
)
_HELP_RE = re.compile(
    r"몇\s*(?:컵|잔|분|번|회|개|초|시간|ml|mL|리터|L|l)"
    r"|얼마나|기준|규칙|룰|조건|방법|어떻게|어떤\s*(?:거|걸|것)"
    r"|뭐\s*(?:먹|마시|하면|해야)|언제까지"
)
_EQUIVALENCY_RE = re.compile(
    r"대신|말고|대체|해도\s*(?:돼|되|괜찮)|먹어도\s*(?:돼|되|괜찮)"
    r"|마셔도\s*(?:돼|되|괜찮)|봐도\s*(?:돼|되|괜찮)|인정|괜찮(?:아|나|을까)?"
    r"|(?:도|으로|로)\s*(?:돼|되나요|되나|괜찮)"
)
_CLEAR_CANCEL_RE = re.compile(
    r"(?:성공|실패|제출|기록|결과).{0,12}(?:취소|되돌|철회)"
    r"|방금.{0,12}(?:기록|제출|바꾼|변경).{0,12}(?:취소|되돌|철회)"
    r"|미션\s*변경.{0,12}(?:취소|되돌|철회)"
)
_AMBIGUOUS_CANCEL_RE = re.compile(r"미션\s*취소|그냥\s*취소|이거\s*취소|안\s*할래")
_DISLIKE_RE = re.compile(r"싫|재미없|재미\s*없|별로|그만할래|하기\s*싫")
_DIFFICULTY_RE = re.compile(r"힘들|어려|못\s*하겠|못하겠|무리|버거|귀찮|빡세")
_FAIL_REPORT_RE = re.compile(
    r"실패|못\s*했|못했|안\s*했|안했|못\s*끝|까먹|깜빡|포기|자버렸"
    r"|안\s*(?:걷|먹|마시|봤|탔|만졌|댐|닿)|손도\s*안\s*댐"
)
_SUCCESS_REPORT_RE = re.compile(
    r"성공|완료|끝냈|다\s*했|다했|해냈|했어|했다|했음|먹었|마셨|씻었|닦았|안\s*먹|안\s*봤|안\s*탔"
)
_NUMERIC_REPORT_RE = re.compile(
    r"(?:\d+(?:\.\d+)?|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|일)\s*"
    r"(?:분|보|바퀴|회|세트|번|초|시간|개|잔|컵|걸음|봉지|병|입|쪽|장|줄|ml|mL|밀리|미리|L|l|리터)"
    r"|일\s*리터|일리터"
)


@dataclass(frozen=True)
class MissionContextAnalysis:
    relatedness: Relatedness
    reason: str
    matched_signals: list[str] = field(default_factory=list)
    health_info_signal: bool = False
    response_hint_level: ResponseHintLevel = "none"
    possible_b_kind: PossibleBKind | None = None
    response_hint: str = ""

    @property
    def is_related(self) -> bool:
        return self.relatedness in {"high", "medium"}


def analyze_mission_context(
    user_message: str | None,
    mission_context: MissionContext | None,
) -> MissionContextAnalysis:
    """Analyze mission relatedness for response hints only.

    The returned object is not an execution command. It must not be used by
    itself to write DB state, submit a result, change missions, or cancel
    records.
    """

    message = (user_message or "").strip()
    context = mission_context or MissionContext()
    if not message or context.is_empty:
        return MissionContextAnalysis("low", "empty_message_or_context")

    health_info_signal = bool(_HEALTH_INFO_RE.search(message))
    relatedness, reason, matched_signals = _classify_relatedness(message, context)
    possible_b_kind = _classify_possible_b_kind(message, relatedness, health_info_signal)
    hint_level = _response_hint_level(relatedness, health_info_signal)
    response_hint = _build_response_hint(context, relatedness, health_info_signal, hint_level, possible_b_kind)

    return MissionContextAnalysis(
        relatedness=relatedness,
        reason=reason,
        matched_signals=matched_signals,
        health_info_signal=health_info_signal,
        response_hint_level=hint_level,
        possible_b_kind=possible_b_kind,
        response_hint=response_hint,
    )


def _classify_relatedness(
    message: str,
    context: MissionContext,
) -> tuple[Relatedness, str, list[str]]:
    signals: list[str] = []
    compact = _compact(message)

    if _contains_any(message, compact, context.target_kw):
        signals.append("target_keyword")
    if context.activity_key and _contains_text(message, compact, context.activity_key):
        signals.append("activity_key")
    if _mission_name_overlap(message, context.mission_name):
        signals.append("mission_name_overlap")
    if context.target_unit and _contains_unit(message, context.target_unit):
        signals.append("target_unit")
    if _metadata_overlap(message, context.success_criteria, context.strict_requirements):
        signals.append("metadata_overlap")
    if _contains_any(message, compact, context.success_kw):
        signals.append("success_metadata")
    if _contains_any(message, compact, context.fail_kw):
        signals.append("fail_metadata")
    if _explicit_current_mission_reference(message):
        signals.append("current_mission_reference")

    strong_signals = {
        "target_keyword",
        "activity_key",
        "target_unit",
        "success_metadata",
        "fail_metadata",
    }
    if any(signal in strong_signals for signal in signals):
        return "high", "strong_mission_signal", signals
    if len(signals) >= 2:
        return "high", "multiple_weak_mission_signals", signals
    if signals:
        return "medium", "weak_mission_signal", signals
    return "low", "no_mission_signal", signals


def _classify_possible_b_kind(
    message: str,
    relatedness: Relatedness,
    health_info_signal: bool,
) -> PossibleBKind | None:
    if relatedness == "low":
        return None
    if health_info_signal:
        return None
    if _CLEAR_CANCEL_RE.search(message):
        return "cancel"
    if _AMBIGUOUS_CANCEL_RE.search(message):
        return None
    if _HELP_RE.search(message):
        return "mission_help"
    if _EQUIVALENCY_RE.search(message):
        return "equivalency"
    if _DISLIKE_RE.search(message):
        return "dislike"
    if _DIFFICULTY_RE.search(message):
        return "difficulty"
    if _FAIL_REPORT_RE.search(message) or _NUMERIC_REPORT_RE.search(message) or _SUCCESS_REPORT_RE.search(message):
        return "submit"
    return None


def _response_hint_level(
    relatedness: Relatedness,
    health_info_signal: bool,
) -> ResponseHintLevel:
    if relatedness == "low":
        return "none"
    if health_info_signal:
        return "light"
    if relatedness == "high":
        return "strong"
    return "light"


def _build_response_hint(
    context: MissionContext,
    relatedness: Relatedness,
    health_info_signal: bool,
    hint_level: ResponseHintLevel,
    possible_b_kind: PossibleBKind | None,
) -> str:
    if hint_level == "none":
        return ""

    mission_label = context.mission_name or "오늘 미션"
    guard = (
        "이 힌트는 최종 답변 맥락 보조용이다. "
        "사용자 발화를 미션 수행 결과 제출로 해석하지 말고, "
        "DB 저장/미션 변경/기록 취소를 암시하지 마라."
    )
    if health_info_signal:
        return (
            f"{guard} 기존 C 건강 정보 답변 흐름을 유지하라. "
            f"'{mission_label}'와 관련이 있으면 답변 말미에만 가볍게 연결하라."
        )
    if possible_b_kind in {"difficulty", "dislike"}:
        return (
            f"{guard} 사용자가 '{mission_label}'에 부담이나 거부감을 느끼는 맥락일 수 있다. "
            "바로 실패 처리하거나 미션 변경을 확정하지 말고 공감 후 선택지를 제안하라."
        )
    if possible_b_kind == "submit":
        return (
            f"{guard} '{mission_label}' 관련 수행 보고처럼 보일 수 있으나, "
            "응답 생성만으로 성공/실패 기록을 확정하지 마라."
        )
    if possible_b_kind in {"mission_help", "equivalency"}:
        return (
            f"{guard} '{mission_label}' 수행 기준이나 인정 여부와 관련된 맥락일 수 있다. "
            "기존 답변 흐름을 유지하되 오늘 미션 조건을 혼동하지 않게 짧게 반영하라."
        )
    if relatedness == "high":
        return f"{guard} 답변 중심에 '{mission_label}' 맥락을 자연스럽게 반영하라."
    return f"{guard} 필요할 때만 '{mission_label}' 맥락을 답변 말미에 가볍게 연결하라."


def _contains_any(message: str, compact_message: str, values: list[str]) -> bool:
    return any(_contains_text(message, compact_message, value) for value in values)


def _contains_text(message: str, compact_message: str, value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    return text in message or text.replace(" ", "") in compact_message


def _contains_unit(message: str, unit: str) -> bool:
    text = message or ""
    compact = _compact(text)
    unit_compact = _compact(unit)
    if unit_compact and unit_compact in compact:
        return True
    if unit_compact in {"l", "L".lower(), "리터"}:
        return bool(re.search(r"일\s*리터|일리터|\d+(?:\.\d+)?\s*(?:L|l|리터)", text))
    if unit_compact == "ml":
        return bool(re.search(r"\d+(?:\.\d+)?\s*(?:ml|mL|밀리|미리)", text))
    return False


def _metadata_overlap(message: str, *metadata_values: str) -> bool:
    message_tokens = _tokens(message)
    if not message_tokens:
        return False
    for value in metadata_values:
        metadata_tokens = _tokens(value)
        meaningful = {token for token in metadata_tokens if token not in _STOPWORDS}
        if meaningful and len(message_tokens & meaningful) >= 2:
            return True
    return False


def _mission_name_overlap(message: str, mission_name: str) -> bool:
    mission_tokens = {
        token
        for token in _tokens(mission_name)
        if token not in _STOPWORDS and not _is_numeric_unit_token(token)
    }
    if not mission_tokens:
        return False
    message_tokens = _tokens(message)
    return bool(mission_tokens & message_tokens)


def _explicit_current_mission_reference(message: str) -> bool:
    compact = _compact(message)
    return (
        "오늘미션" in compact
        or "이번미션" in compact
        or "이미션" in compact
        or "그미션" in compact
    )


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[가-힣A-Za-z0-9]+", text or ""))


def _compact(text: str) -> str:
    return (text or "").replace(" ", "").strip()


def _is_numeric_unit_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:분|초|회|번|개|잔|컵|시간|걸음|보|바퀴|세트|봉지|병|입|ml|mL|밀리|미리|L|l|리터)?", token or ""))
