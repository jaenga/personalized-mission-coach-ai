import time
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from database import (
    init_db, assign_daily_missions, _kst_today,
    get_student_by_credentials, create_chat_session,
    save_profile, fetch_profile,
    save_message, fetch_messages, delete_messages,
    get_student_mission_db, get_student_info_db,
    mark_synced,
)
from ollama_client import generate_chat_message, generate_chat_message_stream, OLLAMA_MODEL
from rag import search_rag, preload_model
from sheets import update_mission_result, cancel_mission_result, generate_daily_status
from qwen_client import preload_qwen
from executor import AdjustmentStatus, CancelStatus, ExecResults, execute_submit
from response_builder import ResponseMode, build_action_ack, build_conflict_ack
from prompts import CLARIFY_HINT_MISSION_REPORT

def _needs_history_for_action(fn_calls: list[tuple[str, dict]]) -> bool:
    return any(fn == "submit_mission_result" for fn, _ in fn_calls)


def _save_message_safe(session_id: str, role: str, content: str, detected_function: str | None = None) -> int:
    try:
        return save_message(session_id, role, content, detected_function)
    except Exception as e:
        print(f"[Chat] message save failed role={role} error={type(e).__name__}: {e}")
        return 0


def _short(text: str | None, limit: int = 90) -> str:
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


def _response_mode_label(action_ack, eq_submit: bool) -> str:
    if action_ack:
        return action_ack.mode.value
    if eq_submit:
        return "equivalency"
    return "gemma"


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


# ── 펑션별 Gemma 힌트 ──────────────────────────────────────────────────────────

app = FastAPI(title="AI 생활습관 코치 MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    preload_model()
    preload_qwen()
    try:
        assigned = assign_daily_missions()
        if assigned:
            print(f"[startup] 오늘 미션 배정: {assigned}명")
    except Exception as e:
        print(f"[startup] 미션 배정 실패 (무시): {e}")
    try:
        today = _kst_today()
        added = generate_daily_status(today)
        if added:
            print(f"[startup] daily_status {today}: {added}명 행 추가됨")
    except Exception as e:
        print(f"[startup] daily_status 생성 실패 (무시): {e}")


# ── 학생 본인 확인 ─────────────────────────────────────────────────────────────

class VerifyRequest(BaseModel):
    student_name: str = Field(..., min_length=1)
    phone_last4:  str = Field(..., min_length=4, max_length=4, pattern=r"^\d{4}$")


@app.post("/verify-student")
def post_verify_student(body: VerifyRequest):
    student = get_student_by_credentials(body.student_name, body.phone_last4)
    if not student:
        raise HTTPException(status_code=404, detail="일치하는 학생을 찾을 수 없어요.")
    return student


# ── 프로필 저장/조회 ───────────────────────────────────────────────────────────

class ProfileRequest(BaseModel):
    session_id:   str = Field(..., min_length=1)
    student_id:   int
    student_name: str = Field(..., min_length=1)


@app.post("/profile")
def post_profile(body: ProfileRequest):
    db_session_id = create_chat_session(body.student_id)
    save_profile(body.session_id, body.student_id, body.student_name, db_session_id)
    return {"ok": True}


@app.get("/profile/{session_id}")
def get_profile(session_id: str):
    profile = fetch_profile(session_id)
    if not profile:
        raise HTTPException(status_code=404, detail="프로필 없음")
    return profile


# ── 오늘 미션 조회 ─────────────────────────────────────────────────────────────

@app.get("/mission")
def get_mission(student_id: int | None = None):
    today = _kst_today()
    if student_id:
        mission = get_student_mission_db(student_id, today)
        if mission:
            return mission
    return {
        "mission_id": None,
        "mission_name": "오늘의 미션",
        "category": "",
        "difficulty": "",
        "status": "assigned",
    }


# ── 금지어 감지 ────────────────────────────────────────────────────────────────

FORBIDDEN_WORDS = ["엄마", "아빠", "부모님", "가족", "형", "언니", "오빠", "동생", "친구", "선생님"]


def detect_violations(ai_message: str, user_input: str) -> list[str]:
    return [
        f"금지어 언급: '{w}' (사용자가 먼저 말하지 않음)"
        for w in FORBIDDEN_WORDS
        if w in ai_message and w not in user_input
    ]


# ── 배경 작업 ──────────────────────────────────────────────────────────────────

async def _cancel_sheet_bg(student_id: int, today: str):
    try:
        cancel_mission_result(student_id, today)
    except Exception as e:
        print(f"[cancel] 시트 초기화 실패: {e}")


async def _sync_sheet_bg(
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
        print(f"[sync] mission_id 없음 — 시트 동기화 스킵 (student_id={student_id})")
        return

    # 구글 시트 업데이트만 (DB 저장은 executor에서 완료)
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


# ── 채팅 ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:    str       = Field(..., min_length=1)
    session_id: str       = Field(..., min_length=1)
    mission:    str | None = None


@app.post("/chat")
async def post_chat(body: ChatRequest, background_tasks: BackgroundTasks):
    from pipeline import (
        step_classify, step_normalize_b_input, step_extract_functions,
        step_execute, step_build_hints, classify_multi, is_equivalency_submit,
    )

    mission_title = body.mission or "오늘의 미션"
    is_greet = body.message == "__GREET__"
    print(f"\n[Chat] <- {_short(body.message)!r} session={body.session_id[:8]}")

    intent = "A"
    fn_calls: list[tuple[str, dict]] = []
    detected_function = None
    fn_args: dict = {}
    rag_result: dict = {"chunks": [], "faqs": [], "context": ""}
    intent_ms = 0
    qwen_ms = 0
    clarify_hint_override = ""

    if not is_greet:
        # ── 1. 인텐트 분류 (미션명 컨텍스트 포함) ──────────────────────────────
        intent, intent_ms = await step_classify(body.message, mission_title)

        # ── 2. 인텐트별 모듈 ───────────────────────────────────────────────────
        if intent == "B":
            qwen_input, should_clarify = step_normalize_b_input(body.message, mission_title)
            if should_clarify:
                intent = "D"
                clarify_hint_override = CLARIFY_HINT_MISSION_REPORT
                print("[Route] B -> D clarify (mission report)")
            else:
                fn_calls, qwen_ms = await step_extract_functions(qwen_input)
                detected_function = fn_calls[0][0] if fn_calls else None
                fn_args = fn_calls[0][1] if fn_calls else {}
        if intent == "C":
            try:
                rag_result = search_rag(body.message)
            except Exception as e:
                print(f"[RAG] 검색 실패 (무시): {e}")

    # ── 3. executor (DB 실행) ──────────────────────────────────────────────────
    combo = classify_multi(fn_calls) if fn_calls else None
    profile = fetch_profile(body.session_id)
    student_id = profile["student_id"] if profile else None
    print(f"[Route] student={student_id or '-'} combo={combo or '-'} calls={_fn_list(fn_calls)}")
    exec_results = None
    pending_submit_args = None

    if student_id and fn_calls:
        exec_results, fn_calls, pending_submit_args, combo = step_execute(student_id, fn_calls, combo)
    elif fn_calls:
        print("[DB] skipped: missing student_id")
    if combo == "conflict":
        detected_function = None

    # ── 4. hint builder (시스템 프롬프트 조립) ─────────────────────────────────
    system_prompt = step_build_hints(
        student_id=student_id,
        fn_calls=fn_calls,
        exec_results=exec_results or ExecResults(),
        combo=combo,
        mission_title=mission_title,
        rag_context=rag_result["context"],
        intent=intent,
        is_greet=is_greet,
        clarify_hint_override=clarify_hint_override,
    )
    print(f"[Prompt] function_results={'Y' if '[기능 실행 결과]' in system_prompt else 'N'}")

    # ── 5. history fetch → LLM 호출 ───────────────────────────────────────────
    gemma_user_message = _gemma_user_message(body.message, exec_results)
    if not is_greet and fn_calls and not _needs_history_for_action(fn_calls):
        messages = [{"role": "user", "content": gemma_user_message}]
    else:
        history = fetch_messages(body.session_id)
        if not is_greet:
            history.append({"role": "user", "content": gemma_user_message})
        messages = history if history else [
            {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
        ]

    eq_submit = is_equivalency_submit(fn_calls) if fn_calls else False
    action_ack = build_conflict_ack() if combo == "conflict" else (None if eq_submit else build_action_ack(exec_results))
    llm_only = ""
    call1_ms = 0
    if action_ack and action_ack.mode is ResponseMode.SERVER_ONLY:
        ai_message = action_ack.message
    else:
        try:
            ai_message, call1_ms = await generate_chat_message(system_prompt, messages)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}")

        # ── 6. equivalency→submit 후처리 (LLM 판단 후 DB 저장) ────────────────────
        if eq_submit and exec_results:
            ai_message = _finalize_equivalency_response(
                ai_message,
                student_id,
                pending_submit_args,
                exec_results,
            )

        llm_only = ai_message
        if not eq_submit and action_ack and action_ack.mode is ResponseMode.PREFIX_WITH_GEMMA:
            ai_message = _prepend_db_action_ack(ai_message, exec_results)
    print(f"[Chat] -> mode={_response_mode_label(action_ack, eq_submit)} response={_short(ai_message)!r}")

    # ── 7. 메시지 저장 (history에는 server prefix 제외한 LLM 응답만 저장) ──────
    if not is_greet:
        _save_message_safe(body.session_id, "user", body.message, detected_function)
    _save_message_safe(body.session_id, "assistant", llm_only or ai_message)

    user_input = body.message if not is_greet else ""
    violations = detect_violations(ai_message, user_input)

    # ── 8. 시트 동기화 (백그라운드) ───────────────────────────────────────────
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

    return {
        "response": ai_message,
        "mission_completed": mission_status is not None,
        "detected_function": detected_function,
        "sources": sources,
        "debug": {
            "intent": intent,
            "fn_args": fn_args,
            "violations": violations,
            "system_prompt": system_prompt,
            "history_turns": len(messages),
            "model": OLLAMA_MODEL,
            "timing": {"intent_ms": intent_ms, "qwen_ms": qwen_ms, "llm_ms": call1_ms},
            "rag_hits": {"chunks": len(rag_result["chunks"]), "faqs": len(rag_result["faqs"])},
        },
    }


@app.post("/chat/stream")
async def post_chat_stream(body: ChatRequest, background_tasks: BackgroundTasks):
    import json as _json
    from pipeline import (
        step_classify, step_normalize_b_input, step_extract_functions,
        step_execute, step_build_hints, classify_multi, is_equivalency_submit,
    )

    mission_title = body.mission or "오늘의 미션"
    is_greet = body.message == "__GREET__"
    print(f"\n[Stream] <- {_short(body.message)!r} session={body.session_id[:8]}")

    async def event_stream():
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

        if not is_greet:
            # ── Stage 1: 인텐트 분류 (미션명 컨텍스트 포함) ─────────────────
            intent, intent_ms = await step_classify(body.message, mission_title)
            intent_label = {"A": "일반 대화", "B": "미션 액션", "C": "정보 조회", "D": "의도 불명확"}.get(intent, intent)
            yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'intent', 'value': intent, 'label': intent_label, 'ms': intent_ms}, ensure_ascii=False)}\n\n"

            # ── Stage 2: 인텐트별 모듈 ──────────────────────────────────────
            if intent == "B":
                qwen_input, should_clarify = step_normalize_b_input(body.message, mission_title)
                if should_clarify:
                    intent = "D"
                    clarify_hint_override = CLARIFY_HINT_MISSION_REPORT
                    print("[Route] B -> D clarify (mission report)")
                else:
                    fn_calls, qwen_ms = await step_extract_functions(qwen_input)
                    detected_function = fn_calls[0][0] if fn_calls else None
                    fn_args = fn_calls[0][1] if fn_calls else {}
                    yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'qwen', 'calls': [[fn, args] for fn, args in fn_calls], 'ms': qwen_ms}, ensure_ascii=False)}\n\n"
            if intent == "C":
                try:
                    t_rag = time.perf_counter()
                    rag_result = search_rag(body.message)
                    rag_ms = round((time.perf_counter() - t_rag) * 1000)
                    hits = len(rag_result["chunks"]) + len(rag_result["faqs"])
                    yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'rag', 'hits': hits, 'ms': rag_ms}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    print(f"[RAG] 검색 실패 (무시): {e}")

        # ── Stage 3: executor (DB 실행) + hint builder (프롬프트 조립) ────
        combo = classify_multi(fn_calls) if fn_calls else None
        profile = fetch_profile(body.session_id)
        student_id = profile["student_id"] if profile else None
        print(f"[Route] student={student_id or '-'} combo={combo or '-'} calls={_fn_list(fn_calls)}")
        exec_results = ExecResults()
        pending_submit_args = None

        if student_id and fn_calls:
            exec_results, fn_calls, pending_submit_args, combo = step_execute(student_id, fn_calls, combo)
        elif fn_calls:
            print("[DB] skipped: missing student_id")
        if combo == "conflict":
            detected_function = None

        system_prompt = step_build_hints(
            student_id=student_id,
            fn_calls=fn_calls,
            exec_results=exec_results,
            combo=combo,
            mission_title=mission_title,
            rag_context=rag_result["context"],
            intent=intent,
            is_greet=is_greet,
            clarify_hint_override=clarify_hint_override,
        )
        print(f"[Prompt] function_results={'Y' if '[기능 실행 결과]' in system_prompt else 'N'}")

        # 이전 히스토리 fetch → 현재 user 메시지 append (DB 저장은 LLM 응답 후)
        gemma_user_message = _gemma_user_message(body.message, exec_results)
        if not is_greet and fn_calls and not _needs_history_for_action(fn_calls):
            messages = [{"role": "user", "content": gemma_user_message}]
        else:
            history = [{"role": m["role"], "content": m["content"]} for m in fetch_messages(body.session_id)]
            if not is_greet:
                history.append({"role": "user", "content": gemma_user_message})
            messages = history if history else [
                {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
            ]

        yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'generating'}, ensure_ascii=False)}\n\n"

        # ── Stage 4: 토큰 스트리밍 ───────────────────────────────────────────
        t_gen = time.perf_counter()
        _TAG_MARKERS = ("[APPROVED]", "[DENIED]")
        eq_submit = is_equivalency_submit(fn_calls) if fn_calls else False
        action_ack = build_conflict_ack() if combo == "conflict" else (None if eq_submit else build_action_ack(exec_results))
        server_prefix = (
            action_ack.message
            if action_ack and action_ack.mode is ResponseMode.PREFIX_WITH_GEMMA
            else ""
        )
        ai_message = ""
        llm_message = ""
        prefix_buffer_mode = bool(server_prefix) and not eq_submit

        if action_ack and action_ack.mode is ResponseMode.SERVER_ONLY:
            ai_message = action_ack.message
            yield f"data: {_json.dumps({'type': 'token', 'content': ai_message}, ensure_ascii=False)}\n\n"
        else:
            if server_prefix:
                print(f"[Response] prefix={_short(server_prefix)!r}")
                ai_message = f"{server_prefix}\n"
                yield f"data: {_json.dumps({'type': 'token', 'content': ai_message}, ensure_ascii=False)}\n\n"

            token_buf = ""
            # lookahead: prefix만큼 버퍼링 후 에코 제거, 이후 즉시 yield
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
                        for tag in _TAG_MARKERS:
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
            # 스트림이 짧아 lookahead 버퍼를 다 못 소진한 경우
            if not prefix_echo_handled and lookahead_buf:
                cleaned = _strip_leading_ack(lookahead_buf, server_prefix)
                ai_message += cleaned
                if cleaned.strip():
                    yield f"data: {_json.dumps({'type': 'token', 'content': cleaned}, ensure_ascii=False)}\n\n"
            elif token_buf:
                for tag in _TAG_MARKERS:
                    token_buf = token_buf.replace(tag, "")
                if token_buf.strip():
                    yield f"data: {_json.dumps({'type': 'token', 'content': token_buf}, ensure_ascii=False)}\n\n"

        gen_ms = round((time.perf_counter() - t_gen) * 1000)

        # ── equivalency→submit 태그 감지 + 후처리 ────────────────────────────
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
            finalized_message = _finalize_equivalency_response(
                llm_message,
                student_id,
                pending_submit_args,
                exec_results,
            )
            if finalized_message.startswith(visible_before_finalize):
                finalize_suffix = finalized_message[len(visible_before_finalize):]
                if finalize_suffix.strip():
                    yield f"data: {_json.dumps({'type': 'token', 'content': finalize_suffix}, ensure_ascii=False)}\n\n"
            ai_message = finalized_message
        print(f"[Stream] -> mode={_response_mode_label(action_ack, eq_submit)} response={_short(ai_message)!r}")

        total_ms = round((time.perf_counter() - t_total) * 1000)
        user_input = body.message if not is_greet else ""
        debug_payload = {
            "intent": intent,
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
        yield f"data: {_json.dumps({'type': 'done', 'debug': debug_payload}, ensure_ascii=False)}\n\n"

        # ── 후처리: 메시지 저장 + 시트 동기화 ────────────────────────────────
        if not is_greet:
            _save_message_safe(body.session_id, "user", body.message, detected_function)
        llm_save = llm_message.replace("[APPROVED]", "").replace("[DENIED]", "").strip()
        _save_message_safe(body.session_id, "assistant", llm_save or ai_message)
        mission_status = None
        if exec_results.submit and exec_results.submit.status.value == "saved":
            mission_status = exec_results.submit.result_type
        if exec_results.cancel and exec_results.cancel.status is CancelStatus.CANCELLED_SUBMIT:
            today = _kst_today()
            background_tasks.add_task(_cancel_sheet_bg, student_id, today)
        if mission_status:
            checkin_id = exec_results.submit.checkin_id if exec_results.submit else None
            background_tasks.add_task(_sync_sheet_bg, body.session_id, user_input, ai_message, mission_status, checkin_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/chat/{session_id}")
def get_chat(session_id: str):
    return fetch_messages(session_id)


@app.delete("/chat/{session_id}")
def delete_chat(session_id: str):
    count = delete_messages(session_id)
    return {"ok": True, "deleted": count}


@app.post("/admin/generate-daily")
def post_generate_daily():
    try:
        today = _kst_today()
        added = generate_daily_status(today)
        return {"ok": True, "date": today, "added": added}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
