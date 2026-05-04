from __future__ import annotations

import json
import os
import re
import time

from database import upsert_user_memory
from ollama_client import generate_json_message


MEMORY_EXTRACTION_TIMEOUT_SEC = float(os.getenv("MEMORY_EXTRACTION_TIMEOUT_SEC", "30"))

VALID_SUBJECTS = {
    "걷기",
    "걸음수 채우기",
    "계단 이용하기",
    "줄넘기",
    "스쿼트",
    "버피테스트",
    "팔굽혀펴기",
    "팔벌려뛰기",
    "플랭크",
    "벽 밀기",
    "제자리 달리기",
    "자유 운동",
    "스트레칭",
    "활동 놀이",
    "야외 놀이",
    "자전거 타기",
    "물 마시기",
    "아침 식사",
    "규칙적 식사",
    "균형 식단",
    "천천히 먹기",
    "과식 방지",
    "야식 금지",
    "식사 집중",
    "식사 위생",
    "간식 줄이기",
    "건강 간식 선택",
    "과일 먹기",
    "채소 먹기",
    "우유 마시기",
    "가공식품 줄이기",
    "건강 음료 선택",
    "취침 시간 지키기",
    "취침 전 루틴",
    "기상 시간 지키기",
    "기상 후 루틴",
    "손 씻기",
    "양치하기",
    "위생 관리",
    "독서",
    "정리 정돈",
    "공부 집중",
    "계획 세우기",
    "게임 시간 줄이기",
    "숏폼 줄이기",
    "영상 시청 줄이기",
    "스마트폰 절제",
    "화면 없는 시간",
}

SHORT_MEMORY_SKIP_ANSWERS = {
    "응",
    "ㅇ",
    "ㅇㅇ",
    "응응",
    "어",
    "엉",
    "네",
    "그래",
    "좋아",
    "맞아",
    "아니",
    "아냐",
    "ㄴ",
    "ㄴㄴ",
    "아님",
    "싫어",
    "취소",
}

PREFERENCE_POSITIVE_RE = re.compile(r"좋아|재밌|재미있|하고\s*싶|괜찮")
PREFERENCE_NEGATIVE_RE = re.compile(r"싫어|싫다|재미없|재미\s*없|별로")
DIFFICULTY_RE = re.compile(r"어려워|어렵|어려움|힘들|못하겠|까먹|깜빡|못\s*했|못했")
GENERIC_SUBJECTS = {"자유 운동", "활동 놀이", "야외 놀이"}
SUBJECT_ALIASES = {
    "축구": "자유 운동",
    "농구": "자유 운동",
    "야구": "자유 운동",
    "수영": "자유 운동",
    "태권도": "자유 운동",
    "달리기": "자유 운동",
    "배드민턴": "활동 놀이",
    "탁구": "활동 놀이",
    "훌라후프": "활동 놀이",
    "공원 놀이": "야외 놀이",
}

MEMORY_EXTRACTION_SYSTEM_PROMPT = """아이의 발화에서 기억할 정보를 1개만 추출해.

저장 가능 타입: preference, difficulty
restriction(알레르기/금지활동/못 먹는 음식)은 절대 추출하지 않음.
too_easy(너무 쉬움)는 추출하지 않음.

difficulty는 "어려워/힘들어/못하겠어/까먹었어"처럼 어렵거나 실패가 명확할 때만 사용해.
preference는 "좋아/싫어/재미있어/재미없어"처럼 선호가 명확할 때 사용해.
예: "줄넘기가 싫어" → {"subject":"줄넘기","type":"preference","polarity":-1}
예: "줄넘기가 어려워" → {"subject":"줄넘기","type":"difficulty","polarity":null}

우선순위: difficulty > preference
단, "싫어/좋아/재미없어/재미있어"는 difficulty가 아니라 preference야.

subject는 아래 목록 중 하나와 정확히 일치하도록 출력해.
목록에 없거나 애매하면 {"subject": null}을 반환해.
새로운 subject를 만들지 말고, 비슷하다는 이유로 억지 매핑하지 마.
축구/농구/야구/배드민턴/수영 같은 목록 밖 활동을 "자유 운동", "활동 놀이", "야외 놀이"로 바꾸지 마.
단, 코드에 명시된 alias 매핑은 서버에서만 처리한다.

[subject 목록]
걷기, 걸음수 채우기, 계단 이용하기, 줄넘기, 스쿼트, 버피테스트,
팔굽혀펴기, 팔벌려뛰기, 플랭크, 벽 밀기, 제자리 달리기, 자유 운동,
스트레칭, 활동 놀이, 야외 놀이, 자전거 타기, 물 마시기, 아침 식사,
규칙적 식사, 균형 식단, 천천히 먹기, 과식 방지, 야식 금지, 식사 집중,
식사 위생, 간식 줄이기, 건강 간식 선택, 과일 먹기, 채소 먹기,
우유 마시기, 가공식품 줄이기, 건강 음료 선택, 취침 시간 지키기,
취침 전 루틴, 기상 시간 지키기, 기상 후 루틴, 손 씻기, 양치하기,
위생 관리, 독서, 정리 정돈, 공부 집중, 계획 세우기, 게임 시간 줄이기,
숏폼 줄이기, 영상 시청 줄이기, 스마트폰 절제, 화면 없는 시간

추출할 정보 없으면 {"subject": null} 반환.
다른 텍스트 없이 JSON만 출력.

출력 형식:
{"subject":"...","type":"preference|difficulty","polarity":1|-1|null}
"""


def should_skip_memory_extraction(
    student_id: int | None,
    user_message: str,
    is_pending_turn: bool = False,
) -> bool:
    if not student_id:
        return True
    if is_pending_turn:
        return True
    text = (user_message or "").replace(" ", "").strip()
    if not text or text == "__GREET__":
        return True
    return text in SHORT_MEMORY_SKIP_ANSWERS


def _infer_memory_signal(user_message: str) -> tuple[str | None, int | None]:
    if DIFFICULTY_RE.search(user_message or ""):
        return "difficulty", None
    if PREFERENCE_NEGATIVE_RE.search(user_message or ""):
        return "preference", -1
    if PREFERENCE_POSITIVE_RE.search(user_message or ""):
        return "preference", 1
    return None, None


def _alias_subject_from_message(user_message: str) -> str | None:
    compact_message = (user_message or "").replace(" ", "")
    for alias, subject in SUBJECT_ALIASES.items():
        if alias.replace(" ", "") in compact_message:
            return subject
    return None


def _memory_skip_reason(
    student_id: int | None,
    user_message: str,
    is_pending_turn: bool = False,
) -> str:
    if not student_id:
        return "missing_student"
    if is_pending_turn:
        return "pending_turn"
    text = (user_message or "").replace(" ", "").strip()
    if not text:
        return "empty"
    if text == "__GREET__":
        return "greet"
    if text in SHORT_MEMORY_SKIP_ANSWERS:
        return "short_answer"
    return ""


def parse_memory_candidate(raw: str, user_message: str = "") -> dict | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    raw_subject = data.get("subject")
    subject = SUBJECT_ALIASES.get(raw_subject, raw_subject)
    alias_subject = _alias_subject_from_message(user_message)
    if alias_subject and subject in GENERIC_SUBJECTS:
        subject = alias_subject
    if not subject:
        return None
    if subject not in VALID_SUBJECTS:
        return None
    if subject in GENERIC_SUBJECTS:
        compact_message = (user_message or "").replace(" ", "")
        subject_mentioned = subject.replace(" ", "") in compact_message
        if not subject_mentioned and alias_subject != subject:
            return None

    memory_type = data.get("type")
    if memory_type not in {"preference", "difficulty"}:
        return None

    polarity = data.get("polarity")
    inferred_type, inferred_polarity = _infer_memory_signal(user_message)
    if inferred_type:
        memory_type = inferred_type
        polarity = inferred_polarity

    if memory_type == "preference":
        if polarity not in {-1, 1}:
            return None
    if memory_type == "difficulty":
        polarity = None

    return {
        "subject": subject,
        "memory_type": memory_type,
        "polarity": polarity,
    }


async def extract_and_save_memory(
    student_id: int | None,
    user_message: str,
    is_pending_turn: bool = False,
) -> dict | None:
    skip_reason = _memory_skip_reason(student_id, user_message, is_pending_turn)
    if skip_reason:
        print(f"[Memory] skipped reason={skip_reason} message={user_message[:60]!r}")
        return None

    print(f"[Memory] extracting student={student_id} message={user_message[:80]!r}")
    started_at = time.perf_counter()
    try:
        raw = await generate_json_message(
            MEMORY_EXTRACTION_SYSTEM_PROMPT,
            f"발화: {user_message}",
            timeout=MEMORY_EXTRACTION_TIMEOUT_SEC,
        )
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        print(
            "[Memory] extraction skipped "
            f"error_type={type(e).__name__} error={e!r} elapsed_ms={elapsed_ms}"
        )
        return None

    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
    print(f"[Memory] extraction done elapsed_ms={elapsed_ms}")
    print(f"[Memory] raw={raw[:200]!r}")
    candidate = parse_memory_candidate(raw, user_message)
    if not candidate:
        print(f"[Memory] no valid memory raw={raw[:120]!r}")
        return None

    print(
        "[Memory] parsed "
        f"subject={candidate['subject']} type={candidate['memory_type']} "
        f"polarity={candidate['polarity']}"
    )
    saved = upsert_user_memory(
        student_id=student_id,
        subject=candidate["subject"],
        memory_type=candidate["memory_type"],
        polarity=candidate["polarity"],
    )
    if saved:
        print(
            "[Memory] saved "
            f"student={student_id} subject={candidate['subject']} type={candidate['memory_type']}"
            f" score={saved.get('score')} count={saved.get('count')}"
        )
    return saved
