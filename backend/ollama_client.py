import os
import re
import json
import time
import httpx
from dotenv import load_dotenv
from equivalency_judgment import EquivalencyJudgment, normalize_decision
from equivalency_normalizer import normalize_equivalency_text

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


def strip_markdown(text: str) -> str:
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\*(.+?)\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"_(.+?)_", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^\s*[-*+]\s", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s", "", text, flags=re.MULTILINE)
    return text.strip()


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
    return strip_markdown(resp.json()["message"]["content"])


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


async def judge_mission_equivalency(judge_system_prompt: str, user_message: str) -> EquivalencyJudgment:
    """대체 수행 판정 전용 호출.

    Expected JSON:
    {"decision": "approved|denied|clarify", "reason": "...", "reply": "...", "clarify_question": null|"..." }
    Legacy {"approved": bool, "need_clarification": bool} responses are still accepted as a fallback.
    """
    raw = None
    try:
        normalized = normalize_equivalency_text(user_message)
        judge_user_message = user_message
        if normalized != user_message:
            judge_user_message = (
                f"원문: {user_message}\n"
                f"표준화 참고: {normalized}\n"
                "표준화 참고는 단위 비교용일 뿐이고, 최종 판단은 시스템 기준으로 해."
            )
        raw = await generate_json_message(judge_system_prompt, judge_user_message, timeout=30.0)
        result = json.loads(raw)
        decision = normalize_decision(
            result.get("decision"),
            approved=result.get("approved"),
            need_clarification=result.get("need_clarification"),
        )
        clarify_question = result.get("clarify_question")
        if not isinstance(clarify_question, str) or not clarify_question.strip():
            clarify_question = None
        if decision == "clarify" and not clarify_question:
            clarify_question = "무엇을 얼마나 했는지 조금만 더 알려줄래?"
        reply = str(result.get("reply") or "").strip()
        if not reply:
            if decision == "approved":
                reply = "응, 그 방법은 미션 기준에 맞아."
            elif decision == "denied":
                reply = "그 방법은 이번 미션 기준으로는 인정하기 어려워."
            else:
                reply = "조금만 더 알려줘야 정확히 볼 수 있어."
        return EquivalencyJudgment(
            decision=decision,
            reason=str(result.get("reason") or "").strip(),
            reply=reply,
            clarify_question=clarify_question,
            raw=result,
        )
    except Exception as e:
        raw_preview = ""
        if raw is not None:
            raw_preview = raw[:200].replace("\n", " ")
        print(
            f"[Equivalency] judge call failed: type={type(e).__name__} "
            f"msg={e!r} raw_len={len(raw) if raw is not None else 0} "
            f"raw_preview={raw_preview!r}"
        )
        return EquivalencyJudgment(
            decision="clarify",
            reason="json_parse_failed",
            reply="조금만 더 알려줘야 정확히 볼 수 있어.",
            clarify_question="무엇을 얼마나 했는지 알려줄래?",
        )


async def generate_json_message(system_prompt: str, user_message: str, timeout: float = 10.0) -> str:
    """JSON 전용 호출. 미션 생성처럼 긴 JSON도 끊기지 않도록 충분한 출력 길이를 둔다."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": "json",
        "think": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 768,
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }
    resp = await _get_client().post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()
