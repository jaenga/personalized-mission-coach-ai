from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app_services import (
    delete_chat_messages,
    generate_daily,
    get_chat_messages,
    get_today_mission,
    get_user_profile,
    register_demo_student,
    save_user_profile,
    startup_tasks,
    verify_student,
)
from chat_service import process_chat, process_chat_stream
from intent_router import close_intent_router_client
from ollama_client import close_ollama_client
from qwen_client import close_qwen_client
from schemas import ChatRequest, ProfileRequest, VerifyRequest


app = FastAPI(title="AI 생활습관 코치 MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    startup_tasks()


@app.on_event("shutdown")
async def shutdown():
    await close_ollama_client()
    await close_intent_router_client()
    await close_qwen_client()


@app.post("/verify-student")
def post_verify_student(body: VerifyRequest):
    return verify_student(body)


@app.post("/demo-register-student")
def post_demo_register_student(body: VerifyRequest):
    return register_demo_student(body)


@app.post("/profile")
def post_profile(body: ProfileRequest):
    return save_user_profile(body)


@app.get("/profile/{session_id}")
def get_profile(session_id: str):
    return get_user_profile(session_id)


@app.get("/mission")
def get_mission(student_id: int | None = None):
    return get_today_mission(student_id)


@app.post("/chat")
async def post_chat(body: ChatRequest, background_tasks: BackgroundTasks):
    return await process_chat(body, background_tasks)


@app.post("/chat/stream")
async def post_chat_stream(body: ChatRequest, background_tasks: BackgroundTasks):
    return await process_chat_stream(body, background_tasks)


@app.get("/chat/{session_id}")
def get_chat(session_id: str):
    return get_chat_messages(session_id)


@app.delete("/chat/{session_id}")
def delete_chat(session_id: str):
    return delete_chat_messages(session_id)


@app.post("/admin/generate-daily")
def post_generate_daily():
    return generate_daily()
