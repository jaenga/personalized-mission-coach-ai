from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from mission_meta import MISSION_META

NormReason = Literal[
    "",
    "negation_verb",
    "numeric",
    "numeric_no_count",
    "numeric_ambiguous",
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
    r"|(?:방금|최근|아까)\s*(?:성공|실패)?(?:한\s*거|한거)?\s*(?:을|를)?\s*(?:취소|되돌|되돌려|철회)"
)
_B_COMMAND_RE = re.compile(
    r"바꿔|취소|조회|보여줘|알려줘|뭐야|뭐예요|언제까지|어떻게|어때|어떤|규칙|마감|기록 봐|기록 보"
)
_EASIER_RE = re.compile(r"쉬운 걸로|너무 어려워|쉽게|어려워서")
_HARDER_RE = re.compile(r"어려운 걸로|너무 쉬워|쉬워서")
_CHANGE_RE = re.compile(r"바꿔|변경|다른 미션|다른 걸로")
_QUESTION_RE = re.compile(
    r"인가요|건가요|거예요\?|맞아\?|맞나요|될까|할까|돼요\?|되나요|인지|어때요\?"
    r"|성공인가|실패인가|성공.*맞|실패.*맞|성공.*되|실패.*되"
)
_NEGATION_VERB_RE = re.compile(
    r"안 ?먹었|못 ?먹었|안 ?마셨|못 ?마셨|안먹|못먹|안마|못마"
)
_EXPLICIT_FAIL_RE = re.compile(r"실패|못했|안했")
_EMOTIONAL_RE = re.compile(r"하기 싫|못하겠|안해|못해|포기")
_EXPLICIT_SUCCESS_RE = re.compile(r"성공|완료|해냈|끝냈|다 했|다했|클리어")
_SUCCESS_RE = re.compile(
    r"했어(?:요)?|먹었어(?:요)?|마셨어(?:요)?|운동했어(?:요)?|달렸어(?:요)?|잘했어(?:요)?"
)
_NUMERIC_REPORT_RE = re.compile(
    r"(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*"
    r"(?:분|보|바퀴|회|세트|번|초|시간|개|잔|컵|걸음|쪽|장|줄)"
)
_PAST_VERB_RE = re.compile(r"[가-힣]{1,8}(?:었|았|했|겼|켰|렸|웠|냈|봤)어(?:요)?")
_QUALIFIER_RE = re.compile(r"조금|약간|반만|거의|잠깐|대충|가끔|살짝|조금밖에")
_CONSUME_PAST_RE = re.compile(
    r"먹었|먹었다|마셨|마셨다|봤어|봤다|시청했|사용했|틀었|켰어|켰다"
)
_SUBSTITUTE_SUCCESS_ACTION_RE = re.compile(
    r"걸었|걸어|갔|가봤|이용했|이용|올라갔|올랐|다녔"
)

_NUMBER_KO = {
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
        if token not in _OVERLAP_STOPWORDS
    }
    message_tokens = _tokenize_koreanish(message)
    return bool(mission_tokens & message_tokens)


def _extract_numeric(text: str, goal) -> float | None:
    unit_map = {
        "회": "회",
        "번": "회",
        "개": "회",
        "분": "분",
        "시간": "분",
        "ml": "ml",
        "mL": "ml",
        "L": "ml",
        "l": "ml",
        "리터": "ml",
        "잔": "ml",
        "컵": "ml",
    }
    goal_unit = unit_map.get(goal.unit, goal.unit)
    pattern = re.compile(
        r"(\d+(?:\.\d+)?|" + "|".join(_NUMBER_KO.keys()) + r")\s*"
        r"(분|시간|회|번|개|잔|컵|L|l|ml|mL|리터)"
    )
    for match in pattern.finditer(text):
        raw_num, raw_unit = match.group(1), match.group(2)
        if unit_map.get(raw_unit, raw_unit) != goal_unit:
            continue

        val = float(_NUMBER_KO.get(raw_num, raw_num))
        if raw_unit == "시간":
            val *= 60
        elif raw_unit in goal.unit_aliases:
            val *= goal.unit_aliases[raw_unit]
        return val
    return None


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

    if _CANCEL_TARGET_RE.search(message):
        return ok("최근 미션 결과 제출을 취소해줘")
    if _EASIER_RE.search(message):
        return ok("더 쉬운 미션으로 바꿔줘")
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
    has_negation = bool(_NEGATION_VERB_RE.search(message))

    if mtype == "substitute" and meta:
        has_success = (
            any(kw in message for kw in meta.success_kw)
            and _SUBSTITUTE_SUCCESS_ACTION_RE.search(message)
        )
        if has_success:
            return success()
        if has_target and not has_negation:
            return fail()
        if has_target and has_negation:
            return clarify("negation_verb")

    if mtype == "prohibit" and has_target and has_negation:
        return success()

    if mtype == "prohibit" and has_target and not has_negation and _CONSUME_PAST_RE.search(message):
        return fail()

    if _EMOTIONAL_RE.search(message) and not _EXPLICIT_FAIL_RE.search(message):
        return ok()

    if _EXPLICIT_FAIL_RE.search(message):
        return fail()

    if has_negation:
        return clarify("negation_verb")

    if _NUMERIC_REPORT_RE.search(message):
        if meta and meta.numeric:
            if mtype == "limit":
                if not has_target:
                    return clarify("numeric")
                reported = _extract_numeric(message, meta.numeric)
                if reported is None:
                    return clarify("numeric")
                return success() if reported <= meta.numeric.threshold else fail()

            reported = _extract_numeric(message, meta.numeric)
            if reported is None:
                return clarify("numeric")
            if reported >= meta.numeric.threshold:
                return success()
            return clarify("numeric_ambiguous")
        return clarify("numeric")

    if meta and meta.numeric and _SUCCESS_RE.search(message):
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
