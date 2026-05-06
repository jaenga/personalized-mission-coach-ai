from fastapi import HTTPException

from database import (
    DEMO_MODE,
    _kst_today,
    assign_daily_missions,
    assign_demo_mission_on_signup,
    adjust_heart_count,
    claim_attendance,
    claim_draw_reward,
    complete_lesson_quiz,
    create_chat_session,
    create_demo_student,
    delete_messages,
    fetch_messages,
    get_app_state,
    get_game_ranking,
    get_lesson_progress,
    get_xp_ranking,
    fetch_profile,
    get_latest_chat_session,
    get_success_summary,
    get_student_by_credentials,
    get_student_mission_db,
    init_db,
    record_game_run,
    save_profile,
    upsert_lesson_progress,
)
from demo_mission_messages import attach_mission_message
from rag import preload_model
from qwen_client import preload_qwen
from sheets import generate_daily_status
from schemas import (
    GameRunRequest,
    HeartAdjustRequest,
    LessonProgressRequest,
    LessonQuizCompleteRequest,
    ProfileRequest,
    VerifyRequest,
)


def startup_tasks() -> None:
    init_db()
    preload_model()
    preload_qwen()
    if DEMO_MODE:
        print("[startup] DEMO_MODE=true: 전체 랜덤 미션 배정 생략, demo_mission 순차 배정 사용")
    else:
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


def verify_student(body: VerifyRequest):
    student = get_student_by_credentials(body.student_name, body.phone_last4)
    if not student:
        raise HTTPException(status_code=404, detail="일치하는 학생을 찾을 수 없어요.")
    return student


def save_user_profile(body: ProfileRequest):
    existing_profile = fetch_profile(body.session_id)
    if existing_profile and existing_profile["student_id"] == body.student_id:
        db_session_id = existing_profile["db_session_id"]
    else:
        db_session_id = get_latest_chat_session(body.student_id) or create_chat_session(body.student_id)
    save_profile(body.session_id, body.student_id, body.student_name, db_session_id)
    mission = None
    if DEMO_MODE:
        mission = attach_mission_message(assign_demo_mission_on_signup(body.student_id))
    return {"ok": True, "mission": mission}


def register_demo_student(body: VerifyRequest):
    student = create_demo_student(body.student_name, body.phone_last4)
    mission = None
    if DEMO_MODE:
        mission = attach_mission_message(assign_demo_mission_on_signup(student["student_id"]))

    return {
        "ok": True,
        "student": student,
        "mission": mission,
    }


def get_user_profile(session_id: str):
    profile = fetch_profile(session_id)
    if not profile:
        raise HTTPException(status_code=404, detail="프로필 없음")
    return profile


def get_today_mission(student_id: int | None = None):
    today = _kst_today()
    if student_id:
        mission = get_student_mission_db(student_id, today)
        if mission:
            return attach_mission_message(mission)
    return {
        "mission_id": None,
        "mission_name": "오늘의 미션",
        "category": "",
        "difficulty": "",
        "status": "assigned",
        "mission_message": "오늘 미션을 아직 불러오지 못했어. 잠시 후 다시 확인해보자!",
    }


def get_student_stats(student_id: int):
    return get_success_summary(student_id)


def get_student_app_state(student_id: int):
    return get_app_state(student_id)


def adjust_student_heart(student_id: int, body: HeartAdjustRequest):
    try:
        return {"app_state": adjust_heart_count(student_id, body.delta)}
    except ValueError as e:
        if str(e) == "no_heart":
            raise HTTPException(status_code=409, detail="하트가 부족해요.")
        raise


def claim_student_draw_reward(student_id: int):
    try:
        return claim_draw_reward(student_id)
    except ValueError as e:
        if str(e) == "no_ticket":
            raise HTTPException(status_code=409, detail="뽑기권이 부족해요.")
        raise


def claim_student_attendance(student_id: int):
    return claim_attendance(student_id)


def get_xp_ranking_for(period: str):
    if period not in ("week", "month"):
        raise HTTPException(status_code=400, detail="period는 week 또는 month여야 해요.")
    return get_xp_ranking(period=period, limit=100)


def record_student_game_run(body: GameRunRequest):
    return record_game_run(
        student_id=body.student_id,
        game_type=body.game_type,
        score=body.score,
        duration_sec=body.duration_sec,
    )


def get_game_ranking_for(period: str, game_type: str | None = None):
    if period not in ("week", "month", "all"):
        raise HTTPException(status_code=400, detail="period는 week / month / all 중 하나여야 해요.")
    return get_game_ranking(period=period, limit=100, game_type=game_type)


def get_student_lesson_progress(student_id: int):
    return get_lesson_progress(student_id)


def update_student_lesson_progress(body: LessonProgressRequest):
    return upsert_lesson_progress(
        student_id=body.student_id,
        lesson_id=body.lesson_id,
        current_step=body.current_step,
        edu_done=body.edu_done,
        quiz_done=body.quiz_done,
    )


def complete_student_lesson_quiz(body: LessonQuizCompleteRequest):
    return complete_lesson_quiz(
        student_id=body.student_id,
        lesson_id=body.lesson_id,
        quiz_score=body.quiz_score,
    )


def get_chat_messages(session_id: str):
    return fetch_messages(session_id)


def delete_chat_messages(session_id: str):
    count = delete_messages(session_id)
    return {"ok": True, "deleted": count}


def generate_daily():
    try:
        today = _kst_today()
        added = generate_daily_status(today)
        return {"ok": True, "date": today, "added": added}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
