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

_FUNCTION_NAME_ALIASES = {
    "cancel_mission": "cancel_mission_action",
}

_CANCEL_REQUEST_RE = re.compile(r"취소|되돌|되돌려|철회|원래대로|없던\s*걸로|없던걸로")

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
            "- today: 오늘/어제/그저께/특정 날짜에 배정된 미션의 내용, 수행 방법, 주의사항, 수행 조건을 물을 때\n"
            "- \"오늘 미션 뭐야?\" → query_type='today', target_date='today'\n"
            "- \"어제 미션 뭐였어?\", \"어제 나 뭐 해야 했어?\" → query_type='today', target_date='yesterday'\n"
            "- \"그저께 미션 뭐였어?\" → query_type='today', target_date='day_before_yesterday'\n"
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
                "target_date": {
                    "type": "string",
                    "description": "조회할 미션 날짜. today, yesterday, day_before_yesterday 또는 YYYY-MM-DD",
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
            "- daily_summary: 하루 기록 조회\n"
            "- weekly_summary: 주간 기록 조회\n"
            "- monthly_summary: 월간 기록 조회\n"
            "예시:\n"
            "- 이번 주 기록 → query_type='weekly_summary', target_period='this_week'\n"
            "- 지난주 기록 → query_type='weekly_summary', target_period='last_week'\n"
            "- 이번 달 기록 → query_type='monthly_summary', target_period='this_month'\n"
            "- 지난달 기록 → query_type='monthly_summary', target_period='last_month'\n"
            "- 특정 월 기록을 물으면 target_month에 해당 월을 2자리 숫자로 넣습니다.\n"
            "  예: 4월 기록 → query_type='monthly_summary', target_month='04', "
            "5월 기록 → query_type='monthly_summary', target_month='05'\n"
            "- 오늘 기록 → query_type='daily_summary', target_date='today'\n"
            "- 어제 기록 → query_type='daily_summary', target_date='yesterday'\n"
            "- 그저께 기록 → query_type='daily_summary', target_date='day_before_yesterday'\n"
            "- 4월 12일 기록 → query_type='daily_summary', target_date='YYYY-MM-DD'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": ["daily_summary", "weekly_summary", "monthly_summary"],
                    "description": "조회할 기록의 범위",
                },
                "target_period": {
                    "type": "string",
                    "enum": ["this_week", "last_week", "this_month", "last_month"],
                    "description": "주간/월간 조회 대상 기간. 명확할 때만 사용",
                },
                "target_date": {
                    "type": "string",
                    "description": "일간 조회 날짜. today, yesterday, day_before_yesterday 또는 YYYY-MM-DD",
                },
                "target_month": {
                    "type": "string",
                    "description": "월간 조회 월. MM 또는 YYYY-MM",
                },
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "cancel_mission_action",
        "description": (
            "미션 제출이나 미션 변경을 취소할 때 호출합니다.\n"
            "- cancel_type='submit': 성공/실패/제출/기록 취소\n"
            "- cancel_type='adjustment': 미션 변경 취소\n"
            "- cancel_type='latest': 최근 작업 취소, 되돌려줘처럼 대상이 모호한 경우\n"
            "예: 성공 취소 / 방금 제출 취소 / 바꾼 거 없던 걸로 / 최근 작업 되돌려줘"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cancel_type": {
                    "type": "string",
                    "enum": ["submit", "adjustment", "latest"],
                    "description": "취소 대상",
                },
            },
        },
    },
]


# 학습 시 사용한 시스템 메시지 (single_turn_qwen2.jsonl 기준 그대로 사용)
_SYSTEM_PROMPT = """당신은 어린이 건강 습관 코치 앱의 AI입니다. 사용자 발화를 보고 반드시 제공된 함수 중 하나를 호출해야 합니다. 자연어 답변은 절대 생성하지 마세요. 함수 호출만 출력하세요.

함수 선택 시 주의사항:
- 오늘/어제/그저께/특정 날짜에 배정된 미션이 무엇인지 물으면 → get_mission_info(query_type="today", target_date=...)
- "오늘 미션 뭐야?" → get_mission_info(query_type="today", target_date="today")
- "어제 미션 뭐였어?", "어제 나 뭐 해야 했어?" → get_mission_info(query_type="today", target_date="yesterday")
- "그저께 미션 뭐였어?" → get_mission_info(query_type="today", target_date="day_before_yesterday")
- 마감 시간·기한을 물으면 → get_mission_info(deadline)
- 규칙·인정 기준·인증 방법을 물으면 → get_mission_info(general_rule)
- 미션 기록/조회/요약/성공 여부/실패 여부를 물으면 → get_user_history
- "어제 기록 보여줘"는 get_user_history, "어제 미션 뭐였어"는 get_mission_info
- 이번 주 기록 → query_type="weekly_summary", target_period="this_week"
- 지난주 기록 → query_type="weekly_summary", target_period="last_week"
- 이번 달 기록 → query_type="monthly_summary", target_period="this_month"
- 지난달 기록 → query_type="monthly_summary", target_period="last_month"
- 특정 월 기록을 물으면 target_month에 해당 월을 2자리 숫자로 넣어라.
  예: "4월 기록" → target_month="04", "5월 기록" → target_month="05"
- 오늘 기록 → query_type="daily_summary", target_date="today"
- 어제 기록 → query_type="daily_summary", target_date="yesterday"
- 그저께 기록 → query_type="daily_summary", target_date="day_before_yesterday"
- 구체적인 대체 행동/장소/시간을 언급하면 → check_mission_equivalency
- 성공/실패/제출/기록 취소 → cancel_mission_action(cancel_type="submit")
- 미션 변경 취소/바꾼 거 취소 → cancel_mission_action(cancel_type="adjustment")
- 최근 작업 취소/되돌려줘 → cancel_mission_action(cancel_type="latest")
- 미션 완료/실패를 보고하면 → submit_mission_result"""


def preload_qwen() -> None:
    """Ollama 방식에서는 별도 preload 불필요. 호환성 유지용."""
    print(f"[Qwen] Ollama 모델 사용: {FUNCTION_MODEL}")


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient()
    return _client


async def close_qwen_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None


async def call_function(user_message: str) -> tuple[list[tuple[str, dict]], int]:
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
        resp = await _get_client().post(
            f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=60.0
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
    except Exception as e:
        print(f"[Qwen] Ollama 호출 실패: {e}")
        return [], 0

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    calls = _parse_tool_calls(raw)
    calls = _canonicalize_function_calls(calls)
    calls = _coerce_function_calls(user_message, calls)
    return calls, elapsed_ms


def _canonicalize_function_calls(
    calls: list[tuple[str, dict]],
) -> list[tuple[str, dict]]:
    normalized = []
    for fn, args in calls:
        canonical_fn = _FUNCTION_NAME_ALIASES.get(fn, fn)
        canonical_args = dict(args or {})
        if canonical_fn == "cancel_mission_action":
            cancel_type = canonical_args.get("cancel_type")
            if cancel_type not in {"submit", "adjustment", "latest"}:
                canonical_args["cancel_type"] = "latest"
        normalized.append((canonical_fn, canonical_args))
    return normalized


def _coerce_function_calls(
    user_message: str,
    calls: list[tuple[str, dict]],
) -> list[tuple[str, dict]]:
    mission_info_call = detect_mission_info_call(user_message)
    if mission_info_call:
        calls = [mission_info_call]
    submit_report_call = detect_submit_report_call(user_message)
    if submit_report_call:
        calls = [submit_report_call]
        return calls
    calls = _coerce_history_call(user_message, calls)
    coerced = [_coerce_function_call(user_message, call) for call in calls]
    if not _CANCEL_REQUEST_RE.search(user_message or ""):
        before = len(coerced)
        coerced = [call for call in coerced if call[0] != "cancel_mission_action"]
        if before != len(coerced):
            print("[Function] dropped cancel call without cancel expression")
    return coerced


def _coerce_function_call(
    user_message: str,
    call: tuple[str, dict],
) -> tuple[str, dict]:
    fn, args = _coerce_mission_info_call(user_message, call)
    if fn != "cancel_mission_action":
        return fn, args

    args = dict(args or {})
    args["cancel_type"] = _detect_cancel_type(user_message)
    return fn, args


def _detect_cancel_type(user_message: str) -> str:
    text = (user_message or "").replace(" ", "")
    if re.search(r"(?:성공|실패|제출|기록|결과)[\s\S]{0,12}(?:취소|되돌|철회)", text):
        return "submit"
    if re.search(r"(?:미션변경|변경|바꾼거|원래미션)[\s\S]{0,12}(?:취소|되돌|철회)", text):
        return "adjustment"
    return "latest"


def _coerce_mission_info_call(
    user_message: str,
    call: tuple[str, dict],
) -> tuple[str, dict]:
    fn, args = call
    if fn != "get_mission_info":
        return call

    args = dict(args or {})
    query_type = args.get("query_type")

    if query_type not in {"today", "deadline", "general_rule"}:
        if "마감" in user_message or "기한" in user_message:
            args = {"query_type": "deadline"}
        elif "규칙" in user_message or "인정" in user_message or "인증" in user_message:
            args = {"query_type": "general_rule"}
        else:
            args = {"query_type": "today"}

    if args.get("query_type") == "today":
        if "그저께" in user_message:
            args["target_date"] = "day_before_yesterday"
        elif "어제" in user_message:
            args["target_date"] = "yesterday"
        elif "오늘" in user_message:
            args["target_date"] = "today"
        else:
            args.setdefault("target_date", "today")

    return fn, args


def detect_mission_info_call(user_message: str) -> tuple[str, dict] | None:
    text = user_message or ""
    compact = text.replace(" ", "")
    has_date = (
        "오늘" in text
        or "어제" in text
        or "그저께" in text
        or re.search(r"\d{4}-\d{2}-\d{2}", text)
    )
    asks_assigned_mission = (
        "미션" in text
        and any(word in compact for word in ("뭐", "무엇", "머였", "뭐였", "내용", "배정"))
    ) or any(word in compact for word in ("뭐해야", "해야했어", "해야했", "뭘해야"))
    asks_history = any(word in text for word in ("기록", "요약", "성공", "실패", "완료", "제출"))

    if has_date and asks_assigned_mission and not asks_history:
        return ("get_mission_info", {"query_type": "today"})
    return None


def detect_submit_report_call(user_message: str) -> tuple[str, dict] | None:
    text = user_message or ""
    compact = text.replace(" ", "")

    is_question = (
        "?" in text
        or any(word in compact for word in [
            "확인해줘",
            "확인해",
            "맞아",
            "맞나요",
            "맞는거야",
            "된거야",
            "인거야",
            "했어?",
            "성공이야?",
        ])
    )
    if is_question:
        return None

    fail_words = [
        "미션실패",
        "오늘미션실패",
        "실패했",
        "못했",
        "못했어",
        "안했",
        "안했어",
        "까먹",
        "못끝",
    ]
    success_words = [
        "미션성공",
        "오늘미션성공",
        "성공했",
        "미션완료",
        "오늘미션완료",
        "완료했",
        "끝냈",
        "다했",
        "다했어",
        "수행했",
    ]

    if any(word in compact for word in fail_words):
        return ("submit_mission_result", {"result_type": "fail"})
    if any(word in compact for word in success_words):
        return ("submit_mission_result", {"result_type": "success"})

    return None


_HISTORY_QUERY_RE = re.compile(
    r"기록|조회|요약|뭐\s*했|했었|성공.*몇|실패.*몇|성공했|실패했|완료했|제출했"
)
_MONTH_HISTORY_RE = re.compile(
    r"(?:(20\d{2})\s*년\s*)?(\d{1,2})\s*월.*(?:기록|조회|요약|보여|알려)"
)


def _coerce_history_call(
    user_message: str,
    calls: list[tuple[str, dict]],
) -> list[tuple[str, dict]]:
    if detect_mission_info_call(user_message):
        return calls
    history_call = detect_history_call(user_message)
    if history_call:
        return [history_call]
    return calls


def detect_history_call(user_message: str) -> tuple[str, dict] | None:
    text = user_message or ""
    compact = text.replace(" ", "")

    has_date = (
        "오늘" in text
        or "어제" in text
        or "그저께" in text
        or re.search(r"\d{4}-\d{2}-\d{2}", text)
    )
    asks_status = any(word in compact for word in [
        "성공했",
        "실패했",
        "완료했",
        "제출했",
        "기록됐",
        "저장됐",
    ])
    is_question = (
        "?" in text
        or compact.endswith(("어", "나", "니", "나요", "었어", "였어"))
    )

    if has_date and asks_status and is_question:
        iso_date = re.search(r"\d{4}-\d{2}-\d{2}", text)
        if "그저께" in text:
            return ("get_user_history", {
                "query_type": "daily_summary",
                "target_date": "day_before_yesterday",
            })
        if "어제" in text:
            return ("get_user_history", {
                "query_type": "daily_summary",
                "target_date": "yesterday",
            })
        if "오늘" in text:
            return ("get_user_history", {
                "query_type": "daily_summary",
                "target_date": "today",
            })
        if iso_date:
            return ("get_user_history", {
                "query_type": "daily_summary",
                "target_date": iso_date.group(0),
            })

    if not _HISTORY_QUERY_RE.search(user_message):
        return None

    month_match = _MONTH_HISTORY_RE.search(user_message)
    if month_match:
        year, month_raw = month_match.groups()
        month = int(month_raw)
        if 1 <= month <= 12:
            target_month = f"{year}-{month:02d}" if year else f"{month:02d}"
            return ("get_user_history", {
                "query_type": "monthly_summary",
                "target_month": target_month,
            })

    if "그저께" in user_message:
        return ("get_user_history", {
            "query_type": "daily_summary",
            "target_date": "day_before_yesterday",
        })
    if "어제" in user_message:
        return ("get_user_history", {
            "query_type": "daily_summary",
            "target_date": "yesterday",
        })
    if "오늘" in user_message:
        return ("get_user_history", {
            "query_type": "daily_summary",
            "target_date": "today",
        })
    if "지난주" in user_message:
        return ("get_user_history", {
            "query_type": "weekly_summary",
            "target_period": "last_week",
        })
    if "이번 주" in user_message or "이번주" in user_message:
        return ("get_user_history", {
            "query_type": "weekly_summary",
            "target_period": "this_week",
        })
    if "지난달" in user_message:
        return ("get_user_history", {
            "query_type": "monthly_summary",
            "target_period": "last_month",
        })
    if "이번 달" in user_message or "이번달" in user_message:
        return ("get_user_history", {
            "query_type": "monthly_summary",
            "target_period": "this_month",
        })

    return None


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
