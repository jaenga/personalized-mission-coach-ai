from datetime import date
from uuid import uuid4
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from database import (
    init_db,
    get_student_by_credentials, create_chat_session,
    save_profile, fetch_profile,
    save_message, fetch_messages, delete_messages,
    get_student_mission_db, get_student_info_db,
    save_mission_result, mark_synced,
    detect_function_from_db,
)
from ollama_client import generate_chat_message, analyze_response, OLLAMA_MODEL
from prompts import build_chat_system_prompt
from rag import search_rag
from sheets import detect_mission_status, update_mission_result, generate_daily_status

analysis_store: dict[str, dict] = {}

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
    try:
        today = date.today().isoformat()
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
    today = date.today().isoformat()
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

async def _run_analysis_bg(analysis_id: str, user_input: str, ai_message: str, call1_ms: int):
    reasoning, call2_ms = await analyze_response(user_input, ai_message)
    analysis_store[analysis_id] = {
        "reasoning": reasoning,
        "timing": {"call1_ms": call1_ms, "call2_ms": call2_ms, "total_ms": call1_ms + call2_ms},
    }


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

    today = date.today().isoformat()
    student_id = profile["student_id"]

    # DB에서 학생/미션 정보 가져오기
    student_info = get_student_info_db(student_id) or {}
    mission_info = get_student_mission_db(student_id, today) or {}

    # 1. DB 저장 (checkin_log)
    result_id = save_mission_result(
        student_id=student_id,
        student_name=student_info.get("student_name", profile.get("student_name", "")),
        mission_id=mission_info.get("mission_id"),
        mission_name=mission_info.get("mission_name", ""),
        status=status,
        result_reason=user_message,
        ai_response=ai_message,
        session_id=session_id,
        detected_function=detected_function,
    )

    # 2. 구글 시트 업데이트
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
            mission_id=mission_info.get("mission_id"),
            mission_name=mission_info.get("mission_name", ""),
            category=mission_info.get("category", ""),
            difficulty=mission_info.get("difficulty", ""),
        )
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
    mission_title = body.mission or "오늘의 미션"
    is_greet = body.message == "__GREET__"

    # function 감지
    detected_function = None
    rag_result: dict = {"chunks": [], "faqs": [], "context": ""}
    if not is_greet:
        detected_function = detect_function_from_db(body.message)
        save_message(body.session_id, "user", body.message, detected_function)

        try:
            rag_result = search_rag(body.message)
        except Exception as e:
            print(f"[RAG] 검색 실패 (무시): {e}")

    system_prompt = build_chat_system_prompt(mission_title, rag_result["context"] if not is_greet else "")

    history = fetch_messages(body.session_id)
    messages = history if history else [
        {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
    ]

    try:
        ai_message, call1_ms = await generate_chat_message(system_prompt, messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}")

    save_message(body.session_id, "assistant", ai_message)

    user_input = body.message if not is_greet else ""
    violations = detect_violations(ai_message, user_input)

    # 미션 결과 감지
    mission_status = None if is_greet else detect_mission_status(user_input)
    if mission_status:
        fn = detected_function or "submit_mission_result"
        background_tasks.add_task(_sync_sheet_bg, body.session_id, user_input, ai_message, mission_status, fn)

    analysis_id = str(uuid4())
    background_tasks.add_task(_run_analysis_bg, analysis_id, user_input, ai_message, call1_ms)

    sources = [
        {"type": "faq", "title": f["title"], "question": f["question"]}
        for f in rag_result["faqs"]
    ] + [
        {"type": "chunk", "title": c["title"], "intent": c["intent"]}
        for c in rag_result["chunks"]
    ]

    return {
        "response": ai_message,
        "analysis_id": analysis_id,
        "mission_completed": mission_status is not None,
        "detected_function": detected_function,
        "sources": sources,
        "debug": {
            "violations": violations,
            "system_prompt": system_prompt,
            "history_turns": len(messages),
            "model": OLLAMA_MODEL,
            "timing": {"call1_ms": call1_ms},
            "rag_hits": {"chunks": len(rag_result["chunks"]), "faqs": len(rag_result["faqs"])},
        },
    }


@app.get("/analysis/{analysis_id}")
async def get_analysis(analysis_id: str):
    result = analysis_store.get(analysis_id)
    if result is None:
        return JSONResponse(status_code=202, content={"status": "pending"})
    del analysis_store[analysis_id]
    return result


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
        today = date.today().isoformat()
        added = generate_daily_status(today)
        return {"ok": True, "date": today, "added": added}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
