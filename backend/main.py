import json
from uuid import uuid4
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from database import init_db, save_message, fetch_messages, delete_messages
from ollama_client import generate_chat_message, call_with_tools, analyze_response, OLLAMA_MODEL, FUNCTION_MODEL
from prompts import build_chat_system_prompt, FUNCTION_SYSTEM_PROMPT
from function_tools import TOOLS, execute_tool

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


# ── 금지어 위반 감지 (서버 사이드, LLM 무관) ──────────────────────────────────

FORBIDDEN_WORDS = ["엄마", "아빠", "부모님", "가족", "형", "언니", "오빠", "동생", "친구", "선생님"]


def detect_violations(ai_message: str, user_input: str) -> list[str]:
    return [
        f"금지어 언급: '{w}' (사용자가 먼저 말하지 않음)"
        for w in FORBIDDEN_WORDS
        if w in ai_message and w not in user_input
    ]


# ── 대화 채팅 ─────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    mission: str | None = None


async def _run_analysis_bg(analysis_id: str, user_input: str, ai_message: str, call1_ms: int):
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
async def post_chat(body: ChatRequest, background_tasks: BackgroundTasks):
    mission_title = body.mission or MISSION["title"]
    system_prompt = build_chat_system_prompt(mission_title)
    is_greet = body.message == "__GREET__"

    if not is_greet:
        save_message(body.session_id, "user", body.message)

    history = fetch_messages(body.session_id)
    messages = history if history else [
        {"role": "user", "content": f"안녕! 오늘 미션 '{mission_title}'을 소개하고 응원해 줘."}
    ]

    tool_called_list = []
    call1_ms = 0

    if not is_greet:
        # ── 1단계: function calling 모델로 의도 파악 ──────────────────────────
        print("\n" + "="*50)
        print("=== USER ===")
        print(f"  message : {body.message}")
        print(f"  session : {body.session_id}")
        print("="*50)

        try:
            tool_context = {"mission": MISSION, "session_id": body.session_id}
            # functiongemma는 현재 발화만 분류 — history 없이 마지막 user 메시지 1개만 전달
            classify_messages = [{"role": "user", "content": body.message}]
            text_resp, tool_calls, call1_ms = await call_with_tools(
                FUNCTION_SYSTEM_PROMPT, classify_messages, TOOLS
            )

            print("\n=== MODEL RAW RESPONSE ===")
            print(f"  model      : {FUNCTION_MODEL}")
            print(f"  elapsed_ms : {call1_ms}")
            print(f"  text_resp  : {text_resp!r}")
            print(f"  tool_calls : {tool_calls}")
            print("="*50)

            if tool_calls:
                print("\n=== TOOL CALLS ===")
                for i, tc in enumerate(tool_calls):
                    print(f"  [{i}] name      : {tc['function']['name']}")
                    print(f"  [{i}] arguments : {tc['function'].get('arguments', {})}")
                    print(f"  [{i}] args type : {type(tc['function'].get('arguments', {}))}")
                print("="*50)

                # 모든 tool_call 순서대로 실행
                tool_results = []
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args = tc["function"].get("arguments", {})
                    if isinstance(fn_args, str):
                        try:
                            fn_args = json.loads(fn_args)
                        except json.JSONDecodeError:
                            fn_args = {}
                    elif fn_args is None:
                        fn_args = {}
                    if fn_name == "no_function":
                        print(f"\n=== EXECUTE TOOL === [SKIP] no_function")
                        continue
                    print(f"\n=== EXECUTE TOOL ===")
                    print(f"  name      : {fn_name}")
                    print(f"  arguments : {fn_args}")
                    print(f"  args type : {type(fn_args)}")
                    result = execute_tool(fn_name, fn_args, tool_context)
                    print(f"\n=== TOOL RESULT ===")
                    print(f"  {result}")
                    print("="*50)
                    tool_called_list.append({"name": fn_name, "arguments": fn_args, "result": result})
                    tool_results.append(result)

                if tool_results:
                    # ── 2단계: tool 결과 포함해서 최종 응답 생성 ─────────────
                    messages_with_tool = messages + [
                        {"role": "assistant", "content": "", "tool_calls": tool_calls},
                    ] + [{"role": "tool", "content": r} for r in tool_results]
                    ai_message, call2_ms = await generate_chat_message(system_prompt, messages_with_tool)
                    call1_ms += call2_ms
                    print(f"\n=== FINAL MODEL RESPONSE === [after tool]")
                    print(f"  model      : {OLLAMA_MODEL}")
                    print(f"  elapsed_ms : {call2_ms}")
                    print(f"  ai_message : {ai_message!r}")
                    print("="*50)
                else:
                    # no_function만 있었던 경우 → 일반 텍스트 응답 재생성
                    ai_message, call2_ms = await generate_chat_message(system_prompt, messages)
                    call1_ms += call2_ms
                    print(f"\n=== FINAL MODEL RESPONSE === [no_function fallback]")
                    print(f"  model      : {OLLAMA_MODEL}")
                    print(f"  elapsed_ms : {call2_ms}")
                    print(f"  ai_message : {ai_message!r}")
                    print("="*50)
            else:
                # tool_calls 없음 → functiongemma 텍스트 응답 버리고 gemma3:4b로 재생성
                ai_message, call2_ms = await generate_chat_message(system_prompt, messages)
                call1_ms += call2_ms
                print(f"\n=== FINAL MODEL RESPONSE === [no tool_calls]")
                print(f"  model      : {OLLAMA_MODEL}")
                print(f"  elapsed_ms : {call2_ms}")
                print(f"  ai_message : {ai_message!r}")
                print("="*50)

        except Exception as e:
            print(f"\n[DEBUG] call_with_tools 예외 발생: {type(e).__name__}: {e}")
            # function calling 모델 실패 시 일반 모델로 폴백
            try:
                ai_message, call1_ms = await generate_chat_message(system_prompt, messages)
            except Exception as e2:
                raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e2}")
    else:
        # 첫 인사(__GREET__)는 function calling 없이 바로 응답
        try:
            ai_message, call1_ms = await generate_chat_message(system_prompt, messages)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}")

    save_message(body.session_id, "assistant", ai_message)

    user_input = body.message if not is_greet else ""
    violations = detect_violations(ai_message, user_input)

    analysis_id = str(uuid4())
    background_tasks.add_task(_run_analysis_bg, analysis_id, user_input, ai_message, call1_ms)

    return {
        "response": ai_message,
        "analysis_id": analysis_id,
        "tool_called": tool_called_list or None,
        "debug": {
            "violations": violations,
            "system_prompt": system_prompt,
            "history_turns": len(messages),
            "model": OLLAMA_MODEL,
            "function_model": FUNCTION_MODEL,
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
