"""
Qwen3 펑션콜링 클라이언트 — Ollama API 방식
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
FUNCTION_MODEL = os.getenv("FUNCTION_MODEL", "qwen3-function:latest")

AVAILABLE_FUNCTIONS: list[dict] = [
    {
        "name": "submit_mission_result",
        "description": (
            "미션 수행 결과를 확정해서 보고할 때 호출합니다.\n"
            "- success: 완료 (다 했어요)\n"
            "- fail: 수행 못함 (못 했어요, 조금 했어요)\n"
            "- 사용하지 않는 경우: 규칙 질문, 미션 변경 요청, 인정 여부 질문"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "result_type": {
                    "type": "string",
                    "enum": ["success", "fail"],
                    "description": "미션 달성 정도 (값: success[완료], fail[수행 실패])",
                },
            },
            "required": ["result_type"],
        },
    },
    {
        "name": "get_mission_info",
        "description": (
            "미션 관련 정보(오늘 미션, 마감 시간, 규칙)를 물어볼 때 호출합니다.\n"
            "- today: 오늘 미션의 내용, 수행 방법, 주의사항, 수행 조건을 물을 때\n"
            "- deadline: 제출 마감, 기한을 물을 때\n"
            "- general_rule: 앱/시스템 차원의 제출·인증·판정·운영 규칙을 물을 때\n"
            "- 사용하지 않는 경우: 결과 보고, 미션 변경 요청, 대체 수행 가능 여부 질문"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": ["today", "deadline", "general_rule"],
                    "description": "조회할 정보의 종류",
                },
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "request_mission_adjustment",
        "description": (
            "미션을 바꾸거나 난이도를 조정해 달라고 요청할 때 호출합니다.\n"
            "- change: 다른 미션 요청\n"
            "- easier: 더 쉬운 미션 요청\n"
            "- harder: 더 어려운 미션 요청"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "adjustment_type": {
                    "type": "string",
                    "enum": ["change", "easier", "harder"],
                    "description": "미션 내용 조정 종류",
                },
            },
            "required": ["adjustment_type"],
        },
    },
    {
        "name": "check_mission_equivalency",
        "description": (
            "다른 행동/장소/시간으로 수행해도 인정되는지 물어볼 때 호출합니다.\n"
            "- behavior: 행동 변경 (자전거로 해도 돼요?)\n"
            "- place: 장소 변경 (집에서 해도 돼요?)\n"
            "- time: 시간 변경 (저녁에 하면 되나요?)"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "equivalency_type": {
                    "type": "string",
                    "enum": ["behavior", "place", "time"],
                    "description": "학생이 제안한 대체 행동 내용",
                },
            },
            "required": ["equivalency_type"],
        },
    },
    {
        "name": "get_user_history",
        "description": (
            "미션 수행 기록을 조회할 때 호출합니다.\n"
            "- weekly_summary: 이번 주 기록\n"
            "- monthly_summary: 이번 달 기록"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": ["weekly_summary", "monthly_summary"],
                    "description": "조회할 기록의 범위",
                },
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "cancel_mission_action",
        "description": (
            "가장 최근 행동을 취소할 때 호출합니다.\n"
            "예: 방금 제출 취소 / 바꾼 거 없던 걸로"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]


# 학습 시 사용한 시스템 메시지 (single_turn_qwen2.jsonl 기준 그대로 사용)
_SYSTEM_PROMPT = """당신은 어린이 건강 습관 코치 앱의 AI입니다. 사용자 발화를 보고 반드시 제공된 함수 중 하나를 호출해야 합니다. 자연어 답변은 절대 생성하지 마세요. 함수 호출만 출력하세요.

함수 선택 시 주의사항:
- 마감 시간·기한을 물으면 → get_mission_info(deadline)
- 규칙·인정 기준·인증 방법을 물으면 → get_mission_info(general_rule)
- 구체적인 대체 행동/장소/시간을 언급하면 → check_mission_equivalency
- 미션 완료/실패를 보고하면 → submit_mission_result"""


def preload_qwen() -> None:
    """Ollama 방식에서는 별도 preload 불필요. 호환성 유지용."""
    print(f"[Qwen] Ollama 모델 사용: {FUNCTION_MODEL}")


def call_function(user_message: str) -> tuple[list[tuple[str, dict]], int]:
    payload = {
        "model": FUNCTION_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message + " /no_think"},
        ],
    }

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            resp.raise_for_status()
            raw = resp.json()["message"]["content"].strip()
    except Exception as e:
        print(f"[Qwen] Ollama 호출 실패: {e}")
        return [], 0

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    print(f"[Qwen] raw output ({elapsed_ms}ms): {raw[:300]}")

    calls = _parse_tool_calls(raw)
    print(f"[Qwen] 펑션콜: {calls}")
    return calls, elapsed_ms


def _parse_tool_calls(text: str) -> list[tuple[str, dict]]:
    results = []
    for match in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.DOTALL):
        try:
            obj = json.loads(match.group(1))
            name = obj.get("name")
            args = obj.get("arguments", {})
            if name:
                results.append((name, args))
        except json.JSONDecodeError:
            pass

    if results:
        return results

    # fallback: 배열 형태 [{"name": ..., "arguments": ...}, ...]
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            arr = json.loads(match.group(0))
            for obj in arr:
                name = obj.get("name")
                args = obj.get("arguments", {})
                if name:
                    results.append((name, args))
            if results:
                return results
        except json.JSONDecodeError:
            pass

    return []
