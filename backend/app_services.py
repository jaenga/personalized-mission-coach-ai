from fastapi import HTTPException

from database import (
    _kst_today,
    assign_daily_missions,
    create_chat_session,
    delete_messages,
    fetch_messages,
    fetch_profile,
    get_student_by_credentials,
    get_student_mission_db,
    init_db,
    save_profile,
)
from rag import preload_model
from qwen_client import preload_qwen
from sheets import generate_daily_status
from schemas import ProfileRequest, VerifyRequest


def startup_tasks() -> None:
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


def verify_student(body: VerifyRequest):
    student = get_student_by_credentials(body.student_name, body.phone_last4)
    if not student:
        raise HTTPException(status_code=404, detail="일치하는 학생을 찾을 수 없어요.")
    return student


def save_user_profile(body: ProfileRequest):
    db_session_id = create_chat_session(body.student_id)
    save_profile(body.session_id, body.student_id, body.student_name, db_session_id)
    return {"ok": True}


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
            return mission
    return {
        "mission_id": None,
        "mission_name": "오늘의 미션",
        "category": "",
        "difficulty": "",
        "status": "assigned",
    }


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
