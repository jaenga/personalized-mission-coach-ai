import os
import json
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b")


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


async def generate_chat_message_stream(system_prompt: str, messages: list[dict]):
    """스트리밍 응답 생성. 토큰을 하나씩 yield."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "stream": True,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue


async def generate_chat_message(system_prompt: str, messages: list[dict]) -> tuple[str, int]:
    """1차 호출: 대화 응답 생성. Returns (ai_message, call1_ms)"""
    t0 = time.perf_counter()
    ai_message = await _call_ollama(
        [{"role": "system", "content": system_prompt}] + messages,
    )
    call1_ms = round((time.perf_counter() - t0) * 1000)
    return ai_message, call1_ms


