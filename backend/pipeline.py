"""
Pipeline — 통합 파이프라인 step 함수 + 멀티펑션 헬퍼.
import 방향: pipeline → executor, hint_builder (단방향)
"""
from __future__ import annotations

import random
import re
import time

from intent_router import classify_intent, split_multi_intent
from qwen_client import call_function
from rag import search_rag
from prompts import CLARIFY_HINT_DEFAULT, CLARIFY_HINT_MISSION_REPORT, build_system_prompt
from database import _kst_today, get_last_action_type, fetch_profile, get_relevant_user_memories
from executor import (
    ExecResults,
    execute_submit, execute_adjustment, execute_cancel,
)
from hint_builder import (
    build_one_hint, build_conflict_prompt, build_fn_hint, build_cancel_hint,
    EQUIVALENCY_SUBMIT_TAG_INSTRUCTION,
)


# ── 멀티펑션 조합 상수 + 헬퍼 (main.py에서 이동) ────────────────────────────

_CONFLICT_PAIRS = [
    {"submit_mission_result", "request_mission_adjustment"},
    {"request_mission_adjustment", "check_mission_equivalency"},
]
_NON_REPEATABLE = {"submit_mission_result", "cancel_mission_action", "request_mission_adjustment"}

_SEQUENTIAL_PAIRS = [
    ("check_mission_equivalency", "submit_mission_result"),
    ("submit_mission_result", "get_user_history"),
]

_DB_BRANCH_PAIRS = {
    frozenset({"cancel_mission_action", "submit_mission_result"}): "submit",
    frozenset({"cancel_mission_action", "request_mission_adjustment"}): "adjustment",
}

_FUNCTION_NAME_ALIASES = {
    "cancel_mission": "cancel_mission_action",
}


def detect_cancel_type(message: str) -> str:
    text = (message or "").replace(" ", "")
    if re.search(r"(?:성공|실패|제출|기록|결과)[\s\S]{0,12}(?:취소|되돌|철회)", text):
        return "submit"
    if re.search(r"(?:미션변경|변경|바꾼거|원래미션)[\s\S]{0,12}(?:취소|되돌|철회)", text):
        return "adjustment"
    return "latest"


def normalize_function_calls(fn_calls: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    normalized = []
    for fn, args in fn_calls:
        canonical_fn = _FUNCTION_NAME_ALIASES.get(fn, fn)
        canonical_args = dict(args or {})
        if canonical_fn == "cancel_mission_action":
            cancel_type = canonical_args.get("cancel_type")
            if cancel_type not in {"submit", "adjustment", "latest"}:
                canonical_args["cancel_type"] = "latest"
        normalized.append((canonical_fn, canonical_args))
    return normalized


def classify_multi(fn_calls: list[tuple[str, dict]]) -> str:
    """멀티펑션 조합 분류. 반환값: 'conflict' | 'sequential' | 'db_branch' | 'independent'"""
    fn_calls = normalize_function_calls(fn_calls)
    names = [fn for fn, _ in fn_calls]

    for name in _NON_REPEATABLE:
        if names.count(name) > 1:
            return "conflict"

    name_set = set(names)

    if any(pair.issubset(name_set) for pair in _CONFLICT_PAIRS):
        return "conflict"

    if frozenset(name_set) in _DB_BRANCH_PAIRS:
        cancel_idx = next((i for i, n in enumerate(names) if n == "cancel_mission_action"), None)
        if cancel_idx == 0:
            return "db_branch"
        return "conflict"

    for first, second in _SEQUENTIAL_PAIRS:
        if first in name_set and second in name_set:
            return "sequential"

    if "get_mission_info" in name_set:
        mission_info_args = next((args for fn, args in fn_calls if fn == "get_mission_info"), {})
        if mission_info_args.get("query_type") == "today":
            if "request_mission_adjustment" in name_set or "cancel_mission_action" in name_set:
                return "sequential"

    return "independent"


def is_equivalency_submit(fn_calls: list[tuple[str, dict]]) -> bool:
    """equivalency→submit 조합인지 확인."""
    names = {fn for fn, _ in fn_calls}
    return "check_mission_equivalency" in names and "submit_mission_result" in names


def _reorder_sequential(fn_calls: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """순차 쌍이 있으면 올바른 실행 순서로 정렬."""
    if len(fn_calls) < 2:
        return fn_calls
    ordered = list(fn_calls)

    for first, second in _SEQUENTIAL_PAIRS:
        first_idx = next((i for i, (fn, _) in enumerate(ordered) if fn == first), None)
        second_idx = next((i for i, (fn, _) in enumerate(ordered) if fn == second), None)
        if first_idx is not None and second_idx is not None and first_idx > second_idx:
            ordered[first_idx], ordered[second_idx] = ordered[second_idx], ordered[first_idx]

    mi_idx = next((i for i, (fn, args) in enumerate(ordered)
                    if fn == "get_mission_info" and args.get("query_type") == "today"), None)
    if mi_idx is not None:
        for priority_fn in ("request_mission_adjustment", "cancel_mission_action"):
            p_idx = next((i for i, (fn, _) in enumerate(ordered) if fn == priority_fn), None)
            if p_idx is not None and p_idx > mi_idx:
                ordered[p_idx], ordered[mi_idx] = ordered[mi_idx], ordered[p_idx]
                break

    return ordered


# ── Step 함수 ────────────────────────────────────────────────────────────────

# ── 미션 보고 정규화 ─────────────────────────────────────────────────────────

def _short(text: str | None, limit: int = 70) -> str:
    if not text:
        return ""
    one_line = " ".join(str(text).split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "…"


def _fn_label(fn: str, args: dict | None = None) -> str:
    args = args or {}
    if fn == "submit_mission_result":
        return f"submit({args.get('result_type', '?')})"
    if fn == "request_mission_adjustment":
        return f"adjust({args.get('adjustment_type', '?')})"
    if fn == "cancel_mission_action":
        return "cancel"
    if fn == "get_mission_info":
        return f"mission_info({args.get('query_type', '?')})"
    if fn == "get_user_history":
        return f"history({args.get('query_type', '?')})"
    if fn == "check_mission_equivalency":
        return f"equiv({args.get('equivalency_type', '?')})"
    return fn


def _fn_list(fn_calls: list[tuple[str, dict]]) -> str:
    return ", ".join(_fn_label(fn, args) for fn, args in fn_calls) or "-"


def _result_label(result: object | None) -> str:
    if not result:
        return "-"
    status = getattr(getattr(result, "status", None), "value", getattr(result, "status", None))
    action = getattr(getattr(result, "action", None), "value", None)
    changed = getattr(result, "db_changed", False)
    detail = (
        getattr(result, "result_type", None)
        or getattr(result, "adjustment_type", None)
        or getattr(result, "new_mission_name", None)
    )
    pieces = [str(status)]
    if detail:
        pieces.append(str(detail))
    pieces.append(f"db={'Y' if changed else 'N'}")
    if action:
        pieces.append(str(action))
    return "/".join(pieces)


def _exec_label(results: ExecResults) -> str:
    return (
        f"submit={_result_label(results.submit)} "
        f"adjust={_result_label(results.adjustment)} "
        f"cancel={_result_label(results.cancel)}"
    )


_B_COMMAND_RE = re.compile(
    r"바꿔|취소|조회|보여줘|알려줘|뭐야|뭐예요|언제까지|어떻게|어때|어떤|규칙|마감|기록 봐|기록 보"
)
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
# 행동+부정: 금지형 미션("과자 안 먹기")에서 성공일 수 있어 별도 처리
# 주의: 못했/안했(일반 실패)은 여기 포함 안 함 → _FAIL_RE에서 처리
_NEGATION_VERB_RE = re.compile(
    r"안 ?먹었|못 ?먹었|안 ?마셨|못 ?마셨|안먹|못먹|안마|못마"
)
# 명확한 실패 표현 (금지형 미션과 무관)
_FAIL_RE = re.compile(r"실패|못했|안했|안해|못해|하기 싫|못하겠")
_EXPLICIT_SUCCESS_RE = re.compile(r"성공|완료|해냈|끝냈|다 했|다했|클리어")
_SUCCESS_RE = re.compile(
    r"했어(?:요)?|먹었어(?:요)?|마셨어(?:요)?|운동했어(?:요)?|달렸어(?:요)?|잘했어(?:요)?"
)
_NUMERIC_REPORT_RE = re.compile(
    r"(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*"
    r"(?:분|보|바퀴|회|세트|번|초|시간|개|잔|컵|걸음|쪽|장|줄)"
)
_PAST_VERB_RE = re.compile(r"[가-힣]{1,8}(?:었|았|했|겼|켰|렸|웠|냈|봤)어(?:요)?")


# 다중 의도 키워드 — 명시적 접속사
_MULTI_INTENT_RE = re.compile(
    r"그리고|그리구|또\s|이랑\s|랑\s|하고\s|마감도|기록도|성공하고|취소하고|바꾸고"
)
# 제출 동사 + 조회 동사가 같이 있으면 공백으로 이어진 다중 의도일 가능성이 높음
_SUBMIT_HINT_RE = re.compile(r"성공|실패|완료|했어|못했|해냈")
_QUERY_HINT_RE = re.compile(r"보여|알려|뭐야|뭔데|언제|기록|조회|마감")

# 위로/격려 상황 감지
_COMFORT_RE = re.compile(
    r"힘들|슬퍼|슬프|짜증|우울|싫어|못하겠|포기|지쳐|피곤|하기 싫"
)

_OVERLAP_STOPWORDS = frozenset({
    "안", "못", "하기", "오늘", "한", "의", "에", "을", "를", "이", "가", "은", "는", "도", "로", "와", "과", "매일", "하루",
    "대신", "작은", "큰", "개", "잔", "번", "분", "초",
})


def _tokenize_koreanish(text: str) -> set[str]:
    return set(re.findall(r"[가-힣A-Za-z0-9]+", text))


def _mission_overlap(message: str, mission_name: str) -> bool:
    """미션명과 메시지의 핵심 토큰이 겹치면 True."""
    if not mission_name or mission_name == "오늘의 미션":
        return False

    mission_tokens = {
        token
        for token in _tokenize_koreanish(mission_name)
        if token not in _OVERLAP_STOPWORDS
    }
    message_tokens = _tokenize_koreanish(message)
    return bool(mission_tokens & message_tokens)


def _should_call_name(
    is_greet: bool,
    intent: str,
    exec_results: ExecResults | None,
    user_message: str,
) -> bool:
    """서버가 이름 호출 여부를 결정한다. 모델에 판단을 맡기지 않는다.

    - 첫 인사: 70%
    - 미션 성공/실패 직후: 30%
    - 위로/격려 상황 (A 인텐트): 50%
    """
    if is_greet:
        return random.random() < 0.70

    if (
        intent == "B"
        and exec_results is not None
        and exec_results.submit is not None
        and exec_results.submit.status.value == "saved"
    ):
        return random.random() < 0.30

    if intent == "A" and _COMFORT_RE.search(user_message):
        return random.random() < 0.50

    return False


def step_normalize_b_input(message: str, mission_name: str) -> tuple[str, bool]:
    """
    B 인텐트 메시지를 Qwen 전에 정규화.
    반환: (qwen에 넘길 메시지, should_clarify)
    should_clarify=True → D로 리다이렉트해서 확인 질문
    """
    # "성공 취소"의 성공/실패는 새 제출이 아니라 취소 대상 설명이다.
    if _CANCEL_NEGATION_RE.search(message):
        print(f"[Normalize] cancel-negation: {_short(message)!r} -> clarify")
        return message, True

    if _ADJUSTMENT_CANCEL_RE.search(message):
        normalized = "미션 변경 취소해줘"
        print(f"[Normalize] cancel-adjustment: {_short(message)!r} -> cancel")
        return normalized, False

    if _CANCEL_TARGET_RE.search(message):
        normalized = "미션 제출 취소해줘"
        print(f"[Normalize] cancel-target: {_short(message)!r} -> cancel")
        return normalized, False

    # 커맨드형 B → 정규화 불필요, 그대로 통과
    if _B_COMMAND_RE.search(message):
        return message, False

    # 행동+부정: 금지형 미션에서 성공일 수 있음 → 항상 D로 확인
    if _NEGATION_VERB_RE.search(message):
        print(f"[Normalize] clarify negation: {_short(message)!r}")
        return message, True

    if _FAIL_RE.search(message):
        normalized = f"오늘 미션 '{mission_name}' 실패했어요"
        print(f"[Normalize] fail: {_short(message)!r}")
        return normalized, False

    if _EXPLICIT_SUCCESS_RE.search(message):
        normalized = f"오늘 미션 '{mission_name}' 성공했어요"
        print(f"[Normalize] success: {_short(message)!r}")
        return normalized, False

    # 숫자+단위 보고는 미션 기준과 비교하지 않고 저장하면 오판 위험이 큼
    if _NUMERIC_REPORT_RE.search(message):
        print(f"[Normalize] clarify numeric: {_short(message)!r}")
        return message, True

    # 미션 키워드 겹침 없으면 정규화 스킵
    if not _mission_overlap(message, mission_name):
        return message, False

    if _SUCCESS_RE.search(message):
        normalized = f"오늘 미션 '{mission_name}' 성공했어요"
        print(f"[Normalize] success: {_short(message)!r}")
        return normalized, False

    # 과거형 동사 있는데 성공/실패 불명확 → 확인 질문
    if _PAST_VERB_RE.search(message):
        print(f"[Normalize] clarify past: {_short(message)!r}")
        return message, True

    return message, False


async def step_classify(message: str, mission_name: str = "") -> tuple[str, int]:
    """인텐트 분류. (intent, ms) 반환."""
    t0 = time.perf_counter()
    intent = await classify_intent(message, mission_name)
    ms = round((time.perf_counter() - t0) * 1000)
    print(f"[Intent] {intent} ({ms}ms)")
    return intent, ms


async def step_extract_functions(message: str) -> tuple[list[tuple[str, dict]], int]:
    """문장 분리 + Qwen 호출 + 중복 제거. (fn_calls, ms) 반환."""
    t0 = time.perf_counter()
    if _ADJUSTMENT_CANCEL_RE.search(message):
        ms = round((time.perf_counter() - t0) * 1000)
        fn_calls = [("cancel_mission_action", {"cancel_type": "adjustment"})]
        print(f"[Function] calls={_fn_list(fn_calls)} ({ms}ms, direct)")
        return fn_calls, ms

    if _CANCEL_TARGET_RE.search(message):
        ms = round((time.perf_counter() - t0) * 1000)
        fn_calls = [("cancel_mission_action", {"cancel_type": detect_cancel_type(message)})]
        print(f"[Function] calls={_fn_list(fn_calls)} ({ms}ms, direct)")
        return fn_calls, ms

    # 다중 의도 키워드 없으면 split 호출 자체를 스킵 (LLM 호출 1회 절감)
    # 명시적 접속사 또는 제출+조회 동시 존재 시 split 실행
    has_multi_intent = _MULTI_INTENT_RE.search(message) or (
        _SUBMIT_HINT_RE.search(message) and _QUERY_HINT_RE.search(message)
    )
    if has_multi_intent:
        parts = await split_multi_intent(message)
    else:
        parts = [message]
    fn_calls: list[tuple[str, dict]] = []
    seen: set[tuple] = set()
    for part in parts:
        calls, _ = await call_function(part)
        for c in calls:
            key = (c[0], tuple(sorted(c[1].items())))
            if key not in seen:
                fn_calls.append(c)
                seen.add(key)
    if (_ADJUSTMENT_CANCEL_RE.search(message) or _CANCEL_TARGET_RE.search(message)) and any(fn == "cancel_mission_action" for fn, _ in fn_calls):
        fn_calls = [("cancel_mission_action", {"cancel_type": detect_cancel_type(message)})]
        print("[Function] cancel-target forced to cancel only")
    ms = round((time.perf_counter() - t0) * 1000)
    fn_calls = normalize_function_calls(fn_calls)
    print(f"[Function] calls={_fn_list(fn_calls)} ({ms}ms, parts={len(parts)})")
    return fn_calls, ms


def step_execute(
    student_id: int,
    fn_calls: list[tuple[str, dict]],
    combo: str,
) -> tuple[ExecResults, list[tuple[str, dict]], dict | None, str]:
    """
    DB 실행. (exec_results, 남은 fn_calls, pending_submit_args, effective_combo) 반환.
    cancel은 실행 후 fn_calls에서 제거.
    reorder는 cancel 제거 후 적용.
    """
    fn_calls = normalize_function_calls(fn_calls)
    print(f"[DB] start student={student_id} combo={combo or '-'} calls={_fn_list(fn_calls)}")
    results = ExecResults()
    pending_submit_args: dict | None = None

    if combo == "conflict":
        print("[DB] skipped: conflict")
        return results, fn_calls, None, combo

    # db_branch는 cancel 실행 전에 "원래 직전 액션"을 검증해야 한다.
    if combo == "db_branch":
        name_set = frozenset(fn for fn, _ in fn_calls)
        expected = _DB_BRANCH_PAIRS.get(name_set)
        last_action = get_last_action_type(student_id)
        print(f"[DB] branch expected={expected} last={last_action}")
        if last_action != expected:
            print("[DB] branch mismatch -> conflict")
            return results, fn_calls, None, "conflict"

    # 1. cancel 분리 + 실행 + fn_calls에서 제거
    if any(fn == "cancel_mission_action" for fn, _ in fn_calls):
        cancel_args = next((args for fn, args in fn_calls if fn == "cancel_mission_action"), {})
        results.cancel = execute_cancel(student_id, cancel_args)
        fn_calls = [(fn, args) for fn, args in fn_calls if fn != "cancel_mission_action"]

    # 3. 남은 fn_calls를 콤보에 따라 처리 (sequential이면 reorder 적용)
    ordered = _reorder_sequential(fn_calls) if combo == "sequential" else fn_calls

    eq_submit = is_equivalency_submit(fn_calls)  # cancel 제거 후 판정
    for fn, args in ordered:
        if fn == "submit_mission_result":
            if eq_submit:
                pending_submit_args = args  # LLM 판단 후 실행
                print(f"[DB] submit deferred for equivalency")
            else:
                results.submit = execute_submit(student_id, args)
        elif fn == "request_mission_adjustment":
            results.adjustment = execute_adjustment(student_id, args)
        # equivalency, mission_info, history → DB write 없음

    print(f"[DB] done combo={combo or '-'} {_exec_label(results)}")
    return results, fn_calls, pending_submit_args, combo


def _build_function_hint(
    student_id: int | None,
    fn_calls: list[tuple[str, dict]],
    exec_results: ExecResults,
    combo: str | None,
) -> str:
    """B 인텐트 전용 힌트 문자열 생성. DB write 없음."""
    has_exec_hint = exec_results.cancel is not None
    if not fn_calls and not has_exec_hint:
        return ""

    if combo == "conflict":
        return build_conflict_prompt(fn_calls).strip()

    hints: list[str] = []

    if combo == "db_branch":
        # db_branch에서 직전 액션 불일치면 step_execute에서 충돌 전환됨.
        # 여기까지 왔으면 정상 순차 → cancel hint + 나머지 hint.
        if student_id is not None:
            if exec_results.cancel:
                hints.append(build_cancel_hint(exec_results.cancel))
            for fn, args in _reorder_sequential(fn_calls):
                hints.append(build_one_hint(student_id, fn, args, exec_results))
        else:
            for fn, args in fn_calls:
                hints.append(build_fn_hint(fn, args))
        return "\n\n".join(hints)

    # sequential / independent
    if student_id is not None:
        ordered = _reorder_sequential(fn_calls) if combo == "sequential" else fn_calls
        eq_submit = is_equivalency_submit(fn_calls)
        if exec_results.cancel:
            hints.append(build_cancel_hint(exec_results.cancel))
        for fn, args in ordered:
            if fn == "submit_mission_result" and eq_submit:
                continue  # submit 힌트 스킵 (LLM이 태그로 판정)
            hints.append(build_one_hint(student_id, fn, args, exec_results))
        if eq_submit:
            hints.append(EQUIVALENCY_SUBMIT_TAG_INSTRUCTION)
    else:
        for fn, args in fn_calls:
            hints.append(build_fn_hint(fn, args))

    return "\n\n".join(hints)


def _format_memory_context(student_id: int | None) -> str:
    if not student_id:
        return ""
    try:
        rows = get_relevant_user_memories(student_id)
    except Exception as e:
        print(f"[Memory] context load failed: {type(e).__name__}: {e}")
        return ""
    if not rows:
        return ""

    lines = []
    for row in rows:
        subject = row.get("subject", "")
        mtype = row.get("type", "")
        score = row.get("score", 0)
        count = row.get("count", 0)
        if not subject:
            continue
        if mtype == "preference":
            label = "좋아함" if (score or 0) > 0 else "싫어함"
        elif mtype == "difficulty":
            label = f"어려워함 ({count}회 언급)"
        elif mtype == "restriction":
            label = "못 함/금지"
        else:
            continue
        lines.append(f"- {subject}: {label}")

    if not lines:
        return ""
    return "\n".join(lines)


def step_build_hints(
    student_id: int | None,
    fn_calls: list[tuple[str, dict]],
    exec_results: ExecResults,
    combo: str | None,
    mission_title: str,
    rag_context: str,
    intent: str,
    is_greet: bool,
    clarify_hint_override: str = "",
    student_name: str = "",
    user_message: str = "",
) -> str:
    """시스템 프롬프트 조립. DB write 없음."""
    function_hint = ""
    if intent == "B":
        function_hint = _build_function_hint(student_id, fn_calls, exec_results, combo)
        print(f"[Prompt] function_hint={'Y' if function_hint else 'N'} combo={combo or '-'} len={len(function_hint)}")

    clarify_hint = ""
    if intent == "D":
        clarify_hint = clarify_hint_override or CLARIFY_HINT_DEFAULT

    name_call_allowed = _should_call_name(is_greet, intent, exec_results, user_message)
    if name_call_allowed:
        print(f"[Name] 이름 호출 허용: {student_name!r}")

    memory_context = "" if is_greet else _format_memory_context(student_id)
    if memory_context:
        print(f"[Memory] context injected lines={memory_context.count(chr(10)) + 1}")

    return build_system_prompt(
        intent=intent,
        mission=mission_title if intent == "A" and is_greet else "",
        hint=function_hint,
        rag_context=rag_context if intent == "C" and not is_greet else "",
        clarify_hint=clarify_hint,
        is_greeting=is_greet,
        student_name=student_name,
        name_call_allowed=name_call_allowed,
        memory_context=memory_context,
    )
