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
    save_mission_result, mark_synced,
    has_checkin_today,
)
from ollama_client import generate_chat_message, generate_chat_message_stream, OLLAMA_MODEL
from rag import search_rag, preload_model
from sheets import update_mission_result, cancel_mission_result, generate_daily_status
from qwen_client import preload_qwen

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
    detected_function: str,
):
    profile = fetch_profile(session_id)
    if not profile:
        return

    today = _kst_today()
    student_id = profile["student_id"]

    # DB에서 학생/미션 정보 가져오기
    student_info = get_student_info_db(student_id) or {}
    mission_info = get_student_mission_db(student_id, today) or {}

    mission_id = mission_info.get("mission_id")
    if not mission_id:
        print(f"[sync] mission_id 없음 — 시트 동기화 스킵 (student_id={student_id})")
        return

    # DB 저장: 힌트 빌드에서 이미 저장된 경우 스킵, 아니면 여기서 저장
    result_id = None
    if not has_checkin_today(student_id):
        result_id = save_mission_result(
            student_id=student_id,
            mission_id=mission_id,
            status=status,
            result_reason=user_message,
            detected_function=detected_function,
        )

    # 구글 시트 업데이트
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
        if result_id is not None:
            mark_synced(result_id)
    except Exception:
        pass


# ── 채팅 ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:    str       = Field(..., min_length=1)
    session_id: str       = Field(..., min_length=1)
    mission:    str | None = None


@app.post("/chat")
async def post_chat(body: ChatRequest, background_tasks: BackgroundTasks):
    from pipeline import (
        step_classify, step_extract_functions, step_execute, step_build_hints,
        classify_multi, is_equivalency_submit,
    )
    from executor import execute_submit

    mission_title = body.mission or "오늘의 미션"
    is_greet = body.message == "__GREET__"

    intent = "A"
    fn_calls: list[tuple[str, dict]] = []
    detected_function = None
    fn_args: dict = {}
    rag_result: dict = {"chunks": [], "faqs": [], "context": ""}
    intent_ms = 0
    qwen_ms = 0

    if not is_greet:
        # ── 1. 인텐트 분류 ─────────────────────────────────────────────────────
        intent, intent_ms = await step_classify(body.message)

        # ── 2. 인텐트별 모듈 ───────────────────────────────────────────────────
        if intent == "B":
            fn_calls, qwen_ms = await step_extract_functions(body.message)
            detected_function = fn_calls[0][0] if fn_calls else None
            fn_args = fn_calls[0][1] if fn_calls else {}
            print(f"[Chat] B-route: calls={fn_calls}")
        elif intent == "C":
            try:
                rag_result = search_rag(body.message)
            except Exception as e:
                print(f"[RAG] 검색 실패 (무시): {e}")

    # ── 3. executor (DB 실행) ──────────────────────────────────────────────────
    combo = classify_multi(fn_calls) if fn_calls else None
    profile = fetch_profile(body.session_id)
    student_id = profile["student_id"] if profile else None
    exec_results = None
    pending_submit_args = None

    if student_id and fn_calls:
        exec_results, fn_calls, pending_submit_args = step_execute(student_id, fn_calls, combo)

    # ── 4. hint builder (시스템 프롬프트 조립) ─────────────────────────────────
    system_prompt = step_build_hints(
        student_id=student_id,
        fn_calls=fn_calls,
        exec_results=exec_results or __import__("executor").ExecResults(),
        combo=combo,
        mission_title=mission_title,
        rag_context=rag_result["context"],
        intent=intent,
        is_greet=is_greet,
    )

    # ── 5. history fetch → LLM 호출 ───────────────────────────────────────────
    history = fetch_messages(body.session_id)
    if not is_greet:
        history.append({"role": "user", "content": body.message})
    messages = history if history else [
        {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
    ]

    try:
        ai_message, call1_ms = await generate_chat_message(system_prompt, messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}")

    # ── 6. equivalency→submit 후처리 (LLM 판단 후 DB 저장) ────────────────────
    eq_submit = is_equivalency_submit(fn_calls) if fn_calls else False
    if eq_submit and "[APPROVED]" in ai_message and pending_submit_args and student_id:
        submit_result = execute_submit(student_id, pending_submit_args)
        if exec_results:
            exec_results.submit = submit_result
        ai_message = ai_message.replace("[APPROVED]", "").strip()
    elif eq_submit and "[DENIED]" in ai_message:
        ai_message = ai_message.replace("[DENIED]", "").strip()

    # ── 7. 메시지 저장 ────────────────────────────────────────────────────────
    if not is_greet:
        save_message(body.session_id, "user", body.message, detected_function)
    save_message(body.session_id, "assistant", ai_message)

    user_input = body.message if not is_greet else ""
    violations = detect_violations(ai_message, user_input)

    # ── 8. 시트 동기화 (백그라운드) ───────────────────────────────────────────
    mission_status = None
    if exec_results and exec_results.submit and exec_results.submit.status.value == "saved":
        mission_status = exec_results.submit.result_type
    if exec_results and exec_results.cancel:
        today = _kst_today()
        background_tasks.add_task(_cancel_sheet_bg, student_id, today)

    if mission_status:
        background_tasks.add_task(_sync_sheet_bg, body.session_id, user_input, ai_message, mission_status, detected_function)

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
        step_classify, step_extract_functions, step_execute, step_build_hints,
        classify_multi, is_equivalency_submit,
    )
    from executor import execute_submit, ExecResults

    mission_title = body.mission or "오늘의 미션"
    is_greet = body.message == "__GREET__"

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

        if not is_greet:
            # ── Stage 1: 인텐트 분류 ────────────────────────────────────────
            intent, intent_ms = await step_classify(body.message)
            intent_label = {"A": "일반 대화", "B": "미션 액션", "C": "정보 조회", "D": "의도 불명확"}.get(intent, intent)
            yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'intent', 'value': intent, 'label': intent_label, 'ms': intent_ms}, ensure_ascii=False)}\n\n"

            # ── Stage 2: 인텐트별 모듈 ──────────────────────────────────────
            if intent == "B":
                fn_calls, qwen_ms = await step_extract_functions(body.message)
                detected_function = fn_calls[0][0] if fn_calls else None
                fn_args = fn_calls[0][1] if fn_calls else {}
                yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'qwen', 'calls': [[fn, args] for fn, args in fn_calls], 'ms': qwen_ms}, ensure_ascii=False)}\n\n"
            elif intent == "C":
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
        exec_results = ExecResults()
        pending_submit_args = None

        if student_id and fn_calls:
            exec_results, fn_calls, pending_submit_args = step_execute(student_id, fn_calls, combo)

        system_prompt = step_build_hints(
            student_id=student_id,
            fn_calls=fn_calls,
            exec_results=exec_results,
            combo=combo,
            mission_title=mission_title,
            rag_context=rag_result["context"],
            intent=intent,
            is_greet=is_greet,
        )

        # 이전 히스토리 fetch → 현재 user 메시지 append → DB 저장
        history = [{"role": m["role"], "content": m["content"]} for m in fetch_messages(body.session_id)]
        if not is_greet:
            history.append({"role": "user", "content": body.message})
            save_message(body.session_id, "user", body.message, None)

        messages = history if history else [
            {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
        ]

        yield f"data: {_json.dumps({'type': 'pipeline', 'stage': 'generating'}, ensure_ascii=False)}\n\n"

        # ── Stage 4: 토큰 스트리밍 ───────────────────────────────────────────
        ai_message = ""
        t_gen = time.perf_counter()
        _TAG_MARKERS = ("[APPROVED]", "[DENIED]")
        eq_submit = is_equivalency_submit(fn_calls) if fn_calls else False
        token_buf = ""
        try:
            async for token in generate_chat_message_stream(system_prompt, messages):
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
        if token_buf:
            for tag in _TAG_MARKERS:
                token_buf = token_buf.replace(tag, "")
            if token_buf.strip():
                yield f"data: {_json.dumps({'type': 'token', 'content': token_buf}, ensure_ascii=False)}\n\n"

        gen_ms = round((time.perf_counter() - t_gen) * 1000)

        # ── equivalency→submit 태그 감지 + 후처리 ────────────────────────────
        eq_approved = False
        if "[APPROVED]" in ai_message:
            eq_approved = True
            ai_message = ai_message.replace("[APPROVED]", "").strip()
            print("[eq-tag] APPROVED 감지 → 성공 저장 예정")
        elif "[DENIED]" in ai_message:
            ai_message = ai_message.replace("[DENIED]", "").strip()
            print("[eq-tag] DENIED 감지 → 저장 안 함")
        elif eq_submit:
            print(f"[eq-tag] 태그 없음! 응답 끝부분: ...{ai_message[-80:]}")

        if eq_submit and eq_approved and pending_submit_args and student_id:
            submit_result = execute_submit(student_id, pending_submit_args)
            exec_results.submit = submit_result

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
        save_message(body.session_id, "assistant", ai_message)
        mission_status = None
        if exec_results.submit and exec_results.submit.status.value == "saved":
            mission_status = exec_results.submit.result_type
        if exec_results.cancel:
            today = _kst_today()
            background_tasks.add_task(_cancel_sheet_bg, student_id, today)
        if mission_status:
            background_tasks.add_task(_sync_sheet_bg, body.session_id, user_input, ai_message, mission_status, detected_function)

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
