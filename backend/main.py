from fastapi import BackgroundTasks, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app_services import (
    adjust_student_heart,
    claim_student_attendance,
    claim_student_draw_reward,
    complete_student_lesson_quiz,
    delete_chat_messages,
    delete_student_account,
    generate_daily,
    get_active_mission_ui_action,
    get_chat_messages,
    get_game_ranking_for,
    get_student_health_note,
    get_student_app_state,
    get_student_lesson_progress,
    get_student_mission_records,
    get_mission_preferences,
    get_student_stats,
    get_student_weekly_share_prompt,
    get_today_mission,
    get_user_profile,
    get_xp_ranking_for,
    record_student_game_run,
    register_demo_student,
    resolve_mission_ui_action,
    save_mission_review,
    save_mission_preferences,
    save_onboarding_preferences,
    save_student_optional_info,
    save_user_profile,
    save_student_health_note,
    submit_mission_correction_request,
    submit_user_feedback,
    startup_tasks,
    update_student_weekly_share_prompt,
    update_student_lesson_progress,
    verify_student,
    delete_student_health_note,
)
from chat_service import process_chat, process_chat_stream
from intent_router import close_intent_router_client
from ollama_client import close_ollama_client, stop_autostarted_ollama
from qwen_client import close_qwen_client
from schemas import (
    ChatRequest,
    GameRunRequest,
    HeartAdjustRequest,
    HealthNoteRequest,
    LessonProgressRequest,
    LessonQuizCompleteRequest,
    MissionCorrectionRequest,
    MissionReviewRequest,
    MissionPreferencesRequest,
    MissionUiActionResolveRequest,
    OnboardingPreferencesRequest,
    ProfileRequest,
    StudentInfoRequest,
    UserFeedbackRequest,
    VerifyRequest,
    WeeklySharePromptActionRequest,
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
    stop_autostarted_ollama()


@app.post("/verify-student")
def post_verify_student(body: VerifyRequest):
    return verify_student(body)


@app.post("/demo-register-student")
def post_demo_register_student(body: VerifyRequest):
    return register_demo_student(body)


@app.post("/profile")
def post_profile(body: ProfileRequest):
    return save_user_profile(body)


@app.post("/student-info")
def post_student_info(body: StudentInfoRequest):
    return save_student_optional_info(body)


@app.get("/profile/{session_id}")
def get_profile(session_id: str):
    return get_user_profile(session_id)


@app.get("/mission")
def get_mission(student_id: int | None = None):
    return get_today_mission(student_id)


@app.get("/stats/{student_id}")
def get_stats(student_id: int):
    return get_student_stats(student_id)


@app.get("/mission-records/{student_id}")
def get_mission_records_route(
    student_id: int,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    return get_student_mission_records(student_id, from_date, to_date)


@app.post("/mission-correction-requests")
def post_mission_correction_request(body: MissionCorrectionRequest):
    return submit_mission_correction_request(body)


@app.post("/user-feedback")
def post_user_feedback(body: UserFeedbackRequest):
    return submit_user_feedback(body)


@app.get("/weekly-share/{student_id}")
def get_weekly_share(student_id: int):
    return get_student_weekly_share_prompt(student_id)


@app.post("/weekly-share/action")
def post_weekly_share_action(body: WeeklySharePromptActionRequest):
    return update_student_weekly_share_prompt(body)


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


@app.post("/mission-review")
def post_mission_review(body: MissionReviewRequest, background_tasks: BackgroundTasks):
    return save_mission_review(body, background_tasks)


@app.post("/onboarding-preferences")
def post_onboarding_preferences(body: OnboardingPreferencesRequest):
    return save_onboarding_preferences(body)


@app.get("/mission-preferences/{student_id}")
def get_mission_preferences_route(student_id: int):
    return get_mission_preferences(student_id)


@app.post("/mission-preferences")
def post_mission_preferences(body: MissionPreferencesRequest):
    return save_mission_preferences(body)


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


@app.delete("/students/{student_id}")
def delete_student_route(student_id: int):
    return delete_student_account(student_id)


@app.get("/mission-ui-actions/active")
async def get_active_ui_action(session_id: str):
    return await get_active_mission_ui_action(session_id)


@app.post("/mission-ui-actions/{action_id}/resolve")
async def post_mission_ui_action_resolve(action_id: str, body: MissionUiActionResolveRequest):
    return await resolve_mission_ui_action(action_id, body)


@app.post("/admin/generate-daily")
def post_generate_daily():
    return generate_daily()
