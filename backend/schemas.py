from pydantic import BaseModel, Field


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
