import os
import json
import re
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")
FUNCTION_MODEL = os.getenv("FUNCTION_MODEL", "functiongemma")


async def _call_ollama(messages: list[dict], use_json: bool = False) -> str:
    """Ollama /api/chat 기본 호출 헬퍼."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload: dict = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": messages,
    }
    if use_json:
        payload["format"] = "json"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return data["message"]["content"].strip()


async def generate_chat_message(system_prompt: str, messages: list[dict]) -> tuple[str, int]:
    """1차 호출: 대화 응답 생성. Returns (ai_message, call1_ms)"""
    t0 = time.perf_counter()
    ai_message = await _call_ollama(
        [{"role": "system", "content": system_prompt}] + messages,
    )
    call1_ms = round((time.perf_counter() - t0) * 1000)
    return ai_message, call1_ms


async def call_with_tools(
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
) -> tuple[str | None, list[dict] | None, int]:
    """
    Function calling 호출.
    Returns: (text_response, tool_calls, elapsed_ms)
      - 모델이 함수를 선택하면 tool_calls에 목록, text_response는 None
      - 일반 응답이면 text_response에 텍스트, tool_calls는 None
    """
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": FUNCTION_MODEL,
        "stream": False,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "tools": tools,
    }

    print("\n" + "="*50)
    print("=== FUNCTION CALLING PAYLOAD ===")
    print(f"  model : {FUNCTION_MODEL}")
    print(f"\n  [system_prompt]\n{payload['messages'][0]['content']}")
    print(f"\n  [messages] ({len(payload['messages']) - 1}턴)")
    for i, m in enumerate(payload["messages"][1:]):
        role = m.get("role", "?")
        content = m.get("content", "")[:200]
        print(f"    [{i}] {role}: {content!r}")
    print(f"\n  [tools] ({len(payload['tools'])}개)")
    for t in payload["tools"]:
        fn = t["function"]
        print(f"    - {fn['name']}: {fn['description'][:80]!r}...")
    print("="*50)

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    elapsed_ms = round((time.perf_counter() - t0) * 1000)

    msg = data["message"]
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        return None, tool_calls, elapsed_ms
    return msg["content"].strip(), None, elapsed_ms


async def analyze_response(user_input: str, ai_message: str) -> tuple[dict, int]:
    """2차 호출: 생성된 응답 분석. Returns (reasoning_dict, call2_ms)"""
    from prompts import build_analysis_prompt

    analysis_prompt = build_analysis_prompt(user_input, ai_message)
    t0 = time.perf_counter()
    try:
        raw = await _call_ollama(
            [{"role": "user", "content": analysis_prompt}],
            use_json=True,
        )
        reasoning = _parse_analysis(raw)
    except Exception:
        reasoning = {}
    call2_ms = round((time.perf_counter() - t0) * 1000)
    return reasoning, call2_ms


def _parse_analysis(raw: str) -> dict:
    """분석 JSON을 파싱해서 reasoning 딕셔너리로 반환."""
    obj = None
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, AttributeError):
        pass

    if obj is None:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group())
            except (json.JSONDecodeError, AttributeError):
                pass

    if obj and isinstance(obj, dict):
        sentence_analysis = [
            {"sentence": obj.get(f"s{i}", "").strip(), "purpose": obj.get(f"p{i}", "").strip()}
            for i in range(1, 4)
            if obj.get(f"s{i}", "").strip()
        ]
        return {
            "input_signal":      obj.get("input_signal", ""),
            "applied_rule":      obj.get("applied_rule", ""),
            "avoided":           obj.get("avoided", ""),
            "response_choice":   obj.get("response_choice", ""),
            "sentence_analysis": sentence_analysis,
        }

    return {}
