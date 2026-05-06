from __future__ import annotations

import json
import os
import re
import time

from activity_keys import (
    ACTIVITY_KEY_ALIASES,
    VALID_ACTIVITY_KEYS,
    normalize_activity_key,
)
from database import upsert_user_memory
from ollama_client import generate_json_message


MEMORY_EXTRACTION_TIMEOUT_SEC = float(os.getenv("MEMORY_EXTRACTION_TIMEOUT_SEC", "30"))

SHORT_MEMORY_SKIP_ANSWERS = {
    "응",
    "네",
    "넵",
    "좋아",
    "그래",
    "맞아",
    "아니",
    "아냐",
    "싫어",
    "취소",
}

TOO_EASY_RE = re.compile(r"너무\s*쉬|쉬웠|쉽다|쉬워|시시|간단")
PREFERENCE_POSITIVE_RE = re.compile(r"좋아|좋았|좋은|선호|재밌|재미있|마음에\s*들")
PREFERENCE_NEGATIVE_RE = re.compile(r"싫어|싫었|싫은|재미없|재미\s*없|별로|비선호|하기\s*싫")
DIFFICULTY_RE = re.compile(r"어려|힘들|못\s*하|못하|버거|무리|까먹|실패")

MEMORY_EXTRACTION_SYSTEM_PROMPT = """아이의 발화에서 장기기억으로 저장할 정보 1개만 JSON으로 추출해.

저장 가능한 type은 preference 또는 difficulty뿐이야.
restriction은 채팅에서 추출하지 않는다.
"너무 쉬워"처럼 쉬움 피드백은 저장하지 않는다.

subject는 반드시 아래 activity_key 목록 중 하나여야 한다.
목록에 없거나 애매하면 {"subject": null}을 출력한다.

[activity_key 목록]
{activity_keys}

출력 형식:
{"subject":"걷기","type":"preference","polarity":1}
{"subject":"줄넘기","type":"difficulty","polarity":null}
{"subject":null}

다른 설명 없이 JSON 하나만 출력해.
"""


def should_skip_memory_extraction(
    student_id: int | None,
    user_message: str,
    is_pending_turn: bool = False,
) -> bool:
    return bool(_memory_skip_reason(student_id, user_message, is_pending_turn))


def _compact(text: str) -> str:
    return "".join((text or "").split()).lower()


def _memory_skip_reason(
    student_id: int | None,
    user_message: str,
    is_pending_turn: bool = False,
) -> str:
    if not student_id:
        return "missing_student"
    if is_pending_turn:
        return "pending_turn"
    text = _compact(user_message)
    if not text:
        return "empty"
    if text == "__greet__":
        return "greet"
    if text in {_compact(value) for value in SHORT_MEMORY_SKIP_ANSWERS}:
        return "short_answer"
    if TOO_EASY_RE.search(user_message or ""):
        return "too_easy"
    return ""


def _find_activity_key_in_text(text: str) -> str | None:
    compact_text = _compact(text)
    if not compact_text:
        return None

    matches: list[tuple[int, str]] = []
    for key in VALID_ACTIVITY_KEYS:
        compact_key = _compact(key)
        if compact_key and compact_key in compact_text:
            matches.append((len(compact_key), key))

    for alias, key in ACTIVITY_KEY_ALIASES.items():
        compact_alias = _compact(alias)
        if compact_alias and compact_alias in compact_text:
            normalized = normalize_activity_key(key)
            if normalized:
                matches.append((len(compact_alias), normalized))

    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def _infer_memory_signal(user_message: str) -> tuple[str | None, int | None]:
    if TOO_EASY_RE.search(user_message or ""):
        return None, None
    if DIFFICULTY_RE.search(user_message or ""):
        return "difficulty", None
    if PREFERENCE_NEGATIVE_RE.search(user_message or ""):
        return "preference", -1
    if PREFERENCE_POSITIVE_RE.search(user_message or ""):
        return "preference", 1
    return None, None


def infer_memory_candidate_from_text(user_message: str) -> dict | None:
    memory_type, polarity = _infer_memory_signal(user_message)
    if not memory_type:
        return None

    subject = _find_activity_key_in_text(user_message)
    if not subject:
        return None

    return {
        "subject": subject,
        "memory_type": memory_type,
        "polarity": polarity,
    }


def _loads_json_object(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def parse_memory_candidate(raw: str, user_message: str = "") -> dict | None:
    data = _loads_json_object(raw)
    if not data:
        return None

    subject = normalize_activity_key(data.get("subject"))
    if not subject:
        return None

    inferred_type, inferred_polarity = _infer_memory_signal(user_message)
    memory_type = inferred_type or data.get("type")
    polarity = inferred_polarity if inferred_type else data.get("polarity")

    if memory_type not in {"preference", "difficulty"}:
        return None
    if memory_type == "preference":
        if polarity in {"1", "+1"}:
            polarity = 1
        elif polarity in {"-1", -1}:
            polarity = -1
        if polarity not in {-1, 1}:
            return None
    if memory_type == "difficulty":
        polarity = None

    return {
        "subject": subject,
        "memory_type": memory_type,
        "polarity": polarity,
    }


def _save_memory_candidate(student_id: int, candidate: dict) -> dict | None:
    return upsert_user_memory(
        student_id=student_id,
        subject=candidate["subject"],
        memory_type=candidate["memory_type"],
        polarity=candidate["polarity"],
    )


async def extract_and_save_memory(
    student_id: int | None,
    user_message: str,
    is_pending_turn: bool = False,
) -> dict | None:
    skip_reason = _memory_skip_reason(student_id, user_message, is_pending_turn)
    if skip_reason:
        print(f"[Memory] skipped reason={skip_reason} message={user_message[:60]!r}")
        return None

    rule_candidate = infer_memory_candidate_from_text(user_message)
    if rule_candidate and student_id:
        saved = _save_memory_candidate(student_id, rule_candidate)
        if saved:
            print(
                "[Memory] saved rule "
                f"student={student_id} subject={rule_candidate['subject']} "
                f"type={rule_candidate['memory_type']}"
            )
        return saved

    print(f"[Memory] extracting student={student_id} message={user_message[:80]!r}")
    started_at = time.perf_counter()
    try:
        prompt = MEMORY_EXTRACTION_SYSTEM_PROMPT.format(
            activity_keys=", ".join(sorted(VALID_ACTIVITY_KEYS))
        )
        raw = await generate_json_message(
            prompt,
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

    saved = _save_memory_candidate(student_id, candidate)
    if saved:
        print(
            "[Memory] saved llm "
            f"student={student_id} subject={candidate['subject']} type={candidate['memory_type']}"
            f" score={saved.get('score')} count={saved.get('count')}"
        )
    return saved
