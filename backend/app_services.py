from fastapi import BackgroundTasks, HTTPException

from activity_keys import normalize_activity_key
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
    delete_student_completely,
    fetch_messages,
    get_app_state,
    get_game_ranking,
    get_lesson_progress,
    get_xp_ranking,
    fetch_profile,
    delete_health_note,
    get_health_note,
    get_latest_chat_session,
    get_success_summary,
    get_student_by_credentials,
    get_student_mission_db,
    init_db,
    record_game_run,
    save_mission_review as save_mission_review_db,
    save_profile,
    upsert_user_memory,
    upsert_health_note,
    upsert_lesson_progress,
)
from demo_mission_messages import attach_mission_message
from memory_service import extract_and_save_memory
from mission_personalization import replace_current_mission_after_onboarding
from mission_ui_action_service import get_active_ui_action, rebuild_ui_action_payload, resolve_mission_ui_action_request
from starlette.concurrency import run_in_threadpool
from ollama_client import ensure_ollama_server
from rag import preload_model
from qwen_client import preload_qwen
from sheets import generate_daily_status
from schemas import (
    GameRunRequest,
    HeartAdjustRequest,
    HealthNoteRequest,
    LessonProgressRequest,
    LessonQuizCompleteRequest,
    MissionReviewRequest,
    MissionUiActionResolveRequest,
    OnboardingPreferencesRequest,
    ProfileRequest,
    VerifyRequest,
)


def startup_tasks() -> None:
    init_db()
    ensure_ollama_server()
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
    if not DEMO_MODE:
        raise HTTPException(status_code=403, detail="현재는 회원가입을 사용할 수 없어요.")

    student = create_demo_student(body.student_name, body.phone_last4)
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
        if not mission:
            if DEMO_MODE:
                mission = assign_demo_mission_on_signup(student_id)
            else:
                assign_daily_missions()
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


def get_student_health_note(student_id: int):
    note = get_health_note(student_id)
    if not note:
        return {
            "student_id": student_id,
            "allergens": [],
            "caution_foods": [],
        }
    return note


def save_student_health_note(body: HealthNoteRequest):
    return upsert_health_note(
        student_id=body.student_id,
        allergens=body.allergens,
        caution_foods=body.caution_foods,
    )


def delete_student_health_note(student_id: int):
    deleted = delete_health_note(student_id)
    return {"ok": True, "deleted": deleted}


def save_mission_review(body: MissionReviewRequest, background_tasks: BackgroundTasks | None = None):
    profile = fetch_profile(body.session_id)
    if not profile:
        raise HTTPException(status_code=404, detail="profile not found")

    try:
        review = save_mission_review_db(
            student_id=profile["student_id"],
            mission_id=body.mission_id,
            rating=body.rating,
            comment=body.comment,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not review:
        raise HTTPException(status_code=404, detail="mission not found")
    if background_tasks and body.comment and body.comment.strip():
        background_tasks.add_task(
            extract_and_save_memory,
            profile["student_id"],
            body.comment.strip(),
            False,
        )
    return {"ok": True, "review": review}


def save_onboarding_preferences(body: OnboardingPreferencesRequest):
    profile = fetch_profile(body.session_id)
    if not profile:
        raise HTTPException(status_code=404, detail="profile not found")

    student_id = profile["student_id"]
    saved = []
    skipped = []
    disliked_activity_keys = []

    for subject in _clean_subjects(body.preferred_activity_keys):
        activity_key = normalize_activity_key(subject)
        if not activity_key:
            skipped.append({"value": subject, "type": "preference", "reason": "invalid_activity_key"})
            continue
        memory = upsert_user_memory(student_id, activity_key, "preference", 1)
        if memory:
            saved.append(memory)

    for subject in _clean_subjects(body.disliked_activity_keys):
        activity_key = normalize_activity_key(subject)
        if not activity_key:
            skipped.append({"value": subject, "type": "preference", "reason": "invalid_activity_key"})
            continue
        memory = upsert_user_memory(student_id, activity_key, "preference", -1)
        if memory:
            saved.append(memory)
            disliked_activity_keys.append(activity_key)

    for subject in _clean_subjects(body.restrictions):
        memory = upsert_user_memory(student_id, subject, "restriction")
        if memory:
            saved.append(memory)

    replacement = {
        "mission_changed": False,
        "replace_reason": None,
        "new_mission": None,
    }
    try:
        replacement = replace_current_mission_after_onboarding(student_id, disliked_activity_keys)
    except Exception as e:
        print(f"[Onboarding] auto replacement failed: {type(e).__name__}: {e}")
        replacement = {
            "mission_changed": False,
            "replace_reason": None,
            "new_mission": None,
            "warning": "onboarding_auto_replace_failed",
        }

    return {
        "ok": True,
        "saved_count": len(saved),
        "skipped": skipped,
        "memories": saved,
        "mission_changed": bool(replacement.get("mission_changed")),
        "replace_reason": replacement.get("replace_reason"),
        "new_mission": replacement.get("new_mission"),
        "replace_check": {
            "should_replace": replacement.get("should_replace", False),
            "reason": replacement.get("reason"),
            "current_mission_id": replacement.get("current_mission_id"),
            "current_activity_key": replacement.get("current_activity_key"),
            "warning": replacement.get("warning"),
        },
    }


def _clean_subjects(values: list[str]) -> list[str]:
    seen = set()
    cleaned = []
    for value in values or []:
        subject = (value or "").strip()
        if not subject or subject in seen:
            continue
        seen.add(subject)
        cleaned.append(subject)
    return cleaned


def get_chat_messages(session_id: str):
    return fetch_messages(session_id)


def delete_chat_messages(session_id: str):
    count = delete_messages(session_id)
    return {"ok": True, "deleted": count}


def delete_student_account(student_id: int):
    deleted = delete_student_completely(student_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="student not found")
    return {"ok": True, "deleted": True}


async def get_active_mission_ui_action(session_id: str):
    profile = await run_in_threadpool(fetch_profile, session_id)
    if not profile:
        return {"ui_action": None}
    student_id = profile["student_id"]
    active = await get_active_ui_action(student_id, session_id)
    if not active:
        return {"ui_action": None}
    return {"ui_action": rebuild_ui_action_payload(active)}


async def resolve_mission_ui_action(action_id: str, body: MissionUiActionResolveRequest):
    return await resolve_mission_ui_action_request(action_id, body.session_id, body.value)


def generate_daily():
    try:
        today = _kst_today()
        added = generate_daily_status(today)
        return {"ok": True, "date": today, "added": added}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
