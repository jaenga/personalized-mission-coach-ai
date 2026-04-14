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
)
from ollama_client import generate_chat_message, analyze_response, OLLAMA_MODEL
from prompts import build_chat_system_prompt
from rag import search_rag, preload_model
from sheets import detect_mission_status, update_mission_result, generate_daily_status
from intent_router import classify_intent
from qwen_client import call_function, preload_qwen

analysis_store: dict[str, dict] = {}

# ── 펑션별 Gemma 힌트 ──────────────────────────────────────────────────────────

def _build_fn_hint(detected_function: str, fn_args: dict) -> str:
    if detected_function == "submit_mission_result":
        result_kor = {"success": "결과: 완료.", "fail": "결과: 수행 실패."}.get(fn_args.get("result_type", ""), "")
        return f"아이가 미션 결과를 제출했어. {result_kor} 자연스럽게 받아주고 기록됐다고 알려줘."
    if detected_function == "get_mission_info":
        return {
            "today": "아이가 오늘 미션 내용을 물어봤어. 오늘 미션을 친절하게 안내해줘.",
            "deadline": "아이가 제출 마감 시간을 물어봤어. 마감 시간을 안내해줘.",
            "general_rule": "아이가 앱 규칙을 물어봤어. 제출·인증·판정 규칙을 안내해줘.",
        }.get(fn_args.get("query_type", ""), "아이가 미션 정보를 물어봤어. 친절하게 안내해줘.")
    if detected_function == "request_mission_adjustment":
        return {
            "change": "아이가 다른 미션으로 바꿔달라고 했어. 요청을 접수했다고 알려줘.",
            "easier": "아이가 더 쉬운 미션을 요청했어. 요청을 접수했다고 알려줘.",
            "harder": "아이가 더 어려운 미션을 요청했어. 요청을 접수했다고 알려줘.",
        }.get(fn_args.get("adjustment_type", ""), "아이가 미션 조정을 요청했어. 요청을 접수했다고 알려줘.")
    if detected_function == "check_mission_equivalency":
        return {
            "behavior": "아이가 다른 행동으로 수행해도 되는지 물어봤어. 대체 수행 가능 여부를 안내해줘.",
            "place": "아이가 다른 장소에서 수행해도 되는지 물어봤어. 대체 수행 가능 여부를 안내해줘.",
            "time": "아이가 다른 시간에 수행해도 되는지 물어봤어. 대체 수행 가능 여부를 안내해줘.",
        }.get(fn_args.get("equivalency_type", ""), "아이가 대체 수행 가능 여부를 물어봤어. 친절하게 안내해줘.")
    if detected_function == "get_user_history":
        return {
            "weekly_summary": "아이가 이번 주 미션 기록을 조회했어. 주간 기록을 안내해줘.",
            "monthly_summary": "아이가 이번 달 미션 기록을 조회했어. 월간 기록을 안내해줘.",
        }.get(fn_args.get("query_type", ""), "아이가 미션 기록을 조회했어. 기록을 안내해줘.")
    if detected_function == "cancel_mission_action":
        return "아이가 가장 최근 행동을 취소하려고 해. 취소됐다고 자연스럽게 알려줘."
    return f"아이가 '{detected_function}' 기능을 요청했어. 자연스럽게 응답해줘."

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

    intent = "A"
    detected_function = None
    fn_args: dict = {}
    rag_result: dict = {"chunks": [], "faqs": [], "context": ""}

    if not is_greet:
        # ── 1. Gemma4:e2b 인텐트 분류 ──────────────────────────────────────────
        intent = await classify_intent(body.message)
        save_message(body.session_id, "user", body.message, detected_function)

        # ── 2. 인텐트별 모듈 활성화 ────────────────────────────────────────────
        if intent == "B":
            # qwen-lora-finetuned 펑션콜링
            detected_function, fn_args, qwen_ms = call_function(body.message)
            print(f"[Chat] B-route: fn={detected_function} args={fn_args} ({qwen_ms}ms)")

        elif intent == "C":
            # RAG 검색
            try:
                rag_result = search_rag(body.message)
            except Exception as e:
                print(f"[RAG] 검색 실패 (무시): {e}")

        # A, D: 추가 모듈 없음 — Gemma4 직접 응답

    # ── 3. 시스템 프롬프트 구성 ─────────────────────────────────────────────────
    system_prompt = build_chat_system_prompt(
        mission_title,
        rag_result["context"] if not is_greet else "",
    )

    if intent == "D":
        system_prompt += "\n\n아이의 말이 무슨 뜻인지 불분명해. 판단하지 말고 딱 한 문장으로 다시 물어봐."

    if intent == "B" and detected_function:
        system_prompt += f"\n\n{_build_fn_hint(detected_function, fn_args)}"

    # ── 4. Gemma4:e2b 응답 생성 ─────────────────────────────────────────────────
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

    # ── 5. 미션 결과 동기화 ──────────────────────────────────────────────────────
    mission_status = None
    if not is_greet and intent == "B":
        if fn_args.get("result_type"):
            # Qwen이 추출한 result_type 우선 사용
            mission_status = fn_args["result_type"]
        else:
            # Qwen이 못 잡았을 때만 키워드 fallback
            mission_status = detect_mission_status(user_input)

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
            "intent": intent,
            "fn_args": fn_args,
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
