import os
import json
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b")


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient()
    return _client


async def close_ollama_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _call_ollama(messages: list[dict], use_json: bool = False) -> str:
    """Ollama /api/chat 기본 호출 헬퍼."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload: dict = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": messages,
        "think": False,
    }
    if use_json:
        payload["format"] = "json"

    resp = await _get_client().post(url, json=payload, timeout=60.0)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


async def generate_chat_message_stream(system_prompt: str, messages: list[dict]):
    """스트리밍 응답 생성. 토큰을 하나씩 yield."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "stream": True,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "think": False,
    }
    async with _get_client().stream("POST", url, json=payload, timeout=120.0) as resp:
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


async def generate_json_message(system_prompt: str, user_message: str, timeout: float = 10.0) -> str:
    """짧은 JSON 전용 호출. background task에서 무한 대기를 피하려고 timeout을 짧게 둔다."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": "json",
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": 96,
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }
    resp = await _get_client().post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()
