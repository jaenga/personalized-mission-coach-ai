import asyncio
import json as _json
import random
import re
import time

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
from memory_service import extract_and_save_memory
from mission_ui_action_service import (
    create_mission_change_reason_action,
    create_mission_dislike_confirm_action,
    create_replacement_mission_input_action,
    get_active_ui_action,
    rebuild_ui_action_payload,
)
from ollama_client import OLLAMA_MODEL, generate_chat_message, generate_chat_message_stream, judge_mission_equivalency
from pending_service import PendingOutcome, classify_mission_dislike, handle_pending_action
from qwen_client import detect_history_call, detect_mission_info_call, detect_submit_report_call
from pipeline import (
    classify_multi,
    is_equivalency_submit,
    step_build_hints,
    step_classify,
    step_execute,
    step_extract_functions,
)
from hint_builder import build_equivalency_judge_prompt
from normalizer import normalize_b_input
from prompts import CLARIFY_HINT_DEFAULT, CLARIFY_HINT_MAP
from rag import search_rag
from response_builder import ResponseMode, build_action_ack, build_conflict_ack
from schemas import ChatRequest
from sheets import cancel_mission_result, update_mission_result
from submit_validator import build_submit_validation_response

_FAKE_STREAM_CHARS = 4
_FAKE_STREAM_DELAY_SEC = 0.1
_CHAT_CONTEXT_MESSAGE_LIMIT = 10
_CLARIFY_TEMPLATE_REASONS = {
    "numeric",
    "numeric_no_count",
    "numeric_ambiguous",
    "negation_verb",
    "difficulty",
}


def _clarify_template(reason: str, user_message: str, mission_title: str) -> str | None:
    if reason not in _CLARIFY_TEMPLATE_REASONS:
        return None
    if reason == "numeric_no_count":
        return "몇 개나 몇 분 했는지 알려줄래? 예를 들어, '3개 했어', '10분 했어'처럼 말해주면 돼! ☺️"
    if reason == "numeric_ambiguous":
        return "목표까지 조금 남았어! 더 해볼래, 아니면 여기까지 기록할까? 💪"
    if reason == "numeric":
        if re.search(r"봤|봄|시청|유튜브|유튭|유투브|영상|쇼츠|릴스", user_message):
            return "무엇을 몇 분 봤는지 조금 더 자세히 알려줄 수 있을까?"
        return "어떤 걸 몇 분이나 몇 개 했는지 조금 더 자세히 알려줄래? 😃"
    if reason == "negation_verb":
        if "엘리베이터" in user_message or "엘레베이터" in user_message or "엘베" in user_message:
            return "엘리베이터는 안 탔구나! 잘했어 👏 그럼 계단을 이용하여 올라가기도 실천했을까? 😆"
        return "오늘 미션 기준으로 성공인지 같이 확인해볼까?"
    if reason == "difficulty":
        return "조금 어렵게 느껴졌구나. 쉬운 미션으로 바꿔줄까? 아니면 오늘 미션으로 계속 기록할래? 🧐"
    return None


def _sse(payload: dict) -> str:
    return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"


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
    return any(fn == "submit_mission_result" for fn, _ in fn_calls)


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


def _short(text: str | None, limit: int = 90) -> str:
    if not text:
        return ""
    one_line = " ".join(str(text).split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "..."


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
    ]

    return text in accept_exact_words


def _is_bare_replacement_acceptance(message: str | None) -> bool:
    text = (message or "").replace(" ", "").strip()
    if not text:
        return False
    accept_phrases = {
        "응",
        "좋아",
        "응좋아",
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
    return bool(_CURRENT_MISSION_STATUS_RE.search(text))


def _current_mission_status_message(mission_row: dict | None, *, changed_question: bool = False) -> str:
    mission_name = (mission_row or {}).get("mission_name")
    if not mission_name:
        return "지금 오늘 미션을 아직 불러오지 못했어. 😣 잠시 뒤에 다시 확인해줘!"
    if changed_question:
        return f'아직 말로만 나온 미션으로 바뀐 건 아니야. 지금 오늘 미션은 "{mission_name}"야.'
    return f'지금 오늘 미션은 "{mission_name}"야.'


def _is_mission_changed_question(message: str | None) -> bool:
    text = _compact_ko(message)
    return bool(text and re.search(r"(?:미션)?(?:바뀐|바꾼).{0,6}(?:거야|거니|맞아|맞니|맞지|건가|거임)", text))


def _is_meaningless_mission_candidate(candidate: str | None) -> bool:
    if not candidate:
        return True

    compact = candidate.replace(" ", "").strip()
    if len(compact) < 2:
        return True

    generic_words = {
        "어", "으", "음", "아", "오",
        "다른", "다른거", "다른것", "새", "새로운",
        "그거", "그걸", "그걸로", "이거", "이걸", "이걸로",
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
    try:
        return await generate_chat_message(
            _PENDING_RESPONSE_PROMPT.format(hint=outcome.message_hint),
            [{"role": "user", "content": "이 상황에 맞게 짧게 답해줘."}],
        )
    except Exception as e:
        print(f"[Pending] response generation failed: {type(e).__name__}: {e}")
        return "알겠어! 그렇게 처리해둘게.", 0


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


def _save_natural_language_confirmation_pending(
    student_id: int | None,
    user_message: str,
    clarify_reason: str,
) -> None:
    """자연어 확인 질문을 보낸 턴이면 다음 턴 답변을 저장된 함수 실행과 연결한다."""
    if not student_id or clarify_reason != "past_ambiguous":
        return
    try:
        pending = save_pending_action(
            student_id,
            "natural_language_confirmation",
            {
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
            },
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
    if pending and is_accepting_mission_suggestion(user_message):
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


def _finalize_equivalency_response(
    ai_message: str,
    student_id: int | None,
    pending_submit_args: dict | None,
    exec_results: ExecResults,
) -> str:
    """[APPROVED]/[DENIED] 태그 제거 후, 실제 저장 결과를 응답에 반영."""
    if "[APPROVED]" in ai_message:
        ai_message = ai_message.replace("[APPROVED]", "").strip()
        if student_id and pending_submit_args:
            submit_result = execute_submit(student_id, pending_submit_args)
            exec_results.submit = submit_result
            ack = build_action_ack(exec_results)
            if not ack:
                return ai_message
            return f"{ai_message}\n{ack.message}".strip()
        return ai_message

    if "[DENIED]" in ai_message:
        return ai_message.replace("[DENIED]", "").strip()

    return ai_message


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


def _detect_condition_adjustment(text: str) -> str | None:
    """사용자 입력에서 조건형 키워드를 감지해 adjustment_type을 반환한다."""
    compact = text.replace(" ", "")
    for keywords, adjustment_type in _CONDITION_ADJUSTMENT_MAP:
        if any(kw in compact for kw in keywords):
            return adjustment_type
    return None


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

    fallback_result, _ = await _random_replacement_response(student_id)
    fallback_result["debug"]["activity_keys"] = activity_keys
    fallback_result["debug"]["fallback_reason"] = "no_activity_key_mission"
    if fallback_result.get("detected_function") == "request_mission_adjustment":
        await run_in_threadpool(save_mission_change_log, student_id, mission_row.get("mission_id"), "just_change")
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
    if not _is_current_mission_status_question(user_message):
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
) -> dict:
    """awaiting_replacement_mission 상태에서 사용자 입력을 미션 매칭 로직으로 처리한다.
    memory extraction은 호출하지 않는다 (일반 대화가 아님).
    """
    action_id = active_ui.get("action_id")
    payload = _action_payload(active_ui)

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
            "response": "좋아! 그럼 원하는 미션을 조금만 더 말해줘. 예를 들면 '실내 미션', '물 마시는 미션'처럼 말하면 돼!",
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
                "response": f"{excluded_label}는 빼둘게. 예를 들면 '실내 미션', '물 마시는 미션'처럼 원하는 조건을 조금만 더 말해줘!",
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
                "debug": {"intent": "REPLACEMENT_MISSION", "method": "condition", "adjustment_type": adjustment_type},
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
                    "debug": {"intent": "REPLACEMENT_MISSION", "method": "exact_match", "mission": exact["mission_name"]},
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
        fallback_result, _ = await _random_replacement_response(
            student_id,
            prefix="일치하는 미션을 찾지 못했어. 대신 랜덤 미션으로 바꿔줄게!",
        )
        await run_in_threadpool(resolve_mission_ui_action, action_id, student_id, session_id, "resolved")
        if fallback_result.get("detected_function") == "request_mission_adjustment":
            await _cleanup_completed_mission_change(student_id, session_id)
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
        "response": "아직 맞는 미션을 찾지 못했어. 예를 들면 '실내 미션', '물 마시는 미션', '야채 먹는 미션'처럼 조금 더 구체적으로 말해줘!",
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
                await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "awaiting_replacement_mission")
                await run_in_threadpool(_save_message_safe, body.session_id, "assistant", result["response"])
                return result

    if not is_greet and student_id:
        pending_outcome = await handle_pending_action(student_id, body.message, body.session_id)
        if pending_outcome:
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
        intent, intent_ms = await step_classify(body.message, mission_title)
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

        submit_report_call = None if fn_calls else detect_submit_report_call(body.message)
        history_call = None if submit_report_call or fn_calls else detect_history_call(body.message)
        mission_info_call = None if submit_report_call or history_call or fn_calls else detect_mission_info_call(body.message)
        if submit_report_call:
            intent = "B"
            fn_calls = [submit_report_call]
            detected_function = submit_report_call[0]
            fn_args = submit_report_call[1]
            print("[Route] submit report forced to submit_mission_result")
        elif history_call:
            intent = "B"
            fn_calls = [history_call]
            detected_function = history_call[0]
            fn_args = history_call[1]
            print("[Route] history query forced to get_user_history")
        elif mission_info_call:
            intent = "B"
            fn_calls = [mission_info_call]
            detected_function = mission_info_call[0]
            fn_args = mission_info_call[1]
            print("[Route] mission info query forced to get_mission_info")

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
        if intent == "C":
            try:
                rag_result = await run_in_threadpool(search_rag, body.message)
            except Exception as e:
                print(f"[RAG] 검색 실패 (무시): {e}")

    clarify_response = _clarify_template(clarify_reason, body.message, mission_title)
    if clarify_response:
        print(f"[Clarify] template reason={clarify_reason} response={_short(clarify_response)!r}")
        if not is_greet:
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, detected_function)
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", clarify_response)
        if not is_greet:
            background_tasks.add_task(extract_and_save_memory, student_id, body.message, False)
        await run_in_threadpool(_save_natural_language_confirmation_pending, student_id, body.message, clarify_reason)
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
            body.message,
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
        ai_message = build_submit_validation_response(submit_validation, mission_title)
        print(f"[Validator.submit] response={_short(ai_message)!r}")
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

    # 서버 주도 대체 수행 판정 (eq_submit인 경우 판정 후 즉시 submit 처리)
    eq_judgment: dict | None = None
    eq_submit = is_equivalency_submit(fn_calls) if fn_calls else False
    if eq_submit and pending_submit_args and student_id:
        judge_prompt = await run_in_threadpool(
            build_equivalency_judge_prompt, student_id, next(
                (args for fn, args in fn_calls if fn == "check_mission_equivalency"), {}
            )
        )
        if judge_prompt:
            eq_judgment = await judge_mission_equivalency(judge_prompt, body.message)
            print(f"[Equivalency] judgment={eq_judgment}")
            if eq_judgment.get("approved") and not eq_judgment.get("need_clarification"):
                submit_result = await run_in_threadpool(execute_submit, student_id, pending_submit_args)
                exec_results.submit = submit_result
                print(f"[Equivalency] submit executed: {submit_result.status}")
            pending_submit_args = None  # 판정 완료, 태그 경로 비활성화

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
    print(f"[Prompt] function_results={'Y' if '[기능 실행 결과]' in system_prompt else 'N'}")

    gemma_user_message = _gemma_user_message(body.message, exec_results)
    if not is_greet and fn_calls and not _needs_history_for_action(fn_calls):
        messages = [{"role": "user", "content": gemma_user_message}]
    else:
        history = await run_in_threadpool(fetch_messages, body.session_id, _CHAT_CONTEXT_MESSAGE_LIMIT)
        if not is_greet:
            history.append({"role": "user", "content": gemma_user_message})
        messages = history if history else [
            {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
        ]

    action_ack = build_conflict_ack() if combo == "conflict" else (None if eq_submit else build_action_ack(exec_results))
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

        if eq_submit:
            ai_message = await run_in_threadpool(
                _finalize_equivalency_response,
                ai_message,
                student_id,
                pending_submit_args,
                exec_results,
            )

        ai_message = _filter_ai_response(ai_message)
        llm_only = ai_message
        if not eq_submit and action_ack and action_ack.mode is ResponseMode.PREFIX_WITH_GEMMA:
            ai_message = _prepend_db_action_ack(ai_message, exec_results)
    print(f"[Chat] -> mode={_response_mode_label(action_ack, eq_submit)} response={_short(ai_message)!r}")

    if not is_greet:
        await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, detected_function)
    await run_in_threadpool(_save_message_safe, body.session_id, "assistant", ai_message)
    if not is_greet:
        await run_in_threadpool(_save_natural_language_confirmation_pending, student_id, body.message, clarify_reason)
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
    }
    if exec_results and exec_results.submit:
        debug["submit_result"] = {
            "status": exec_results.submit.status.value,
            "result_type": exec_results.submit.result_type,
            "db_changed": exec_results.submit.db_changed,
        }
    if submit_validation:
        debug["submit_validation"] = submit_validation.to_debug()
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
    print(f"\n[Stream] <- {_short(body.message)!r} session={body.session_id[:8]}")

    async def event_stream():
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
        profile = await run_in_threadpool(fetch_profile, body.session_id)
        student_id = profile["student_id"] if profile else None
        student_name = profile.get("student_name", "") if profile else ""
        mission_id = None
        mission_row = None
        if student_id:
            mission_row = await run_in_threadpool(get_student_mission_db, student_id, _kst_today())
            if mission_row:
                mission_id = mission_row.get("mission_id")
                current_mission_title = mission_row.get("mission_name") or current_mission_title

        if not is_greet and student_id:
            status_result = await _handle_current_mission_status_question(
                student_id,
                body.session_id,
                body.message,
                mission_row,
            )
            if status_result:
                async for event in _fake_stream_template_response(status_result["response"]):
                    yield event
                yield _done_sse(status_result.get("ui_action"), status_result.get("debug"))
                return

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
                        async for event in _fake_stream_template_response(accepted_result["response"]):
                            yield event
                        yield _done_sse(accepted_result.get("ui_action"), accepted_result.get("debug"))
                        return

                if action_type in ("mission_change_reason", "mission_dislike_confirm", "mission_change_method"):
                    # 버튼 대기 중 → 일반 채팅 차단, 기존 버튼 재전달
                    print(f"[UiActionGuard] blocking chat, active action_type={action_type} action_id={active_ui.get('action_id')}")
                    block_message = "아래 선택지 중 하나를 골라줘!"
                    async for event in _fake_stream_template_response(block_message):
                        yield event
                    yield _done_sse(ui_action_payload, {"intent": "UI_ACTION_GUARD", "ui_action_type": action_type})
                    return

                if action_type == "awaiting_replacement_mission":
                    result = await _handle_replacement_mission_input(student_id, body.session_id, body.message, active_ui)
                    await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, "awaiting_replacement_mission")
                    await run_in_threadpool(_save_message_safe, body.session_id, "assistant", result["response"])
                    async for event in _fake_stream_template_response(result["response"]):
                        yield event
                    yield _done_sse(result["ui_action"], result["debug"])
                    return

        if not is_greet and student_id:
            pending_started = time.perf_counter()
            pending_outcome = await handle_pending_action(student_id, body.message, body.session_id)
            if pending_outcome:
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

        if not is_greet and student_id:
            orphan_acceptance = await _handle_orphan_mission_acceptance(
                student_id,
                body.session_id,
                body.message,
                mission_row,
            )
            if orphan_acceptance:
                async for event in _fake_stream_template_response(orphan_acceptance["response"]):
                    yield event
                yield _done_sse(orphan_acceptance.get("ui_action"), orphan_acceptance.get("debug"))
                return

        if not is_greet and student_id and mission_row:
            negative_started = time.perf_counter()
            negative_activity_result = await _handle_negative_activity_request(
                student_id,
                body.session_id,
                body.message,
                mission_row,
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

        if not is_greet and student_id and mission_row:
            dislike_started = time.perf_counter()
            if await classify_mission_dislike(body.message, current_mission_title):
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
        clarify_hint_override = ""
        clarify_reason = ""

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
            intent, intent_ms = await step_classify(body.message, current_mission_title)
            if intent == "B" and "취소" in body.message:
                norm = normalize_b_input(body.message, current_mission_title, mission_id)
                if norm.should_clarify:
                    intent = "D"
                    clarify_reason = norm.reason
                    clarify_hint_override = CLARIFY_HINT_MAP.get(norm.reason, CLARIFY_HINT_DEFAULT)
                    print(f"[Route] B -> D clarify ({norm.reason or 'default'})")
                elif "취소" in norm.message:
                    fn_calls, qwen_ms = await step_extract_functions(norm.message)
                    detected_function = fn_calls[0][0] if fn_calls else None
                    fn_args = fn_calls[0][1] if fn_calls else {}

            submit_report_call = None if fn_calls else detect_submit_report_call(body.message)
            history_call = None if submit_report_call or fn_calls else detect_history_call(body.message)
            mission_info_call = None if submit_report_call or history_call or fn_calls else detect_mission_info_call(body.message)
            if submit_report_call:
                intent = "B"
                fn_calls = [submit_report_call]
                detected_function = submit_report_call[0]
                fn_args = submit_report_call[1]
                print("[Route] submit report forced to submit_mission_result")
            elif history_call:
                intent = "B"
                fn_calls = [history_call]
                detected_function = history_call[0]
                fn_args = history_call[1]
                print("[Route] history query forced to get_user_history")
            elif mission_info_call:
                intent = "B"
                fn_calls = [mission_info_call]
                detected_function = mission_info_call[0]
                fn_args = mission_info_call[1]
                print("[Route] mission info query forced to get_mission_info")
            intent_label = {"A": "일반 대화", "B": "미션 액션", "C": "정보 조회", "D": "의도 불명확"}.get(intent, intent)
            yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'intent', 'value': intent, 'label': intent_label, 'ms': intent_ms}, ensure_ascii=False)}\n\n"

            if fn_calls:
                qwen_ms = 0
                yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'qwen', 'calls': [[fn, args] for fn, args in fn_calls], 'ms': qwen_ms}, ensure_ascii=False)}\n\n"
            elif intent == "B":
                norm = normalize_b_input(body.message, current_mission_title, mission_id)
                if norm.should_clarify:
                    intent = "D"
                    clarify_reason = norm.reason
                    clarify_hint_override = CLARIFY_HINT_MAP.get(norm.reason, CLARIFY_HINT_DEFAULT)
                    print(f"[Route] B -> D clarify ({norm.reason or 'default'})")
                else:
                    fn_calls, qwen_ms = await step_extract_functions(norm.message)
                    detected_function = fn_calls[0][0] if fn_calls else None
                    fn_args = fn_calls[0][1] if fn_calls else {}
                    yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'qwen', 'calls': [[fn, args] for fn, args in fn_calls], 'ms': qwen_ms}, ensure_ascii=False)}\n\n"
            if intent == "C":
                try:
                    t_rag = time.perf_counter()
                    rag_result = await run_in_threadpool(search_rag, body.message)
                    rag_ms = round((time.perf_counter() - t_rag) * 1000)
                    hits = len(rag_result["chunks"]) + len(rag_result["faqs"])
                    yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'rag', 'hits': hits, 'ms': rag_ms}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    print(f"[RAG] 검색 실패 (무시): {e}")

        clarify_response = _clarify_template(clarify_reason, body.message, current_mission_title)
        if clarify_response:
            print(f"[Clarify] template reason={clarify_reason} response={_short(clarify_response)!r}")
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, detected_function)
            await run_in_threadpool(_save_message_safe, body.session_id, "assistant", clarify_response)
            background_tasks.add_task(extract_and_save_memory, student_id, body.message, False)
            async for event in _fake_stream_template_response(clarify_response):
                yield event
            await run_in_threadpool(_save_natural_language_confirmation_pending, student_id, body.message, clarify_reason)
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
            exec_results, fn_calls, pending_submit_args, combo, submit_validation = await run_in_threadpool(
                step_execute,
                student_id,
                fn_calls,
                combo,
                body.message,
                current_mission_title,
                mission_id,
            )
        elif fn_calls:
            print("[DB] skipped: missing student_id")
        if combo == "conflict":
            detected_function = None
        if exec_results.adjustment and exec_results.adjustment.status is AdjustmentStatus.CHANGED:
            await _cleanup_completed_mission_change(student_id, body.session_id)

        if submit_validation and not submit_validation.should_execute:
            ai_message = build_submit_validation_response(submit_validation, current_mission_title)
            print(f"[Validator.submit] response={_short(ai_message)!r}")
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
        eq_judgment: dict | None = None
        eq_submit = is_equivalency_submit(fn_calls) if fn_calls else False
        if eq_submit and pending_submit_args and student_id:
            judge_prompt = await run_in_threadpool(
                build_equivalency_judge_prompt, student_id, next(
                    (args for fn, args in fn_calls if fn == "check_mission_equivalency"), {}
                )
            )
            if judge_prompt:
                eq_judgment = await judge_mission_equivalency(judge_prompt, body.message)
                print(f"[Equivalency] judgment={eq_judgment}")
                if eq_judgment.get("approved") and not eq_judgment.get("need_clarification"):
                    submit_result = await run_in_threadpool(execute_submit, student_id, pending_submit_args)
                    exec_results.submit = submit_result
                    print(f"[Equivalency] submit executed: {submit_result.status}")
                pending_submit_args = None  # 판정 완료, 태그 경로 비활성화

        system_prompt = await run_in_threadpool(
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
                {"role": "user", "content": f"안녕! 오늘 미션 '{current_mission_title}'을 소개하고 응원해 줘."}
            ]

        yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'generating'}, ensure_ascii=False)}\n\n"

        t_gen = time.perf_counter()
        tag_markers = ("[APPROVED]", "[DENIED]")
        # eq_submit은 위에서 이미 계산됨; pending_submit_args=None이면 태그 판정 경로 비활성
        action_ack = build_conflict_ack() if combo == "conflict" else (None if eq_submit else build_action_ack(exec_results))
        server_prefix = (
            action_ack.message
            if action_ack and action_ack.mode is ResponseMode.PREFIX_WITH_GEMMA
            else ""
        )
        ai_message = ""
        llm_message = ""
        prefix_buffer_mode = bool(server_prefix) and not eq_submit

        if mission_change_guard_result and not fn_calls:
            ai_message = mission_change_guard_result["message"]
            async for event in _fake_stream_template_response(ai_message):
                yield event
        elif action_ack and action_ack.mode is ResponseMode.SERVER_ONLY:
            ai_message = action_ack.message
            async for event in _fake_stream_template_response(ai_message):
                yield event
        else:
            if server_prefix:
                print(f"[Response] prefix={_short(server_prefix)!r}")
                ai_message = f"{server_prefix}\n"
                async for event in _fake_stream_template_response(ai_message):
                    yield event

            token_buf = ""
            lookahead_limit = len(server_prefix) + 10 if server_prefix else 0
            lookahead_buf = ""
            prefix_echo_handled = not prefix_buffer_mode
            try:
                async for token in generate_chat_message_stream(system_prompt, messages):
                    llm_message += token

                    if not prefix_echo_handled:
                        lookahead_buf += token
                        if len(lookahead_buf) >= lookahead_limit:
                            cleaned = _strip_leading_ack(lookahead_buf, server_prefix)
                            prefix_echo_handled = True
                            ai_message += cleaned
                            if cleaned.strip():
                                yield f"data: {_json.dumps({'type': 'token', 'content': cleaned}, ensure_ascii=False)}\n\n"
                        continue

                    ai_message += token
                    if eq_submit:
                        token_buf += token
                        for tag in tag_markers:
                            if tag in token_buf:
                                token_buf = token_buf.replace(tag, "")
                        if "[" not in token_buf:
                            if token_buf:
                                yield f"data: {_json.dumps({'type': 'token', 'content': token_buf}, ensure_ascii=False)}\n\n"
                            token_buf = ""
                    else:
                        yield f"data: {_json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {_json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
                return
            if not prefix_echo_handled and lookahead_buf:
                cleaned = _strip_leading_ack(lookahead_buf, server_prefix)
                ai_message += cleaned
                if cleaned.strip():
                    yield f"data: {_json.dumps({'type': 'token', 'content': cleaned}, ensure_ascii=False)}\n\n"
            elif token_buf:
                for tag in tag_markers:
                    token_buf = token_buf.replace(tag, "")
                if token_buf.strip():
                    yield f"data: {_json.dumps({'type': 'token', 'content': token_buf}, ensure_ascii=False)}\n\n"

        gen_ms = round((time.perf_counter() - t_gen) * 1000)

        if "[APPROVED]" in llm_message:
            print("[Equiv] approved")
        elif "[DENIED]" in llm_message:
            print("[Equiv] denied")
        elif eq_submit:
            print(f"[Equiv] missing tag tail={_short(llm_message[-80:])!r}")

        if eq_submit:
            visible_before_finalize = (
                llm_message.replace("[APPROVED]", "").replace("[DENIED]", "").strip()
            )
            finalized_message = await run_in_threadpool(
                _finalize_equivalency_response,
                llm_message,
                student_id,
                pending_submit_args,
                exec_results,
            )
            if finalized_message.startswith(visible_before_finalize):
                finalize_suffix = finalized_message[len(visible_before_finalize):]
                if finalize_suffix.strip():
                    async for event in _fake_stream_template_response(finalize_suffix):
                        yield event
            ai_message = finalized_message
        print(f"[Stream] -> mode={_response_mode_label(action_ack, eq_submit)} response={_short(ai_message)!r}")

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
                "total_ms": total_ms,
            },
            "rag_hits": {"chunks": len(rag_result["chunks"]), "faqs": len(rag_result["faqs"])},
        }
        if exec_results.submit:
            debug_payload["submit_result"] = {
                "status": exec_results.submit.status.value,
                "result_type": exec_results.submit.result_type,
                "db_changed": exec_results.submit.db_changed,
            }
        if submit_validation:
            debug_payload["submit_validation"] = submit_validation.to_debug()
        xp_award = _award_mission_xp_if_success(exec_results, student_id, mission_id)
        _attach_xp_award_to_debug(debug_payload, xp_award)
        if not is_greet:
            await run_in_threadpool(_save_message_safe, body.session_id, "user", body.message, detected_function)
        save_content = ai_message.strip()
        await run_in_threadpool(_save_message_safe, body.session_id, "assistant", save_content)
        if not is_greet:
            await run_in_threadpool(_save_natural_language_confirmation_pending, student_id, body.message, clarify_reason)
            background_tasks.add_task(extract_and_save_memory, student_id, body.message, False)

        mission_status = None
        if exec_results.submit and exec_results.submit.status.value == "saved":
            mission_status = exec_results.submit.result_type
        yield _done_sse(
            None,
            debug_payload,
            **_mission_review_trigger_kwargs(exec_results.submit if exec_results else None, mission_id),
        )
        if exec_results.cancel and exec_results.cancel.status is CancelStatus.CANCELLED_SUBMIT:
            today = _kst_today()
            background_tasks.add_task(_cancel_sheet_bg, student_id, today)
        if mission_status:
            checkin_id = exec_results.submit.checkin_id if exec_results.submit else None
            background_tasks.add_task(_sync_sheet_bg, body.session_id, user_input, ai_message, mission_status, checkin_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
