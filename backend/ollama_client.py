import os
import json
import re
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


async def generate_chat_message(system_prompt: str, messages: list[dict]) -> tuple[str, int]:
    """1차 호출: 대화 응답 생성. Returns (ai_message, call1_ms)"""
    t0 = time.perf_counter()
    ai_message = await _call_ollama(
        [{"role": "system", "content": system_prompt}] + messages,
    )
    call1_ms = round((time.perf_counter() - t0) * 1000)
    return ai_message, call1_ms


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
