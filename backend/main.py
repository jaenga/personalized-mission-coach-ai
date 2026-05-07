from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app_services import (
    adjust_student_heart,
    claim_student_attendance,
    claim_student_draw_reward,
    complete_student_lesson_quiz,
    delete_chat_messages,
    generate_daily,
    get_chat_messages,
    get_game_ranking_for,
    get_student_health_note,
    get_student_app_state,
    get_student_lesson_progress,
    get_student_stats,
    get_today_mission,
    get_user_profile,
    get_xp_ranking_for,
    record_student_game_run,
    register_demo_student,
    save_user_profile,
    save_student_health_note,
    startup_tasks,
    update_student_lesson_progress,
    verify_student,
    delete_student_health_note,
)
from chat_service import process_chat, process_chat_stream
from intent_router import close_intent_router_client
from ollama_client import close_ollama_client
from qwen_client import close_qwen_client
from schemas import (
    ChatRequest,
    GameRunRequest,
    HeartAdjustRequest,
    HealthNoteRequest,
    LessonProgressRequest,
    LessonQuizCompleteRequest,
    ProfileRequest,
    VerifyRequest,
)


app = FastAPI(title="AI 생활습관 코치 MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
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


@app.get("/stats/{student_id}")
def get_stats(student_id: int):
    return get_student_stats(student_id)


@app.get("/app-state/{student_id}")
def get_app_state_route(student_id: int):
    return get_student_app_state(student_id)


@app.post("/app-state/{student_id}/heart")
def post_app_state_heart_route(student_id: int, body: HeartAdjustRequest):
    return adjust_student_heart(student_id, body)


@app.post("/draw/reward/{student_id}")
def post_draw_reward(student_id: int):
    return claim_student_draw_reward(student_id)


@app.post("/attendance/check-in/{student_id}")
def post_attendance_check_in(student_id: int):
    return claim_student_attendance(student_id)


@app.get("/ranking/xp")
def get_ranking_xp(period: str = "week"):
    return get_xp_ranking_for(period)


@app.post("/game/runs")
def post_game_run(body: GameRunRequest):
    return record_student_game_run(body)


@app.get("/ranking/game")
def get_ranking_game(period: str = "week", game_type: str | None = None):
    return get_game_ranking_for(period, game_type)


@app.get("/lessons/progress/{student_id}")
def get_lessons_progress(student_id: int):
    return get_student_lesson_progress(student_id)


@app.post("/lessons/progress")
def post_lessons_progress(body: LessonProgressRequest):
    return update_student_lesson_progress(body)


@app.post("/lessons/quiz-complete")
def post_lessons_quiz_complete(body: LessonQuizCompleteRequest):
    return complete_student_lesson_quiz(body)


@app.get("/health-note/{student_id}")
def get_health_note_route(student_id: int):
    return get_student_health_note(student_id)


@app.post("/health-note")
def post_health_note_route(body: HealthNoteRequest):
    return save_student_health_note(body)


@app.delete("/health-note/{student_id}")
def delete_health_note_route(student_id: int):
    return delete_student_health_note(student_id)


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
