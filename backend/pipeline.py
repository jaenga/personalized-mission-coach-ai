"""
Pipeline — 통합 파이프라인 step 함수 + 멀티펑션 헬퍼.
import 방향: pipeline → executor, hint_builder (단방향)
"""
from __future__ import annotations

import time

from intent_router import classify_intent, split_multi_intent
from qwen_client import call_function
from rag import search_rag
from prompts import build_chat_system_prompt
from database import _kst_today, get_last_action_type, fetch_profile
from executor import (
    ExecResults,
    execute_submit, execute_adjustment, execute_cancel,
)
from hint_builder import (
    build_one_hint, build_conflict_prompt, build_fn_hint,
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


def classify_multi(fn_calls: list[tuple[str, dict]]) -> str:
    """멀티펑션 조합 분류. 반환값: 'conflict' | 'sequential' | 'db_branch' | 'independent'"""
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

async def step_classify(message: str) -> tuple[str, int]:
    """인텐트 분류. (intent, ms) 반환."""
    t0 = time.perf_counter()
    intent = await classify_intent(message)
    ms = round((time.perf_counter() - t0) * 1000)
    return intent, ms


async def step_extract_functions(message: str) -> tuple[list[tuple[str, dict]], int]:
    """문장 분리 + Qwen 호출 + 중복 제거. (fn_calls, ms) 반환."""
    t0 = time.perf_counter()
    parts = await split_multi_intent(message)
    fn_calls: list[tuple[str, dict]] = []
    seen: set[tuple] = set()
    for part in parts:
        calls, _ = call_function(part)
        for c in calls:
            key = (c[0], tuple(sorted(c[1].items())))
            if key not in seen:
                fn_calls.append(c)
                seen.add(key)
    ms = round((time.perf_counter() - t0) * 1000)
    return fn_calls, ms


def step_execute(
    student_id: int,
    fn_calls: list[tuple[str, dict]],
    combo: str,
) -> tuple[ExecResults, list[tuple[str, dict]], dict | None]:
    """
    DB 실행. (exec_results, 남은 fn_calls, pending_submit_args) 반환.
    cancel은 실행 후 fn_calls에서 제거.
    reorder는 cancel 제거 후 적용.
    """
    results = ExecResults()
    pending_submit_args: dict | None = None

    if combo == "conflict":
        return results, fn_calls, None

    # 1. cancel 분리 + 실행 + fn_calls에서 제거
    if any(fn == "cancel_mission_action" for fn, _ in fn_calls):
        results.cancel = execute_cancel(student_id)
        fn_calls = [(fn, args) for fn, args in fn_calls if fn != "cancel_mission_action"]

    # 2. db_branch: cancel 이미 실행됨. 직전 액션 일치 검증은 여기서.
    if combo == "db_branch":
        last_action = get_last_action_type(student_id)
        name_set = frozenset(fn for fn, _ in fn_calls)
        expected = _DB_BRANCH_PAIRS.get(name_set)
        if last_action != expected:
            # 직전 액션 불일치 → 충돌로 전환. cancel은 이미 실행됐으므로 결과는 유지.
            return results, fn_calls, None

    # 3. 남은 fn_calls를 콤보에 따라 처리 (sequential이면 reorder 적용)
    ordered = _reorder_sequential(fn_calls) if combo == "sequential" else fn_calls

    eq_submit = is_equivalency_submit(fn_calls)  # cancel 제거 후 판정
    for fn, args in ordered:
        if fn == "submit_mission_result":
            if eq_submit:
                pending_submit_args = args  # LLM 판단 후 실행
            else:
                results.submit = execute_submit(student_id, args)
        elif fn == "request_mission_adjustment":
            results.adjustment = execute_adjustment(student_id, args)
        # equivalency, mission_info, history → DB write 없음

    return results, fn_calls, pending_submit_args


def step_build_hints(
    student_id: int | None,
    fn_calls: list[tuple[str, dict]],
    exec_results: ExecResults,
    combo: str | None,
    mission_title: str,
    rag_context: str,
    intent: str,
    is_greet: bool,
) -> str:
    """시스템 프롬프트 조립. DB write 없음."""
    system_prompt = build_chat_system_prompt(
        mission_title,
        rag_context if not is_greet else "",
    )

    if intent == "D":
        system_prompt += "\n\n아이의 말이 무슨 뜻인지 불분명해. 판단하지 말고 딱 한 문장으로 다시 물어봐."

    if intent == "B" and fn_calls:
        if combo == "conflict":
            system_prompt += build_conflict_prompt(fn_calls)
        elif combo == "db_branch":
            # db_branch에서 직전 액션 불일치면 step_execute에서 충돌 전환됨
            # 여기까지 왔으면 정상 순차 → cancel hint + 나머지 hint
            if student_id is not None:
                hints = []
                if exec_results.cancel:
                    from hint_builder import build_cancel_hint
                    hints.append(build_cancel_hint(exec_results.cancel))
                ordered = _reorder_sequential(fn_calls)
                for fn, args in ordered:
                    hints.append(build_one_hint(student_id, fn, args, exec_results))
                system_prompt += "\n\n" + "\n\n".join(hints)
            else:
                for fn, args in fn_calls:
                    system_prompt += f"\n\n{build_fn_hint(fn, args)}"
        else:
            # sequential / independent
            if student_id is not None:
                ordered = _reorder_sequential(fn_calls) if combo == "sequential" else fn_calls
                eq_submit = is_equivalency_submit(fn_calls)
                hints = []
                for fn, args in ordered:
                    if fn == "submit_mission_result" and eq_submit:
                        continue  # submit 힌트 스킵 (LLM이 태그로 판정)
                    hints.append(build_one_hint(student_id, fn, args, exec_results))
                if eq_submit:
                    hints.append(EQUIVALENCY_SUBMIT_TAG_INSTRUCTION)
                system_prompt += "\n\n" + "\n\n".join(hints)
            else:
                for fn, args in fn_calls:
                    system_prompt += f"\n\n{build_fn_hint(fn, args)}"

    return system_prompt
