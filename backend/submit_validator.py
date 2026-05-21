from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from mission_meta import MISSION_META, extract_numeric

SubmitValidationAction = Literal["execute", "clarify", "block"]
SubmitResultType = Literal["success", "fail"]


@dataclass(frozen=True)
class SubmitValidationResult:
    action: SubmitValidationAction
    result_type: SubmitResultType | None = None
    reason: str = ""
    message: str = ""

    @property
    def should_execute(self) -> bool:
        return self.action == "execute" and self.result_type in {"success", "fail"}

    def to_debug(self) -> dict:
        return {
            "action": self.action,
            "result_type": self.result_type,
            "reason": self.reason,
        }


HARD_TEMPORAL = ("어제", "그저께", "엊그제", "지난번", "저번", "예전", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")
SOFT_TEMPORAL = ("이미", "아까")
SMALLTALK_EXACT = ("고마워", "그렇구나", "아하", "ㅋㅋ", "ㅎㅎ", "오케이", "알겠어")
SMALLTALK_MAX_LEN = 10

FALLBACK_RESPONSES = {
    "clarify_no_keyword": "어떤 미션 얘기하는 거야? 좀 더 알려줘!",
    "clarify_time_ambiguous": "오늘 한 거야? 언제 했는지 알려줘!",
    "clarify_number_only": "몇 분 동안 어떤 미션을 했는지 알려줘!",
    "clarify_partial": "조금 했구나! 얼마나 했는지 더 알려줄 수 있어?",
    "clarify_negation": "오늘 미션 기준으로 성공인지 같이 확인해볼까?",
    "block_smalltalk": "그렇구나! 오늘 미션은 잘 되고 있어?",
    "block_question": "그건 기록하지 않고 알려줄게!",
    "block_submit": "어떤 미션을 완료한 건지 조금 더 알려줘!",
    "error_no_db": "앗, 지금 기록이 잘 안 됐어. 다시 말해줄 수 있어?",
}

_QUESTION_INTENT_RE = re.compile(
    r"알려줘|어떻게|뭐야|뭐였|됐어|되었어|해줄\s*수\s*있|마셔도\s*돼|먹어도\s*돼|해도\s*돼"
    r"|성공\s*기준|실패\s*기준|기록\s*(?:됐|되었|저장)"
)
_COMPLETION_VERB_RE = re.compile(
    r"했어|했다|했음|했는데|마셨어|마셨|마심|먹었어|먹음|걸었어|걸었|닦았어|씻었어|완료했어|다\s*했어|끝났어|끝냈|마쳤어|해냈|클리어"
)
_SCREEN_RESTRICTION_VERB_RE = re.compile(
    r"봤어|봤다|안\s*봤어|안\s*봤다|시청했어|시청했다|안\s*시청했어|시청\s*안"
)
_NUMERIC_RE = re.compile(
    r"(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*"
    r"(?:분|보|바퀴|회|세트|번|초|시간|개|잔|컵|걸음|쪽|장|줄)"
)
_NEGATION_RE = re.compile(
    r"안\s*(?:먹었|먹고|마셨|봤|봄|보|했|탔|시청)"
    r"|못\s*(?:먹었|마셨|봤|봄|보|했|탔|시청)"
    r"|먹지\s*않|마시지\s*않|보지\s*않|하지\s*않|시청\s*안"
    r"|안먹|못먹|안마|못마|안봤|못봤|안했|못했"
)
_CONSUME_OR_SCREEN_RE = re.compile(
    r"먹었|먹음|먹어버|먹었다|마셨|봤어|봤다|봄|시청했|사용했|틀었|켰어|켰다"
)
_EXPLICIT_FAIL_RE = re.compile(
    r"실패"
    r"|못\s*했"
    r"|못\s*마셨"
    r"|안\s*했"
    r"|못\s*함"
    r"|안\s*함"
    r"|못\s*끝"
    r"|아예\s*못"
    r"|까먹"
    r"|패스\s*함"
)
_EXPLICIT_SUCCESS_RE = re.compile(r"미션\s*성공|오늘\s*미션\s*성공|성공했|미션\s*완료|오늘\s*미션\s*완료|완료했|끝냈|다\s*했|다했|수행했|해냈|클리어")
_FUTURE_REFUSAL_RE = re.compile(r"안\s*(?:할래|하겠|하려고)|하지\s*않을래|못\s*하겠|하기\s*싫")
_SUBSTITUTE_AVOID_RE = re.compile(r"안\s*(?:타|탔|이용|씀)|대신")
_SUBSTITUTE_ACTION_RE = re.compile(r"올라갔|내려갔|걸었|이용했|갔")
_QUALIFIER_RE = re.compile(r"조금|약간|반만|거의|잠깐|대충|가끔|살짝|조금밖에|한\s*입")
_DB_COMPLETION_PHRASE_RE = re.compile(
    r"기록(?:했|해뒀|됐|되었|완료)"
    r"|저장(?:했|해뒀|됐|되었)"
    r"|바꿨|바꿨어|바꿔뒀|변경(?:했|됐|되었)"
    r"|취소(?:했|됐|되었)"
    r"|완료(?:했|됐|되었)"
)

_OVERLAP_STOPWORDS = frozenset({
    "안", "못", "하기", "오늘", "한", "의", "에", "을", "를", "이", "가", "은", "는", "도", "로", "와", "과", "매일", "하루",
    "대신", "작은", "큰", "개", "잔", "번", "분", "초", "미션",
})


def is_smalltalk(message: str) -> bool:
    text = (message or "").strip()
    compact = re.sub(r"[\s!~.]+", "", text)
    return len(compact) <= SMALLTALK_MAX_LEN and compact in SMALLTALK_EXACT


def has_submit_blocker(message: str) -> tuple[str, str] | None:
    text = message or ""
    if any(word in text for word in HARD_TEMPORAL):
        return "clarify", "clarify_time_ambiguous"
    if any(word in text for word in SOFT_TEMPORAL) and "오늘" not in text:
        return "clarify", "clarify_time_ambiguous"
    if is_smalltalk(text):
        return "block", "block_smalltalk"
    if _FUTURE_REFUSAL_RE.search(text):
        return "clarify", "clarify_negation"
    if _QUESTION_INTENT_RE.search(text.replace(" ", "")) or _QUESTION_INTENT_RE.search(text):
        return "block", "block_question"
    if "?" in text and not _has_report_signal_with_question(text):
        return "block", "block_question"
    return None


def contains_numeric_expression(message: str) -> bool:
    return bool(_NUMERIC_RE.search(message or ""))


def _has_report_signal_with_question(message: str) -> bool:
    text = message or ""
    if not contains_numeric_expression(text):
        return False
    return bool(
        _COMPLETION_VERB_RE.search(text)
        or _CONSUME_OR_SCREEN_RE.search(text)
        or _NEGATION_RE.search(text)
    )


def contains_db_completion_phrase(gemma_text: str) -> bool:
    """Gemma 생성분만 넣어서 검사한다. 서버 ACK가 섞인 전체 응답에는 쓰지 않는다."""
    return bool(_DB_COMPLETION_PHRASE_RE.search(gemma_text or ""))


def build_submit_validation_response(
    result: SubmitValidationResult,
    mission_name: str = "",
) -> str:
    template = FALLBACK_RESPONSES.get(result.reason) or result.message
    if not template:
        template = FALLBACK_RESPONSES["block_submit"]
    return template.format(mission_name=mission_name or "오늘 미션")


def should_promote_to_submit_path(
    user_message: str,
    mission_name: str,
    mission_id: int | None = None,
) -> bool:
    if has_submit_blocker(user_message):
        return False
    if not _has_mission_keyword(user_message, mission_name, mission_id):
        return False

    meta = MISSION_META.get(mission_id) if mission_id else None
    if meta and meta.type == "prohibit":
        return bool(_SCREEN_RESTRICTION_VERB_RE.search(user_message or "") or _NEGATION_RE.search(user_message or ""))
    if meta and meta.type == "limit":
        return bool(
            contains_numeric_expression(user_message)
            or _NEGATION_RE.search(user_message or "")
            or _COMPLETION_VERB_RE.search(user_message or "")
        )
    if meta and meta.type == "substitute":
        return _is_clear_substitute_success(user_message, meta)

    return bool(_COMPLETION_VERB_RE.search(user_message or "") or contains_numeric_expression(user_message))


def validate_submit_candidate(
    user_message: str,
    mission_name: str,
    mission_id: int | None,
    qwen_args: dict | None,
) -> SubmitValidationResult:
    text = user_message or ""
    args = qwen_args or {}
    blocker = has_submit_blocker(text)
    if blocker:
        action, reason = blocker
        return _result(action, reason)

    meta = MISSION_META.get(mission_id) if mission_id else None
    mission_type = meta.type if meta else "perform"
    has_keyword = _has_mission_keyword(text, mission_name, mission_id)
    has_numeric = contains_numeric_expression(text)
    has_negation = bool(_NEGATION_RE.search(text))

    if _QUALIFIER_RE.search(text):
        return _result("clarify", "clarify_partial")

    if mission_type == "prohibit" and has_keyword:
        if has_negation:
            return _execute("success", "validated_prohibit_negation")
        if _CONSUME_OR_SCREEN_RE.search(text):
            return _execute("fail", "validated_prohibit_consumed")
        return _result("clarify", "clarify_negation")

    if mission_type == "substitute" and meta and _is_clear_substitute_success(text, meta):
        return _execute("success", "validated_success")

    if mission_type == "limit" and has_keyword and has_negation and not has_numeric:
        return _execute("success", "validated_limit_negation")

    if has_negation:
        if _EXPLICIT_FAIL_RE.search(text):
            return _execute("fail", "validated_fail")
        return _result("clarify", "clarify_negation")

    if has_numeric and not has_keyword:
        return _result("clarify", "clarify_number_only")

    requested_type = args.get("result_type")
    if requested_type not in {"success", "fail"}:
        requested_type = None

    if mission_type == "limit" and meta and meta.numeric and has_numeric:
        reported = extract_numeric(text, meta.numeric)
        if reported is None:
            return _result("clarify", "clarify_number_only")
        result_type = "success" if reported <= meta.numeric.threshold else "fail"
        return _execute(result_type, "validated_limit_numeric")

    if _EXPLICIT_FAIL_RE.search(text):
        return _execute("fail", "validated_fail")

    if requested_type == "fail":
        return _execute("fail", "validated_fail")

    if not has_keyword and not _explicitly_mentions_mission(text):
        return _result("clarify", "clarify_no_keyword")

    if has_numeric or _EXPLICIT_SUCCESS_RE.search(text) or _COMPLETION_VERB_RE.search(text):
        return _execute("success", "validated_success")

    if requested_type == "success":
        return _result("clarify", "clarify_no_keyword")

    return _result("clarify", "clarify_no_keyword")


def _result(action: SubmitValidationAction, reason: str) -> SubmitValidationResult:
    return SubmitValidationResult(
        action=action,
        result_type=None,
        reason=reason,
        message=FALLBACK_RESPONSES.get(reason, ""),
    )


def _execute(result_type: SubmitResultType, reason: str) -> SubmitValidationResult:
    return SubmitValidationResult(action="execute", result_type=result_type, reason=reason)


def _is_clear_substitute_success(message: str, meta) -> bool:
    text = message or ""
    has_avoid_keyword = any(keyword and keyword in text for keyword in meta.target_kw)
    return bool(
        has_avoid_keyword
        and _SUBSTITUTE_AVOID_RE.search(text)
        and "계단" in text
        and _SUBSTITUTE_ACTION_RE.search(text)
    )


def _explicitly_mentions_mission(message: str) -> bool:
    compact = (message or "").replace(" ", "")
    return "미션" in compact or "오늘미션" in compact


def _has_mission_keyword(
    message: str,
    mission_name: str,
    mission_id: int | None,
) -> bool:
    text = message or ""
    meta = MISSION_META.get(mission_id) if mission_id else None
    if meta:
        if any(keyword and keyword in text for keyword in meta.target_kw):
            return True
    return _mission_overlap(text, mission_name)


def _mission_overlap(message: str, mission_name: str) -> bool:
    if not mission_name or mission_name == "오늘의 미션":
        return False

    mission_tokens = {
        token
        for token in _tokenize_koreanish(mission_name)
        if token not in _OVERLAP_STOPWORDS and not _is_numeric_unit_token(token)
    }
    message_tokens = {
        token
        for token in _tokenize_koreanish(message)
        if not _is_numeric_unit_token(token)
    }
    return bool(mission_tokens & message_tokens)


def _tokenize_koreanish(text: str) -> set[str]:
    return set(re.findall(r"[가-힣A-Za-z0-9]+", text or ""))


def _is_numeric_unit_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:분|초|회|번|개|잔|컵|시간|걸음|보|세트)?", token or ""))
