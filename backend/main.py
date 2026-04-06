import asyncio
import json
import logging
import time
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from database import delete_messages, fetch_messages, init_db, save_message
from function_tools import execute_tool
from functiongemma_hf_client import get_functiongemma_client, initialize_functiongemma_client
from ollama_client import OLLAMA_MODEL, analyze_response, generate_chat_message
from prompts import build_chat_system_prompt

logger = logging.getLogger(__name__)

# 분석 결과 임시 저장소 (analysis_id → result)
analysis_store: dict[str, dict] = {}

app = FastAPI(title="AI 생활습관 코치 MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()
    initialize_functiongemma_client()


# ── 오늘의 미션 (MVP: 하드코딩) ──────────────────────────────────────────────

MISSION = {
    "id": 1,
    "title": "물 4잔 마시기",
    "description": "오늘 하루 동안 물을 4잔 마셔 보자! 🥤",
}


@app.get("/mission")
def get_mission() -> dict:
    return MISSION


# ── 금지어 위반 감지 (서버 사이드, LLM 무관) ──────────────────────────────────

FORBIDDEN_WORDS = ["엄마", "아빠", "부모님", "가족", "형", "언니", "오빠", "동생", "친구", "선생님"]


def detect_violations(ai_message: str, user_input: str) -> list[str]:
    return [
        f"금지어 언급: '{w}' (사용자가 먼저 말하지 않음)"
        for w in FORBIDDEN_WORDS
        if w in ai_message and w not in user_input
    ]


# ── FunctionGemma(HF) 분류 ───────────────────────────────────────────────────

class FunctionCallRequest(BaseModel):
    message: str = Field(..., min_length=1)


async def classify_function_call(user_text: str) -> tuple[str, dict | None, int]:
    client = get_functiongemma_client()
    t0 = time.perf_counter()
    raw_output, function_call = await asyncio.to_thread(client.predict_with_raw, user_text)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    return raw_output, function_call, elapsed_ms


@app.post("/function-call")
async def post_function_call(body: FunctionCallRequest) -> dict:
    raw_output, function_call, elapsed_ms = await classify_function_call(body.message)
    return {
        "function_call": function_call,
        "debug": {
            "elapsed_ms": elapsed_ms,
            "raw_output": raw_output,
        },
    }


# ── 대화 채팅 ─────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    mission: str | None = None


async def _run_analysis_bg(analysis_id: str, user_input: str, ai_message: str, call1_ms: int) -> None:
    """백그라운드: 2차 분석 호출 후 결과를 analysis_store에 저장."""
    reasoning, call2_ms = await analyze_response(user_input, ai_message)
    analysis_store[analysis_id] = {
        "reasoning": reasoning,
        "timing": {
            "call1_ms": call1_ms,
            "call2_ms": call2_ms,
            "total_ms": call1_ms + call2_ms,
        },
    }


@app.post("/chat")
async def post_chat(body: ChatRequest, background_tasks: BackgroundTasks) -> dict:
    mission_title = body.mission or MISSION["title"]
    system_prompt = build_chat_system_prompt(mission_title)
    is_greet = body.message == "__GREET__"

    if not is_greet:
        save_message(body.session_id, "user", body.message)

    history = fetch_messages(body.session_id)
    messages = history if history else [
        {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
    ]

    tool_called_list: list[dict] = []
    call1_ms = 0
    function_call: dict | None = None
    function_raw = ""

    if not is_greet:
        logger.info("Classifying function call: session=%s message=%r", body.session_id, body.message)
        try:
            function_raw, function_call, call1_ms = await classify_function_call(body.message)
            logger.info(
                "FunctionGemma(HF) output: elapsed_ms=%s raw=%r parsed=%s",
                call1_ms,
                function_raw,
                function_call,
            )

            if function_call:
                tool_context = {"mission": MISSION, "session_id": body.session_id}
                fn_name = function_call.get("name")
                fn_args = function_call.get("arguments", {})

                if isinstance(fn_args, str):
                    try:
                        fn_args = json.loads(fn_args)
                    except json.JSONDecodeError:
                        fn_args = {}
                if fn_args is None:
                    fn_args = {}

                if fn_name and fn_name != "no_function":
                    result = execute_tool(fn_name, fn_args, tool_context)
                    tool_called_list.append({"name": fn_name, "arguments": fn_args, "result": result})

                    tool_call_for_chat = [{
                        "function": {
                            "name": fn_name,
                            "arguments": fn_args,
                        }
                    }]
                    messages_with_tool = messages + [
                        {"role": "assistant", "content": "", "tool_calls": tool_call_for_chat},
                        {"role": "tool", "content": result},
                    ]
                    ai_message, call2_ms = await generate_chat_message(system_prompt, messages_with_tool)
                    call1_ms += call2_ms
                else:
                    ai_message, call2_ms = await generate_chat_message(system_prompt, messages)
                    call1_ms += call2_ms
            else:
                ai_message, call2_ms = await generate_chat_message(system_prompt, messages)
                call1_ms += call2_ms

        except Exception as e:
            logger.exception("FunctionGemma classification failed: %s", e)
            # function calling 모델 실패 시 일반 모델로 폴백
            try:
                ai_message, call1_ms = await generate_chat_message(system_prompt, messages)
            except Exception as e2:
                raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e2}") from e2
    else:
        # 첫 인사(__GREET__)는 function calling 없이 바로 응답
        try:
            ai_message, call1_ms = await generate_chat_message(system_prompt, messages)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}") from e

    save_message(body.session_id, "assistant", ai_message)

    user_input = body.message if not is_greet else ""
    violations = detect_violations(ai_message, user_input)

    analysis_id = str(uuid4())
    background_tasks.add_task(_run_analysis_bg, analysis_id, user_input, ai_message, call1_ms)

    return {
        "response": ai_message,
        "analysis_id": analysis_id,
        "function_call": function_call,
        "tool_called": tool_called_list or None,
        "debug": {
            "violations": violations,
            "system_prompt": system_prompt,
            "history_turns": len(messages),
            "model": OLLAMA_MODEL,
            "function_model": "hf:functiongemma",
            "function_raw": function_raw,
            "timing": {"call1_ms": call1_ms},
        },
    }


@app.get("/analysis/{analysis_id}")
async def get_analysis(analysis_id: str):
    """분석 결과 폴링 엔드포인트. 아직 준비 중이면 202 반환."""
    result = analysis_store.get(analysis_id)
    if result is None:
        return JSONResponse(status_code=202, content={"status": "pending"})
    del analysis_store[analysis_id]
    return result


@app.get("/chat/{session_id}")
def get_chat(session_id: str):
    return fetch_messages(session_id)


@app.delete("/chat/{session_id}")
def delete_chat(session_id: str):
    count = delete_messages(session_id)
    return {"ok": True, "deleted": count}
