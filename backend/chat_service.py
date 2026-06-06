import asyncio
from dataclasses import asdict, is_dataclass
import functools
import json as _json
import random
import re
import time
import uuid

from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from database import (
    _kst_today,
    award_mission_xp,
    fetch_messages,
    fetch_profile,
    find_mission_by_user_text,
    find_similar_mission_by_user_text,
    get_pending_mission_suggestion,
    get_student_info_db,
    get_student_mission_db,
    has_checkin_today,
    mark_synced,
    resolve_pending_mission_suggestion,
    resolve_mission_ui_action,
    save_mission_change_log,
    save_mission_adjustment,
    save_chat_turn,
    save_message,
    save_pending_action,
    save_pending_mission_suggestion,
    update_mission_ui_action_payload,
    upsert_user_memory,
)
from activity_matcher import (
    extract_negative_activity_keys,
    is_direct_condition_change_request,
    is_negative_activity_request,
    match_activity_keys,
    select_replacement_mission,
)
from executor import AdjustmentStatus, CancelStatus, ExecResults, execute_adjustment, execute_submit
from equivalency_service import EquivalencyService
from equivalency_response_hint import build_fallback_reply
from health_safety_guard import (
    append_health_safety_suffix,
    detect_health_risk_signal,
)
from memory_service import extract_and_save_memory
from mission_context import build_mission_context
from mission_contextual_hint import MissionContextAnalysis, analyze_mission_context
from mission_meta import MISSION_META
from mission_ui_action_service import (
    create_generated_mission_suggestion,
    create_mission_change_reason_action,
    create_mission_dislike_confirm_action,
    create_replacement_mission_input_action,
    get_active_ui_action,
    rebuild_ui_action_payload,
)
from ollama_client import OLLAMA_MODEL, generate_chat_message, generate_chat_message_stream
from pending_service import PendingOutcome, classify_mission_change_escape, classify_mission_dislike, handle_pending_action
from pipeline import (
    classify_multi,
    is_equivalency_submit,
    step_build_hints,
    step_classify,
    step_execute,
    step_extract_functions,
)
from normalizer import normalize_b_input
from prompts import CLARIFY_HINT_DEFAULT, CLARIFY_HINT_MAP
from rag import search_rag
from routing_service import MissionRouter
from response_builder import ResponseMode, build_action_ack, build_conflict_ack
from schemas import ChatRequest
from sheets import cancel_mission_result, update_mission_result
from submit_validator import (
    build_submit_validation_response,
    contains_db_completion_phrase,
    should_promote_to_submit_path,
    validate_submit_candidate,
)

_FAKE_STREAM_CHARS = 4
_FAKE_STREAM_DELAY_SEC = 0.1
_CHAT_CONTEXT_MESSAGE_LIMIT = 10
_MISSION_ROUTER = MissionRouter()
_EQUIVALENCY_SERVICE = EquivalencyService()
_CLARIFY_TEMPLATE_REASONS = {
    "numeric",
    "numeric_no_count",
    "numeric_ambiguous",
    "negation_verb",
    "difficulty",
    "past_ambiguous",
}

_PAST_RESULT_TIME_RE = re.compile(
    r"어제|그제|그저께|엊그제|지난번|저번|예전|월요일(?:에)?|화요일(?:에)?|수요일(?:에)?|목요일(?:에)?|금요일(?:에)?|토요일(?:에)?|일요일(?:에)?"
)
_PAST_RESULT_HINT_RE = re.compile(
    r"성공|실패|완료|못\s*했|못했|안\s*했|안했|까먹|패스|안\s*먹|안먹|안\s*봤|안봤|안\s*탔|안탔"
    r"|먹었어(?:요)?|마셨어(?:요)?|봤어(?:요)?|못\s*마셨어(?:요)?|못마셨어(?:요)?"
    r"|\d+\s*(?:개|회|번|분|잔|컵|초|시간)"
)
_CURRENT_MISSION_ACTION_RE = re.compile(
    r"(?:오늘|지금|현재)\s*미션[\s\S]{0,16}(?:바꿔|바꾸|변경|교체)"
    r"|(?:방금|최근|아까)[\s\S]{0,16}(?:미션\s*)?(?:바꾸는\s*거|바꾸려던\s*거|바꾼\s*거|변경)[\s\S]{0,16}(?:취소|되돌|철회)"
)
_PAST_LOOKUP_QUERY_RE = re.compile(
    r"미션[\s\S]{0,12}(?:뭐였|뭐야|뭐였는지\s*알려|무엇|뭔지)"
    r"|미션[\s\S]{0,20}(?:얼마나|몇\s*번|몇\s*개|몇\s*회)[\s\S]{0,12}(?:했는지|했어|했어요|보여|알려)"
    r"|뭐\s*해야\s*했"
    r"|기록\s*(?:보여줘|조회|확인|알려줘)"
    r"|조회해줘|요약해줘"
    r"|(?:내가\s*)?뭐\s*했는지\s*확인"
    r"|성공했는지\s*확인|실패했는지\s*확인"
)

_MISSION_CHANGE_EXAMPLE_TEXT = "'실내 미션', '물 마시는 미션', '습관 키우기 미션', '가벼운 운동 미션', '화면 줄이기 미션'"


def _primary_mission_keyword(mission_title: str, mission_id: int | None = None) -> str:
    meta = MISSION_META.get(mission_id or -1)
    if meta and meta.target_kw:
        return meta.target_kw[0]
    title = (mission_title or "오늘 미션").strip()
    title = re.sub(r"\s*(?:하기|마시기|먹기|보기|걷기|씻기|양치하기)\s*$", "", title)
    return title or "오늘 미션"


def _object_phrase(word: str) -> str:
    if not word:
        return "오늘 미션을"
    last = ord(word[-1])
    if 0xAC00 <= last <= 0xD7A3 and (last - 0xAC00) % 28 == 0:
        return f"{word}를"
    return f"{word}을"


def _mission_quantity_question(mission_title: str, mission_id: int | None, reason: str) -> str:
    meta = MISSION_META.get(mission_id or -1)
    goal = meta.numeric if meta else None
    keyword = _primary_mission_keyword(mission_title, mission_id)
    if not goal:
        return "오늘 미션을 어떤 행동으로 얼마나 했는지 한 문장으로 말해줘!"

    unit = goal.unit
    target_phrase = _object_phrase(keyword)
    if unit in {"분", "초", "시간"}:
        ask = f"{target_phrase} 몇 {unit} 했는지"
        example = f"{keyword} {int(goal.threshold) if float(goal.threshold).is_integer() else goal.threshold}{unit} 했어"
    elif unit in {"회", "번"}:
        ask = f"{target_phrase} 몇 번 했는지"
        example = f"{keyword} {int(goal.threshold) if float(goal.threshold).is_integer() else goal.threshold}번 했어"
    elif unit in {"ml", "L", "리터"}:
        ask = f"{target_phrase} 얼마나 마셨는지"
        example = f"{keyword} 500ml 마셨어"
    elif unit in {"잔", "컵"}:
        ask = f"{target_phrase} 몇 잔 마셨는지"
        example = f"{keyword} 1잔 마셨어"
    elif unit == "바퀴":
        ask = f"{target_phrase} 몇 바퀴 했는지"
        example = f"{keyword} 두 바퀴 했어"
    elif unit == "봉지":
        ask = f"{target_phrase} 몇 봉지인지"
        example = f"{keyword} 1봉지 먹었어"
    elif unit in {"개", "입", "세트", "보", "걸음"}:
        ask = f"{target_phrase} 몇 {unit} 했는지"
        example = f"{keyword} {int(goal.threshold) if float(goal.threshold).is_integer() else goal.threshold}{unit} 했어"
    else:
        ask = f"{target_phrase} 얼마나 했는지"
        example = f"{keyword} {int(goal.threshold) if float(goal.threshold).is_integer() else goal.threshold}{unit} 했어"

    if reason == "numeric_ambiguous":
        return f"목표까지는 조금 부족해 보여. 오늘 미션 기준으로 {ask} 다시 말해줄래?"
    return f"오늘 미션 기준으로 {ask} 한 문장으로 말해줘. 예를 들면 '{example}'처럼 말하면 돼!"


def _clarify_template(reason: str, user_message: str, mission_title: str, mission_id: int | None = None) -> str | None:
    if reason not in _CLARIFY_TEMPLATE_REASONS:
        return None
    if reason == "past_ambiguous":
        if re.search(r"바꿔|바꾸|변경|교체", user_message or ""):
            return "지난 미션은 바로 처리할 수 없어~ 오늘 미션을 바꾸고 싶은 거라면 다시 말해줘!"
        if "어제" in (user_message or ""):
            return "어제의 미션은 기록할 수 없어~ 오늘 미션 성공이라면 다시 말해줘!"
        return "지난 미션은 기록할 수 없어~ 오늘 미션 성공이라면 다시 말해줘!"
    if reason == "numeric_no_count":
        return _mission_quantity_question(mission_title, mission_id, reason)
    if reason == "numeric_ambiguous":
        return _mission_quantity_question(mission_title, mission_id, reason)
    if reason == "numeric":
        if re.search(r"봤|봄|시청|유튜브|유튭|유투브|영상|쇼츠|릴스", user_message):
            return "무엇을 몇 분 봤는지 조금 더 자세히 알려줄 수 있을까?"
        return _mission_quantity_question(mission_title, mission_id, reason)
    if reason == "negation_verb":
        if "엘리베이터" in user_message or "엘레베이터" in user_message or "엘베" in user_message:
            return "엘리베이터는 안 탔구나! 잘했어 👏 그럼 계단을 이용하여 올라가기도 실천했을까? 😆"
        return "오늘 미션 기준으로 성공인지 같이 확인해볼까?"
    if reason == "difficulty":
        return "조금 어렵게 느껴졌구나. 쉬운 미션으로 바꿔줄까? 아니면 오늘 미션으로 계속 기록할래? 🧐"
    return None


def _past_result_clarify_response(user_message: str) -> str | None:
    text = user_message or ""
    if not (_PAST_RESULT_TIME_RE.search(text) and _PAST_RESULT_HINT_RE.search(text)):
        return None
    if _PAST_LOOKUP_QUERY_RE.search(text):
        return None
    if _CURRENT_MISSION_ACTION_RE.search(text):
        return None
    return _clarify_template("past_ambiguous", text, "") or "지난 미션은 기록할 수 없어~ 오늘 미션 성공이라면 다시 말해줘!"


def _json_default(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "value"):
        return value.value
    return str(value)


def _sse(payload: dict) -> str:
    return f"data: {_json.dumps(payload, ensure_ascii=False, default=_json_default)}\n\n"


def _done_sse(
    ui_action=None,
    debug: dict | None = None,
    *,
    mission_result_submitted: bool = False,
    mission_result_type: str | None = None,
    mission_id: int | None = None,
) -> str:
    payload = {
        "type": "done",
        "ui_action": ui_action,
        "mission_result_submitted": bool(mission_result_submitted),
    }
    if debug is not None:
        payload["debug"] = debug
    if mission_result_submitted:
        payload["mission_result_type"] = mission_result_type
        if mission_id is not None:
            payload["mission_id"] = mission_id
    return _sse(payload)


def _mission_review_trigger_kwargs(submit_result, mission_id: int | None) -> dict:
    if (
        submit_result
        and getattr(getattr(submit_result, "status", None), "value", None) == "saved"
        and submit_result.result_type in ("success", "fail")
    ):
        return {
            "mission_result_submitted": True,
            "mission_result_type": submit_result.result_type,
            "mission_id": mission_id,
        }
    return {}


def _chunk_template_response(text: str, chunk_size: int = _FAKE_STREAM_CHARS) -> list[str]:
    """서버 템플릿 응답을 프론트 스트리밍처럼 보이도록 작은 조각으로 나눈다."""
    if not text:
        return []
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


async def _fake_stream_template_response(text: str):
    for chunk in _chunk_template_response(text):
        yield _sse({"type": "token", "content": chunk})
        await asyncio.sleep(_FAKE_STREAM_DELAY_SEC)


def _needs_history_for_action(fn_calls: list[tuple[str, dict]]) -> bool:
    return False


_QUANTITY_FOLLOWUP_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(층|분|초|회|번|개|잔|컵|L|l|리터|ml|mL)"
)
_COMPLETED_FOLLOWUP_RE = re.compile(
    r"했|했어|했어요|완료|올라갔|올랐|걸었|마셨|먹었|봤|씻었|사용했|이용했"
)
_ASSISTANT_QUANTITY_PROMPT_RE = re.compile(
    r"몇\s*(층|분|초|회|번|개|잔|컵)|얼마나|어느\s*정도"
)
_ASSISTANT_MISSION_CONTEXT_RE = re.compile(
    r"미션|성공|인정|괜찮|돼|되|계단|엘리베이터"
)
# "그럼 성공이야?" / "그럼 실패야?"처럼 결과를 묻는 형태는 단순 보고가 아니라 동치 판정 대상이다.
_EQUIVALENCY_FOLLOWUP_HINT_RE = re.compile(
    r"그럼\s*(?:성공|실패|인정|돼|되|괜찮|안\s*돼|안돼)"
    r"|그러면\s*(?:성공|실패|인정|돼|되|괜찮|안\s*돼|안돼)"
    r"|성공이야\s*\?"
    r"|성공인가\s*\??"
    r"|실패야\s*\?"
    r"|실패인가\s*\??"
    r"|실패인\s*거야\s*\??"
    r"|인정이야\s*\??"
    r"|인정돼\s*\??"
    r"|안\s*돼\s*\?"
    r"|안돼\s*\?"
)


def _latest_assistant_message(history: list[dict] | None) -> str:
    for message in reversed(history or []):
        if message.get("role") == "assistant":
            return str(message.get("content") or "")
    return ""


def _looks_like_contextual_quantity_submit(user_message: str, history: list[dict] | None) -> bool:
    text = user_message or ""
    if not (_QUANTITY_FOLLOWUP_RE.search(text) and _COMPLETED_FOLLOWUP_RE.search(text)):
        return False
    # "그럼 성공이야?"처럼 결과를 묻는 형태는 동치 판정으로 보내야 한다.
    if _EQUIVALENCY_FOLLOWUP_HINT_RE.search(text):
        return False

    previous_assistant = _latest_assistant_message(history)
    if not previous_assistant:
        return False

    return bool(
        _ASSISTANT_QUANTITY_PROMPT_RE.search(previous_assistant)
        and _ASSISTANT_MISSION_CONTEXT_RE.search(previous_assistant)
    )


def _save_message_safe(
    session_id: str,
    role: str,
    content: str,
    detected_function: str | None = None,
) -> int:
    try:
        return save_message(session_id, role, content, detected_function)
    except Exception as e:
        print(f"[Chat] message save failed role={role} error={type(e).__name__}: {e}")
        return 0


def _save_chat_turn_safe(
    session_id: str,
    user_content: str | None,
    assistant_content: str,
    detected_function: str | None = None,
    request_id: str | None = None,
    assistant_debug: dict | None = None,
) -> tuple[int, int]:
    try:
        return save_chat_turn(
            session_id,
            user_content,
            assistant_content,
            detected_function,
            request_id=request_id,
            assistant_debug=assistant_debug,
        )
    except Exception as e:
        print(f"[Chat] chat turn save failed request_id={request_id or '-'} error={type(e).__name__}: {e}")
        return 0, 0


def _short(text: str | None, limit: int = 90) -> str:
    if not text:
        return ""
    one_line = " ".join(str(text).split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "..."


def _mission_context_analysis_debug(analysis: MissionContextAnalysis | None) -> dict | None:
    if not analysis:
        return None
    return {
        "relatedness": analysis.relatedness,
        "reason": analysis.reason,
        "matched_signals": analysis.matched_signals,
        "health_info_signal": analysis.health_info_signal,
        "response_hint_level": analysis.response_hint_level,
        "possible_b_kind": analysis.possible_b_kind,
    }


def _prepare_mission_context_analysis(
    user_message: str,
    mission_row: dict | None,
    mission_id: int | None,
    mission_title: str,
    is_greet: bool,
) -> MissionContextAnalysis | None:
    if is_greet or not user_message:
        return None
    context = build_mission_context(mission_row, mission_id=mission_id, mission_name=mission_title)
    if context.is_empty:
        return None
    analysis = analyze_mission_context(user_message, context)
    print(
        "[MissionContext] "
        f"relatedness={analysis.relatedness} "
        f"hint={analysis.response_hint_level} "
        f"health={'Y' if analysis.health_info_signal else 'N'} "
        f"kind={analysis.possible_b_kind or '-'} "
        f"signals={','.join(analysis.matched_signals) or '-'}"
    )
    return analysis


def _append_mission_context_response_hint(
    system_prompt: str,
    analysis: MissionContextAnalysis | None,
    intent: str,
) -> str:
    if not analysis or not analysis.response_hint:
        return system_prompt
    if analysis.response_hint_level == "none":
        return system_prompt
    if intent not in {"A", "C", "D"}:
        return system_prompt

    hint_block = "\n\n".join([
        "[오늘 미션 맥락 응답 힌트]",
        analysis.response_hint,
        (
            f"- relatedness: {analysis.relatedness}\n"
            f"- response_hint_level: {analysis.response_hint_level}\n"
            f"- health_info_signal: {'true' if analysis.health_info_signal else 'false'}"
        ),
    ])
    return f"{system_prompt}\n\n{hint_block}"


class _StreamTrace:
    def __init__(self, request_id: str, session_id: str, message: str) -> None:
        self.request_id = request_id
        self.session_id = session_id
        self.message = message
        self.started_at = time.perf_counter()

    def ms(self) -> int:
        return round((time.perf_counter() - self.started_at) * 1000)

    def log(self, event: str, **fields) -> None:
        detail = " ".join(
            f"{key}={value}"
            for key, value in fields.items()
            if value is not None
        )
        suffix = f" {detail}" if detail else ""
        print(f"[StreamTrace {self.request_id}] +{self.ms()}ms {event}{suffix}")


async def _trace_thread(trace: _StreamTrace, label: str, func, *args, **kwargs):
    started = time.perf_counter()
    trace.log(f"{label}.start")
    try:
        call = functools.partial(func, *args, **kwargs)
        return await run_in_threadpool(call)
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        trace.log(f"{label}.end", ms=elapsed_ms)


def _add_stream_bg_task(
    background_tasks: BackgroundTasks,
    trace: _StreamTrace,
    name: str,
    func,
    *args,
    **kwargs,
) -> None:
    trace.log("background.register", task=name)

    async def _runner():
        started = time.perf_counter()
        trace.log("background.start", task=name)
        try:
            if asyncio.iscoroutinefunction(func):
                await func(*args, **kwargs)
            else:
                call = functools.partial(func, *args, **kwargs)
                await run_in_threadpool(call)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            trace.log("background.end", task=name, ms=elapsed_ms)

    background_tasks.add_task(_runner)


def _fn_label(fn: str, args: dict | None = None) -> str:
    args = args or {}
    if fn == "submit_mission_result":
        return f"submit({args.get('result_type', '?')})"
    if fn == "request_mission_adjustment":
        return f"adjust({args.get('adjustment_type', '?')})"
    if fn == "cancel_mission_action":
        return "cancel"
    if fn == "get_mission_info":
        query_type = args.get("query_type", "?")
        target_date = args.get("target_date")
        if target_date:
            return f"mission_info({query_type}/{target_date})"
        return f"mission_info({query_type})"
    if fn == "get_user_history":
        return f"history({args.get('query_type', '?')})"
    if fn == "check_mission_equivalency":
        return f"equiv({args.get('equivalency_type', '?')})"
    return fn


def _fn_list(fn_calls: list[tuple[str, dict]]) -> str:
    return ", ".join(_fn_label(fn, args) for fn, args in fn_calls) or "-"


def _has_cancel_call(fn_calls: list[tuple[str, dict]]) -> bool:
    return any(fn == "cancel_mission_action" for fn, _ in fn_calls)


def should_force_mission_adjustment(message: str) -> bool:
    text = (message or "").replace(" ", "")
    if _MISSION_CHANGE_NEGATION_RE.search(text):
        return False
    if _CANCEL_NEGATION_RE.search(message or ""):
        return False
    if _CANCEL_REQUEST_RE.search(text):
        return False
    change_words = [
        "미션바꿔",
        "미션변경",
        "바꿔줘",
        "바꿔줄래",
        "변경해줘",
        "바꾸고싶어",
    ]
    return any(word in text for word in change_words)


_MISSION_CHANGE_NEGATION_RE = re.compile(r"바꾸지마|바꾸지말|변경하지마|변경하지말|바꾸면안|변경하면안")
_CANCEL_NEGATION_RE = re.compile(r"(?:취소|되돌|되돌려|철회)\s*하지\s*(?:마|말|말아|마라)")
_CANCEL_REQUEST_RE = re.compile(r"취소|되돌|되돌려|철회|원래대로")


def is_accepting_mission_suggestion(message: str) -> bool:
    text = (message or "").replace(" ", "").strip()

    reject_words = ["아니", "싫어", "말고", "다른", "취소"]
    if any(word in text for word in reject_words):
        return False

    accept_exact_words = [
        "응",
        "넹",
        "넵",
        "넴",
        "좋아",
        "그래",
        "ㅇㅇ",
        "네",
        "맞아",
        "그걸로",
        "그걸로해줘",
        "그미션으로해줘",
        "어좋아",
        "음좋아",
        "아좋아",
        "오좋아",
        "어응",
        "응좋아",
        "그래좋아",
        "엉",
        "엉좋아",
        "엉해줘",
        "응해줘",
        "좋아해줘",
        "그래해줘",
        "그거해줘",
        "그걸로바꿔줘",
        "어해봐",
        "어바꿔줘",
        "어그걸로",
        "어그걸로해줘",
        "응해봐",
        "그래해봐",
        "좋아해봐",
        "그걸로해봐",
        "그걸로바꿔",
        "넹좋아",
        "넵좋아",
        "넴좋아",
        "넹해줘",
        "넵해줘",
        "넴해줘",
        "넹그걸로",
        "넵그걸로",
        "넴그걸로",
        "넹바꿔줘",
        "넵바꿔줘",
        "넴바꿔줘",
    ]

    return text in accept_exact_words


def _is_rejecting_mission_suggestion(message: str | None) -> bool:
    text = (message or "").replace(" ", "").strip()
    if not text:
        return False
    reject_phrases = {
        "아니",
        "아니요",
        "아뇨",
        "ㄴ",
        "ㄴㄴ",
        "노",
        "no",
        "싫어",
        "안해",
        "안할래",
        "안바꿔",
        "안바꿀래",
        "바꾸지마",
        "변경하지마",
        "취소",
    }
    if text in reject_phrases:
        return True
    return bool(re.search(r"그게(?:지금|오늘)?미션|이미(?:그|그거|그미션|오늘미션)|지금미션이잖|오늘미션이잖", text))


def _is_explicit_fail_report(message: str | None) -> bool:
    text = message or ""
    compact = text.replace(" ", "")
    return bool(re.search(r"실패|못\s*했|못\s*함|못했|못함|안\s*했|안했|까먹|패스", text) or re.search(r"못했|못함|안했|까먹|패스", compact))


def _is_bare_replacement_acceptance(message: str | None) -> bool:
    text = (message or "").replace(" ", "").strip()
    if not text:
        return False
    accept_phrases = {
        "응",
        "넹",
        "넵",
        "넴",
        "좋아",
        "응좋아",
        "넹좋아",
        "넵좋아",
        "넴좋아",
        "그래",
        "그래좋아",
        "네",
        "ㅇㅇ",
        "오케이",
        "오키",
        "ok",
        "okay",
        "엉",
        "어좋아",
        "음좋아",
        "아좋아",
        "응맘에들어",
        "응마음에들어",
        "맘에들어",
        "마음에들어",
        "좋은데",
        "괜찮아",
    }
    return text in accept_phrases


_EQUIVALENCY_QUESTION_GUARD_RE = re.compile(
    r"대신|말고|없어서|없으면|같은\s*걸로|쳐줘|봐줘|인정"
    r"|(?:는\s*건|는건|건)\s*(?:돼|되|괜찮|인정)"
    r"|(?:하면|하면은|면)\s*(?:돼|되|괜찮|인정)"
    r"|(?:해도|먹어도|마셔도|봐도|걸어도|씻어도|타도|들어도|춤춰도|올라가도)\s*(?:미션으로\s*)?(?:돼|되|괜찮|인정)"
    r"|(?:집|학교|운동장|복도|밖|야외|교실|방|거실)에서.{0,12}(?:돼|되|괜찮|인정)"
)


def _looks_like_equivalency_question(message: str | None) -> bool:
    text = message or ""
    compact = text.replace(" ", "")
    if re.search(r"미션변경|바꿔줘|변경해줘|교체해줘|쉬운걸로|어려운걸로", compact):
        return False
    return bool(_EQUIVALENCY_QUESTION_GUARD_RE.search(text))


def _is_mission_dislike_try_today_acceptance(message: str | None) -> bool:
    text = (message or "").replace(" ", "").strip()
    if not text:
        return False
    if _is_bare_replacement_acceptance(message):
        return True
    return bool(re.search(r"도전|해볼게|해볼래|해볼께|해볼|해보자|할게|할께", text))


_CURRENT_MISSION_STATUS_RE = re.compile(
    r"(?:"
    r"미션.{0,8}(?:바뀐|바꾼).{0,6}(?:거야|거니|맞아|맞니|맞지|건가|거임)"
    r"|(?:바뀐|바꾼).{0,6}(?:거야|거니|맞아|맞니|맞지|건가|거임)"
    r"|(?:지금|현재|오늘|오늘의).{0,4}미션.{0,6}(?:뭐|무엇|뭔|알려|궁금)"
    r"|미션.{0,4}(?:뭐야|뭔데|뭔지|무엇)"
    r")"
)


def _is_current_mission_status_question(message: str | None) -> bool:
    text = _compact_ko(message)
    if not text:
        return False
    if "미션" in text and any(word in text for word in ("규칙", "룰", "기준", "방법", "조건", "몇개", "몇개까지", "하루몇개")):
        return False
    return bool(_CURRENT_MISSION_STATUS_RE.search(text))


def _current_mission_status_message(mission_row: dict | None, *, changed_question: bool = False) -> str:
    mission_name = (mission_row or {}).get("mission_name")
    if not mission_name:
        return "지금 오늘 미션을 아직 불러오지 못했어. 😣 잠시 뒤에 다시 확인해줘!"
    if changed_question:
        return f"아직 정식으로 바뀐 건 아니야~ 오늘 미션은 그대로 '{mission_name}'야!"
    return f"오늘 미션은 '{mission_name}'야! 같이 한번 도전해보자~ 💪"


def _is_mission_changed_question(message: str | None) -> bool:
    text = _compact_ko(message)
    return bool(text and re.search(r"(?:미션)?(?:바뀐|바꾼).{0,6}(?:거야|거니|맞아|맞니|맞지|건가|거임)", text))


def _should_use_current_mission_status_guard(message: str | None) -> bool:
    """Only guard questions about whether a mission actually changed."""
    return _is_mission_changed_question(message)


def _is_meaningless_mission_candidate(candidate: str | None) -> bool:
    if not candidate:
        return True

    compact = candidate.replace(" ", "").strip()
    if len(compact) < 2:
        return True

    generic_words = {
        "어", "으", "음", "아", "오",
        "다른", "다른거", "다른것", "새", "새로운",
        "그거", "응 그거", "그걸", "그걸로", "이거", "이걸", "이걸로",
    }

    return compact in generic_words


def extract_mission_candidate_text(user_message: str) -> str | None:
    """
    미션 변경 요청에서 원하는 미션 후보 텍스트를 추출한다.
    "으로", "로" 같은 전치사를 기준으로 텍스트를 분리한다.
    """
    if not user_message:
        return None

    text = user_message.strip()
    compact_text = text.replace(" ", "")

    generic_change_requests = {
        "다른미션으로바꿔줘",
        "새로운미션으로바꿔줘",
        "새미션으로바꿔줘",
        "다른걸로바꿔줘",
        "다른거로바꿔줘",
        "다른것으로바꿔줘",
    }
    if compact_text in generic_change_requests:
        return None

    # 전치사 기준으로 분리
    prepositions = ["으로 바꿔", "로 바꿔", "으로 변경", "로 변경", "으로", "로"]
    for prep in prepositions:
        if prep in text:
            parts = text.split(prep, 1)
            if parts[0].strip():
                candidate = parts[0].strip()
                # 불필요한 단어 제거
                remove_words = [
                    "그럼", "나", "좀", "해줘", "하는", "거야", "다른", "새로운", "새", "또", "다시", "한번", "미션",
                ]
                for word in remove_words:
                    candidate = candidate.replace(word, " ").strip()
                candidate = " ".join(candidate.split())
                if candidate and not _is_meaningless_mission_candidate(candidate):
                    return candidate
                if candidate and _is_meaningless_mission_candidate(candidate):
                    return None

    # 변경 키워드 기준으로도 시도
    change_keywords = ["미션바꿔", "미션변경", "바꿔줘", "바꿔줄래", "변경해줘", "바꾸고싶어"]
    for keyword in change_keywords:
        if keyword in text:
            parts = text.split(keyword, 1)
            candidate = ""
            if parts[0].strip():
                candidate = parts[0].strip()
            elif len(parts) > 1 and parts[1].strip():
                candidate = parts[1].strip()

            remove_words = [
                "그럼", "나", "좀", "해줘", "하는", "거야", "으로", "로", "다른", "새로운", "새", "또", "다시", "한번", "미션",
            ]
            for word in remove_words:
                candidate = candidate.replace(word, " ").strip()
            candidate = " ".join(candidate.split())
            if candidate and not _is_meaningless_mission_candidate(candidate):
                return candidate
            if candidate and _is_meaningless_mission_candidate(candidate):
                return None

    return None


def _response_mode_label(action_ack, eq_submit: bool) -> str:
    if action_ack:
        return action_ack.mode.value
    if eq_submit:
        return "equivalency"
    return "gemma"


_PENDING_RESPONSE_PROMPT = """너는 토미라는 토마토 캐릭터야.
아이와 친구처럼 반말로 말해.
2문장 이내로 짧게 말해.

[상황]
{hint}

자연스럽게 한마디 해줘.
"""

def _mission_dislike_hint(mission_name: str, mission_rule: str) -> str:
    return (
        f"아이가 오늘 미션 '{mission_name}'이 재미없다고 했어. "
        f"미션 규칙: {mission_rule} "
        "이 미션의 좋은 점이나 재밌는 점을 1문장으로 먼저 말해주고, "
        "그래도 오늘 딱 한 번만 도전해볼지 짧게 물어봐. 강요하지 말고 친구처럼 부드럽게."
    )


async def _save_dislike_memory(student_id: int, activity_key: str | None) -> dict | None:
    if not activity_key:
        return None
    try:
        return await run_in_threadpool(upsert_user_memory, student_id, activity_key, "preference", -1)
    except Exception as e:
        print(f"[Dislike] memory upsert failed: {type(e).__name__}: {e}")
    return None


async def _generate_pending_response(outcome: PendingOutcome) -> tuple[str, int]:
    if outcome.action_type == "natural_language_confirmation" and outcome.decision == "continue":
        return "좋아, 그럼 조금 더 해보고 와! 아직 기록은 안 할게.", 0
    if outcome.decision in {
        "ambiguous",
        "time_ambiguous",
        "time_not_today",
        "negation_ambiguous",
        "numeric_detail_ambiguous",
        "numeric_status_question",
        "clarify_cancelled",
    }:
        quoted = re.search(r"'([^']+)'", outcome.message_hint or "")
        if quoted:
            return quoted.group(1), 0
    if outcome.action_type == "natural_language_confirmation" and outcome.decision == "ambiguous":
        return "조금만 더 자세히 알려줘!", 0
    action_ack = build_action_ack(outcome.exec_results)
    if action_ack and action_ack.mode is ResponseMode.SERVER_ONLY:
        return action_ack.message, 0
    try:
        ai_message, llm_ms = await generate_chat_message(
            _PENDING_RESPONSE_PROMPT.format(hint=outcome.message_hint),
            [{"role": "user", "content": "이 상황에 맞게 짧게 답해줘."}],
        )
        if action_ack and action_ack.mode is ResponseMode.PREFIX_WITH_GEMMA:
            return f"{action_ack.message}\n{ai_message}".strip(), llm_ms
        return ai_message, llm_ms
    except Exception as e:
        print(f"[Pending] response generation failed: {type(e).__name__}: {e}")
        if action_ack:
            return action_ack.message, 0
        return "조금만 더 자세히 알려줘!", 0


def _pending_debug(outcome: PendingOutcome, llm_ms: int, ai_message: str) -> dict:
    return {
        "intent": "PENDING_ACTION",
        "pending_action_type": outcome.action_type,
        "pending_decision": outcome.decision,
        "pending_status": outcome.status,
        "violations": detect_violations(ai_message, ""),
        "system_prompt": _PENDING_RESPONSE_PROMPT.format(hint=outcome.message_hint),
        "history_turns": 0,
        "model": OLLAMA_MODEL,
        "timing": {"llm_ms": llm_ms},
        "rag_hits": {"chunks": 0, "faqs": 0},
    }


def _equivalency_clarify_question(judgment: dict | None) -> str:
    return _equivalency_fallback_text(judgment).strip() or _EQUIVALENCY_CLARIFY_FALLBACK


def _save_equivalency_clarify_pending(
    student_id: int | None,
    user_message: str,
    mission_row: dict | None,
    judgment: dict | None,
) -> None:
    if not student_id:
        return
    mission_row = mission_row or {}
    target_value = mission_row.get("target_value")
    if hasattr(target_value, "__float__"):
        target_value = float(target_value)
    try:
        pending = save_pending_action(
            student_id,
            "natural_language_confirmation",
            {
                "confirmation_type": "equivalency_clarify",
                "original_user_message": user_message,
                "clarify_reason": "equivalency_clarify",
                "clarify_question": _equivalency_clarify_question(judgment),
                "mission_id": mission_row.get("mission_id"),
                "mission_name": mission_row.get("mission_name"),
                "target_value": target_value,
                "target_unit": mission_row.get("target_unit"),
                "target_metric": mission_row.get("target_metric"),
            },
        )
        print(f"[Pending] equivalency_clarify created id={pending.get('id')}")
    except Exception as e:
        print(f"[Pending] equivalency_clarify create failed: {type(e).__name__}: {e}")


async def _handle_stream_active_pending_gate(
    student_id: int,
    session_id: str,
    user_message: str,
    background_tasks: BackgroundTasks,
    mission_id: int | None,
) -> dict | None:
    active_ui = await get_active_ui_action(student_id, session_id)
    if active_ui:
        action_type = active_ui.get("action_type")
        ui_action_payload = rebuild_ui_action_payload(active_ui)

        if action_type == "mission_dislike_confirm":
            accepted_result = await _handle_mission_dislike_confirm_acceptance(
                student_id,
                session_id,
                user_message,
                active_ui,
            )
            if accepted_result:
                return accepted_result

        if action_type in ("mission_change_reason", "mission_dislike_confirm", "mission_change_method"):
            escape = classify_mission_change_escape(user_message)
            if escape is not None:
                action_id = active_ui.get("action_id")
                exec_results = ExecResults()
                ui_resolved = False
                if escape == "keep":
                    await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
                    ui_resolved = True
                    response = "좋아, 지금 미션 그대로 할게!"
                elif escape == "success":
                    await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
                    ui_resolved = True
                    response = "오늘 미션을 어떻게 했는지 한 번만 더 알려줘!"
                else:
                    exec_results.submit = await run_in_threadpool(
                        execute_submit, student_id, {"result_type": escape}
                    )
                    action_ack = build_action_ack(exec_results)
                    response = action_ack.message if action_ack else "방금 기록을 저장하지 못했어! ⚠️"
                    if exec_results.submit.status.value == "saved":
                        await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
                        ui_resolved = True
                await run_in_threadpool(_save_message_safe, session_id, "user", user_message, action_type)
                await run_in_threadpool(_save_message_safe, session_id, "assistant", response)
                if exec_results.submit and exec_results.submit.status.value == "saved":
                    background_tasks.add_task(
                        _sync_sheet_bg, session_id, user_message, response,
                        exec_results.submit.result_type, exec_results.submit.checkin_id,
                    )
                return {
                    "response": response,
                    "ui_action": None if ui_resolved else ui_action_payload,
                    "debug": {"intent": "UI_ESCAPE", "escape": escape, "action_type": action_type},
                }
            if _wants_generated_replacement(user_message):
                result = await _resolve_generated_change_from_active_ui(
                    student_id,
                    session_id,
                    user_message,
                    active_ui,
                )
                await run_in_threadpool(_save_message_safe, session_id, "user", user_message, action_type)
                await run_in_threadpool(_save_message_safe, session_id, "assistant", result["response"])
                return result
            print(f"[PendingGate.ui] blocking chat, active action_type={action_type} action_id={active_ui.get('action_id')}")
            return {
                "response": "아래 선택지 중 하나를 골라줘!",
                "ui_action": ui_action_payload,
                "debug": {"intent": "UI_ACTION_GUARD", "ui_action_type": action_type},
            }

        if action_type == "awaiting_replacement_mission":
            escape = classify_mission_change_escape(user_message)
            if escape is not None:
                action_id = active_ui.get("action_id")
                exec_results = ExecResults()
                ui_resolved = False
                if escape == "keep":
                    await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
                    ui_resolved = True
                    response = "좋아, 지금 미션 그대로 할게!"
                elif escape == "success":
                    await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
                    ui_resolved = True
                    response = "오늘 미션을 어떻게 했는지 한 번만 더 알려줘!"
                else:
                    exec_results.submit = await run_in_threadpool(
                        execute_submit, student_id, {"result_type": escape}
                    )
                    action_ack = build_action_ack(exec_results)
                    response = action_ack.message if action_ack else "방금 기록을 저장하지 못했어! ⚠️"
                    if exec_results.submit.status.value == "saved":
                        await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
                        ui_resolved = True
                await run_in_threadpool(_save_message_safe, session_id, "user", user_message, action_type)
                await run_in_threadpool(_save_message_safe, session_id, "assistant", response)
                if exec_results.submit and exec_results.submit.status.value == "saved":
                    background_tasks.add_task(
                        _sync_sheet_bg, session_id, user_message, response,
                        exec_results.submit.result_type, exec_results.submit.checkin_id,
                    )
                return {
                    "response": response,
                    "ui_action": None if ui_resolved else ui_action_payload,
                    "debug": {"intent": "UI_ESCAPE", "escape": escape, "action_type": action_type},
                }
            result = await _handle_replacement_mission_input(student_id, session_id, user_message, active_ui)
            if not result:
                result = {
                    "response": f"어떤 미션으로 바꾸고 싶은지 조금 더 구체적으로 말해줘. 예를 들면 {_MISSION_CHANGE_EXAMPLE_TEXT}처럼 말하면 돼!",
                    "ui_action": rebuild_ui_action_payload(active_ui),
                    "debug": {
                        "intent": "REPLACEMENT_MISSION",
                        "method": "gate_fallback_no_result",
                    },
                }
            await run_in_threadpool(_save_message_safe, session_id, "user", user_message, "awaiting_replacement_mission")
            await run_in_threadpool(_save_message_safe, session_id, "assistant", result["response"])
            return result

        print(f"[PendingGate.ui] unknown active action_type={action_type}")
        return {
            "response": "이전 선택을 먼저 마무리해야 해. 아래 선택지나 안내에 맞춰 다시 말해줘!",
            "ui_action": ui_action_payload,
            "debug": {"intent": "UI_ACTION_GUARD", "ui_action_type": action_type, "unknown": True},
        }

    pending_started = time.perf_counter()
    pending_outcome = await handle_pending_action(student_id, user_message, session_id)
    if not pending_outcome:
        return None
    if pending_outcome.should_reroute:
        return None

    ai_message, call1_ms = await _generate_pending_response(pending_outcome)
    print(
        "[PendingGate] response "
        f"action={pending_outcome.action_type} status={pending_outcome.status} "
        f"response={_short(ai_message)!r}"
    )
    await run_in_threadpool(_save_message_safe, session_id, "user", user_message, pending_outcome.action_type)
    await run_in_threadpool(_save_message_safe, session_id, "assistant", ai_message)

    mission_status = None
    if pending_outcome.exec_results.submit and pending_outcome.exec_results.submit.status.value == "saved":
        mission_status = pending_outcome.exec_results.submit.result_type
        checkin_id = pending_outcome.exec_results.submit.checkin_id
        sync_user_message = pending_outcome.sync_user_message or user_message
        background_tasks.add_task(_sync_sheet_bg, session_id, sync_user_message, ai_message, mission_status, checkin_id)
    if (
        pending_outcome.exec_results.cancel
        and pending_outcome.exec_results.cancel.status is CancelStatus.CANCELLED_SUBMIT
    ):
        background_tasks.add_task(_cancel_sheet_bg, student_id, _kst_today())

    debug_payload = _pending_debug(pending_outcome, call1_ms, ai_message)
    debug_payload["timing"]["total_ms"] = round((time.perf_counter() - pending_started) * 1000)
    return {
        "response": ai_message,
        "ui_action": pending_outcome.ui_action,
        "debug": debug_payload,
        "review_kwargs": _mission_review_trigger_kwargs(
            pending_outcome.exec_results.submit if pending_outcome.exec_results else None,
            mission_id,
        ),
    }


async def _generate_hint_response(hint: str) -> tuple[str, int]:
    try:
        return await generate_chat_message(
            _PENDING_RESPONSE_PROMPT.format(hint=hint),
            [{"role": "user", "content": "이 상황에 맞게 짧게 답해줘."}],
        )
    except Exception as e:
        print(f"[HintResponse] generation failed: {type(e).__name__}: {e}")
        return "그렇구나. 그럼 오늘 한 번만 해볼지 같이 정해보자!", 0


def _hint_debug(intent: str, hint: str, llm_ms: int, ai_message: str) -> dict:
    return {
        "intent": intent,
        "violations": detect_violations(ai_message, ""),
        "system_prompt": _PENDING_RESPONSE_PROMPT.format(hint=hint),
        "history_turns": 0,
        "model": OLLAMA_MODEL,
        "timing": {"llm_ms": llm_ms},
        "rag_hits": {"chunks": 0, "faqs": 0},
    }


_NATURAL_LANGUAGE_CONFIRMATION_REASONS = frozenset({
    "clarify_negation",
    "numeric_ambiguous",
    "difficulty",
    "clarify_partial",
    "clarify_time_ambiguous",
})


def _save_natural_language_confirmation_pending(
    student_id: int | None,
    user_message: str,
    clarify_reason: str,
    mission_id: int | None = None,
    mission_name: str = "",
) -> None:
    """자연어 확인 질문을 보낸 턴이면 다음 턴 답변을 저장된 함수 실행과 연결한다."""
    if not student_id or clarify_reason not in _NATURAL_LANGUAGE_CONFIRMATION_REASONS:
        return
    if clarify_reason == "numeric_ambiguous":
        payload = {
            "confirmation_type": "numeric_partial_confirmation",
            "choices": {
                "record_now": {
                    "fn": "submit_mission_result",
                    "args": {"result_type": "fail"},
                },
                "continue": {
                    "fn": "noop",
                },
            },
            "original_user_message": user_message,
            "clarify_reason": clarify_reason,
            "mission_id": mission_id,
            "mission_name": mission_name,
        }
    elif clarify_reason == "difficulty":
        payload = {
            "confirmation_type": "partial_progress_difficulty",
            "choices": {
                "record_current": {
                    "fn": "submit_mission_result",
                    "args": {"result_type": "fail"},
                },
                "change_easier": {
                    "fn": "request_mission_adjustment",
                    "args": {"adjustment_type": "easier"},
                },
            },
            "original_user_message": user_message,
            "clarify_reason": "partial_progress_difficulty",
            "mission_id": mission_id,
            "mission_name": mission_name,
        }
    else:
        payload = {
            "confirmation_type": "submit_mission_result",
            "on_yes": {
                "fn": "submit_mission_result",
                "args": {"result_type": "success"},
            },
            "on_no": {
                "fn": "submit_mission_result",
                "args": {"result_type": "fail"},
            },
            "original_user_message": user_message,
            "clarify_reason": clarify_reason,
            "mission_id": mission_id,
            "mission_name": mission_name,
        }
    try:
        pending = save_pending_action(
            student_id,
            "natural_language_confirmation",
            payload,
        )
        print(f"[Pending] natural_language_confirmation created id={pending.get('id')} reason={clarify_reason}")
    except Exception as e:
        print(f"[Pending] natural_language_confirmation create failed: {type(e).__name__}: {e}")


def _strip_leading_ack(text: str, ack_message: str) -> str:
    """Gemma가 서버 확정 안내문을 반복하면 앞부분에서 제거한다."""
    if not text or not ack_message:
        return text

    stripped = text.lstrip()
    candidates = {
        ack_message,
        ack_message.rstrip(" ✅❌🔄↩️⚠️"),
    }
    for candidate in sorted(candidates, key=len, reverse=True):
        if candidate and stripped.startswith(candidate):
            stripped = stripped[len(candidate):].lstrip()
            if stripped.startswith(("\n", ".", "!", "！")):
                stripped = stripped[1:].lstrip()
            print(f"[Response] stripped repeated prefix={_short(candidate)!r}")
            return stripped
    return text


def _gemma_user_message(original_message: str, exec_results: ExecResults | None) -> str:
    """DB 실행 후 Gemma가 원문 요청보다 실행 결과에 집중하도록 user message를 보정한다."""
    if exec_results and exec_results.adjustment and exec_results.adjustment.status is AdjustmentStatus.CHANGED:
        result = exec_results.adjustment
        return "\n".join([
            "방금 미션 변경이 완료됐어.",
            "이전 미션에 대해 짧게 받아주고, 새 미션을 앞으로 할 미션으로 설명해줘.",
            f"이전 미션: {result.old_mission_name or ''}",
            f"새 미션: {result.new_mission_name or ''}",
        ])
    return original_message


def _prepare_mission_change_guard(student_id: int | None, user_message: str, fn_calls: list[tuple[str, dict]]) -> tuple[dict | None, list[tuple[str, dict]]]:
    guard_result = None
    if not student_id or not user_message:
        return guard_result, fn_calls
    if _has_cancel_call(fn_calls):
        return guard_result, fn_calls

    pending = get_pending_mission_suggestion(student_id)
    if pending:
        current_mission = get_student_mission_db(student_id)
        if _is_explicit_fail_report(user_message):
            resolve_pending_mission_suggestion(pending["suggestion_id"], status="cancelled")
            fn_calls = [call for call in fn_calls if call[0] != "request_mission_adjustment"]
            return guard_result, [("submit_mission_result", {"result_type": "fail"})]
        if current_mission and pending["suggested_mission_id"] == current_mission.get("mission_id"):
            resolve_pending_mission_suggestion(pending["suggestion_id"], status="cancelled")
            guard_result = {
                "type": "suggestion_cancelled_same_mission",
                "mission_id": pending["suggested_mission_id"],
                "mission_name": pending["mission_name"],
                "message": f'"{pending["mission_name"]}"는 이미 오늘 미션이야. 미션은 바꾸지 않을게.',
            }
            return guard_result, []
        if _is_rejecting_mission_suggestion(user_message):
            resolve_pending_mission_suggestion(pending["suggestion_id"], status="rejected")
            guard_result = {
                "type": "suggestion_rejected",
                "mission_id": pending["suggested_mission_id"],
                "mission_name": pending["mission_name"],
                "message": "알겠어, 미션은 바꾸지 않을게.",
            }
            return guard_result, []
        if is_accepting_mission_suggestion(user_message):
            if current_mission:
                if has_checkin_today(student_id):
                    guard_result = {
                        "type": "already_submitted",
                        "message": "오늘 미션 결과를 이미 저장해서 지금은 미션을 바꿀 수 없어. 바꾸고 싶으면 먼저 방금 기록을 취소해줘! 🙂",
                    }
                    return guard_result, []
                save_mission_adjustment(
                    student_id=student_id,
                    old_mission_id=current_mission["mission_id"],
                    new_mission_id=pending["suggested_mission_id"],
                )
                resolve_pending_mission_suggestion(pending["suggestion_id"], status="accepted")
                guard_result = {
                    "type": "adjustment_saved",
                    "mission_id": pending["suggested_mission_id"],
                    "mission_name": pending["mission_name"],
                    "message": f'좋아! 오늘 미션을 "{pending["mission_name"]}"로 바꿨어.',
                }
                return guard_result, []
        guard_result = {
            "type": "suggestion_pending",
            "mission_id": pending["suggested_mission_id"],
            "mission_name": pending["mission_name"],
            "message": f'"{pending["mission_name"]}"로 바꿀까? 바꾸려면 "응"이나 "네"라고 말해줘!',
        }
        return guard_result, []

    if should_force_mission_adjustment(user_message):
        print("[Guard] force request_mission_adjustment because user asked to change mission")
        fn_calls = [call for call in fn_calls if call[0] != "submit_mission_result"]

        # 후보 텍스트 추출
        candidate_text = extract_mission_candidate_text(user_message)
        if not candidate_text:
            # 후보 텍스트 없음: generic 변경으로
            fn_calls = [
                ("request_mission_adjustment", {
                    "adjustment_type": "change",
                    "requested_text": user_message,
                })
            ]
            return guard_result, fn_calls

        # 후보 텍스트 있음: 정확 매칭 시도
        exact_mission = find_mission_by_user_text(candidate_text)
        if exact_mission:
            current_mission = get_student_mission_db(student_id)
            if current_mission:
                if has_checkin_today(student_id):
                    guard_result = {
                        "type": "already_submitted",
                        "message": "오늘 미션 결과를 이미 저장해서 지금은 미션을 바꿀 수 없어. 바꾸고 싶으면 먼저 방금 기록을 취소해줘! 🙂",
                    }
                    return guard_result, []
                save_mission_adjustment(
                    student_id=student_id,
                    old_mission_id=current_mission["mission_id"],
                    new_mission_id=exact_mission["mission_id"],
                )
                guard_result = {
                    "type": "adjustment_saved",
                    "mission_id": exact_mission["mission_id"],
                    "mission_name": exact_mission["mission_name"],
                    "message": f'좋아! 오늘 미션을 "{exact_mission["mission_name"]}"로 바꿨어.',
                }
                return guard_result, []

        # 정확 미션 없음: 유사 매칭 시도
        similar_mission = find_similar_mission_by_user_text(candidate_text)
        if similar_mission:
            save_pending_mission_suggestion(
                student_id=student_id,
                suggested_mission_id=similar_mission["mission_id"],
                source_text=user_message,
            )
            guard_result = {
                "type": "suggestion",
                "mission_id": similar_mission["mission_id"],
                "mission_name": similar_mission["mission_name"],
                "message": f'비슷한 미션으로 "{similar_mission["mission_name"]}"가 있어! 이 미션으로 바꿔볼까?',
            }
            return guard_result, []

        # 유사 미션도 없음: 찾지 못했음 안내
        guard_result = {
            "type": "not_found",
            "message": f'아직 "{candidate_text}"에 맞는 미션은 찾지 못했어. 다른 미션으로 바꾸고 싶으면 "다른 미션으로 바꿔줘"라고 말해줘! 😉',
        }
        return guard_result, []

    return guard_result, fn_calls


# ── 가드: AI/캐릭터 정체성 질문 전처리 ────────────────────────────────────────
_AI_IDENTITY_QUESTION_RE = re.compile(
    r"("
    r"(?:너|넌|토미|너\s*혹시|너\s*사실|너\s*진짜)?[\s\S]{0,8}"
    r"(?:AI|ai|인공지능|챗봇|챗지피티|ChatGPT|GPT|gpt|Gemma|gemma|젬마\s*4?|젬마|구글|딥마인드|"
    r"봇|로봇|프로그램|모델|언어\s*모델|대규모\s*언어\s*모델|LLM|llm)"
    r"[\s\S]{0,8}(?:야|이야|임|이냐|냐|지|맞지|잖아|아니야|아니지|맞아|인가|이니|아님)?"
    r"|"
    r"(?:너|넌|토미)?[\s\S]{0,8}"
    r"(?:사람|인간|생명|살아있|현실에 있|실제)"
    r"[\s\S]{0,8}(?:야|이야|임|이냐|냐|지|맞지|잖아|아니야|아니지|맞아|인가|이니|아님)?"
    r"|"
    r"(?:너|넌|너는|토미|토마토)[\s\S]{0,8}"
    r"(?:누구|뭐야|정체|이름)"
    r"|"
    r"(?:토미|토마토)[\s\S]{0,8}"
    r"(?:AI|ai|인공지능|챗봇|Gemma|gemma|젬마\s*4?|젬마|구글|딥마인드|사람|진짜|정체|뭐야|누구)"
    r"|"
    r"(?:토미|토마토)[\s\S]{0,12}"
    r"(?:말해|살아|몸|왜|어떻게)"
    r")",
    re.IGNORECASE,
)
_AI_IDENTITY_RESPONSES = [
    "나는 토미야! 같이 건강 습관 만들어가는 토마토 친구야 🍅 오늘 미션 얘기해볼까?",
    "나는 토미야! 건강 습관을 같이 만들어가는 친구야 🍅 오늘 미션도 같이 해보자!",
    "토미라고 불러줘! 네 건강 습관을 옆에서 응원하는 토마토 친구야 🍅",
    "나는 토미야! 너랑 미션도 이야기하고 건강 습관도 같이 챙기는 친구야 🍅",
    "나는 토미! 오늘도 네 건강 습관을 같이 응원해주는 친구야 🍅",
]


_FIXED_FAQ_RESPONSES = {
    "토미가 누구야": (
        "나는 건강한 생활을 유지해서 잘 익은 빨간 토마토, 토미야! 🍅\n"
        "토미는 빨간 토마토라서 건강한 습관의 중요성을 잘 알고 있어!\n"
        "앞으로 너의 건강 습관을 같이 응원해줄게!\n"
        "토미랑 함께 건강한 습관을 하나씩 길러보자! 😊"
    ),
    "뽑기권이 뭐야": (
        "뽑기권은 하트나 경험치를 얻을 수 있는 특별한 티켓이야! 🎟️\n\n"
        "뽑기권을 사용하면 하트, 경험치를 랜덤으로 얻을 수 있어!\n"
        "뽑기권은 출석체크를 하면 1개, 퀴즈를 끝까지 풀면 1개, 오늘의 미션을 성공하면 1개 받을 수 있어\n\n"
        "뽑기를 해보고 싶다면 홈 화면에서 티켓 모양 버튼을 찾아봐! ✨"
    ),
    "하트가 뭐야": (
        "하트는 ‘토미랑 달리기’ 게임에 들어갈 때 필요한 입장권이야! ❤️\n\n"
        "게임을 한 번 할 때마다 하트 1개가 필요해.\n"
        "하트는 뽑기권으로 뽑을 수 있으니까, 뽑기권을 열심히 모아서 하트도 얻어봐!\n\n"
        "하트를 모으면 토미랑 더 많이 달릴 수 있어! 🏃"
    ),
    "보상은 어떻게 얻어": (
        "보상은 건강한 습관을 실천하면 받을 수 있어! 🎁\n\n"
        "미션을 성공하면 경험치와 뽑기권 1개를 받을 수 있고, 퀴즈를 모두 맞히면 뽑기권 1개, 출석을 해도 뽑기권 1개를 받을 수 있어.\n\n"
        "열심히 모아서 건강한 토마토가 되자! 🍅"
    ),
    "퀴즈는 어떻게 풀어": (
        "퀴즈를 풀고 싶다면 아래 하단 바에 있는 [퀴즈: 하단바에 맞게 수정] 버튼을 눌러봐! 📚\n\n"
        "퀴즈를 풀기 전에는 토미가 알려주는 건강 교육을 먼저 들어야 해.\n"
        "교육을 끝까지 들어야 퀴즈가 열리니까 꼭 기억해줘!\n\n"
        "[교육-퀴즈]는 하루에 2개까지 할 수 있고, 퀴즈를 모두 맞히면 뽑기권 1개도 받을 수 있어.\n\n"
        "건강 지식도 배우고, 보상도 받아보자~ ✨"
    ),
}


def _fixed_faq_response(message: str | None) -> str | None:
    compact = re.sub(r"[\s?!?.。~]+", "", message or "")
    for question, response in _FIXED_FAQ_RESPONSES.items():
        if compact == re.sub(r"[\s?!?.。~]+", "", question):
            return response
    return None


def _identity_response() -> str:
    return random.choice(_AI_IDENTITY_RESPONSES)


_AI_OUTPUT_RE = re.compile(
    r"인공지능|AI\s*(?:야|이야|이에요|입니다|예요|모델)|챗봇|언어\s*모델|대규모\s*언어\s*모델|\bLLM\b|\bGPT\b|\bGemma\b|(?<!\w)gemma(?!\w)|젬마|딥마인드",
    re.IGNORECASE,
)
_OFFTOPIC_RE = re.compile(
    r"주식|코인|비트코인|이더리움|암호화폐|선물\s*거래",
    re.IGNORECASE,
)
_OFFTOPIC_RESPONSE = "그 얘기도 재밌지만, 나는 건강 습관이랑 오늘 미션 얘기를 더 잘 도와줄 수 있어 🍅 오늘 미션 이야기 해볼까?"
_VOLUME_AMOUNT_RE = re.compile(
    r"(\d+(?:\.\d+)?|반|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|일)\s*"
    r"(리터|L|l|ml|mL|밀리리터|밀리)"
)
_VOLUME_CUP_QUESTION_RE = re.compile(r"몇\s*(?:컵|잔)|컵(?:으로|으론|으로는)|잔(?:으로|으론|으로는)")
_VOLUME_ML_QUESTION_RE = re.compile(r"몇\s*(?:ml|mL|밀리|밀리리터)")
_VOLUME_CUP_AMOUNT_RE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?|반|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|일)\s*(컵|잔)"
)
_VOLUME_CONFIRMATION_QUESTION_RE = re.compile(
    r"그럼|인(?:가|지)|건(?:가|지)|거(?:야|지)|맞(?:아|나|지)|되(?:나|는|지)|돼|마시면|먹으면|성공"
)
_KOREAN_NUMBER_VALUE = {
    "반": 0.5,
    "한": 1,
    "일": 1,
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


def _format_decimal(value: float, digits: int = 1) -> str:
    rounded = round(float(value), digits)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.{digits}f}".rstrip("0").rstrip(".")


def _parse_volume_amount(raw: str, unit: str) -> tuple[float, str]:
    value = _KOREAN_NUMBER_VALUE.get(raw)
    if value is None:
        value = float(raw)
    normalized_unit = "ml" if unit in {"ml", "mL", "밀리", "밀리리터"} else "리터"
    ml_value = value if normalized_unit == "ml" else value * 1000
    source_label = f"{_format_decimal(value)}{normalized_unit}"
    return ml_value, source_label


def _fixed_volume_conversion_response(message: str) -> str | None:
    text = message or ""
    cup_amount_match = _VOLUME_CUP_AMOUNT_RE.search(text)
    if cup_amount_match and _VOLUME_CONFIRMATION_QUESTION_RE.search(text.replace(" ", "")):
        return "응, 1리터 목표라면 보통 200ml 컵 기준으로 5컵이야. 종이컵처럼 180ml 정도면 약 5.6컵이고, 기록은 아직 하지 않을게."

    amount_match = _VOLUME_AMOUNT_RE.search(text)
    if not amount_match:
        return None
    asks_cups = bool(_VOLUME_CUP_QUESTION_RE.search(text))
    asks_ml = bool(_VOLUME_ML_QUESTION_RE.search(text))
    if not asks_cups and not asks_ml:
        return None

    ml_value, source_label = _parse_volume_amount(amount_match.group(1), amount_match.group(2))
    ml_label = _format_decimal(ml_value)
    if asks_cups:
        standard_cups = _format_decimal(ml_value / 200)
        paper_cups = _format_decimal(ml_value / 180)
        return (
            f"{source_label}는 {ml_label}ml야. "
            f"보통 컵 1컵을 200ml로 보면 {standard_cups}컵이고, "
            f"종이컵은 약 180ml라서 약 {paper_cups}컵이야."
        )
    return f"{source_label}는 {ml_label}ml야."


def _filter_ai_response(text: str) -> str:
    """응답 중 AI 정체성 노출 문장을 토미 자기소개 문장으로 교체."""
    if not _AI_OUTPUT_RE.search(text):
        return text
    sentences = re.split(r"(?<=[.!?~\n])\s*", text)
    filtered: list[str] = []
    replaced = False
    for s in sentences:
        if s.strip() and _AI_OUTPUT_RE.search(s):
            if not replaced:
                filtered.append("나는 토미야! 같이 건강 습관 만들어가는 토마토 친구야 🍅")
                replaced = True
        else:
            filtered.append(s)
    result = " ".join(s for s in filtered if s.strip())
    if replaced:
        print("[Guard] AI output filtered")
    return result or text


def _exec_results_db_changed(exec_results: ExecResults | None) -> bool:
    if not exec_results:
        return False
    return any(
        bool(getattr(result, "db_changed", False))
        for result in (exec_results.submit, exec_results.adjustment, exec_results.cancel)
        if result is not None
    )


_DB_COMPLETION_FALLBACK = "앗, 지금 기록이 잘 안 됐어. 다시 말해줄 수 있어?"


def _unsafe_gemma_db_completion(gemma_text: str, exec_results: ExecResults | None) -> bool:
    """Gemma 생성분만 검사한다. 서버 ACK가 섞인 최종 응답에는 쓰지 않는다."""
    return bool(gemma_text and not _exec_results_db_changed(exec_results) and contains_db_completion_phrase(gemma_text))


_SUCCESS_SUBMIT_CONFLICT_RE = re.compile(
    r"실패(?:로|야|했|기록|저장|완료)"
    r"|기록(?:이\s*)?(?:안|안\s*됐|안됐|되지\s*않|아직)"
    r"|저장(?:이\s*)?(?:안|안\s*됐|안됐|되지\s*않|아직)"
    r"|시스템에\s*아직\s*기록"
    r"|못\s*했|못했|안\s*했|안했"
)
_FAIL_SUBMIT_CONFLICT_RE = re.compile(
    r"성공(?:이야|이네|했|으로|기록|저장|완료)"
    r"|인정(?:돼|이야|할\s*수|될\s*수)"
    r"|잘\s*했|잘했|대단|멋지|훌륭"
)
_CONSTRAINED_FAIL_PRAISE_RE = re.compile(
    r"잘\s*했|잘했|대단|멋지|훌륭|기특|칭찬"
    r"|꾸준(?:히)?"
    r"|좋은\s*(?:시도|선택|습관|노력)"
    r"|(?:많이|오래|열심히|계속)\s*(?:봤|보았|먹었|먹음|했|했다|사용|게임)[\s\S]{0,16}(?:좋|멋|대단|잘)"
    r"|(?:\d+(?:\.\d+)?|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(?:분|시간|개|봉지|번|회)?이나\s*(?:봤|보았|먹었|했|했다|사용|게임)"
)
_ADJUSTMENT_CONFLICT_RE = re.compile(
    r"바꿀까|바꿔볼까"
    r"|아직[\s\S]{0,12}(?:안|아니|않)[\s\S]{0,12}바뀐"
    r"|바뀌지\s*않|변경(?:이\s*)?(?:안|안\s*됐|안됐|되지\s*않)"
    r"|미션(?:은|이)?\s*그대로"
)
_CANCEL_CONFLICT_RE = re.compile(
    r"취소할[\s\S]{0,12}없"
    r"|취소(?:가|는|를|이)?\s*(?:안|안\s*됐|안됐|되지\s*않)"
    r"|되돌릴[\s\S]{0,12}없"
)


def _failure_tone_type(mission_id: int | None = None, mission_metadata: dict | None = None) -> str:
    metric = str((mission_metadata or {}).get("target_metric") or "").strip()
    if metric == "max_duration":
        return "limit"
    if mission_id == 159:
        return "order"
    meta = MISSION_META.get(mission_id or -1)
    if not meta:
        return "perform"
    if meta.type in {"limit", "prohibit", "substitute"}:
        return meta.type
    return "perform"


def _needs_strict_failure_tone(mission_id: int | None = None, mission_metadata: dict | None = None) -> bool:
    return _failure_tone_type(mission_id, mission_metadata) in {"limit", "prohibit", "substitute", "order"}


def _failure_tone_instruction(
    exec_results: ExecResults | None,
    mission_id: int | None = None,
    mission_metadata: dict | None = None,
) -> str:
    submit = exec_results.submit if exec_results else None
    if not (submit and submit.db_changed and submit.result_type == "fail"):
        return ""
    tone_type = _failure_tone_type(mission_id, mission_metadata)
    if tone_type in {"limit", "prohibit", "substitute", "order"}:
        return "\n".join([
            "",
            "[실패 응답 톤 규칙]",
            f"- 오늘 미션 유형은 {tone_type}형이다.",
            "- 실패 행동 자체를 칭찬하지 않는다.",
            "- '잘했어', '대단해', '멋져', '꾸준히 했네', '좋은 선택이야'처럼 실패 행동을 좋게 평가하는 표현을 쓰지 않는다.",
            "- 대신 '솔직히 말해줘서 고마워', '오늘은 목표와 달랐네', '다음엔 조금 줄여보자/지켜보자'처럼 짧고 담백하게 말한다.",
        ])
    return "\n".join([
        "",
        "[실패 응답 톤 규칙]",
        "- 오늘 미션 유형은 수행형이다.",
        "- 목표 미달 사실은 유지하되, 아이가 일부라도 시도한 행동은 짧게 인정해도 된다.",
        "- 예: '5분이라도 해본 건 좋아. 오늘은 실패로 기록됐지만 다음엔 목표까지 가보자!'",
    ])


def _db_action_response_conflict(
    gemma_text: str,
    exec_results: ExecResults | None,
    mission_id: int | None = None,
    mission_metadata: dict | None = None,
) -> str | None:
    """Return the action label when Gemma contradicts a DB write result."""
    text = gemma_text or ""
    if not text or not exec_results:
        return None

    submit = exec_results.submit
    if submit and submit.db_changed and submit.result_type == "success":
        return "submit_success" if _SUCCESS_SUBMIT_CONFLICT_RE.search(text) else None
    if submit and submit.db_changed and submit.result_type == "fail":
        if _needs_strict_failure_tone(mission_id, mission_metadata) and _CONSTRAINED_FAIL_PRAISE_RE.search(text):
            return "submit_fail_constrained_praise"
        return "submit_fail" if _FAIL_SUBMIT_CONFLICT_RE.search(text) else None

    adjustment = exec_results.adjustment
    if adjustment and adjustment.db_changed:
        return "adjustment" if _ADJUSTMENT_CONFLICT_RE.search(text) else None

    cancel = exec_results.cancel
    if cancel and cancel.db_changed:
        return "cancel" if _CANCEL_CONFLICT_RE.search(text) else None

    return None


def _ensure_db_action_response_consistency(
    gemma_text: str,
    exec_results: ExecResults | None,
    action_ack,
    mission_id: int | None = None,
    mission_metadata: dict | None = None,
) -> str | None:
    """If Gemma contradicts a DB write, return a safe server ACK fallback."""
    conflict = _db_action_response_conflict(gemma_text, exec_results, mission_id, mission_metadata)
    if not conflict:
        return None
    fallback = getattr(action_ack, "message", None) or _DB_COMPLETION_FALLBACK
    print(
        f"[Guard] DB action response conflict type={conflict} "
        f"source={ascii(_short(gemma_text, 100))} fallback={ascii(_short(fallback, 100))}"
    )
    return fallback


def _tail_after_server_prefix(text: str, server_prefix: str) -> str:
    if not server_prefix:
        return text or ""
    prefix = f"{server_prefix}\n"
    if (text or "").startswith(prefix):
        return text[len(prefix):]
    if (text or "").startswith(server_prefix):
        return text[len(server_prefix):].lstrip()
    return text or ""


_EQUIVALENCY_APPROVAL_RE = re.compile(
    r"인정(?:돼|이야|할 수|될 수)|괜찮아|해도 돼|먹어도 돼|마셔도 돼|들어도 돼|봐도 돼|충분해|가능해"
)
_EQUIVALENCY_DENIAL_RE = re.compile(
    r"안 돼|안돼|"
    r"인정(?:이 )?(?:안|어려)|인정되지|인정할 수 없어|"
    r"실패|성공이\s*어려워|어렵겠|어려워|"
    r"해야 해|해야 돼"
)
_EQUIVALENCY_MISLEADING_LIMIT_DENIAL_RE = re.compile(
    r"(?:유튜브|쇼츠|릴스|틱톡|영상|게임|TV|티비|넷플릭스)(?:만|을?만)[\s\S]{0,12}(?:봐야|해야|하면)"
)
_EQUIVALENCY_CLARIFY_VERDICT_RE = re.compile(
    r"인정(?:돼|이야|할 수|될 수)|괜찮아|해도 돼|먹어도 돼|마셔도 돼|들어도 돼|봐도 돼|"
    r"안 돼|안돼|인정(?:이 )?(?:안|어려)|불인정|실패|"
    r"재미있을\s*거야|좋을\s*거야|문제없어|문제\s*없어"
)

def _equivalency_text_conflicts(decision: str | None, text: str) -> bool:
    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision == "denied":
        return bool(
            _EQUIVALENCY_APPROVAL_RE.search(text)
            or _EQUIVALENCY_MISLEADING_LIMIT_DENIAL_RE.search(text)
        )
    if normalized_decision == "approved":
        return bool(_EQUIVALENCY_DENIAL_RE.search(text))
    return False


def _equivalency_fallback_text(judgment: dict | None) -> str:
    return build_fallback_reply(judgment).strip() or _EQUIVALENCY_CLARIFY_FALLBACK


def _ensure_equivalency_response_consistency(ai_message: str, judgment: dict | None) -> str:
    if not judgment:
        return ai_message
    decision = judgment.get("decision")
    text = ai_message or ""
    conflict = _equivalency_text_conflicts(decision, text)
    # clarify는 guard 제거. Gemma가 자연스럽게 답하면 그대로 노출 — judge가 잘못 clarify로 갔을 때
    # 좋은 응답을 generic fallback으로 덮어쓰는 부작용을 막는다.
    if not conflict:
        return ai_message
    fallback = _equivalency_fallback_text(judgment)
    print(
        f"[Equivalency] response guard decision={decision} "
        f"source={_short(ai_message, 80)!r} fallback={_short(fallback, 80)!r}"
    )
    return fallback


def _debug_judgment(judgment: dict | None):
    if judgment is None:
        return None
    if hasattr(judgment, "to_dict"):
        return judgment.to_dict()
    return dict(judgment)


FORBIDDEN_WORDS = ["엄마", "아빠", "부모님", "가족", "형", "언니", "오빠", "동생", "친구", "선생님"]


def detect_violations(ai_message: str, user_input: str) -> list[str]:
    return [
        f"금지어 언급: '{w}' (사용자가 먼저 말하지 않음)"
        for w in FORBIDDEN_WORDS
        if w in ai_message and w not in user_input
    ]


def _cancel_sheet_bg(student_id: int, today: str):
    try:
        cancel_mission_result(student_id, today)
    except Exception as e:
        print(f"[cancel] 시트 초기화 실패: {e}")


def _sync_sheet_bg(
    session_id: str,
    user_message: str,
    ai_message: str,
    status: str,
    checkin_id: int | None = None,
):
    """구글 시트 동기화. DB 저장은 executor가 이미 처리했으므로 여기서는 시트만"""
    profile = fetch_profile(session_id)
    if not profile:
        return

    today = _kst_today()
    student_id = profile["student_id"]
    student_info = get_student_info_db(student_id) or {}
    mission_info = get_student_mission_db(student_id, today) or {}
    mission_id = mission_info.get("mission_id")
    if not mission_id:
        print(f"[sync] mission_id 없음 - 시트 동기화 스킵 (student_id={student_id})")
        return

    try:
        update_mission_result(
            student_id=student_id,
            today=today,
            result_reason=user_message,
            ai_response=ai_message,
            status=status,
            student_name=student_info.get("student_name", ""),
            age=student_info.get("age"),
            gender=student_info.get("gender", ""),
            location=student_info.get("location", ""),
            mission_id=mission_id,
            mission_name=mission_info.get("mission_name", ""),
            category=mission_info.get("category", ""),
            difficulty=mission_info.get("difficulty", ""),
        )
        if checkin_id is not None:
            mark_synced(checkin_id)
    except Exception:
        pass


_EQUIVALENCY_CLARIFY_FALLBACK = "조금만 더 자세히 알려줄래? 어떤 행동을 얼마나 했는지 말해주면 좋아 😊"


def _parse_equivalency_json(raw: str) -> dict | None:
    """대체 수행 LLM 응답을 JSON으로 파싱. 실패 시 None.

    {decision, reason, reply, clarify_question} 형태를 기대한다.
    """
    if not raw:
        return None
    text = raw.strip()
    # 코드펜스 제거
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # JSON 객체 영역만 추출 (앞뒤 잡음 제거)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = _json.loads(text[start:end + 1])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    decision = (data.get("decision") or "").strip().lower()
    if decision not in ("approved", "denied", "clarify"):
        return None
    reply = (data.get("reply") or "").strip()
    clarify_question = data.get("clarify_question")
    if isinstance(clarify_question, str):
        clarify_question = clarify_question.strip() or None
    else:
        clarify_question = None
    return {
        "decision": decision,
        "reason": (data.get("reason") or "").strip(),
        "reply": reply,
        "clarify_question": clarify_question,
    }


def _equivalency_visible_text(parsed: dict | None) -> str:
    """파싱된 JSON에서 사용자에게 보여줄 텍스트만 추출."""
    if not parsed:
        return _EQUIVALENCY_CLARIFY_FALLBACK
    reply = parsed.get("reply") or ""
    if parsed["decision"] == "clarify":
        question = parsed.get("clarify_question") or ""
        if reply and question and question not in reply:
            return f"{reply} {question}".strip()
        return (question or reply or _EQUIVALENCY_CLARIFY_FALLBACK).strip()
    return reply.strip() or _EQUIVALENCY_CLARIFY_FALLBACK


def _finalize_equivalency_response(
    ai_message: str,
    student_id: int | None,
    pending_submit_args: dict | None,
    exec_results: ExecResults,
    user_message: str = "",
    mission_title: str = "",
    mission_id: int | None = None,
) -> str:
    """LLM JSON 응답을 파싱해서 decision에 따라 submit 실행 여부를 정한다.

    approved → execute_submit + reply 노출
    denied   → DB 저장 없이 reply만 노출
    clarify  → DB 저장 없이 clarify_question 노출
    파싱 실패 → DB 저장 없이 clarify fallback 노출
    """
    parsed = _parse_equivalency_json(ai_message)
    if parsed is None:
        print(f"[Equivalency] JSON parse failed source={_short(ai_message)!r}")
        return _EQUIVALENCY_CLARIFY_FALLBACK

    visible = _equivalency_visible_text(parsed)

    if parsed["decision"] == "approved":
        if student_id and pending_submit_args:
            validation = _validate_and_execute_submit(
                student_id,
                pending_submit_args,
                user_message,
                mission_title,
                mission_id,
                exec_results,
            )
            if validation and not validation.should_execute:
                return build_submit_validation_response(validation, mission_title, user_message, mission_id)
            ack = build_action_ack(exec_results)
            if not ack:
                return visible
            return f"{visible}\n{ack.message}".strip()
        return visible

    # denied 또는 clarify → DB 저장하지 않음
    return visible


def _validate_and_execute_submit(
    student_id: int,
    pending_submit_args: dict,
    user_message: str,
    mission_title: str,
    mission_id: int | None,
    exec_results: ExecResults,
):
    validation = validate_submit_candidate(
        user_message=user_message,
        mission_name=mission_title,
        mission_id=mission_id,
        qwen_args=pending_submit_args,
        mission_metadata=get_student_mission_db(student_id, _kst_today()) if student_id else None,
    )
    print(
        "[Validator.submit] equivalency "
        f"action={validation.action} "
        f"result={validation.result_type or '-'} "
        f"reason={validation.reason or '-'}"
    )
    if validation.should_execute:
        exec_results.submit = execute_submit(
            student_id,
            {**pending_submit_args, "result_type": validation.result_type},
        )
        print(f"[Equivalency] submit executed: {exec_results.submit.status}")
    return validation


def _prepend_db_action_ack(ai_message: str, exec_results: ExecResults | None) -> str:
    ack = build_action_ack(exec_results)
    if ack and ack.message and not ai_message.startswith(ack.message):
        ai_message = _strip_leading_ack(ai_message, ack.message)
        print(f"[Response] prefix={_short(ack.message)!r}")
        return f"{ack.message}\n{ai_message}".strip()
    return ai_message


def _award_mission_xp_if_success(
    exec_results: ExecResults | None,
    student_id: int | None,
    mission_id: int | None,
) -> dict | None:
    """submit이 SAVED + result_type=success면 XP 지급 + xp_history 기록!

    Returns award dict (xp_gain, ticket_gain, level_before/after, leveled_up, app_state)
    또는 조건 미충족/실패 시 None
    """
    if not student_id or not mission_id:
        return None
    submit = getattr(exec_results, "submit", None)
    if not submit:
        return None
    status = getattr(submit.status, "value", submit.status)
    if status != "saved" or submit.result_type != "success":
        return None
    try:
        award = award_mission_xp(student_id, mission_id)
        print(f"[XP] +{award['xp_gain']} xp, +{award['ticket_gain']} ticket"
              f" (lv {award['level_before']} -> {award['level_after']})")
        return award
    except Exception as e:
        print(f"[XP] award failed: {e}")
        return None


def _attach_xp_award_to_debug(debug: dict, award: dict | None) -> None:
    """award_mission_xp 결과를 debug payload에 병합."""
    if not award:
        return
    debug["app_state"] = award["app_state"]
    debug["reward"] = {
        "type": "mission_success",
        "xp": award["xp_gain"],
        "tickets": award["ticket_gain"],
        "leveled_up": award["leveled_up"],
        "level_after": award["level_after"],
    }


# 조건형 키워드 → adjustment_type 매핑
_CONDITION_ADJUSTMENT_MAP: list[tuple[list[str], str]] = [
    (["쉬운", "쉽게", "간단한", "가벼운"], "easier"),
    (["어려운", "어렵게", "힘든", "도전적인"], "harder"),
    (["아무거나", "다른", "다른거", "다른걸로", "아무"], "change"),
]

_GENERATIVE_REPLACEMENT_RE = re.compile(
    r"아무거나|아무\s*거나|새로운|새\s*미션|안\s*해본|안해본|처음\s*해보는|"
    r"추천(?:해줘|해|해줄래)?|재밌는|재미있는"
)


def _detect_condition_adjustment(text: str) -> str | None:
    """사용자 입력에서 조건형 키워드를 감지해 adjustment_type을 반환한다."""
    compact = text.replace(" ", "")
    for keywords, adjustment_type in _CONDITION_ADJUSTMENT_MAP:
        if any(kw in compact for kw in keywords):
            return adjustment_type
    return None


def _wants_generated_replacement(text: str | None) -> bool:
    return bool(_GENERATIVE_REPLACEMENT_RE.search(text or ""))


def _compact_ko(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def classify_mission_change_shortcut(message: str) -> str | None:
    """Classify natural mission-change complaints before Qwen/Gemma routing."""
    compact = _compact_ko(message)
    raw = message or ""
    if not compact:
        return None
    if _looks_like_equivalency_question(raw):
        return None
    if _MISSION_CHANGE_NEGATION_RE.search(compact) or _CANCEL_REQUEST_RE.search(compact):
        return None

    too_hard_patterns = [
        r"너무어려",
        r"미션이어렵",
        r"미션어려",
        r"미션어렵",
        r"어려운미션",
        r"이미션힘들",
        r"미션힘들",
        r"못하겠",
        r"쉬운.*미션.*바꿔",
        r"쉬운.*걸로.*바꿔",
        r"쉬운걸로",
        r"쉬운.*미션.*줘",
        r"더쉬운.*(거|걸|미션).*줘",
        r"쉽게.*바꿔",
    ]
    if _has_any(compact, too_hard_patterns):
        return "too_hard"

    dislike_patterns = [
        r"노잼",
        r"재미없",
        r"미션싫",
        r"이미션싫",
        r"오늘미션싫",
        r"싫어$",
        r"싫다$",
    ]
    if _has_any(compact, dislike_patterns):
        return "dislike"

    cant_do_patterns = [
        r"못해$",
        r"못함$",
        r"할수없",
        r"할수없는상황",
        r"밖에못나가",
        r"비.*와서.*못",
        r"장소가없",
        r"장소없",
        r"불가능",
        r"빼고",
        r"제외",
    ]
    if _has_any(compact, cant_do_patterns) or _has_any(raw, [r"못\s+해"]):
        return "cant_do"

    return None


def _action_payload(active_ui: dict | None) -> dict:
    if not active_ui:
        return {}
    payload = active_ui.get("payload")
    return payload if isinstance(payload, dict) else {}


def _changed_response(mission_name: str) -> str:
    return f'좋아! 오늘 미션을 "{mission_name}"로 바꿨어. 같이 해보자! 💪'


async def _random_replacement_response(
    student_id: int,
    prefix: str = "정확히 맞는 미션을 찾기 어려워서, 대신 다른 미션으로 바꿔줄게!",
) -> tuple[dict, bool]:
    result = await run_in_threadpool(execute_adjustment, student_id, {"adjustment_type": "change"})
    if result.status is AdjustmentStatus.CHANGED:
        return (
            {
                "response": f'{prefix} 오늘 미션은 "{result.new_mission_name}"야.',
                "mission_completed": False,
                "detected_function": "request_mission_adjustment",
                "sources": [],
                "ui_action": None,
                "debug": {
                    "intent": "REPLACEMENT_MISSION",
                    "method": "random_fallback",
                    "fn_args": {"adjustment_type": "change"},
                    "adjustment_type": "change",
                    "adjustment_status": result.status.value,
                },
            },
            True,
        )
    if result.status is AdjustmentStatus.ALREADY_SUBMITTED:
        return (
            {
                "response": "오늘 미션 결과를 이미 저장했어서 지금은 바꿀 수 없어. 바꾸고 싶으면 먼저 기록을 취소해줘!",
                "mission_completed": False,
                "detected_function": None,
                "sources": [],
                "ui_action": None,
                "debug": {
                    "intent": "REPLACEMENT_MISSION",
                    "method": "random_fallback",
                    "adjustment_status": result.status.value,
                },
            },
            True,
        )
    return (
        {
            "response": "지금 바꿀 수 있는 다른 미션을 찾지 못했어. 잠시 뒤에 다시 시도해줘!",
            "mission_completed": False,
            "detected_function": None,
            "sources": [],
            "ui_action": None,
            "debug": {
                "intent": "REPLACEMENT_MISSION",
                "method": "random_fallback",
                "adjustment_status": result.status.value,
            },
        },
        False,
    )


async def _generated_replacement_suggestion_response(
    student_id: int,
    user_message: str,
    payload: dict | None = None,
) -> dict:
    response, debug = await create_generated_mission_suggestion(
        student_id,
        {
            **(payload or {}),
            "source_reason": (payload or {}).get("source_reason") or "natural_generate_new",
            "source_text": user_message,
            "requested_text": user_message,
        },
    )
    return {
        "response": response,
        "mission_completed": False,
        "detected_function": "awaiting_replacement_mission",
        "sources": [],
        "ui_action": None,
        "debug": {
            "intent": "REPLACEMENT_MISSION",
            "method": "generated_suggestion",
            **debug,
        },
    }


async def _resolve_generated_change_from_active_ui(
    student_id: int,
    session_id: str,
    user_message: str,
    active_ui: dict,
) -> dict:
    action_id = active_ui.get("action_id")
    if action_id:
        await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
    result = await _generated_replacement_suggestion_response(
        student_id,
        user_message,
        _action_payload(active_ui),
    )
    result["debug"]["previous_ui_action_type"] = active_ui.get("action_type")
    return result


async def _apply_activity_replacement(
    student_id: int,
    activity_keys: list[str],
    current: dict | None = None,
) -> dict | None:
    current = current or await run_in_threadpool(get_student_mission_db, student_id, _kst_today())
    if not current:
        return None
    if await run_in_threadpool(has_checkin_today, student_id):
        return {
            "response": "오늘 미션 결과를 이미 저장했어서 지금은 바꿀 수 없어. 바꾸고 싶으면 먼저 기록을 취소해줘!",
            "mission_completed": False,
            "detected_function": None,
            "sources": [],
            "ui_action": None,
            "debug": {"intent": "REPLACEMENT_MISSION", "method": "activity_key", "blocked": "already_submitted"},
        }

    replacement = await run_in_threadpool(
        select_replacement_mission,
        student_id,
        current.get("mission_id"),
        activity_keys,
    )
    if not replacement:
        return None

    await run_in_threadpool(save_mission_adjustment, student_id, current["mission_id"], replacement["mission_id"])
    return {
        "response": _changed_response(replacement["mission_name"]),
        "mission_completed": False,
        "detected_function": "request_mission_adjustment",
        "sources": [],
        "ui_action": None,
        "debug": {
            "intent": "REPLACEMENT_MISSION",
            "method": "activity_key",
            "fn_args": {"adjustment_type": "change"},
            "adjustment_type": "change",
            "activity_keys": activity_keys,
            "mission_id": replacement["mission_id"],
            "mission": replacement["mission_name"],
        },
    }


async def _handle_direct_activity_replacement(
    student_id: int,
    user_message: str,
    mission_row: dict,
) -> dict | None:
    candidate = extract_mission_candidate_text(user_message) or user_message
    activity_keys = match_activity_keys(candidate)
    if not activity_keys:
        return None

    result = await _apply_activity_replacement(student_id, activity_keys, mission_row)
    if result:
        if result.get("detected_function") == "request_mission_adjustment":
            await run_in_threadpool(save_mission_change_log, student_id, mission_row.get("mission_id"), "just_change")
        return result

    fallback_result = await _generated_replacement_suggestion_response(
        student_id,
        user_message,
        {
            "mission_id": mission_row.get("mission_id"),
            "mission_name": mission_row.get("mission_name"),
            "mission_rule": mission_row.get("mission_rule"),
            "activity_key": mission_row.get("activity_key"),
            "source_reason": "direct_activity_generate_fallback",
        },
    )
    fallback_result["debug"]["activity_keys"] = activity_keys
    fallback_result["debug"]["fallback_reason"] = "no_activity_key_mission"
    return fallback_result


async def _handle_mission_change_shortcut(
    student_id: int,
    session_id: str,
    user_message: str,
    mission_row: dict,
    shortcut_type: str,
) -> dict | None:
    payload = {
        "mission_id": mission_row.get("mission_id"),
        "mission_name": mission_row.get("mission_name"),
        "mission_rule": mission_row.get("mission_rule"),
        "activity_key": mission_row.get("activity_key"),
        "reason_type": shortcut_type,
        "original_user_message": user_message,
    }

    if shortcut_type == "too_hard":
        log_row = await run_in_threadpool(save_mission_change_log, student_id, mission_row.get("mission_id"), "too_hard")
        activity_key = mission_row.get("activity_key") or (log_row or {}).get("activity_key")
        memory = None
        if activity_key:
            memory = await run_in_threadpool(upsert_user_memory, student_id, activity_key, "difficulty")
        exec_results = ExecResults()
        exec_results.adjustment = await run_in_threadpool(execute_adjustment, student_id, {"adjustment_type": "easier"})
        if exec_results.adjustment and exec_results.adjustment.status is AdjustmentStatus.CHANGED:
            await _cleanup_completed_mission_change(student_id, session_id)
        ack = build_action_ack(exec_results)
        response = ack.message if ack else "쉬운 미션으로 바꾸려고 했는데 지금은 바꿀 수 있는 미션을 찾지 못했어."
        return {
            "response": response,
            "mission_completed": False,
            "detected_function": "request_mission_adjustment",
            "sources": [],
            "ui_action": None,
            "debug": {
                "intent": "MISSION_CHANGE_SHORTCUT",
                "shortcut_type": shortcut_type,
                "fn_args": {"adjustment_type": "easier"},
                "adjustment_type": "easier",
                "adjustment_status": exec_results.adjustment.status.value if exec_results.adjustment else None,
                "memory_saved": bool(memory),
            },
        }

    if shortcut_type == "dislike":
        await run_in_threadpool(save_mission_change_log, student_id, mission_row.get("mission_id"), "dislike")
        memory = await _save_dislike_memory(student_id, mission_row.get("activity_key"))
        ui_action = await create_mission_dislike_confirm_action(student_id, session_id, payload)
        hint = _mission_dislike_hint(
            mission_row.get("mission_name", "오늘 미션"),
            mission_row.get("mission_rule", ""),
        )
        ai_message, call1_ms = await _generate_hint_response(hint)
        return {
            "response": ai_message,
            "mission_completed": False,
            "detected_function": "mission_dislike_confirm",
            "sources": [],
            "ui_action": ui_action,
            "debug": {
                "intent": "MISSION_CHANGE_SHORTCUT",
                "shortcut_type": shortcut_type,
                "ui_action_id": ui_action.get("action_id"),
                "memory_saved": bool(memory),
                "llm_ms": call1_ms,
            },
        }

    if shortcut_type == "cant_do":
        await run_in_threadpool(save_mission_change_log, student_id, mission_row.get("mission_id"), "cant_do")
        ui_action = await create_replacement_mission_input_action(
            student_id,
            session_id,
            {**payload, "source_reason": "cant_do"},
        )
        return {
            "response": "그럼 어떤 미션으로 바꿔줄까? 하고 싶은 미션이나 조건을 말해줘.",
            "mission_completed": False,
            "detected_function": "awaiting_replacement_mission",
            "sources": [],
            "ui_action": ui_action,
            "debug": {
                "intent": "MISSION_CHANGE_SHORTCUT",
                "shortcut_type": shortcut_type,
                "next_ui_action_type": "awaiting_replacement_mission",
                "ui_action_id": ui_action.get("action_id"),
            },
        }

    return None


async def _save_negative_activity_memories(student_id: int, activity_keys: list[str]) -> list[dict]:
    saved: list[dict] = []
    for activity_key in activity_keys:
        try:
            memory = await run_in_threadpool(upsert_user_memory, student_id, activity_key, "preference", -1)
            if memory:
                saved.append(memory)
        except Exception as e:
            print(f"[NegativeActivity] memory upsert failed key={activity_key}: {type(e).__name__}: {e}")
    return saved


async def _handle_current_mission_status_question(
    student_id: int,
    session_id: str,
    user_message: str,
    mission_row: dict | None,
) -> dict | None:
    if not _should_use_current_mission_status_guard(user_message):
        return None

    current = mission_row or await run_in_threadpool(get_student_mission_db, student_id, _kst_today())
    response = _current_mission_status_message(
        current,
        changed_question=_is_mission_changed_question(user_message),
    )
    await run_in_threadpool(_save_message_safe, session_id, "user", user_message, "get_mission_info")
    await run_in_threadpool(_save_message_safe, session_id, "assistant", response)
    return {
        "response": response,
        "mission_completed": False,
        "detected_function": "get_mission_info",
        "sources": [],
        "ui_action": None,
        "debug": {
            "intent": "CURRENT_MISSION_STATUS_GUARD",
            "mission_id": (current or {}).get("mission_id"),
        },
    }


async def _handle_orphan_mission_acceptance(
    student_id: int,
    session_id: str,
    user_message: str,
    mission_row: dict | None,
) -> dict | None:
    if not _is_bare_replacement_acceptance(user_message):
        return None

    pending_suggestion = await run_in_threadpool(get_pending_mission_suggestion, student_id)
    if pending_suggestion:
        return None

    response = "좋아! 오늘 미션으로 같이 해보자 😊"
    await run_in_threadpool(_save_message_safe, session_id, "user", user_message)
    await run_in_threadpool(_save_message_safe, session_id, "assistant", response)
    return {
        "response": response,
        "mission_completed": False,
        "detected_function": None,
        "sources": [],
        "ui_action": None,
        "debug": {
            "intent": "BARE_ACCEPTANCE_ACK",
            "mission_id": (mission_row or {}).get("mission_id"),
        },
    }


async def _handle_mission_dislike_confirm_acceptance(
    student_id: int,
    session_id: str,
    user_message: str,
    active_ui: dict,
) -> dict | None:
    if not _is_mission_dislike_try_today_acceptance(user_message):
        return None

    action_id = active_ui.get("action_id")
    if action_id:
        await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
    response = "좋아! 오늘은 지금 미션으로 같이 도전해보자 😊"
    await run_in_threadpool(_save_message_safe, session_id, "user", user_message, "mission_dislike_confirm")
    await run_in_threadpool(_save_message_safe, session_id, "assistant", response)
    return {
        "response": response,
        "mission_completed": False,
        "detected_function": "mission_dislike_confirm",
        "sources": [],
        "ui_action": None,
        "debug": {
            "intent": "MISSION_DISLIKE_CONFIRM_ACCEPTED",
            "ui_action_id": action_id,
        },
    }


async def _cleanup_completed_mission_change(student_id: int | None, session_id: str) -> None:
    if not student_id:
        return
    try:
        pending = await run_in_threadpool(get_pending_mission_suggestion, student_id)
        if pending:
            await run_in_threadpool(resolve_pending_mission_suggestion, pending["suggestion_id"], "cancelled")
    except Exception as e:
        print(f"[MissionChangeCleanup] pending suggestion cleanup failed: {type(e).__name__}: {e}")

    try:
        active = await get_active_ui_action(student_id, session_id)
        if active and active.get("action_type") in {
            "mission_change_reason",
            "mission_dislike_confirm",
            "mission_change_method",
            "awaiting_replacement_mission",
        }:
            await run_in_threadpool(
                resolve_mission_ui_action,
                active.get("action_id"),
                student_id,
                session_id,
                "resolved",
            )
    except Exception as e:
        print(f"[MissionChangeCleanup] ui action cleanup failed: {type(e).__name__}: {e}")


async def _handle_negative_activity_request(
    student_id: int,
    session_id: str,
    user_message: str,
    mission_row: dict,
) -> dict | None:
    if should_promote_to_submit_path(
        user_message,
        mission_row.get("mission_name") or "",
        mission_row.get("mission_id"),
    ):
        return None

    if _looks_like_equivalency_question(user_message):
        return None

    if not is_negative_activity_request(user_message):
        return None

    activity_keys = extract_negative_activity_keys(user_message)
    if not activity_keys:
        return None

    reason_type = "cant_do" if re.search(r"못\s*해|못하|못\s*하|못\s*나가|못나가|불가능|할\s*수\s*없|빼고|제외", user_message) else "dislike"
    await run_in_threadpool(save_mission_change_log, student_id, mission_row.get("mission_id"), reason_type)
    memories = await _save_negative_activity_memories(student_id, activity_keys)
    payload = {
        "mission_id": mission_row.get("mission_id"),
        "mission_name": mission_row.get("mission_name"),
        "mission_rule": mission_row.get("mission_rule"),
        "activity_key": mission_row.get("activity_key"),
        "excluded_activity_keys": activity_keys,
        "source_reason": "negative_activity",
        "reason_type": reason_type,
        "original_user_message": user_message,
    }
    ui_action = await create_replacement_mission_input_action(student_id, session_id, payload)
    excluded_label = activity_keys[0]
    response = f"{excluded_label}는 빼고 어떤 미션으로 바꿔줄까? 하고 싶은 미션이나 조건을 말해줘. 😁"
    return {
        "response": response,
        "mission_completed": False,
        "detected_function": "awaiting_replacement_mission",
        "sources": [],
        "ui_action": ui_action,
        "debug": {
            "intent": "NEGATIVE_ACTIVITY_GUARD",
            "negative_activity_keys": activity_keys,
            "next_ui_action_type": "awaiting_replacement_mission",
            "ui_action_id": ui_action.get("action_id"),
            "memory_saved": bool(memories),
        },
    }


async def _handle_replacement_mission_input(
    student_id: int,
    session_id: str,
    user_message: str,
    active_ui: dict,
) -> dict | None:
    """awaiting_replacement_mission 상태에서 사용자 입력을 미션 매칭 로직으로 처리한다.
    memory extraction은 호출하지 않는다 (일반 대화가 아님).
    """
    action_id = active_ui.get("action_id")
    payload = _action_payload(active_ui)

    if _looks_like_equivalency_question(user_message):
        if action_id:
            await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
        return None

    candidate = extract_mission_candidate_text(user_message) or user_message.strip()
    if is_negative_activity_request(candidate):
        negative_keys = extract_negative_activity_keys(candidate)
        if negative_keys:
            memories = await _save_negative_activity_memories(student_id, negative_keys)
            updated_payload = {
                **payload,
                "excluded_activity_keys": sorted(set(payload.get("excluded_activity_keys") or []) | set(negative_keys)),
                "last_negative_input": user_message,
            }
            updated_action = await run_in_threadpool(
                update_mission_ui_action_payload,
                action_id,
                student_id,
                session_id,
                updated_payload,
            )
            active_for_payload = updated_action or {**active_ui, "payload": updated_payload}
            excluded_label = negative_keys[0]
            return {
                "response": f"{excluded_label}는 빼고 어떤 미션으로 바꿔줄까? 하고 싶은 미션이나 조건을 말해줘. 😁",
                "mission_completed": False,
                "detected_function": "awaiting_replacement_mission",
                "sources": [],
                "ui_action": rebuild_ui_action_payload(active_for_payload),
                "debug": {
                    "intent": "REPLACEMENT_MISSION",
                    "method": "negative_activity_retry",
                    "negative_activity_keys": negative_keys,
                    "memory_saved": bool(memories),
                },
            }

    retry_count = int(payload.get("retry_count") or 0) + 1
    if _is_bare_replacement_acceptance(user_message):
        updated_payload = {
            **payload,
            "retry_count": retry_count,
            "last_bare_acceptance_input": user_message,
        }
        updated_action = await run_in_threadpool(
            update_mission_ui_action_payload,
            action_id,
            student_id,
            session_id,
            updated_payload,
        )
        active_for_payload = updated_action or {**active_ui, "payload": updated_payload}
        return {
            "response": f"좋아! 그럼 원하는 미션을 조금만 더 말해줘. 예를 들면 {_MISSION_CHANGE_EXAMPLE_TEXT}처럼 말하면 돼!",
            "mission_completed": False,
            "detected_function": "awaiting_replacement_mission",
            "sources": [],
            "ui_action": rebuild_ui_action_payload(active_for_payload),
            "debug": {
                "intent": "REPLACEMENT_MISSION",
                "method": "bare_acceptance",
                "retry_count": retry_count,
            },
        }

    excluded_keys = set(payload.get("excluded_activity_keys") or [])
    raw_activity_keys = match_activity_keys(candidate)
    activity_keys = [key for key in raw_activity_keys if key not in excluded_keys]
    if _wants_generated_replacement(user_message) and not activity_keys:
        result = await _generated_replacement_suggestion_response(student_id, user_message, payload)
        await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
        return result
    if raw_activity_keys and not activity_keys and excluded_keys:
        excluded_label = sorted(excluded_keys)[0]
        return {
            "response": f"{excluded_label}는 빼기로 했어. 다른 미션이나 조건을 말해줘!",
            "mission_completed": False,
            "detected_function": "awaiting_replacement_mission",
            "sources": [],
            "ui_action": rebuild_ui_action_payload(active_ui),
            "debug": {
                "intent": "REPLACEMENT_MISSION",
                "method": "excluded_activity_blocked",
                "activity_keys": raw_activity_keys,
                "excluded_activity_keys": sorted(excluded_keys),
            },
        }
    if activity_keys:
        result = await _apply_activity_replacement(student_id, activity_keys)
        if result:
            await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
            if result.get("detected_function") == "request_mission_adjustment":
                await _cleanup_completed_mission_change(student_id, session_id)
            return result

    # 1. 조건형 키워드 감지 ("쉬운 걸로", "아무거나" 등)
    adjustment_type = _detect_condition_adjustment(user_message)
    if adjustment_type:
        if excluded_keys:
            updated_payload = {
                **payload,
                "last_condition_input": user_message,
            }
            updated_action = await run_in_threadpool(
                update_mission_ui_action_payload,
                action_id,
                student_id,
                session_id,
                updated_payload,
            )
            active_for_payload = updated_action or {**active_ui, "payload": updated_payload}
            excluded_label = sorted(excluded_keys)[0]
            return {
                "response": f"{excluded_label}는 빼둘게. 예를 들면 {_MISSION_CHANGE_EXAMPLE_TEXT}처럼 원하는 조건을 조금만 더 말해줘!",
                "mission_completed": False,
                "detected_function": "awaiting_replacement_mission",
                "sources": [],
                "ui_action": rebuild_ui_action_payload(active_for_payload),
                "debug": {
                    "intent": "REPLACEMENT_MISSION",
                    "method": "condition_blocked_by_exclusion",
                    "adjustment_type": adjustment_type,
                    "excluded_activity_keys": sorted(excluded_keys),
                },
            }
        result = await run_in_threadpool(execute_adjustment, student_id, {"adjustment_type": adjustment_type})
        if result.status is AdjustmentStatus.CHANGED:
            await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
            await _cleanup_completed_mission_change(student_id, session_id)
            return {
                "response": f'좋아! 오늘 미션을 "{result.new_mission_name}"로 바꿨어. 같이 해보자! 💪',
                "mission_completed": False,
                "detected_function": "request_mission_adjustment",
                "sources": [],
                "ui_action": None,
                "debug": {
                    "intent": "REPLACEMENT_MISSION",
                    "method": "condition",
                    "adjustment_type": adjustment_type,
                    "fn_args": {"adjustment_type": adjustment_type},
                },
            }
        if result.status is AdjustmentStatus.ALREADY_SUBMITTED:
            await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
            return {
                "response": "오늘 미션 결과를 이미 저장했어서 지금은 바꿀 수 없어. 바꾸고 싶으면 먼저 기록을 취소해줘!",
                "mission_completed": False,
                "detected_function": None,
                "sources": [],
                "ui_action": None,
                "debug": {"intent": "REPLACEMENT_MISSION", "method": "condition", "adjustment_status": result.status.value},
            }
        # NO_ALTERNATIVE 등 → 재질문으로 이어짐

    # 2. 특정 미션명 정확 매칭
    if not _is_meaningless_mission_candidate(candidate):
        exact = await run_in_threadpool(find_mission_by_user_text, candidate)
        if exact:
            current = await run_in_threadpool(get_student_mission_db, student_id, _kst_today())
            if current and exact.get("mission_id") != current.get("mission_id"):
                if await run_in_threadpool(has_checkin_today, student_id):
                    await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
                    return {
                        "response": "오늘 미션 결과를 이미 저장했어서 지금은 바꿀 수 없어. 바꾸고 싶으면 먼저 기록을 취소해줘!",
                        "mission_completed": False,
                        "detected_function": None,
                        "sources": [],
                        "ui_action": None,
                        "debug": {"intent": "REPLACEMENT_MISSION", "method": "exact_match", "blocked": "already_submitted"},
                    }
                await run_in_threadpool(save_mission_adjustment, student_id, current["mission_id"], exact["mission_id"])
                await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
                await _cleanup_completed_mission_change(student_id, session_id)
                return {
                    "response": _changed_response(exact["mission_name"]),
                    "mission_completed": False,
                    "detected_function": "request_mission_adjustment",
                    "sources": [],
                    "ui_action": None,
                    "debug": {
                        "intent": "REPLACEMENT_MISSION",
                        "method": "exact_match",
                        "mission": exact["mission_name"],
                        "adjustment_type": "change",
                        "fn_args": {"adjustment_type": "change"},
                    },
                }

        # 3. 유사 매칭
        similar = await run_in_threadpool(find_similar_mission_by_user_text, candidate)
        if similar:
            current = await run_in_threadpool(get_student_mission_db, student_id, _kst_today())
            if current and similar.get("mission_id") != current.get("mission_id"):
                await run_in_threadpool(save_pending_mission_suggestion, student_id, similar["mission_id"], user_message)
                await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
                return {
                    "response": f'비슷한 미션으로 "{similar["mission_name"]}"가 있어! 이 미션으로 바꿔볼까?',
                    "mission_completed": False,
                    "detected_function": None,
                    "sources": [],
                    "ui_action": None,
                    "debug": {"intent": "REPLACEMENT_MISSION", "method": "similar_match", "mission": similar["mission_name"]},
                }

    if retry_count >= 2:
        fallback_result = await _generated_replacement_suggestion_response(
            student_id,
            user_message,
            {**payload, "source_reason": "replacement_retry_generate"},
        )
        await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
        fallback_result["debug"]["retry_count"] = retry_count
        return fallback_result

    updated_payload = {
        **payload,
        "retry_count": retry_count,
        "last_failed_input": user_message,
    }
    updated_action = await run_in_threadpool(
        update_mission_ui_action_payload,
        action_id,
        student_id,
        session_id,
        updated_payload,
    )
    active_for_payload = updated_action or {**active_ui, "payload": updated_payload}
    print(f"[Replacement] no match for={_short(user_message)!r} action_id={action_id} retry={retry_count}")
    return {
        "response": f"아직 맞는 미션을 찾지 못했어. 예를 들면 {_MISSION_CHANGE_EXAMPLE_TEXT}처럼 조금 더 구체적으로 말해줘!",
        "mission_completed": False,
        "detected_function": None,
        "sources": [],
        "ui_action": rebuild_ui_action_payload(active_for_payload),
        "debug": {"intent": "REPLACEMENT_MISSION", "method": "no_match", "retry_count": retry_count},
    }


async def process_chat(body: ChatRequest, background_tasks: BackgroundTasks):
    mission_title = body.mission or "오늘의 미션"
    is_greet = body.message == "__GREET__"
    print(f"\n[Chat] <- {_short(body.message)!r} session={body.session_id[:8]}")

    if is_greet and body.mission and "오늘 미션은" in body.mission:
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", body.mission)
        return {
            "response": body.mission,
            "mission_completed": False,
            "detected_function": None,
            "sources": [],
            "ui_action": None,
            "debug": {"intent": "GREETING_TEMPLATE", "timing": {}},
        }

    if not is_greet:
        volume_response = _fixed_volume_conversion_response(body.message)
        if volume_response:
            print("[Guard] volume conversion question detected -> fixed response")
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", volume_response)
            return {
                "response": volume_response,
                "mission_completed": False,
                "detected_function": None,
                "sources": [],
                "ui_action": None,
                "debug": {"intent": "VOLUME_CONVERSION_GUARD", "timing": {}},
            }

    fixed_faq_message = _fixed_faq_response(body.message)
    if not is_greet and fixed_faq_message:
        print("[Guard] fixed FAQ detected -> fixed response")
        await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", fixed_faq_message)
        return {
            "response": fixed_faq_message,
            "mission_completed": False,
            "detected_function": None,
            "sources": [],
            "ui_action": None,
            "debug": {"intent": "FIXED_FAQ_GUARD", "timing": {}},
        }

    if not is_greet and _AI_IDENTITY_QUESTION_RE.search(body.message):
        print("[Guard] AI identity question detected -> fixed response")
        identity_message = _identity_response()
        await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", identity_message)
        return {
            "response": identity_message,
            "mission_completed": False,
            "detected_function": None,
            "sources": [],
            "ui_action": None,
            "debug": {"intent": "IDENTITY_GUARD", "timing": {}},
        }

    if not is_greet and _OFFTOPIC_RE.search(body.message):
        print("[Guard] off-topic detected -> fixed response")
        await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", _OFFTOPIC_RESPONSE)
        return {
            "response": _OFFTOPIC_RESPONSE,
            "mission_completed": False,
            "detected_function": None,
            "sources": [],
            "ui_action": None,
            "debug": {"intent": "OFFTOPIC_GUARD", "timing": {}},
        }

    profile = await run_in_threadpool(fetch_profile, body.session_id)
    student_id = profile["student_id"] if profile else None
    student_name = profile.get("student_name", "") if profile else ""
    mission_id = None
    mission_row = None
    if student_id:
        mission_row = await run_in_threadpool(get_student_mission_db, student_id, _kst_today())
        if mission_row:
            mission_id = mission_row.get("mission_id")
            mission_title = mission_row.get("mission_name") or mission_title
    mission_context_analysis = _prepare_mission_context_analysis(
        body.message,
        mission_row,
        mission_id,
        mission_title,
        is_greet,
    )

    if not is_greet and student_id:
        status_result = await _handle_current_mission_status_question(
            student_id,
            body.session_id,
            body.message,
            mission_row,
        )
        if status_result:
            return status_result

    if not is_greet and student_id:
        active_ui = await get_active_ui_action(student_id, body.session_id)
        if active_ui:
            action_type = active_ui.get("action_type")
            ui_action_payload = rebuild_ui_action_payload(active_ui)

            if action_type == "mission_dislike_confirm":
                accepted_result = await _handle_mission_dislike_confirm_acceptance(
                    student_id,
                    body.session_id,
                    body.message,
                    active_ui,
                )
                if accepted_result:
                    return accepted_result

            if action_type in ("mission_change_reason", "mission_dislike_confirm", "mission_change_method"):
                if _wants_generated_replacement(body.message):
                    result = await _resolve_generated_change_from_active_ui(
                        student_id,
                        body.session_id,
                        body.message,
                        active_ui,
                    )
                    await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, action_type)
                    await run_in_threadpool(_save_message_safe, body.session_id, "assistant", result["response"])
                    return result
                # 버튼 대기 중 → 일반 채팅 차단, 기존 버튼 재전달
                print(f"[UiActionGuard] blocking chat, active action_type={action_type} action_id={active_ui.get('action_id')}")
                block_message = "아래 선택지 중 하나를 골라줘!"
                return {
                    "response": block_message,
                    "mission_completed": False,
                    "detected_function": None,
                    "sources": [],
                    "ui_action": ui_action_payload,
                    "debug": {"intent": "UI_ACTION_GUARD", "ui_action_type": action_type},
                }

            if action_type == "awaiting_replacement_mission":
                result = await _handle_replacement_mission_input(student_id, body.session_id, body.message, active_ui)
                if result:
                    await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "awaiting_replacement_mission")
                    await run_in_threadpool(_save_message_safe, body.session_id, "assistant", result["response"])
                    return result

    if not is_greet and student_id:
        pending_outcome = await handle_pending_action(student_id, body.message, body.session_id)
        if pending_outcome and not pending_outcome.should_reroute:
            ai_message, call1_ms = await _generate_pending_response(pending_outcome)
            print(
                "[Pending] response "
                f"action={pending_outcome.action_type} status={pending_outcome.status} "
                f"response={_short(ai_message)!r}"
            )
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, pending_outcome.action_type)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)

            mission_status = None
            if pending_outcome.exec_results.submit and pending_outcome.exec_results.submit.status.value == "saved":
                mission_status = pending_outcome.exec_results.submit.result_type
                checkin_id = pending_outcome.exec_results.submit.checkin_id
                sync_user_message = pending_outcome.sync_user_message or body.message
                background_tasks.add_task(_sync_sheet_bg, body.session_id, sync_user_message, ai_message, mission_status, checkin_id)
            if (
                pending_outcome.exec_results.cancel
                and pending_outcome.exec_results.cancel.status is CancelStatus.CANCELLED_SUBMIT
            ):
                background_tasks.add_task(_cancel_sheet_bg, student_id, _kst_today())

            return {
                "response": ai_message,
                "mission_completed": mission_status is not None,
                "detected_function": pending_outcome.action_type,
                "sources": [],
                "ui_action": pending_outcome.ui_action,
                "debug": _pending_debug(pending_outcome, call1_ms, ai_message),
            }

    if not is_greet:
        past_clarify_response = _past_result_clarify_response(body.message)
        if past_clarify_response:
            print(f"[Guard] past result clarify -> {_short(past_clarify_response)!r}")
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", past_clarify_response)
            background_tasks.add_task(extract_and_save_memory, student_id, body.message, False)
            return {
                "response": past_clarify_response,
                "mission_completed": False,
                "detected_function": None,
                "sources": [],
                "ui_action": None,
                "debug": {
                    "intent": "PAST_RESULT_GUARD",
                    "clarify_reason": "past_ambiguous",
                    "fn_args": {},
                    "timing": {},
                },
            }

    if not is_greet and student_id:
        orphan_acceptance = await _handle_orphan_mission_acceptance(
            student_id,
            body.session_id,
            body.message,
            mission_row,
        )
        if orphan_acceptance:
            return orphan_acceptance

    if not is_greet and student_id and mission_row:
        negative_activity_result = await _handle_negative_activity_request(
            student_id,
            body.session_id,
            body.message,
            mission_row,
        )
        if negative_activity_result:
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "awaiting_replacement_mission")
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", negative_activity_result["response"])
            return negative_activity_result

    if not is_greet and student_id and mission_row:
        shortcut_type = classify_mission_change_shortcut(body.message)
        if shortcut_type:
            shortcut_result = await _handle_mission_change_shortcut(
                student_id,
                body.session_id,
                body.message,
                mission_row,
                shortcut_type,
            )
            if shortcut_result:
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, shortcut_result.get("detected_function"))
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", shortcut_result["response"])
                return shortcut_result

    if not is_greet and student_id and mission_row:
        if await classify_mission_dislike(body.message, mission_title):
            payload = {
                "mission_id": mission_row.get("mission_id"),
                "mission_name": mission_row.get("mission_name"),
                "mission_rule": mission_row.get("mission_rule"),
                "activity_key": mission_row.get("activity_key"),
                "reason_type": "dislike",
                "original_user_message": body.message,
            }
            await run_in_threadpool(save_mission_change_log, student_id, mission_row.get("mission_id"), "dislike")
            memory = await _save_dislike_memory(student_id, mission_row.get("activity_key"))
            ui_action = await create_mission_dislike_confirm_action(student_id, body.session_id, payload)
            hint = _mission_dislike_hint(
                mission_row.get("mission_name", "오늘 미션"),
                mission_row.get("mission_rule", ""),
            )
            ai_message, call1_ms = await _generate_hint_response(hint)
            print(f"[Dislike] ui_action created mission_id={mission_row.get('mission_id')} action_id={ui_action.get('action_id')} response={_short(ai_message)!r}")
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "mission_dislike_confirm")
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)
            return {
                "response": ai_message,
                "mission_completed": False,
                "detected_function": "mission_dislike_confirm",
                "sources": [],
                "ui_action": ui_action,
                "debug": {"intent": "MISSION_DISLIKE_GUARD", "ui_action_id": ui_action.get("action_id"), "memory_saved": bool(memory)},
            }

    if not is_greet and student_id and mission_row and should_force_mission_adjustment(body.message):
        if not _MISSION_CHANGE_NEGATION_RE.search((body.message or "").replace(" ", "")):
            candidate_text = extract_mission_candidate_text(body.message)
            if is_direct_condition_change_request(body.message):
                direct_result = await _handle_direct_activity_replacement(student_id, body.message, mission_row)
                if direct_result:
                    if direct_result.get("detected_function") == "request_mission_adjustment":
                        await _cleanup_completed_mission_change(student_id, body.session_id)
                    await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "request_mission_adjustment")
                    await run_in_threadpool(_save_message_safe, body.session_id, "assistant", direct_result["response"])
                    return direct_result

            if candidate_text:
                payload = {
                    "mission_id": mission_row.get("mission_id"),
                    "mission_name": mission_row.get("mission_name"),
                    "mission_rule": mission_row.get("mission_rule"),
                    "activity_key": mission_row.get("activity_key"),
                    "source_reason": "direct_condition",
                    "requested_text": body.message,
                }
                ui_action = await create_replacement_mission_input_action(student_id, body.session_id, payload)
                ai_message = "좋아, 어떤 미션으로 바꾸면 좋을지 조건을 조금 더 말해줘."
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "awaiting_replacement_mission")
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)
                return {
                    "response": ai_message,
                    "mission_completed": False,
                    "detected_function": "awaiting_replacement_mission",
                    "sources": [],
                    "ui_action": ui_action,
                    "debug": {"intent": "DIRECT_REPLACEMENT_REQUEST", "ui_action_id": ui_action.get("action_id")},
                }

            if not candidate_text:
                payload = {
                    "mission_id": mission_row.get("mission_id"),
                    "mission_name": mission_row.get("mission_name"),
                    "mission_rule": mission_row.get("mission_rule"),
                    "activity_key": mission_row.get("activity_key"),
                }
                ui_action = await create_mission_change_reason_action(student_id, body.session_id, payload)
                ai_message = "미션을 왜 바꾸고 싶은지 나에게 알려줄 수 있을까? ☺️"
                print(f"[MissionChange] ui_action created mission_id={mission_row.get('mission_id')} action_id={ui_action.get('action_id')}")
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "mission_change_reason")
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)
                return {
                    "response": ai_message,
                    "mission_completed": False,
                    "detected_function": "mission_change_reason",
                    "sources": [],
                    "ui_action": ui_action,
                    "debug": {"intent": "MISSION_CHANGE_REASON_GUARD", "ui_action_id": ui_action.get("action_id")},
                }

    intent = "A"
    fn_calls: list[tuple[str, dict]] = []
    detected_function = None
    fn_args: dict = {}
    rag_result: dict = {"chunks": [], "faqs": [], "context": ""}
    intent_ms = 0
    qwen_ms = 0
    clarify_hint_override = ""
    clarify_reason = ""
    risk_signal = detect_health_risk_signal(body.message if not is_greet else "")
    forced_rag_by_health_risk = False
    route_user_message = body.message

    if not is_greet:
        if _CANCEL_NEGATION_RE.search(body.message):
            cancel_negation_message = "알겠어, 취소하지 않을게! 😊"
            print("[Guard] cancel negation detected -> fixed response")
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", cancel_negation_message)
            return {
                "response": cancel_negation_message,
                "mission_completed": False,
                "detected_function": None,
                "sources": [],
                "ui_action": None,
                "debug": {"intent": "CANCEL_NEGATION_GUARD", "timing": {}},
            }
        contextual_history = await run_in_threadpool(fetch_messages, body.session_id, _CHAT_CONTEXT_MESSAGE_LIMIT)
        if student_id and _looks_like_contextual_quantity_submit(body.message, contextual_history):
            intent = "B"
            fn_calls = [("submit_mission_result", {"result_type": "success"})]
            detected_function = "submit_mission_result"
            fn_args = {"result_type": "success"}
            route_user_message = f"{mission_title} {body.message}"
            print("[Route] contextual quantity follow-up -> submit(success)")
        else:
            intent, intent_ms = await step_classify(body.message, mission_title)
        if not fn_calls and intent in ("A", "D") and should_promote_to_submit_path(body.message, mission_title, mission_id):
            print("[Route] promoted to B by submit report detector")
            intent = "B"
        if intent == "B" and "취소" in body.message:
            norm = normalize_b_input(body.message, mission_title, mission_id)
            if norm.should_clarify:
                intent = "D"
                clarify_reason = norm.reason
                clarify_hint_override = CLARIFY_HINT_MAP.get(norm.reason, CLARIFY_HINT_DEFAULT)
                print(f"[Route] B -> D clarify ({norm.reason or 'default'})")
            elif "취소" in norm.message:
                fn_calls, qwen_ms = await step_extract_functions(norm.message)
                detected_function = fn_calls[0][0] if fn_calls else None
                fn_args = fn_calls[0][1] if fn_calls else {}

        route_decision = _MISSION_ROUTER.decide(body.message, fn_calls)
        if route_decision:
            intent = route_decision.intent
            fn_calls = route_decision.fn_calls
            detected_function = route_decision.detected_function
            fn_args = route_decision.fn_args
            print(route_decision.log_message)

        if intent == "B" and not fn_calls:
            norm = normalize_b_input(body.message, mission_title, mission_id)
            if norm.should_clarify:
                intent = "D"
                clarify_reason = norm.reason
                clarify_hint_override = CLARIFY_HINT_MAP.get(norm.reason, CLARIFY_HINT_DEFAULT)
                print(f"[Route] B -> D clarify ({norm.reason or 'default'})")
            else:
                fn_calls, qwen_ms = await step_extract_functions(norm.message)
                detected_function = fn_calls[0][0] if fn_calls else None
                fn_args = fn_calls[0][1] if fn_calls else {}
        if risk_signal["has_risk"] and intent == "A":
            intent = "C"
            forced_rag_by_health_risk = True
            print("[Safety] health risk signal detected in intent A -> force intent C/RAG")
        if intent == "C":
            try:
                rag_result = await run_in_threadpool(search_rag, body.message)
            except Exception as e:
                print(f"[RAG] 검색 실패 (무시): {e}")

    clarify_response = _clarify_template(clarify_reason, body.message, mission_title, mission_id)
    if clarify_response:
        print(f"[Clarify] template reason={clarify_reason} response={_short(clarify_response)!r}")
        if not is_greet:
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, detected_function)
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", clarify_response)
        if not is_greet:
            background_tasks.add_task(extract_and_save_memory, student_id, body.message, False)
        await run_in_threadpool(
            _save_natural_language_confirmation_pending,
            student_id,
            body.message,
            clarify_reason,
            mission_id,
            mission_title,
        )
        return {
            "response": clarify_response,
            "mission_completed": False,
            "detected_function": None,
            "sources": [],
            "ui_action": None,
            "debug": {
                "intent": intent,
                "clarify_reason": clarify_reason,
                "clarify_template": True,
                "fn_args": fn_args,
                "violations": detect_violations(clarify_response, body.message),
                "system_prompt": "",
                "history_turns": 0,
                "model": OLLAMA_MODEL,
                "timing": {"intent_ms": intent_ms, "qwen_ms": qwen_ms, "llm_ms": 0},
                "rag_hits": {"chunks": 0, "faqs": 0},
                "health_risk": {
                    "has_risk": risk_signal["has_risk"],
                    "matched_keywords": risk_signal["matched_keywords"],
                    "risk_level": risk_signal["risk_level"],
                },
                "forced_rag_by_health_risk": forced_rag_by_health_risk,
            },
        }

    combo = classify_multi(fn_calls) if fn_calls else None
    if _MISSION_CHANGE_NEGATION_RE.search((body.message or "").replace(" ", "")):
        fn_calls = [call for call in fn_calls if call[0] != "request_mission_adjustment"]
        combo = classify_multi(fn_calls) if fn_calls else None
    mission_change_guard_result, fn_calls = _prepare_mission_change_guard(student_id, body.message, fn_calls)
    if mission_change_guard_result and mission_change_guard_result.get("type") == "adjustment_saved":
        await _cleanup_completed_mission_change(student_id, body.session_id)

    # Recompute combo because the guard may have changed fn_calls.
    combo = classify_multi(fn_calls) if fn_calls else None
    if mission_change_guard_result and not fn_calls:
        detected_function = "request_mission_adjustment"
        fn_args = {"adjustment_type": "change", "requested_text": body.message}
    elif not _has_cancel_call(fn_calls) and should_force_mission_adjustment(body.message):
        detected_function = "request_mission_adjustment"
    print(f"[Route] student={student_id or '-'} combo={combo or '-'} calls={_fn_list(fn_calls)}")
    exec_results = ExecResults()
    pending_submit_args = None
    submit_validation = None

    if student_id and fn_calls:
        exec_results, fn_calls, pending_submit_args, combo, submit_validation = await run_in_threadpool(
            step_execute,
            student_id,
            fn_calls,
            combo,
            route_user_message,
            mission_title,
            mission_id,
        )
    elif fn_calls:
        print("[DB] skipped: missing student_id")
    if combo == "conflict":
        detected_function = None
    if exec_results.adjustment and exec_results.adjustment.status is AdjustmentStatus.CHANGED:
        await _cleanup_completed_mission_change(student_id, body.session_id)

    if submit_validation and not submit_validation.should_execute:
        ai_message = build_submit_validation_response(submit_validation, mission_title, body.message, mission_id)
        print(f"[Validator.submit] response={_short(ai_message)!r}")
        await run_in_threadpool(
            _save_natural_language_confirmation_pending,
            student_id,
            body.message,
            submit_validation.reason,
            mission_id,
            mission_title,
        )
        if not is_greet:
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, None)
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)
        if not is_greet:
            background_tasks.add_task(extract_and_save_memory, student_id, body.message, False)
        debug = {
            "intent": intent,
            "clarify_reason": clarify_reason,
            "fn_args": fn_args,
            "submit_validation": submit_validation.to_debug(),
            "violations": detect_violations(ai_message, body.message if not is_greet else ""),
            "system_prompt": "",
            "history_turns": 0,
            "model": OLLAMA_MODEL,
            "timing": {"intent_ms": intent_ms, "qwen_ms": qwen_ms, "llm_ms": 0},
            "rag_hits": {"chunks": len(rag_result["chunks"]), "faqs": len(rag_result["faqs"])},
        }
        return {
            "response": ai_message,
            "mission_completed": False,
            "detected_function": None,
            "sources": [],
            "ui_action": None,
            "debug": debug,
        }

    # 서버 주도 대체 수행 판정
    eq_submit = is_equivalency_submit(fn_calls) if fn_calls else False
    eq_standalone = bool(fn_calls) and any(
        fn == "check_mission_equivalency" for fn, _ in fn_calls
    ) and not eq_submit
    eq_result = await _EQUIVALENCY_SERVICE.resolve(
        student_id=student_id,
        fn_calls=fn_calls,
        pending_submit_args=pending_submit_args,
        user_message=body.message,
        mission_title=mission_title,
        mission_id=mission_id,
        exec_results=exec_results,
    )
    eq_judgment = eq_result.judgment
    pending_submit_args = eq_result.pending_submit_args
    submit_validation = eq_result.submit_validation or submit_validation
    if eq_judgment:
        print(
            f"[Equivalency] decision={eq_judgment.get('decision')} "
            f"reason={_short(eq_judgment.get('reason'), 80)!r}"
        )

    # JSON 출력 모드: 서버 판정이 없을 때만 LLM이 JSON으로 응답한다
    eq_json_mode = eq_result.json_mode

    system_prompt = await run_in_threadpool(
        step_build_hints,
        student_id=student_id,
        fn_calls=fn_calls,
        exec_results=exec_results,
        combo=combo,
        mission_title=mission_title,
        rag_context=rag_result["context"],
        intent=intent,
        is_greet=is_greet,
        clarify_hint_override=clarify_hint_override,
        student_name=student_name,
        user_message=body.message,
        eq_judgment=eq_judgment,
    )
    system_prompt += _failure_tone_instruction(exec_results, mission_id, mission_row)
    system_prompt = _append_mission_context_response_hint(system_prompt, mission_context_analysis, intent)
    print(f"[Prompt] function_results={'Y' if '[기능 실행 결과]' in system_prompt else 'N'}")

    gemma_user_message = _gemma_user_message(body.message, exec_results)
    if not is_greet and fn_calls and not _needs_history_for_action(fn_calls):
        messages = [{"role": "user", "content": gemma_user_message}]
    else:
        fetched_history = await run_in_threadpool(fetch_messages, body.session_id, _CHAT_CONTEXT_MESSAGE_LIMIT)
        history = [{"role": m["role"], "content": m["content"]} for m in fetched_history]
        if not is_greet:
            history.append({"role": "user", "content": gemma_user_message})
        messages = history if history else [
            {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
        ]

    action_ack = build_conflict_ack() if combo == "conflict" else (None if (eq_submit or eq_standalone) else build_action_ack(exec_results))
    llm_only = ""
    call1_ms = 0
    if mission_change_guard_result and not fn_calls:
        ai_message = mission_change_guard_result["message"]
        llm_only = ai_message
        print(f"[Guard] direct response={_short(ai_message)!r}")
    elif action_ack and action_ack.mode is ResponseMode.SERVER_ONLY:
        ai_message = action_ack.message
    else:
        try:
            ai_message, call1_ms = await generate_chat_message(system_prompt, messages)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}")

        if eq_json_mode:
            ai_message = await run_in_threadpool(
                _finalize_equivalency_response,
                ai_message,
                student_id,
                pending_submit_args,
                exec_results,
                body.message,
                mission_title,
                mission_id,
            )

        ai_message = _filter_ai_response(ai_message)
        if eq_judgment:
            ai_message = _ensure_equivalency_response_consistency(ai_message, eq_judgment)
        llm_only = ai_message
        if _unsafe_gemma_db_completion(llm_only, exec_results):
            print(f"[Guard] unsafe Gemma DB completion fallback source={_short(llm_only)!r}")
            ai_message = _DB_COMPLETION_FALLBACK
            llm_only = ai_message
        if not eq_submit and action_ack and action_ack.mode is ResponseMode.PREFIX_WITH_GEMMA:
            safe_fallback = _ensure_db_action_response_consistency(llm_only, exec_results, action_ack, mission_id, mission_row)
            ai_message = safe_fallback if safe_fallback else _prepend_db_action_ack(ai_message, exec_results)
        elif not eq_submit:
            safe_fallback = _ensure_db_action_response_consistency(llm_only, exec_results, action_ack, mission_id, mission_row)
            if safe_fallback:
                ai_message = safe_fallback
    ai_message = append_health_safety_suffix(ai_message, risk_signal, intent)
    if risk_signal["has_risk"] and intent == "C":
        llm_only = ai_message
    print(f"[Chat] -> mode={_response_mode_label(action_ack, eq_submit)} response={_short(ai_message)!r}")

    if not is_greet:
        await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, detected_function)
    await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)
    if not is_greet:
        await run_in_threadpool(
            _save_natural_language_confirmation_pending,
            student_id,
            body.message,
            clarify_reason,
            mission_id,
            mission_title,
        )
    if not is_greet:
        background_tasks.add_task(extract_and_save_memory, student_id, body.message, False)

    user_input = body.message if not is_greet else ""
    violations = detect_violations(ai_message, user_input)

    mission_status = None
    if exec_results and exec_results.submit and exec_results.submit.status.value == "saved":
        mission_status = exec_results.submit.result_type
    if (
        exec_results
        and exec_results.cancel
        and exec_results.cancel.status is CancelStatus.CANCELLED_SUBMIT
    ):
        today = _kst_today()
        background_tasks.add_task(_cancel_sheet_bg, student_id, today)

    if mission_status:
        checkin_id = exec_results.submit.checkin_id if exec_results and exec_results.submit else None
        background_tasks.add_task(_sync_sheet_bg, body.session_id, user_input, ai_message, mission_status, checkin_id)

    sources = [
        {"type": "faq", "title": f["title"], "question": f["question"]}
        for f in rag_result["faqs"]
    ] + [
        {"type": "chunk", "title": c["title"], "intent": c["intent"]}
        for c in rag_result["chunks"]
    ]

    debug = {
        "intent": intent,
        "clarify_reason": clarify_reason,
        "fn_args": fn_args,
        "violations": violations,
        "system_prompt": system_prompt,
        "history_turns": len(messages),
        "model": OLLAMA_MODEL,
        "timing": {"intent_ms": intent_ms, "qwen_ms": qwen_ms, "llm_ms": call1_ms},
        "rag_hits": {"chunks": len(rag_result["chunks"]), "faqs": len(rag_result["faqs"])},
        "health_risk": {
            "has_risk": risk_signal["has_risk"],
            "matched_keywords": risk_signal["matched_keywords"],
            "risk_level": risk_signal["risk_level"],
        },
        "forced_rag_by_health_risk": forced_rag_by_health_risk,
    }
    if exec_results and exec_results.submit:
        debug["submit_result"] = {
            "status": exec_results.submit.status.value,
            "result_type": exec_results.submit.result_type,
            "db_changed": exec_results.submit.db_changed,
        }
    if submit_validation:
        debug["submit_validation"] = submit_validation.to_debug()
    if eq_judgment:
        debug["equivalency_judgment"] = _debug_judgment(eq_judgment)
    context_debug = _mission_context_analysis_debug(mission_context_analysis)
    if context_debug:
        debug["mission_context_analysis"] = context_debug
    xp_award = _award_mission_xp_if_success(exec_results, student_id, mission_id)
    _attach_xp_award_to_debug(debug, xp_award)

    return {
        "response": ai_message,
        "mission_completed": mission_status is not None,
        "detected_function": detected_function,
        "sources": sources,
        "ui_action": None,
        "debug": debug,
    }


async def process_chat_stream(body: ChatRequest, background_tasks: BackgroundTasks):
    mission_title = body.mission or "오늘의 미션"
    is_greet = body.message == "__GREET__"
    request_id = uuid.uuid4().hex[:8]
    trace = _StreamTrace(request_id, body.session_id, body.message)
    print(f"\n[Stream] <- {_short(body.message)!r} session={body.session_id[:8]} request_id={request_id}")
    trace.log("request.received", session=body.session_id[:8], greet=is_greet, message=_short(body.message))

    async def event_stream():
        trace.log("stream.generator.start")
        if not is_greet:
            volume_response = _fixed_volume_conversion_response(body.message)
            if volume_response:
                print("[Guard] volume conversion question detected -> fixed response (stream)")
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", volume_response)
                async for event in _fake_stream_template_response(volume_response):
                    yield event
                yield _done_sse(None, {"intent": "VOLUME_CONVERSION_GUARD", "timing": {}})
                return

        fixed_faq_message = _fixed_faq_response(body.message)
        if not is_greet and fixed_faq_message:
            print("[Guard] fixed FAQ detected -> fixed response (stream)")
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", fixed_faq_message)
            async for event in _fake_stream_template_response(fixed_faq_message):
                yield event
            yield _done_sse(None, {"intent": "FIXED_FAQ_GUARD", "timing": {}})
            return

        if not is_greet and _AI_IDENTITY_QUESTION_RE.search(body.message):
            print("[Guard] AI identity question detected -> fixed response (stream)")
            identity_message = _identity_response()
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", identity_message)
            async for event in _fake_stream_template_response(identity_message):
                yield event
            yield _done_sse(None, {"intent": "IDENTITY_GUARD", "timing": {}})
            return

        if not is_greet and _OFFTOPIC_RE.search(body.message):
            print("[Guard] off-topic detected -> fixed response (stream)")
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", _OFFTOPIC_RESPONSE)
            async for event in _fake_stream_template_response(_OFFTOPIC_RESPONSE):
                yield event
            yield _done_sse(None, {"intent": "OFFTOPIC_GUARD", "timing": {}})
            return

        current_mission_title = mission_title
        profile = await _trace_thread(trace, "db.read.profile", fetch_profile, body.session_id)
        student_id = profile["student_id"] if profile else None
        student_name = profile.get("student_name", "") if profile else ""
        mission_id = None
        mission_row = None
        if student_id:
            mission_row = await _trace_thread(trace, "db.read.today_mission", get_student_mission_db, student_id, _kst_today())
            if mission_row:
                mission_id = mission_row.get("mission_id")
                current_mission_title = mission_row.get("mission_name") or current_mission_title
        trace.log("request.context.ready", student_id=student_id or "-", mission_id=mission_id or "-", mission=_short(current_mission_title, 50))
        mission_context_analysis = _prepare_mission_context_analysis(
            body.message,
            mission_row,
            mission_id,
            current_mission_title,
            is_greet,
        )
        if mission_context_analysis:
            trace.log(
                "mission_context.analysis",
                relatedness=mission_context_analysis.relatedness,
                hint=mission_context_analysis.response_hint_level,
                health=mission_context_analysis.health_info_signal,
                kind=mission_context_analysis.possible_b_kind or "-",
            )

        if not is_greet and student_id:
            started = time.perf_counter()
            trace.log("pre_guard.pending_gate.start")
            pending_gate_result = await _handle_stream_active_pending_gate(
                student_id,
                body.session_id,
                body.message,
                background_tasks,
                mission_id,
            )
            trace.log(
                "pre_guard.pending_gate.end",
                ms=round((time.perf_counter() - started) * 1000),
                hit=bool(pending_gate_result),
            )
            if pending_gate_result:
                response = pending_gate_result["response"]
                async for event in _fake_stream_template_response(response):
                    yield event
                yield _done_sse(
                    pending_gate_result.get("ui_action"),
                    pending_gate_result.get("debug"),
                    **(pending_gate_result.get("review_kwargs") or {}),
                )
                return

        if not is_greet and student_id:
            started = time.perf_counter()
            trace.log("pre_guard.current_mission_status.start")
            status_result = await _handle_current_mission_status_question(
                student_id,
                body.session_id,
                body.message,
                mission_row,
            )
            trace.log(
                "pre_guard.current_mission_status.end",
                ms=round((time.perf_counter() - started) * 1000),
                hit=bool(status_result),
            )
            if status_result:
                async for event in _fake_stream_template_response(status_result["response"]):
                    yield event
                yield _done_sse(status_result.get("ui_action"), status_result.get("debug"))
                return

        if not is_greet and student_id:
            started = time.perf_counter()
            trace.log("pre_guard.active_ui.start")
            active_ui = await get_active_ui_action(student_id, body.session_id)
            trace.log(
                "pre_guard.active_ui.end",
                ms=round((time.perf_counter() - started) * 1000),
                hit=bool(active_ui),
                action_type=active_ui.get("action_type") if active_ui else None,
            )
            if active_ui:
                action_type = active_ui.get("action_type")
                ui_action_payload = rebuild_ui_action_payload(active_ui)

                if action_type == "mission_dislike_confirm":
                    accepted_result = await _handle_mission_dislike_confirm_acceptance(
                        student_id,
                        body.session_id,
                        body.message,
                        active_ui,
                    )
                    if accepted_result:
                        async for event in _fake_stream_template_response(accepted_result["response"]):
                            yield event
                        yield _done_sse(accepted_result.get("ui_action"), accepted_result.get("debug"))
                        return

                if action_type in ("mission_change_reason", "mission_dislike_confirm", "mission_change_method"):
                    if _wants_generated_replacement(body.message):
                        result = await _resolve_generated_change_from_active_ui(
                            student_id,
                            body.session_id,
                            body.message,
                            active_ui,
                        )
                        await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, action_type)
                        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", result["response"])
                        async for event in _fake_stream_template_response(result["response"]):
                            yield event
                        yield _done_sse(result.get("ui_action"), result.get("debug"))
                        return
                    # 버튼 대기 중 → 일반 채팅 차단, 기존 버튼 재전달
                    print(f"[UiActionGuard] blocking chat, active action_type={action_type} action_id={active_ui.get('action_id')}")
                    block_message = "아래 선택지 중 하나를 골라줘!"
                    async for event in _fake_stream_template_response(block_message):
                        yield event
                    yield _done_sse(ui_action_payload, {"intent": "UI_ACTION_GUARD", "ui_action_type": action_type})
                    return

                if action_type == "awaiting_replacement_mission":
                    result = await _handle_replacement_mission_input(student_id, body.session_id, body.message, active_ui)
                    if result:
                        await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "awaiting_replacement_mission")
                        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", result["response"])
                        async for event in _fake_stream_template_response(result["response"]):
                            yield event
                        yield _done_sse(result["ui_action"], result["debug"])
                        return

        if not is_greet and student_id:
            pending_started = time.perf_counter()
            trace.log("pre_guard.pending_action.start")
            pending_outcome = await handle_pending_action(student_id, body.message, body.session_id)
            trace.log(
                "pre_guard.pending_action.end",
                ms=round((time.perf_counter() - pending_started) * 1000),
                hit=bool(pending_outcome),
                should_reroute=bool(pending_outcome and pending_outcome.should_reroute),
            )
            if pending_outcome and not pending_outcome.should_reroute:
                ai_message, call1_ms = await _generate_pending_response(pending_outcome)
                print(
                    "[Pending] response "
                    f"action={pending_outcome.action_type} status={pending_outcome.status} "
                    f"response={_short(ai_message)!r}"
                )
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, pending_outcome.action_type)
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)
                async for event in _fake_stream_template_response(ai_message):
                    yield event

                mission_status = None
                if pending_outcome.exec_results.submit and pending_outcome.exec_results.submit.status.value == "saved":
                    mission_status = pending_outcome.exec_results.submit.result_type
                    checkin_id = pending_outcome.exec_results.submit.checkin_id
                    sync_user_message = pending_outcome.sync_user_message or body.message
                    background_tasks.add_task(_sync_sheet_bg, body.session_id, sync_user_message, ai_message, mission_status, checkin_id)
                if (
                    pending_outcome.exec_results.cancel
                    and pending_outcome.exec_results.cancel.status is CancelStatus.CANCELLED_SUBMIT
                ):
                    background_tasks.add_task(_cancel_sheet_bg, student_id, _kst_today())

                debug_payload = _pending_debug(pending_outcome, call1_ms, ai_message)
                debug_payload["timing"]["total_ms"] = round((time.perf_counter() - pending_started) * 1000)
                yield _done_sse(
                    pending_outcome.ui_action,
                    debug_payload,
                    **_mission_review_trigger_kwargs(
                        pending_outcome.exec_results.submit if pending_outcome.exec_results else None,
                        mission_id,
                    ),
                )
                return

        if not is_greet:
            past_clarify_response = _past_result_clarify_response(body.message)
            if past_clarify_response:
                print(f"[Guard] past result clarify -> {_short(past_clarify_response)!r}")
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", past_clarify_response)
                background_tasks.add_task(extract_and_save_memory, student_id, body.message, False)
                async for event in _fake_stream_template_response(past_clarify_response):
                    yield event
                yield _done_sse(
                    None,
                    {
                        "intent": "PAST_RESULT_GUARD",
                        "clarify_reason": "past_ambiguous",
                        "fn_args": {},
                        "timing": {},
                    },
                )
                return

        if not is_greet and student_id:
            started = time.perf_counter()
            trace.log("pre_guard.orphan_acceptance.start")
            orphan_acceptance = await _handle_orphan_mission_acceptance(
                student_id,
                body.session_id,
                body.message,
                mission_row,
            )
            trace.log(
                "pre_guard.orphan_acceptance.end",
                ms=round((time.perf_counter() - started) * 1000),
                hit=bool(orphan_acceptance),
            )
            if orphan_acceptance:
                async for event in _fake_stream_template_response(orphan_acceptance["response"]):
                    yield event
                yield _done_sse(orphan_acceptance.get("ui_action"), orphan_acceptance.get("debug"))
                return

        if not is_greet and student_id and mission_row:
            negative_started = time.perf_counter()
            trace.log("pre_guard.negative_activity.start")
            negative_activity_result = await _handle_negative_activity_request(
                student_id,
                body.session_id,
                body.message,
                mission_row,
            )
            trace.log(
                "pre_guard.negative_activity.end",
                ms=round((time.perf_counter() - negative_started) * 1000),
                hit=bool(negative_activity_result),
            )
            if negative_activity_result:
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "awaiting_replacement_mission")
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", negative_activity_result["response"])
                async for event in _fake_stream_template_response(negative_activity_result["response"]):
                    yield event
                debug_payload = negative_activity_result.get("debug") or {}
                debug_payload.setdefault("timing", {})["total_ms"] = round((time.perf_counter() - negative_started) * 1000)
                yield _done_sse(negative_activity_result.get("ui_action"), debug_payload)
                return

        if not is_greet and student_id and mission_row:
            shortcut_started = time.perf_counter()
            trace.log("pre_guard.mission_change_shortcut.start")
            shortcut_type = classify_mission_change_shortcut(body.message)
            if shortcut_type:
                shortcut_result = await _handle_mission_change_shortcut(
                    student_id,
                    body.session_id,
                    body.message,
                    mission_row,
                    shortcut_type,
                )
                if shortcut_result:
                    await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, shortcut_result.get("detected_function"))
                    await run_in_threadpool(_save_message_safe, body.session_id, "assistant", shortcut_result["response"])
                    async for event in _fake_stream_template_response(shortcut_result["response"]):
                        yield event
                    debug_payload = shortcut_result.get("debug") or {}
                    debug_payload.setdefault("timing", {})["total_ms"] = round((time.perf_counter() - shortcut_started) * 1000)
                    yield _done_sse(shortcut_result.get("ui_action"), debug_payload)
                    return
            trace.log(
                "pre_guard.mission_change_shortcut.end",
                ms=round((time.perf_counter() - shortcut_started) * 1000),
                hit=False,
            )

        if not is_greet and student_id and mission_row:
            dislike_started = time.perf_counter()
            trace.log("pre_guard.mission_dislike.start")
            mission_disliked = await classify_mission_dislike(body.message, current_mission_title)
            trace.log(
                "pre_guard.mission_dislike.end",
                ms=round((time.perf_counter() - dislike_started) * 1000),
                hit=bool(mission_disliked),
            )
            if mission_disliked:
                payload = {
                    "mission_id": mission_row.get("mission_id"),
                    "mission_name": mission_row.get("mission_name"),
                    "mission_rule": mission_row.get("mission_rule"),
                    "activity_key": mission_row.get("activity_key"),
                    "reason_type": "dislike",
                    "original_user_message": body.message,
                }
                await run_in_threadpool(save_mission_change_log, student_id, mission_row.get("mission_id"), "dislike")
                memory = await _save_dislike_memory(student_id, mission_row.get("activity_key"))
                ui_action = await create_mission_dislike_confirm_action(student_id, body.session_id, payload)
                hint = _mission_dislike_hint(
                    mission_row.get("mission_name", "오늘 미션"),
                    mission_row.get("mission_rule", ""),
                )
                ai_message, call1_ms = await _generate_hint_response(hint)
                print(f"[Dislike] ui_action created mission_id={mission_row.get('mission_id')} action_id={ui_action.get('action_id')} response={_short(ai_message)!r}")
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "mission_dislike_confirm")
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)
                async for event in _fake_stream_template_response(ai_message):
                    yield event
                total_ms = round((time.perf_counter() - dislike_started) * 1000)
                yield _done_sse(ui_action, {"intent": "MISSION_DISLIKE_GUARD", "ui_action_id": ui_action.get("action_id"), "memory_saved": bool(memory), "timing": {"total_ms": total_ms}})
                return

        if not is_greet and student_id and mission_row and should_force_mission_adjustment(body.message):
            if not _MISSION_CHANGE_NEGATION_RE.search((body.message or "").replace(" ", "")):
                candidate_text = extract_mission_candidate_text(body.message)
                change_started = time.perf_counter()
                if is_direct_condition_change_request(body.message):
                    direct_result = await _handle_direct_activity_replacement(student_id, body.message, mission_row)
                    if direct_result:
                        if direct_result.get("detected_function") == "request_mission_adjustment":
                            await _cleanup_completed_mission_change(student_id, body.session_id)
                        await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "request_mission_adjustment")
                        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", direct_result["response"])
                        async for event in _fake_stream_template_response(direct_result["response"]):
                            yield event
                        total_ms = round((time.perf_counter() - change_started) * 1000)
                        direct_result["debug"].setdefault("timing", {})["total_ms"] = total_ms
                        yield _done_sse(direct_result["ui_action"], direct_result["debug"])
                        return

                if candidate_text:
                    payload = {
                        "mission_id": mission_row.get("mission_id"),
                        "mission_name": mission_row.get("mission_name"),
                        "mission_rule": mission_row.get("mission_rule"),
                        "activity_key": mission_row.get("activity_key"),
                        "source_reason": "direct_condition",
                        "requested_text": body.message,
                    }
                    ui_action = await create_replacement_mission_input_action(student_id, body.session_id, payload)
                    ai_message = "좋아, 어떤 미션으로 바꾸면 좋을지 조건을 조금 더 말해줘."
                    await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "awaiting_replacement_mission")
                    await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)
                    async for event in _fake_stream_template_response(ai_message):
                        yield event
                    total_ms = round((time.perf_counter() - change_started) * 1000)
                    yield _done_sse(ui_action, {"intent": "DIRECT_REPLACEMENT_REQUEST", "ui_action_id": ui_action.get("action_id"), "timing": {"total_ms": total_ms}})
                    return

                if not candidate_text:
                    change_started = time.perf_counter()
                    payload = {
                        "mission_id": mission_row.get("mission_id"),
                        "mission_name": mission_row.get("mission_name"),
                        "mission_rule": mission_row.get("mission_rule"),
                        "activity_key": mission_row.get("activity_key"),
                    }
                    ui_action = await create_mission_change_reason_action(student_id, body.session_id, payload)
                    ai_message = "미션을 왜 바꾸고 싶은지 나에게 알려줄 수 있을까?"
                    print(f"[MissionChange] ui_action created mission_id={mission_row.get('mission_id')} action_id={ui_action.get('action_id')}")
                    await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "mission_change_reason")
                    await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)
                    async for event in _fake_stream_template_response(ai_message):
                        yield event
                    total_ms = round((time.perf_counter() - change_started) * 1000)
                    yield _done_sse(ui_action, {"intent": "MISSION_CHANGE_REASON_GUARD", "ui_action_id": ui_action.get("action_id"), "timing": {"total_ms": total_ms}})
                    return

        intent = "A"
        fn_calls: list[tuple[str, dict]] = []
        detected_function = None
        fn_args: dict = {}
        rag_result: dict = {"chunks": [], "faqs": [], "context": ""}
        intent_ms = 0
        qwen_ms = 0
        rag_ms = 0
        t_total = time.perf_counter()
        trace.log("main_pipeline.start")
        clarify_hint_override = ""
        clarify_reason = ""
        risk_signal = detect_health_risk_signal(body.message if not is_greet else "")
        forced_rag_by_health_risk = False
        route_user_message = body.message

        if not is_greet:
            if _CANCEL_NEGATION_RE.search(body.message):
                print("[Guard] cancel negation detected -> fixed response (stream)")
                cancel_negation_message = "알겠어, 취소하지 않을게!"
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message)
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", cancel_negation_message)
                async for event in _fake_stream_template_response(cancel_negation_message):
                    yield event
                yield _done_sse(None, {"intent": "CANCEL_NEGATION_GUARD", "timing": {}})
                return

            pre_intent_decision = _MISSION_ROUTER.decide_before_intent(body.message)
            if pre_intent_decision:
                intent = pre_intent_decision.intent
                fn_calls = pre_intent_decision.fn_calls
                detected_function = pre_intent_decision.detected_function
                fn_args = pre_intent_decision.fn_args
                print(pre_intent_decision.log_message)
                trace.log(
                    "intent_router.skip",
                    reason="pre_intent_rule",
                    source=detected_function,
                    calls=_fn_list(fn_calls),
                )
            else:
                contextual_history = await _trace_thread(
                    trace,
                    "db.read.history.contextual_quantity",
                    fetch_messages,
                    body.session_id,
                    _CHAT_CONTEXT_MESSAGE_LIMIT,
                )
                if student_id and _looks_like_contextual_quantity_submit(body.message, contextual_history):
                    intent = "B"
                    fn_calls = [("submit_mission_result", {"result_type": "success"})]
                    detected_function = "submit_mission_result"
                    fn_args = {"result_type": "success"}
                    route_user_message = f"{current_mission_title} {body.message}"
                    print("[Route] contextual quantity follow-up -> submit(success) (stream)")
                    trace.log("intent.skip", reason="contextual_quantity_submit", intent=intent, calls=_fn_list(fn_calls))
                else:
                    trace.log("intent_router.start", model="ROUTER_MODEL")
                    intent, intent_ms = await step_classify(body.message, current_mission_title)
                    trace.log("intent_router.end", intent=intent, ms=intent_ms)
            if not fn_calls and intent in ("A", "D") and should_promote_to_submit_path(body.message, current_mission_title, mission_id):
                print("[Route] promoted to B by submit report detector (stream)")
                intent = "B"
                trace.log("intent.promoted", reason="submit_report_detector", intent=intent)
            if intent == "B" and "취소" in body.message:
                norm = normalize_b_input(body.message, current_mission_title, mission_id)
                if norm.should_clarify:
                    intent = "D"
                    clarify_reason = norm.reason
                    clarify_hint_override = CLARIFY_HINT_MAP.get(norm.reason, CLARIFY_HINT_DEFAULT)
                    print(f"[Route] B -> D clarify ({norm.reason or 'default'})")
                elif "취소" in norm.message:
                    trace.log("qwen_function_call.start", source="qwen", normalized=_short(norm.message))
                    fn_calls, qwen_ms = await step_extract_functions(norm.message)
                    trace.log("qwen_function_call.end", source="qwen", ms=qwen_ms, calls=_fn_list(fn_calls))
                    detected_function = fn_calls[0][0] if fn_calls else None
                    fn_args = fn_calls[0][1] if fn_calls else {}

            route_decision = _MISSION_ROUTER.decide(body.message, fn_calls)
            if route_decision:
                intent = route_decision.intent
                fn_calls = route_decision.fn_calls
                detected_function = route_decision.detected_function
                fn_args = route_decision.fn_args
                print(route_decision.log_message)

            if risk_signal["has_risk"] and intent == "A":
                intent = "C"
                forced_rag_by_health_risk = True
                print("[Safety] health risk signal detected in intent A -> force intent C/RAG")
            if route_decision:
                trace.log("function_call.forced_by_rule", calls=_fn_list(fn_calls))
            intent_label = {"A": "일반 대화", "B": "미션 액션", "C": "정보 조회", "D": "의도 불명확"}.get(intent, intent)
            yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'intent', 'value': intent, 'label': intent_label, 'ms': intent_ms}, ensure_ascii=False)}\n\n"

            if fn_calls:
                qwen_ms = 0
                trace.log("qwen_function_call.skip", reason="fn_calls_already_available", source="rule_or_context", calls=_fn_list(fn_calls))
                yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'qwen', 'calls': [[fn, args] for fn, args in fn_calls], 'ms': qwen_ms}, ensure_ascii=False)}\n\n"
            elif intent == "B":
                norm = normalize_b_input(body.message, current_mission_title, mission_id)
                if norm.should_clarify:
                    intent = "D"
                    clarify_reason = norm.reason
                    clarify_hint_override = CLARIFY_HINT_MAP.get(norm.reason, CLARIFY_HINT_DEFAULT)
                    print(f"[Route] B -> D clarify ({norm.reason or 'default'})")
                else:
                    trace.log("qwen_function_call.start", source="qwen", normalized=_short(norm.message))
                    fn_calls, qwen_ms = await step_extract_functions(norm.message)
                    trace.log("qwen_function_call.end", source="qwen", ms=qwen_ms, calls=_fn_list(fn_calls))
                    detected_function = fn_calls[0][0] if fn_calls else None
                    fn_args = fn_calls[0][1] if fn_calls else {}
                    yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'qwen', 'calls': [[fn, args] for fn, args in fn_calls], 'ms': qwen_ms}, ensure_ascii=False)}\n\n"
            if intent == "C":
                try:
                    t_rag = time.perf_counter()
                    rag_result = await _trace_thread(trace, "rag.search", search_rag, body.message)
                    rag_ms = round((time.perf_counter() - t_rag) * 1000)
                    hits = len(rag_result["chunks"]) + len(rag_result["faqs"])
                    trace.log("rag.search.summary", ms=rag_ms, hits=hits)
                    yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'rag', 'hits': hits, 'ms': rag_ms}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    print(f"[RAG] 검색 실패 (무시): {e}")
                    trace.log("rag.search.error", error=f"{type(e).__name__}: {e}")

        clarify_response = _clarify_template(clarify_reason, body.message, current_mission_title, mission_id)
        if clarify_response:
            print(f"[Clarify] template reason={clarify_reason} response={_short(clarify_response)!r}")
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, detected_function)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", clarify_response)
            background_tasks.add_task(extract_and_save_memory, student_id, body.message, False)
            async for event in _fake_stream_template_response(clarify_response):
                yield event
            await run_in_threadpool(
                _save_natural_language_confirmation_pending,
                student_id,
                body.message,
                clarify_reason,
                mission_id,
                current_mission_title,
            )
            total_ms = round((time.perf_counter() - t_total) * 1000)
            yield _done_sse(
                None,
                {
                    "intent": intent,
                    "clarify_reason": clarify_reason,
                    "clarify_template": True,
                    "fn_args": fn_args,
                    "violations": detect_violations(clarify_response, body.message),
                    "system_prompt": "",
                    "history_turns": 0,
                    "model": OLLAMA_MODEL,
                    "timing": {
                        "intent_ms": intent_ms,
                        "qwen_ms": qwen_ms,
                        "rag_ms": rag_ms,
                        "gen_ms": 0,
                        "total_ms": total_ms,
                    },
                    "rag_hits": {"chunks": 0, "faqs": 0},
                    "health_risk": {
                        "has_risk": risk_signal["has_risk"],
                        "matched_keywords": risk_signal["matched_keywords"],
                        "risk_level": risk_signal["risk_level"],
                    },
                    "forced_rag_by_health_risk": forced_rag_by_health_risk,
                },
            )
            return

        combo = classify_multi(fn_calls) if fn_calls else None
        if _MISSION_CHANGE_NEGATION_RE.search((body.message or "").replace(" ", "")):
            fn_calls = [call for call in fn_calls if call[0] != "request_mission_adjustment"]
            combo = classify_multi(fn_calls) if fn_calls else None
        mission_change_guard_result, fn_calls = _prepare_mission_change_guard(student_id, body.message, fn_calls)
        if mission_change_guard_result and mission_change_guard_result.get("type") == "adjustment_saved":
            await _cleanup_completed_mission_change(student_id, body.session_id)

        # Recompute combo because the guard may have changed fn_calls.
        combo = classify_multi(fn_calls) if fn_calls else None
        if mission_change_guard_result and not fn_calls:
            detected_function = "request_mission_adjustment"
            fn_args = {"adjustment_type": "change", "requested_text": body.message}
        elif not _has_cancel_call(fn_calls) and should_force_mission_adjustment(body.message):
            detected_function = "request_mission_adjustment"
        print(f"[Route] student={student_id or '-'} combo={combo or '-'} calls={_fn_list(fn_calls)}")
        exec_results = ExecResults()
        pending_submit_args = None
        submit_validation = None

        if student_id and fn_calls:
            exec_results, fn_calls, pending_submit_args, combo, submit_validation = await _trace_thread(
                trace,
                "function_execute.db",
                step_execute,
                student_id,
                fn_calls,
                combo,
                route_user_message,
                current_mission_title,
                mission_id,
            )
        elif fn_calls:
            print("[DB] skipped: missing student_id")
            trace.log("function_execute.skip", reason="missing_student_id", calls=_fn_list(fn_calls))
        if combo == "conflict":
            detected_function = None
        if exec_results.adjustment and exec_results.adjustment.status is AdjustmentStatus.CHANGED:
            trace.log("db.write.cleanup_mission_change.start")
            await _cleanup_completed_mission_change(student_id, body.session_id)
            trace.log("db.write.cleanup_mission_change.end")

        if submit_validation and not submit_validation.should_execute:
            ai_message = build_submit_validation_response(submit_validation, current_mission_title, body.message, mission_id)
            print(f"[Validator.submit] response={_short(ai_message)!r}")
            await run_in_threadpool(
                _save_natural_language_confirmation_pending,
                student_id,
                body.message,
                submit_validation.reason,
                mission_id,
                current_mission_title,
            )
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, None)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)
            background_tasks.add_task(extract_and_save_memory, student_id, body.message, False)
            async for event in _fake_stream_template_response(ai_message):
                yield event
            total_ms = round((time.perf_counter() - t_total) * 1000)
            yield _done_sse(
                None,
                {
                    "intent": intent,
                    "clarify_reason": clarify_reason,
                    "fn_args": fn_args,
                    "submit_validation": submit_validation.to_debug(),
                    "violations": detect_violations(ai_message, body.message),
                    "system_prompt": "",
                    "history_turns": 0,
                    "model": OLLAMA_MODEL,
                    "timing": {
                        "intent_ms": intent_ms,
                        "qwen_ms": qwen_ms,
                        "rag_ms": rag_ms,
                        "gen_ms": 0,
                        "total_ms": total_ms,
                    },
                    "rag_hits": {"chunks": len(rag_result["chunks"]), "faqs": len(rag_result["faqs"])},
                },
            )
            return

        # 서버 주도 대체 수행 판정
        eq_submit = is_equivalency_submit(fn_calls) if fn_calls else False
        eq_standalone = bool(fn_calls) and any(
            fn == "check_mission_equivalency" for fn, _ in fn_calls
        ) and not eq_submit
        trace.log("equivalency.resolve.start", eq_submit=eq_submit, eq_standalone=eq_standalone)
        eq_result = await _EQUIVALENCY_SERVICE.resolve(
            student_id=student_id,
            fn_calls=fn_calls,
            pending_submit_args=pending_submit_args,
            user_message=body.message,
            session_id=body.session_id,
            mission_title=current_mission_title,
            mission_id=mission_id,
            exec_results=exec_results,
        )
        trace.log(
            "equivalency.resolve.end",
            has_judgment=bool(eq_result.judgment),
            json_mode=eq_result.json_mode,
        )
        eq_judgment = eq_result.judgment
        pending_submit_args = eq_result.pending_submit_args
        submit_validation = eq_result.submit_validation or submit_validation
        if eq_judgment:
            print(
                f"[Equivalency] decision={eq_judgment.get('decision')} "
                f"reason={_short(eq_judgment.get('reason'), 80)!r}"
            )
            if eq_judgment.get("decision") == "clarify":
                clarify_question = _equivalency_clarify_question(eq_judgment)
                await run_in_threadpool(
                    _save_equivalency_clarify_pending,
                    student_id,
                    body.message,
                    mission_row,
                    eq_judgment,
                )
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "check_mission_equivalency")
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", clarify_question)
                background_tasks.add_task(extract_and_save_memory, student_id, body.message, False)
                async for event in _fake_stream_template_response(clarify_question):
                    yield event
                total_ms = round((time.perf_counter() - t_total) * 1000)
                yield _done_sse(
                    None,
                    {
                        "intent": intent,
                        "clarify_reason": "equivalency_clarify",
                        "equivalency_judgment": _debug_judgment(eq_judgment),
                        "fn_args": fn_args,
                        "violations": detect_violations(clarify_question, body.message),
                        "system_prompt": "",
                        "history_turns": 0,
                        "model": OLLAMA_MODEL,
                        "timing": {
                            "intent_ms": intent_ms,
                            "qwen_ms": qwen_ms,
                            "rag_ms": rag_ms,
                            "gen_ms": 0,
                            "total_ms": total_ms,
                        },
                        "rag_hits": {"chunks": len(rag_result["chunks"]), "faqs": len(rag_result["faqs"])},
                    },
                )
                return

        # JSON 출력 모드: 서버 판정이 없을 때만 LLM이 JSON으로 응답
        eq_json_mode = eq_result.json_mode

        system_prompt = await _trace_thread(
            trace,
            "prompt_build",
            step_build_hints,
            student_id=student_id,
            fn_calls=fn_calls,
            exec_results=exec_results,
            combo=combo,
            mission_title=current_mission_title,
            rag_context=rag_result["context"],
            intent=intent,
            is_greet=is_greet,
            clarify_hint_override=clarify_hint_override,
            student_name=student_name,
            user_message=body.message,
            eq_judgment=eq_judgment,
        )
        system_prompt += _failure_tone_instruction(exec_results, mission_id, mission_row)
        system_prompt = _append_mission_context_response_hint(system_prompt, mission_context_analysis, intent)
        print(f"[Prompt] function_results={'Y' if '[기능 실행 결과]' in system_prompt else 'N'}")

        gemma_user_message = _gemma_user_message(body.message, exec_results)
        if not is_greet and fn_calls and not _needs_history_for_action(fn_calls):
            messages = [{"role": "user", "content": gemma_user_message}]
            trace.log("db.read.history.skip", reason="function_call_without_history_need", message_count=len(messages))
        else:
            fetched_history = await _trace_thread(
                trace,
                "db.read.history.generation",
                fetch_messages,
                body.session_id,
                _CHAT_CONTEXT_MESSAGE_LIMIT,
            )
            history = [{"role": m["role"], "content": m["content"]} for m in fetched_history]
            if not is_greet:
                history.append({"role": "user", "content": gemma_user_message})
            messages = history if history else [
                {"role": "user", "content": f"안녕! 오늘 미션 '{current_mission_title}'을 소개하고 응원해 줘."}
            ]
            trace.log("db.read.history.generation.summary", fetched=len(fetched_history), message_count=len(messages))

        trace.log("stream.pipeline.generating.before_yield")
        yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'generating'}, ensure_ascii=False)}\n\n"
        trace.log("stream.pipeline.generating.after_yield")

        t_gen = time.perf_counter()
        action_ack = build_conflict_ack() if combo == "conflict" else (None if (eq_submit or eq_standalone) else build_action_ack(exec_results))
        server_prefix = (
            action_ack.message
            if action_ack and action_ack.mode is ResponseMode.PREFIX_WITH_GEMMA
            else ""
        )
        ai_message = ""
        llm_message = ""
        prefix_buffer_mode = bool(server_prefix) and not eq_submit
        buffer_for_completion_guard = False
        buffer_for_action_consistency_guard = False
        first_token_ms = None

        if mission_change_guard_result and not fn_calls:
            ai_message = mission_change_guard_result["message"]
            trace.log("gemma.skip", reason="mission_change_guard")
            async for event in _fake_stream_template_response(ai_message):
                yield event
        elif action_ack and action_ack.mode is ResponseMode.SERVER_ONLY:
            ai_message = action_ack.message
            trace.log("gemma.skip", reason="server_only_action_ack")
            async for event in _fake_stream_template_response(ai_message):
                yield event
        else:
            if server_prefix:
                print(f"[Response] prefix={_short(server_prefix)!r}")
                ai_message = f"{server_prefix}\n"
                async for event in _fake_stream_template_response(ai_message):
                    yield event
            # eq_json_mode이면 JSON 원문 노출 방지를 위해 끝까지 버퍼링한다
            buffer_for_completion_guard = (
                not eq_submit and not server_prefix and not _exec_results_db_changed(exec_results)
            )
            buffer_for_action_consistency_guard = prefix_buffer_mode and _exec_results_db_changed(exec_results)
            suppress_token_emit = eq_json_mode or buffer_for_completion_guard or buffer_for_action_consistency_guard
            trace.log(
                "gemma.call.start",
                model=OLLAMA_MODEL,
                messages=len(messages),
                prompt_chars=len(system_prompt),
                suppress_token_emit=suppress_token_emit,
                eq_json_mode=eq_json_mode,
            )

            lookahead_limit = len(server_prefix) + 10 if server_prefix else 0
            lookahead_buf = ""
            prefix_echo_handled = not prefix_buffer_mode
            try:
                async for token in generate_chat_message_stream(system_prompt, messages):
                    if first_token_ms is None:
                        first_token_ms = round((time.perf_counter() - t_gen) * 1000)
                        trace.log("gemma.first_token", ms=first_token_ms, token_preview=_short(token, 30))
                    llm_message += token

                    if not prefix_echo_handled:
                        lookahead_buf += token
                        if len(lookahead_buf) >= lookahead_limit:
                            cleaned = _strip_leading_ack(lookahead_buf, server_prefix)
                            prefix_echo_handled = True
                            ai_message += cleaned
                            if cleaned.strip() and not suppress_token_emit:
                                yield f"data: {_json.dumps({'type': 'token', 'content': cleaned}, ensure_ascii=False)}\n\n"
                        continue

                    ai_message += token
                    if not suppress_token_emit:
                        yield f"data: {_json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
            except Exception as e:
                trace.log("gemma.call.error", error=f"{type(e).__name__}: {e}")
                yield f"data: {_json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
                return
            if not prefix_echo_handled and lookahead_buf:
                cleaned = _strip_leading_ack(lookahead_buf, server_prefix)
                ai_message += cleaned
                if cleaned.strip() and not suppress_token_emit:
                    yield f"data: {_json.dumps({'type': 'token', 'content': cleaned}, ensure_ascii=False)}\n\n"

        gen_ms = round((time.perf_counter() - t_gen) * 1000)
        trace.log("gemma.call.end", gen_ms=gen_ms, first_token_ms=first_token_ms, output_chars=len(ai_message))

        if eq_json_mode:
            finalized_message = await run_in_threadpool(
                _finalize_equivalency_response,
                llm_message,
                student_id,
                pending_submit_args,
                exec_results,
                body.message,
                current_mission_title,
                mission_id,
            )
            if eq_judgment:
                finalized_message = _ensure_equivalency_response_consistency(finalized_message, eq_judgment)
            ai_message = finalized_message
            print(f"[Equiv] json finalized={_short(finalized_message)!r}")
            if finalized_message.strip():
                async for event in _fake_stream_template_response(finalized_message):
                    yield event
        elif buffer_for_completion_guard:
            if _unsafe_gemma_db_completion(llm_message, exec_results):
                print(f"[Guard] unsafe Gemma DB completion fallback source={_short(llm_message)!r}")
                ai_message = _DB_COMPLETION_FALLBACK
            if eq_judgment:
                ai_message = _ensure_equivalency_response_consistency(ai_message, eq_judgment)
            if ai_message.strip():
                async for event in _fake_stream_template_response(ai_message):
                    yield event
        elif buffer_for_action_consistency_guard:
            tail = _tail_after_server_prefix(ai_message, server_prefix)
            safe_fallback = _ensure_db_action_response_consistency(tail, exec_results, action_ack, mission_id, mission_row)
            if safe_fallback:
                ai_message = safe_fallback
            elif tail.strip():
                async for event in _fake_stream_template_response(tail):
                    yield event

        before_safety_suffix = ai_message
        ai_message = append_health_safety_suffix(ai_message, risk_signal, intent)
        safety_suffix = ai_message[len(before_safety_suffix):]
        if safety_suffix.strip():
            async for event in _fake_stream_template_response(safety_suffix):
                yield event
        print(f"[Stream] -> mode={_response_mode_label(action_ack, eq_submit)} response={_short(ai_message)!r}")
        trace.log("model_response.ready", mode=_response_mode_label(action_ack, eq_submit), output_chars=len(ai_message))

        total_ms = round((time.perf_counter() - t_total) * 1000)
        user_input = body.message if not is_greet else ""
        debug_payload = {
            "intent": intent,
            "clarify_reason": clarify_reason,
            "fn_args": fn_args,
            "violations": detect_violations(ai_message, user_input),
            "system_prompt": system_prompt,
            "history_turns": len(messages),
            "model": OLLAMA_MODEL,
            "timing": {
                "intent_ms": intent_ms,
                "qwen_ms": qwen_ms,
                "rag_ms": rag_ms,
                "gen_ms": gen_ms,
                "first_token_ms": first_token_ms,
                "total_ms": total_ms,
            },
            "rag_hits": {"chunks": len(rag_result["chunks"]), "faqs": len(rag_result["faqs"])},
            "health_risk": {
                "has_risk": risk_signal["has_risk"],
                "matched_keywords": risk_signal["matched_keywords"],
                "risk_level": risk_signal["risk_level"],
            },
            "forced_rag_by_health_risk": forced_rag_by_health_risk,
        }
        if exec_results.submit:
            debug_payload["submit_result"] = {
                "status": exec_results.submit.status.value,
                "result_type": exec_results.submit.result_type,
                "db_changed": exec_results.submit.db_changed,
            }
        if submit_validation:
            debug_payload["submit_validation"] = submit_validation.to_debug()
        if eq_judgment:
            debug_payload["equivalency_judgment"] = _debug_judgment(eq_judgment)
        context_debug = _mission_context_analysis_debug(mission_context_analysis)
        if context_debug:
            debug_payload["mission_context_analysis"] = context_debug
        xp_award = _award_mission_xp_if_success(exec_results, student_id, mission_id)
        _attach_xp_award_to_debug(debug_payload, xp_award)
        save_content = ai_message.strip()
        await _trace_thread(
            trace,
            "db.write.save_chat_turn.final",
            _save_chat_turn_safe,
            body.session_id,
            body.message if not is_greet else None,
            save_content,
            detected_function,
            request_id,
            debug_payload,
        )
        if not is_greet:
            await _trace_thread(
                trace,
                "db.write.save_confirmation_pending",
                _save_natural_language_confirmation_pending,
                student_id,
                body.message,
                clarify_reason,
                mission_id,
                current_mission_title,
            )
            _add_stream_bg_task(
                background_tasks,
                trace,
                "extract_and_save_memory",
                extract_and_save_memory,
                student_id,
                body.message,
                False,
            )
        trace.log("response.pre_done.after_saves", pipeline_total_ms=round((time.perf_counter() - t_total) * 1000), trace_total_ms=trace.ms())

        mission_status = None
        if exec_results.submit and exec_results.submit.status.value == "saved":
            mission_status = exec_results.submit.result_type
        trace.log("response.done.before_yield", total_ms=total_ms, trace_total_ms=trace.ms())
        yield _done_sse(
            None,
            debug_payload,
            **_mission_review_trigger_kwargs(exec_results.submit if exec_results else None, mission_id),
        )
        trace.log("response.done.after_yield", trace_total_ms=trace.ms())
        if exec_results.cancel and exec_results.cancel.status is CancelStatus.CANCELLED_SUBMIT:
            today = _kst_today()
            _add_stream_bg_task(background_tasks, trace, "cancel_sheet", _cancel_sheet_bg, student_id, today)
        if mission_status:
            checkin_id = exec_results.submit.checkin_id if exec_results.submit else None
            _add_stream_bg_task(
                background_tasks,
                trace,
                "sync_sheet",
                _sync_sheet_bg,
                body.session_id,
                user_input,
                ai_message,
                mission_status,
                checkin_id,
            )
        trace.log("stream.generator.end", trace_total_ms=trace.ms())

    trace.log("streaming_response.created")
    return StreamingResponse(event_stream(), media_type="text/event-stream")
