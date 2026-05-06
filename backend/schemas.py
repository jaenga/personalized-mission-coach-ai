from pydantic import BaseModel, Field


class VerifyRequest(BaseModel):
    student_name: str = Field(..., min_length=1)
    phone_last4: str = Field(..., min_length=4, max_length=4, pattern=r"^\d{4}$")


class ProfileRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    student_id: int
    student_name: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    mission: str | None = None


class MissionUiActionResolveRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


class MissionReviewRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    mission_id: int
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = None


class OnboardingPreferencesRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    preferred_activity_keys: list[str] = Field(default_factory=list)
    disliked_activity_keys: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)


class UiActionButton(BaseModel):
    value: str
    label: str


class UiActionPayload(BaseModel):
    action_id: str
    type: str
    lock_chat: bool
    buttons: list[UiActionButton]
