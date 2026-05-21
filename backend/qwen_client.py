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
_PAST_RESULT_TIME_RE = re.compile(r"어제|그저께|엊그제|지난번|저번|예전|수요일|월요일|화요일|목요일|금요일|토요일|일요일")
_EXPLICIT_SUBMIT_REPORT_RE = re.compile(
    r"미션\s*(?:성공|실패|완료)"
    r"|오늘\s*미션\s*(?:성공|실패|완료)"
    r"|(?:성공|실패|완료|끝냈|다\s*했|다했|수행했|해냈)"
    r"|(?:못\s*했|못했|안\s*했|안했|까먹)"
    r"|(?:먹음|마심|참았|먹어버|해버|봄|안\s*먹|안\s*봤|안\s*탔|씻었|닦았|올라갔)"
)
_EQUIVALENCY_QUESTION_RE = re.compile(
    r"대신|말고|없어서|없으면|다른|바꿔서|같은\s*걸로|쳐줘|봐줘|인정"
    r"|성공(?:이야|임|인가|으로)"
    r"|실패(?:야|임|인가)"
    r"|(?:하면|하면은|면)\s*(?:돼|되|괜찮|인정)"
    r"|해도\s*(?:돼|되|괜찮|인정)"
    r"|먹어도\s*(?:돼|되|괜찮|인정)"
    r"|마셔도\s*(?:돼|되|괜찮|인정)"
    r"|봐도\s*(?:돼|되|괜찮|인정)"
    r"|걸어도\s*(?:돼|되|괜찮|인정)"
    r"|씻어도\s*(?:돼|되|괜찮|인정)"
    r"|타도\s*(?:돼|되|괜찮|인정)"
    r"|들어도\s*(?:돼|되|괜찮|인정)"
    r"|올라가도\s*(?:돼|되|괜찮|인정)"
    r"|에서\s*(?:해도|해도돼|해도되|돼|되|괜찮)"
    r"|후에\s*(?:해도|해도돼|해도되|돼|되|괜찮)"
    r"|전에\s*(?:해도|해도돼|해도되|돼|되|괜찮)"
)

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
- "대신", "말고", "해도 돼?", "인정돼?", "같은 걸로 봐줘?", "집/복도/학교/저녁/아침에 해도 돼?"처럼 대체 가능성을 묻는 말은 규칙 질문이 아니라 check_mission_equivalency
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
    if _is_past_result_statement(user_message):
        return []
    strong_equivalency_call = detect_strong_equivalency_call(user_message)
    if strong_equivalency_call:
        return [strong_equivalency_call]
    submit_report_call = detect_submit_report_call(user_message)
    if submit_report_call:
        return [submit_report_call]
    adjustment_call = detect_mission_adjustment_call(user_message)
    if adjustment_call:
        return [adjustment_call]
    calls = _coerce_history_call(user_message, calls)
    if calls and calls[0][0] == "get_user_history":
        return calls
    mission_info_call = detect_mission_info_call(user_message)
    if mission_info_call:
        calls = [mission_info_call]
    weak_equivalency_call = detect_weak_equivalency_call(user_message)
    if weak_equivalency_call and not mission_info_call:
        return [weak_equivalency_call]
    coerced = [_coerce_function_call(user_message, call) for call in calls]
    if not _EXPLICIT_SUBMIT_REPORT_RE.search(user_message or ""):
        before = len(coerced)
        coerced = [call for call in coerced if call[0] != "submit_mission_result"]
        if before != len(coerced):
            print("[Function] dropped submit call without explicit submit report")
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


_MISSION_INFO_RE = re.compile(
    r"(미션|mission).{0,10}(뭐|뭔|무엇|어떤|알려|알고|알아|있어|있냐|있니|뭐야|뭔지|뭔데|뭔디|뭐냐|뭐예요|뭐에요|뭐임|뭐죠|뭐요|뭔가요|뭐니|궁금)",
    re.IGNORECASE,
)


# "strong" equivalency: 사용자가 "대신/말고/대체" 같은 명시적 대체 의도 키워드를 쓴 경우.
# 이건 진짜 동치 질문이므로 다른 라우팅보다 우선해야 한다.
_STRONG_EQUIVALENCY_SIGNAL_RE = re.compile(r"대신에?|말고|대체로?")


def _classify_equivalency_type(text: str) -> str:
    place_patterns = (
        r"(?:집|학교|운동장|복도|밖|야외|교실|방|거실).{0,8}(?:에서|으로|로|말고)",
        r"(?:집|학교).{0,4}계단",
    )
    time_patterns = (
        r"(?:아침(?!밥)|저녁|밤|낮).{0,10}(?:후에|전에|시간|걸어도|해도|돼|되|괜찮|인정)",
        r"(?:(?<!전)후에|전에|전에만|뒤에|나중에|있다가|조금\s*있다가).{0,12}(?:해도|돼|되|괜찮|인정|성공|실패|마셔도|씻어도)",
        r"(?:기상|잠들기|외출|직후|직전).{0,12}(?:해도|돼|되|괜찮|인정|성공|실패)",
        r"\d+\s*분.{0,8}(?:넘|초과|이면|보면\s*실패|실패)",
    )
    if any(re.search(pattern, text) for pattern in place_patterns):
        return "place"
    if any(re.search(pattern, text) for pattern in time_patterns):
        return "time"
    return "behavior"


def _equivalency_call_common_guards(text: str, compact: str) -> bool:
    """equivalency 라우팅 공통 가드. True면 매칭 차단."""
    if not _EQUIVALENCY_QUESTION_RE.search(text):
        return True
    if detect_mission_info_call(text):
        return True
    if any(word in compact for word in ("미션변경", "바꿔줘", "교체해줘", "쉬운걸로", "어려운걸로")):
        return True
    if any(word in compact for word in ("기록", "조회", "요약", "취소", "되돌려")):
        return True
    return False


def detect_strong_equivalency_call(user_message: str) -> tuple[str, dict] | None:
    """명시적 대체 의도("대신/말고/대체")가 있는 진짜 동치 질문만 잡는다."""
    text = user_message or ""
    compact = text.replace(" ", "")
    if _equivalency_call_common_guards(text, compact):
        return None
    if not _STRONG_EQUIVALENCY_SIGNAL_RE.search(text):
        return None
    eq_type = _classify_equivalency_type(text)
    return ("check_mission_equivalency", {"equivalency_type": eq_type})


def detect_weak_equivalency_call(user_message: str) -> tuple[str, dict] | None:
    """대체 의도 키워드 없이 의문문("성공이야?/인정돼?")만 있는 경우.

    submit_report/get_mission_info detector 뒤에 호출되어 fallback 역할.
    """
    text = user_message or ""
    compact = text.replace(" ", "")
    if _equivalency_call_common_guards(text, compact):
        return None
    if _STRONG_EQUIVALENCY_SIGNAL_RE.search(text):
        # 이미 strong이 잡혔어야 함. 여기까지 오면 호출 순서 잘못이지만 안전하게 처리.
        eq_type = _classify_equivalency_type(text)
        return ("check_mission_equivalency", {"equivalency_type": eq_type})
    eq_type = _classify_equivalency_type(text)
    return ("check_mission_equivalency", {"equivalency_type": eq_type})


# 하위 호환: 기존 호출 코드는 strong+weak 합쳐서 본다.
def detect_equivalency_call(user_message: str) -> tuple[str, dict] | None:
    return detect_strong_equivalency_call(user_message) or detect_weak_equivalency_call(user_message)


def detect_mission_info_call(user_message: str) -> tuple[str, dict] | None:
    text = user_message or ""
    compact = text.replace(" ", "")
    if any(word in compact for word in ("마감", "기한", "언제까지", "몇시까지", "몇시까지야")):
        return ("get_mission_info", {"query_type": "deadline"})
    if any(word in compact for word in ("인증방법", "인증규칙", "인정기준", "제출규칙", "판정기준", "성공기준", "실패기준")):
        return ("get_mission_info", {"query_type": "general_rule"})
    if re.search(r"(얼마나|몇\s*분|몇\s*개|몇\s*번|몇\s*회).{0,12}(해야|하면|걸어야|걸으면|올라가야|오르면|마셔야|먹어야|봐야|보면)", text):
        return ("get_mission_info", {"query_type": "general_rule"})
    if re.search(r"(만\s*)?(해도|하면|먹어도|마셔도|봐도|씻으면|닦으면).{0,8}(돼|되나|되냐|성공|괜찮)", text):
        if not any(word in compact for word in ("대신", "말고", "대체", "없어서", "없는데")):
            return ("get_mission_info", {"query_type": "general_rule"})
    if re.search(r"(아무거나|시리얼|한\s*잔|한잔|손만|양치만|바닥만|꼭|이나|그렇게나).{0,12}(돼|해야|성공|되나|되냐)", text):
        return ("get_mission_info", {"query_type": "general_rule"})
    if "아까" in text and "오늘" in text and re.search(r"성공|미션", text):
        return ("get_mission_info", {"query_type": "today"})

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

    has_mission = "미션" in text or "mission" in text.lower()
    asks_what = any(word in compact for word in [
        "뭐야", "뭔지", "뭔데", "뭔디", "뭐냐고", "뭐냐", "뭐예요", "뭐에요",
        "뭐임", "뭐죠", "뭐요", "뭔가요", "뭐니", "무엇", "알려줘", "알려줄래",
        "알고싶어", "알아야", "알고싶은데", "알려",
    ])

    if not asks_history and (_MISSION_INFO_RE.search(compact) or asks_assigned_mission or (has_mission and asks_what)):
        args = {"query_type": "today"}
        if "그저께" in text:
            args["target_date"] = "day_before_yesterday"
        elif "어제" in text:
            args["target_date"] = "yesterday"
        elif "오늘" in text or not has_date:
            args["target_date"] = "today"
        return ("get_mission_info", args)
    return None


def detect_mission_adjustment_call(user_message: str) -> tuple[str, dict] | None:
    text = user_message or ""
    compact = text.replace(" ", "")
    if any(word in compact for word in ("취소", "되돌려", "철회")):
        return None
    if re.search(r"쉬운걸로|쉽게(?:바꿔|해줘|변경)", compact):
        return ("request_mission_adjustment", {"adjustment_type": "easier"})
    if re.search(r"다른거|다른걸|다른미션|바꿔줘|변경해줘|교체해줘", compact):
        return ("request_mission_adjustment", {"adjustment_type": "change"})
    return None


def detect_submit_report_call(user_message: str) -> tuple[str, dict] | None:
    text = user_message or ""
    compact = text.replace(" ", "")

    if _is_past_result_statement(text):
        return None

    if any(word in compact for word in ("성공이야", "성공인가", "성공맞아", "성공임")):
        if any(word in compact for word in ("했는데", "했어", "했어요", "끝냈", "다했", "수행했", "해냈")):
            return ("submit_mission_result", {"result_type": "success"})

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
        "패스함",
        "탔어",
        "먹어버",
        "해버",
        "봤어",
        "봄",
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
        "먹음",
        "마심",
        "참았",
        "안먹",
        "안봤",
        "안탔",
        "씻었",
        "닦았",
        "올라갔",
        "끝내고",
    ]

    if re.search(r"(엘리베이터|엘레베이터|엘베|승강기).{0,12}(탔|이용)", compact):
        if re.search(r"안(?:탔|타고|이용)|대신", compact) and "계단" in compact:
            return ("submit_mission_result", {"result_type": "success"})
        return ("submit_mission_result", {"result_type": "fail"})
    if re.search(r"(과자|쿠키|포카칩|스낵).{0,12}(안먹|참았)", compact):
        return ("submit_mission_result", {"result_type": "success"})
    if re.search(r"(과자|쿠키|포카칩|스낵).{0,12}(먹어버|먹었|먹음|먹었다)", compact):
        return ("submit_mission_result", {"result_type": "fail"})
    if re.search(r"(손씻|손을씻|손씻었|손만씻|씻었)", compact) and not is_question:
        return ("submit_mission_result", {"result_type": "success"})
    if re.search(r"(아침밥|아침).{0,8}(먹음|먹었)", compact):
        return ("submit_mission_result", {"result_type": "success"})
    if re.search(r"(물).{0,8}(마심|마셨어|마셨)", compact):
        return ("submit_mission_result", {"result_type": "success"})

    if any(word in compact for word in fail_words):
        return ("submit_mission_result", {"result_type": "fail"})
    if any(word in compact for word in success_words):
        return ("submit_mission_result", {"result_type": "success"})

    return None


def _is_past_result_statement(user_message: str) -> bool:
    text = user_message or ""
    if "오늘" in text:
        return False
    return bool(_PAST_RESULT_TIME_RE.search(text) and re.search(r"성공|했|먹|마셨|봤|봄|안\s*먹|안\s*봤", text))


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
