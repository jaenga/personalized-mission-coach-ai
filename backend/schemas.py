from pydantic import BaseModel, Field
from datetime import date
from typing import Literal


class VerifyRequest(BaseModel):
    student_name: str = Field(..., min_length=1)
    phone_last4: str = Field(..., min_length=4, max_length=4, pattern=r"^\d{4}$")


class ProfileRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    student_id: int
    student_name: str = Field(..., min_length=1)


class HeartAdjustRequest(BaseModel):
    delta: int = Field(..., ge=-5, le=5)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    mission: str | None = None


class GameRunRequest(BaseModel):
    student_id: int
    game_type: str = Field(..., min_length=1)
    score: int = Field(..., ge=0)
    duration_sec: int = Field(0, ge=0)


class LessonProgressRequest(BaseModel):
    student_id: int
    lesson_id: str = Field(..., min_length=1)
    current_step: int | None = Field(None, ge=0)
    edu_done: bool | None = None
    quiz_done: bool | None = None


class LessonQuizCompleteRequest(BaseModel):
    student_id: int
    lesson_id: str = Field(..., min_length=1)
    quiz_score: int | None = Field(None, ge=0)


class HealthNoteRequest(BaseModel):
    student_id: int
    allergens: list[str] = Field(default_factory=list)
    caution_foods: list[str] = Field(default_factory=list)


class MissionUiActionResolveRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


class MissionReviewRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    mission_id: int
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = None


class MissionCorrectionRequest(BaseModel):
    student_id: int
    checkin_id: int | None = None
    mission_id: int
    target_date: date
    current_result: Literal["success", "failure", "completed", "fail", "unsubmitted"]
    requested_result: Literal["success", "failure", "fail", "other"]
    message: str | None = Field(None, max_length=1000)


class UserFeedbackRequest(BaseModel):
    student_id: int
    feedback_type: Literal["app_feedback", "bug_report", "inquiry", "other"]
    message: str = Field(..., min_length=1, max_length=2000)


class WeeklySharePromptActionRequest(BaseModel):
    student_id: int
    week_start: str = Field(..., min_length=10, max_length=10)
    action: str = Field(..., pattern=r"^(dismissed|shared)$")


class OnboardingPreferencesRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    preferred_activity_keys: list[str] = Field(default_factory=list)
    disliked_activity_keys: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)


class MissionPreferencesRequest(BaseModel):
    student_id: int
    preferred_activity_keys: list[str] = Field(default_factory=list)
    disliked_activity_keys: list[str] = Field(default_factory=list)


class UiActionButton(BaseModel):
    value: str
    label: str


class UiActionPayload(BaseModel):
    action_id: str
    type: str
    lock_chat: bool
    buttons: list[UiActionButton]
