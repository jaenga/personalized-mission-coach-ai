from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from mission_meta import MISSION_META, extract_numeric

NormReason = Literal[
    "",
    "negation_verb",
    "numeric",
    "numeric_no_count",
    "numeric_ambiguous",
    "difficulty",
    "qualifier",
    "past_ambiguous",
]


@dataclass
class NormResult:
    message: str
    should_clarify: bool
    reason: NormReason


_CANCEL_TARGET_RE = re.compile(
    r"(?:미션\s*)?(?:성공|실패)(?:\s*(?:제출|기록|한\s*거|한거))?\s*(?:을|를)?\s*(?:취소|되돌|되돌려|철회)"
    r"|(?:방금|최근|아까)?\s*(?:미션\s*결과\s*)?(?:제출|기록)(?:한\s*거|한거|된\s*거|된거)?\s*(?:을|를)?\s*(?:취소|되돌|되돌려|철회)"
    r"|(?:응|그래|좋아|네|ㅇㅇ)?\s*(?:취소|되돌|되돌려|철회)\s*(?:해줘|해|할래)?"
    r"|(?:방금|최근|아까)\s*(?:성공|실패)?(?:한\s*거|한거)?\s*(?:을|를)?\s*(?:취소|되돌|되돌려|철회)"
)
_ADJUSTMENT_CANCEL_RE = re.compile(
    r"(?:미션\s*)?(?:변경|바꾼\s*거|바꾼거|바꾼\s*미션|원래\s*미션)"
    r"[\s\S]{0,12}(?:취소|되돌|되돌려|철회|원래대로)"
)
_CANCEL_NEGATION_RE = re.compile(r"(?:취소|되돌|되돌려|철회)\s*하지\s*(?:마|말|말아|마라)")
_HARD_TEMPORAL_RE = re.compile(r"어제|그저께|엊그제|지난번|저번|예전|수요일|월요일|화요일|목요일|금요일|토요일|일요일")
_B_COMMAND_RE = re.compile(
    r"바꿔|취소|조회|보여줘|알려줘|뭐야|뭐예요|언제까지|어떻게|어때|어떤|규칙|마감|기록 봐|기록 보"
)
_EASIER_RE = re.compile(r"쉬운 걸로|쉽게\s*(?:바꿔|해줘|변경)|쉬운\s*미션")
_TOO_DIFFICULT_RE = re.compile(r"너무 어려워|어려워서|어려워|어려움|어렵|힘들어|못하겠")
_HARDER_RE = re.compile(r"어려운 걸로|너무 쉬워|너무 쉬움|쉬워서|쉬움")
_CHANGE_RE = re.compile(r"바꿔|변경|다른 미션|다른 걸로")
_QUESTION_RE = re.compile(
    r"(?:성공|실패|완료|fail|success)[\s\S]{0,16}"
    r"(?:인가요|인가\??|건가요|건가\??|거\s*[예에][요여]\??|거야\??|거임\??|"
    r"맞아\??|맞아요\??|맞나요|맞는지|맞을까|될까|되는지|돼요\??|되나요|되나\??|"
    r"인지|어때요\??|어때\??)"
)
_NEGATION_VERB_RE = re.compile(
    r"안 ?먹었|안 ?먹고|못 ?먹었|안 ?마셨|못 ?마셨|안 ?봤|못 ?봤|안 ?봄|못 ?봄|안 ?탔|못 ?탔|안 ?탔다|못 ?탔다|안먹|못먹|안마|못마|안봤|못봤|안타|못타"
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
_EMOTIONAL_RE = re.compile(r"하기 싫|못하겠|안해|못해|포기")
_EXPLICIT_SUCCESS_RE = re.compile(r"성공|완료|해냈|끝냈|다 했|다했|클리어")
_SUCCESS_RE = re.compile(
    r"했어(?:요)?|먹었어(?:요)?|먹음|마셨어(?:요)?|마심|운동했어(?:요)?|달렸어(?:요)?|잘했어(?:요)?"
)
_NUMERIC_REPORT_RE = re.compile(
    r"(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*"
    r"(?:분|보|바퀴|회|세트|번|초|시간|개|잔|컵|걸음|쪽|장|줄)"
)
_PAST_VERB_RE = re.compile(r"[가-힣]{1,8}(?:었|았|했|겼|켰|렸|웠|냈|봤)어(?:요)?")
_QUALIFIER_RE = re.compile(r"조금|약간|반만|거의|잠깐|대충|가끔|살짝|조금밖에|한\s*입")
_CONSUME_PAST_RE = re.compile(
    r"먹었|먹었다|마셨|마셨다|봤어|봤다|시청했|사용했|틀었|켰어|켰다"
)
_SUBSTITUTE_SUCCESS_ACTION_RE = re.compile(
    r"걸었|걸어|갔|가봤|이용했|이용|올라갔|올랐|다녔"
)
_SUBSTITUTE_AVOID_RE = re.compile(r"안\s*(?:타|탔|이용|씀)|대신")
_SUBSTITUTE_ACTION_RE = re.compile(r"올라갔|내려갔|걸었|이용했|갔")

_OVERLAP_STOPWORDS = frozenset({
    "안", "못", "하기", "오늘", "한", "의", "에", "을", "를", "이", "가", "은", "는", "도", "로", "와", "과", "매일", "하루",
    "대신", "작은", "큰", "개", "잔", "번", "분", "초",
})


def _tokenize_koreanish(text: str) -> set[str]:
    return set(re.findall(r"[가-힣A-Za-z0-9]+", text))


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


def _is_numeric_unit_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:분|초|회|번|개|잔|컵|시간|걸음|보|세트)?", token or ""))


def normalize_b_input(
    message: str,
    mission_name: str,
    mission_id: int | None = None,
) -> NormResult:
    def ok(msg=message):
        return NormResult(msg, False, "")

    def clarify(reason):
        return NormResult(message, True, reason)

    def success():
        return ok(f"오늘 미션 '{mission_name}' 성공했어요")

    def fail():
        return ok(f"오늘 미션 '{mission_name}' 실패했어요")

    if _CANCEL_NEGATION_RE.search(message):
        return clarify("")
    if _HARD_TEMPORAL_RE.search(message):
        return clarify("past_ambiguous")
    if _ADJUSTMENT_CANCEL_RE.search(message):
        return ok("미션 변경 취소해줘")
    if _CANCEL_TARGET_RE.search(message):
        return ok("미션 제출 취소해줘")
    if _EASIER_RE.search(message):
        return ok("더 쉬운 미션으로 바꿔줘")
    if _TOO_DIFFICULT_RE.search(message):
        return clarify("difficulty")
    if _HARDER_RE.search(message):
        return ok("더 어려운 미션으로 바꿔줘")
    if _CHANGE_RE.search(message):
        return ok("미션 바꿔줘")
    if _B_COMMAND_RE.search(message):
        return ok()
    if _QUESTION_RE.search(message):
        return clarify("")

    meta = MISSION_META.get(mission_id) if mission_id else None
    if meta is None:
        if _NEGATION_VERB_RE.search(message):
            return clarify("negation_verb")

        if _EXPLICIT_FAIL_RE.search(message):
            return fail()

        if _EXPLICIT_SUCCESS_RE.search(message):
            if _QUALIFIER_RE.search(message):
                return clarify("qualifier")
            return success()

        if _NUMERIC_REPORT_RE.search(message):
            return clarify("numeric")

        if _QUALIFIER_RE.search(message):
            return clarify("qualifier")

        if _PAST_VERB_RE.search(message) and _mission_overlap(message, mission_name):
            return clarify("past_ambiguous")

        return clarify("")

    mtype = meta.type if meta else "perform"
    has_target = bool(meta and any(kw in message for kw in meta.target_kw))
    has_mission_overlap = _mission_overlap(message, mission_name)
    has_mission_target = has_target or has_mission_overlap
    has_negation = bool(_NEGATION_VERB_RE.search(message))

    if mtype == "substitute" and meta:
        if _is_clear_substitute_success(message, meta):
            return success()
        if has_target and not has_negation:
            return fail()
        if has_target and has_negation:
            return clarify("negation_verb")

    if mtype == "prohibit" and has_target and has_negation:
        return success()

    if mtype == "prohibit" and has_target and not has_negation and _CONSUME_PAST_RE.search(message):
        return fail()

    if mtype == "limit" and has_mission_target and has_negation and not _NUMERIC_REPORT_RE.search(message):
        return success()

    if _EMOTIONAL_RE.search(message) and not _EXPLICIT_FAIL_RE.search(message):
        return ok()

    if _EXPLICIT_FAIL_RE.search(message):
        return fail()

    if has_negation:
        return clarify("negation_verb")

    if _NUMERIC_REPORT_RE.search(message):
        if meta and meta.numeric:
            if mtype == "limit":
                if not has_mission_target:
                    return clarify("numeric")
                reported = extract_numeric(message, meta.numeric)
                if reported is None:
                    return clarify("numeric")
                return success() if reported <= meta.numeric.threshold else fail()

            if not has_mission_target:
                return clarify("numeric")
            reported = extract_numeric(message, meta.numeric)
            if reported is None:
                return clarify("numeric")
            if reported >= meta.numeric.threshold:
                return success()
            return clarify("numeric_ambiguous")
        return clarify("numeric")

    if meta and meta.numeric and _SUCCESS_RE.search(message):
        if _QUALIFIER_RE.search(message):
            return clarify("qualifier")
        if has_mission_target and meta.success_kw and any(kw in message for kw in meta.success_kw):
            return success()
        return clarify("numeric_no_count")

    if _EXPLICIT_SUCCESS_RE.search(message):
        if _QUALIFIER_RE.search(message):
            return clarify("qualifier")
        return success()

    if _QUALIFIER_RE.search(message):
        return clarify("qualifier")

    if not _mission_overlap(message, mission_name):
        return ok()
    if _SUCCESS_RE.search(message):
        return success()
    if _PAST_VERB_RE.search(message):
        return clarify("past_ambiguous")

    return ok()


def _is_clear_substitute_success(message: str, meta) -> bool:
    text = message or ""
    has_avoid_keyword = any(keyword and keyword in text for keyword in meta.target_kw)
    return bool(
        has_avoid_keyword
        and _SUBSTITUTE_AVOID_RE.search(text)
        and "계단" in text
        and _SUBSTITUTE_ACTION_RE.search(text)
    )
