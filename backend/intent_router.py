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


async def classify_intent(user_message: str) -> IntentLabel:
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": ROUTER_MODEL,
        "stream": False,
        "think": False,  # thinking 모드 비활성화
        "messages": [
            {"role": "system", "content": _INTENT_SYSTEM},
            {"role": "user", "content": user_message},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            raw = resp.json()["message"]["content"].strip()
    except Exception as e:
        print(f"[IntentRouter] 분류 실패, D로 폴백: {type(e).__name__}: {e}")
        return "D"

    match = re.search(r"\b([ABCD])\b", raw.upper())
    label: IntentLabel = match.group(1) if match else "D"  # type: ignore[assignment]
    print(f"[IntentRouter] '{user_message[:30]}' → {label}")
    return label
