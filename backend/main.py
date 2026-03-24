from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal

from database import init_db, save_checkin_log, fetch_checkin_logs, update_review
from ollama_client import generate_response, OLLAMA_MODEL
from prompts import SYSTEM_PROMPT, build_user_prompt

app = FastAPI(title="AI 생활습관 코치 MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ── 오늘의 미션 (MVP: 하드코딩) ──────────────────────────────────────────────

MISSION = {
    "id": 1,
    "title": "물 4잔 마시기",
    "description": "오늘 하루 동안 물을 4잔 마셔 보자! 🥤",
}


@app.get("/mission")
def get_mission():
    return MISSION


# ── 피드백 제출 ──────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    mission: str = Field(..., min_length=1)
    result: str = Field(..., pattern="^(success|partial|failure)$")
    reason: str | None = None
    # 테스트 로그용 선택 필드
    prompt_version: str = "v1"
    expected_label: str | None = None
    memo: str | None = None


class FeedbackResponse(BaseModel):
    id: int
    ai_response: str


@app.post("/feedback", response_model=FeedbackResponse)
async def post_feedback(body: FeedbackRequest):
    user_prompt = build_user_prompt(body.mission, body.result, body.reason)

    try:
        ai_response = await generate_response(SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}")

    log_id = save_checkin_log(
        mission=body.mission,
        result=body.result,
        reason_text=body.reason,
        ai_response=ai_response,
        model_name=OLLAMA_MODEL,
        prompt_version=body.prompt_version,
        expected_label=body.expected_label,
        memo=body.memo,
    )
    return FeedbackResponse(id=log_id, ai_response=ai_response)


# ── 기록 조회 ─────────────────────────────────────────────────────────────────

@app.get("/logs")
def get_logs(limit: int = 50):
    return fetch_checkin_logs(limit)


# ── 리뷰 라벨 저장 ────────────────────────────────────────────────────────────

QualityLabel = Literal["good", "borderline", "fail"]
FailureType  = Literal[
    "none", "hallucination", "safety",
    "mismatch", "vague_input", "repetitive", "off_target",
]


class ReviewRequest(BaseModel):
    quality_label: QualityLabel | None = None
    failure_type:  FailureType  | None = None
    reviewer_note: str          | None = None


@app.patch("/logs/{log_id}/review")
def patch_review(log_id: int, body: ReviewRequest):
    """quality_label / failure_type / reviewer_note 를 특정 로그에 기록한다."""
    ok = update_review(
        log_id,
        body.quality_label,
        body.failure_type,
        body.reviewer_note,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"id={log_id} 로그를 찾을 수 없습니다")
    return {"ok": True, "id": log_id}
