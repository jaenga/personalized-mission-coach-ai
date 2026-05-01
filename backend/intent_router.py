"""
Intent Router — Gemma4:e2b로 사용자 입력을 A/B/C/D 네 가지 인텐트로 분류

A: 잡담/감정표현   → Gemma4가 바로 응답
B: 앱 기능 요청    → qwen-lora-finetuned 펑션콜링
C: 건강 관련 질문  → RAG 조회 후 Gemma4 응답
D: 애매/정보 부족  → Gemma4가 짧게 되묻기
"""
from __future__ import annotations

import os
import re
import httpx
from typing import Literal

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gemma4:e2b")

IntentLabel = Literal["A", "B", "C", "D"]

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient()
    return _client


async def close_intent_router_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None

_HEALTH_QUESTION_RE = re.compile(
    r"(왜|어떻게|좋아|좋아요|나빠|나빠요|건강|효과|도움|중요|필요|영양|칼로리|키가|살이|아파|통증)"
)

# 규칙 기반 pre-classification (LLM 호출 없이 바로 반환)
_PRE_GREET_RE = re.compile(
    r"^(안녕|하이|헬로|hi|hello|ㅎㅇ|반가워|좋은\s*아침|굿모닝|굿모닝!|안뇽)[\s!~.]*$",
    re.IGNORECASE,
)

# 잡담/감정 키워드 — 미션명 컨텍스트를 붙이면 B로 오분류될 수 있어서 제외
_CASUAL_EMOTION_RE = re.compile(
    r"배고|심심|졸려|피곤|힘들어|슬퍼|짜증|우울|기분|신나|좋겠|싫어|무서|외로|행복|설레"
)
_MISSION_COMMAND_RE = re.compile(
    r"(미션|제출|성공|완료|실패|취소|바꿔|변경|쉽게|어렵게|조회|기록|마감|규칙|기준|인증)"
)
_NUMERIC_REPORT_RE = re.compile(
    r"(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*"
    r"(?:분|보|바퀴|회|세트|번|초|시간|개|잔|컵|걸음|쪽|장|줄)"
)

_INTENT_SYSTEM = _INTENT_SYSTEM = """너는 초등학생 AI 생활습관 코치 앱의 인텐트 분류기야.
사용자 메시지를 읽고 아래 중 하나만 답해.

## 분류 기준

**A: 잡담/감정표현**
- 기분, 일상 이야기, 칭찬 요청, 감정 공유
- 예시: "오늘 기분 좋아", "심심해", "칭찬해줘"

**B: 앱 기능 요청**
- 미션 제출/취소, 미션 교체/난이도 조정, 기록 조회
- **미션 정보 조회**: 오늘 미션, 마감시간, 성공 기준, 규칙
- 키워드: "제출", "취소", "바꿔", "난이도", "쉽게", "어렵게", "조회", "기록", "요약", "마감", "규칙", "기준"
- 예시: 
  * "미션 성공했어요" → B (미션 제출)
  * "취소해줘" → B (취소 요청)
  * "더 쉽게 해줘" → B (난이도 조정)
  * "이번 주 기록 보여줘" → B (기록 조회)
  * "미션 바꿔줘" → B (미션 교체)
  * "오늘 미션 뭐야?" → B (미션 정보)
  * "마감 언제까지야?" → B (마감 정보)
  * "성공 기준이 뭐예요?" → B (규칙 정보)
  * "인증 어떻게 해?" → B (미션 규칙)

**C: 건강 지식 질문**
- **건강/영양/운동/습관에 대한 일반 지식** 질문만 해당
- "왜", "어떻게", "좋아요", "나빠요" 등 건강 정보 요청
- 예시:
  * "물을 많이 마시면 왜 좋아요?" → C
  * "스트레칭은 왜 해야 해요?" → C
  * "아침밥을 먹으면 어떤 점이 좋아요?" → C
  * "채소를 먹으면 건강에 좋아요?" → C
  * "일찍 자는 게 왜 중요해요?" → C
  * "운동하면 키가 커요?" → C

**D: 애매/정보 부족**
- 의미 불분명, 단어 하나, 맥락 없음
- 예시: "응", "ㅇㅇ", "그거"

## 중요 규칙
1. **미션 관련 모든 것**(제출/취소/조정/조회/규칙/마감) → 무조건 **B**
2. **건강 지식** 질문("왜 좋아요", "어떻게 해요", "건강") → **C**
3. 감정 표현만 있으면 → **A**
4. 판단 불가하면 → **D**

## 헷갈리는 케이스
- "오늘 미션 뭐야?" → B (미션 정보)
- "물 마시기가 왜 좋아요?" → C (건강 지식)
- "줄넘기 대신 달리기 해도 돼요?" → B (미션 교체/규칙)
- "스트레칭은 왜 해야 해요?" → C (건강 지식)

반드시 A, B, C, D 중 한 글자만 출력해."""


_SPLIT_SYSTEM = """사용자 메시지에 앱 기능 요청이 2개 들어있으면 분리해줘.

규칙:
- 기능 요청이 1개면 → 그대로 출력
- 기능 요청이 2개면 → 줄바꿈으로 구분해서 2줄 출력
- 반드시 원문의 의미를 유지해. 요약하거나 바꾸지 마.
- 최대 2개까지만.

예시:
입력: "미션 성공이요! 이번 주 기록도 보여줘"
출력:
미션 성공이요!
이번 주 기록도 보여줘

입력: "취소하고 다시 성공으로 제출해줘"
출력:
취소해줘
성공으로 제출해줘

입력: "미션 바꿔줘"
출력:
미션 바꿔줘"""


async def split_multi_intent(user_message: str) -> list[str]:
    """B 인텐트 메시지를 기능 단위로 분리. 1~2개 반환."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": ROUTER_MODEL,
        "stream": False,
        "think": False,
        "messages": [
            {"role": "system", "content": _SPLIT_SYSTEM},
            {"role": "user", "content": user_message},
        ],
    }
    try:
        resp = await _get_client().post(url, json=payload, timeout=30.0)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
    except Exception as e:
        print(f"[IntentRouter] 문장 분리 실패, 원문 유지: {e}")
        return [user_message]

    parts = [line.strip() for line in raw.split("\n") if line.strip()]
    if len(parts) == 0:
        return [user_message]
    if len(parts) > 2:
        parts = parts[:2]
    return parts


async def classify_intent(user_message: str, mission_name: str = "") -> IntentLabel:
    stripped = user_message.strip()

    # Pre-classification: 명백한 인사 → A (LLM 없이)
    if _PRE_GREET_RE.match(stripped):
        print("[PreClassify] greeting → A")
        return "A"

    # Pre-classification: 1~2글자 단답 (미션 키워드 없으면) → D
    if len(stripped) <= 2 and not _MISSION_COMMAND_RE.search(stripped):
        print(f"[PreClassify] short input({len(stripped)}글자) → D")
        return "D"

    use_mission_context = (
        bool(mission_name)
        and mission_name != "오늘의 미션"
        and _HEALTH_QUESTION_RE.search(user_message) is None
        and _CASUAL_EMOTION_RE.search(user_message) is None
    )
    prompt_message = f"[오늘 미션: {mission_name}]\n{user_message}" if use_mission_context else user_message
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": ROUTER_MODEL,
        "stream": False,
        "think": False,
        "messages": [
            {"role": "system", "content": _INTENT_SYSTEM},
            {"role": "user", "content": prompt_message},
        ],
    }
    try:
        resp = await _get_client().post(url, json=payload, timeout=60.0)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
    except Exception as e:
        print(f"[IntentRouter] 분류 실패, D로 폴백: {type(e).__name__}: {e}")
        return "D"

    match = re.search(r"\b([ABCD])\b", raw.upper())
    label: IntentLabel = match.group(1) if match else "D"  # type: ignore[assignment]
    return label
