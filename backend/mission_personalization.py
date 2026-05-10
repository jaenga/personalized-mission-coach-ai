from __future__ import annotations

from collections import defaultdict
from typing import Any

import psycopg2.extras

from activity_keys import VALID_ACTIVITY_KEYS, normalize_activity_key
from activity_matcher import ACTIVITY_KEY_GROUPS
from database import (
    _kst_today,
    get_conn,
    get_last_action_type,
    get_student_mission_db,
    has_checkin_today,
    insert_generated_mission,
    save_mission_adjustment,
    save_mission_change_log,
    save_generated_mission_assignment,
)


AVOID_SCORE_THRESHOLD = -2.0


def _valid_unique(values: list[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = normalize_activity_key(value)
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _restriction_mentions_outdoor(text: str | None) -> bool:
    compact = "".join((text or "").split()).lower()
    if not compact:
        return False
    outdoor_words = ("야외", "밖", "바깥", "외출", "나가", "걷기", "걷")
    blocked_words = ("못", "어려", "힘들", "불가", "안돼", "안되", "금지", "제외")
    return any(word in compact for word in outdoor_words) and any(word in compact for word in blocked_words)


def _outdoor_activity_keys() -> list[str]:
    return _valid_unique(ACTIVITY_KEY_GROUPS.get("outdoor", []))


def _difficulty_rank(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"easy", "low", "beginner"} or "쉬" in normalized or "낮" in normalized:
        return "easy"
    if normalized in {"hard", "high", "difficult"} or "어려" in normalized or "높" in normalized:
        return "hard"
    return "normal"


def _fetch_rows(student_id: int) -> tuple[list[dict], list[dict], list[dict]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, subject, type, score, count, updated_at
                FROM user_memories
                WHERE student_id = %s
                ORDER BY updated_at DESC, id DESC
                """,
                (student_id,),
            )
            memories = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT id, mission_id, activity_key, rating, review_date, created_at
                FROM mission_reviews
                WHERE student_id = %s
                ORDER BY review_date DESC, id DESC
                """,
                (student_id,),
            )
            reviews = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT id, mission_id, activity_key, reason_type, created_at
                FROM mission_change_logs
                WHERE student_id = %s
                ORDER BY created_at DESC, id DESC
                """,
                (student_id,),
            )
            change_logs = [dict(row) for row in cur.fetchall()]

    return memories, reviews, change_logs


def calculate_personalization_profile(student_id: int) -> dict[str, Any]:
    scores: dict[str, float] = defaultdict(float)
    reasons: list[dict[str, Any]] = []
    restricted: set[str] = set()
    difficulty: set[str] = set()
    avoid_events: set[str] = set()
    restriction_terms: list[str] = []
    hard_votes = 0
    easy_votes = 0

    memories, reviews, change_logs = _fetch_rows(student_id)

    for memory in memories:
        subject = memory.get("subject")
        memory_type = memory.get("type")
        if memory_type == "restriction":
            raw_subject = str(subject or "").strip()
            if raw_subject:
                restriction_terms.append(raw_subject)
            key = normalize_activity_key(subject)
            if key:
                restricted.add(key)
                reasons.append({"source": "user_memories", "type": "restriction", "activity_key": key})
            if _restriction_mentions_outdoor(subject):
                for outdoor_key in _outdoor_activity_keys():
                    restricted.add(outdoor_key)
                reasons.append({"source": "user_memories", "type": "restriction", "activity_key": "outdoor"})
            continue

        key = normalize_activity_key(subject)
        if not key:
            continue

        if memory_type == "preference":
            score = int(memory.get("score") or 0)
            scores[key] += float(score)
            if score < 0:
                avoid_events.add(key)
            reasons.append(
                {"source": "user_memories", "type": "preference", "activity_key": key, "delta": score}
            )
        elif memory_type == "difficulty":
            count = max(1, int(memory.get("count") or 1))
            scores[key] -= min(1.0, count * 0.25)
            difficulty.add(key)
            easy_votes += count
            reasons.append(
                {"source": "user_memories", "type": "difficulty", "activity_key": key, "count": count}
            )

    for review in reviews:
        key = normalize_activity_key(review.get("activity_key"))
        if not key:
            continue
        rating = int(review.get("rating") or 0)
        if rating >= 4:
            scores[key] += 1.5
            reasons.append({"source": "mission_reviews", "type": "rating_high", "activity_key": key, "rating": rating})
        elif rating <= 2:
            scores[key] -= 2.0
            avoid_events.add(key)
            reasons.append({"source": "mission_reviews", "type": "rating_low", "activity_key": key, "rating": rating})

    for log in change_logs:
        key = normalize_activity_key(log.get("activity_key"))
        if not key:
            continue
        reason_type = log.get("reason_type")
        if reason_type == "too_hard":
            scores[key] -= 1.0
            difficulty.add(key)
            easy_votes += 1
        elif reason_type == "too_easy":
            scores[key] += 0.5
            hard_votes += 1
        elif reason_type == "dislike":
            scores[key] -= 2.0
            avoid_events.add(key)
        elif reason_type == "cant_do":
            scores[key] -= 1.5
            avoid_events.add(key)
        elif reason_type == "just_change":
            scores[key] -= 0.5
        reasons.append({"source": "mission_change_logs", "type": reason_type, "activity_key": key})

    for key in restricted:
        scores.pop(key, None)
        difficulty.discard(key)
        avoid_events.discard(key)

    avoid_keys = {
        key
        for key, score in scores.items()
        if key not in restricted and (score <= AVOID_SCORE_THRESHOLD or key in avoid_events)
    }
    preferred_keys = [
        key
        for key, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if score > 0 and key not in restricted and key not in avoid_keys
    ]

    scored_candidates = [
        key
        for key, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if key not in restricted and key not in avoid_keys and score >= 0
    ]
    if not scored_candidates:
        scored_candidates = sorted(
            key for key in VALID_ACTIVITY_KEYS if key not in restricted and key not in avoid_keys
        )

    difficulty_hint = "easy" if easy_votes > hard_votes else "hard" if hard_votes > easy_votes else "normal"

    return {
        "student_id": student_id,
        "preferred_activity_keys": preferred_keys[:8],
        "avoid_activity_keys": sorted(avoid_keys),
        "restricted_activity_keys": sorted(restricted),
        "difficulty_activity_keys": sorted(key for key in difficulty if key not in restricted),
        "candidate_activity_keys": scored_candidates[:8],
        "difficulty_hint": difficulty_hint,
        "restriction_terms": restriction_terms[:20],
        "scores": {key: round(value, 2) for key, value in sorted(scores.items())},
        "reasons": reasons,
    }


def should_replace_current_mission_after_onboarding(
    student_id: int,
    newly_disliked_activity_keys: list[str] | None = None,
) -> dict[str, Any]:
    today = _kst_today()
    current = get_student_mission_db(student_id, today)
    if not current:
        return {
            "should_replace": False,
            "reason": "no current mission assigned today",
            "current_mission_id": None,
            "current_activity_key": None,
        }

    current_mission_id = current.get("mission_id")
    current_key = normalize_activity_key(current.get("activity_key"))
    profile = calculate_personalization_profile(student_id)

    base = {
        "current_mission_id": current_mission_id,
        "current_activity_key": current_key,
        "restricted_activity_keys": profile["restricted_activity_keys"],
        "avoid_activity_keys": profile["avoid_activity_keys"],
        "candidate_activity_keys": profile["candidate_activity_keys"],
        "profile": profile,
    }

    if has_checkin_today(student_id):
        return {**base, "should_replace": False, "reason": "current mission already submitted today"}

    if get_last_action_type(student_id) == "adjustment":
        return {**base, "should_replace": False, "reason": "current mission was already changed today"}

    if not current_key:
        return {
            **base,
            "should_replace": False,
            "reason": "current mission has no valid activity_key",
            "warning": "current_mission_activity_key_missing",
        }

    restricted = set(profile["restricted_activity_keys"])
    newly_disliked = set(_valid_unique(newly_disliked_activity_keys or []))
    scores = profile.get("scores", {})
    strong_avoid = {
        key
        for key in profile["avoid_activity_keys"]
        if float(scores.get(key, 0)) <= AVOID_SCORE_THRESHOLD or key in newly_disliked
    }
    difficulty_keys = set(profile["difficulty_activity_keys"])
    difficulty_rank = _difficulty_rank(current.get("difficulty"))

    if current_key in restricted:
        return {
            **base,
            "should_replace": True,
            "reason": "current mission activity_key is restricted",
            "replace_reason": "현재 미션이 제한한 활동과 겹쳐서 바꿨어",
        }

    if current_key in newly_disliked:
        return {
            **base,
            "should_replace": True,
            "reason": "current mission activity_key was disliked during onboarding",
            "replace_reason": "현재 미션이 싫어하는 활동과 겹쳐서 바꿨어",
        }

    if current_key in strong_avoid:
        return {
            **base,
            "should_replace": True,
            "reason": "current mission activity_key is strongly disliked",
            "replace_reason": "현재 미션이 비선호 활동과 겹쳐서 바꿨어",
        }

    if current_key in difficulty_keys and difficulty_rank == "hard":
        return {
            **base,
            "should_replace": True,
            "reason": "current mission is hard for a difficult activity_key",
            "replace_reason": "현재 미션이 어려웠던 활동이고 난이도도 높아서 바꿨어",
        }

    return {
        **base,
        "should_replace": False,
        "reason": "current mission is compatible with onboarding preferences",
    }


def _order_case(activity_keys: list[str]) -> str:
    if not activity_keys:
        return "0"
    return "CASE " + " ".join(
        f"WHEN activity_key = %s THEN {idx}" for idx, _ in enumerate(activity_keys)
    ) + " ELSE 999 END"


def _select_replacement(
    current_mission_id: int,
    preferred_keys: list[str],
    excluded_keys: list[str],
) -> dict | None:
    preferred_keys = _valid_unique(preferred_keys)
    excluded_keys = _valid_unique(excluded_keys)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if preferred_keys:
                order_case = _order_case(preferred_keys)
                cur.execute(
                    f"""
                    SELECT mission_id, mission_name, mission_rule, activity_key,
                           difficulty, main_category, mission_location
                    FROM missions
                    WHERE is_active = TRUE
                      AND mission_id != %s
                      AND activity_key = ANY(%s)
                      AND NOT (activity_key = ANY(%s))
                    ORDER BY {order_case}, RANDOM()
                    LIMIT 1
                    """,
                    [current_mission_id, preferred_keys, excluded_keys, *preferred_keys],
                )
                row = cur.fetchone()
                if row:
                    return dict(row)

            cur.execute(
                """
                SELECT mission_id, mission_name, mission_rule, activity_key,
                       difficulty, main_category, mission_location
                FROM missions
                WHERE is_active = TRUE
                  AND mission_id != %s
                  AND NOT (activity_key = ANY(%s))
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (current_mission_id, excluded_keys),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
            return None


def replace_current_mission_after_onboarding(
    student_id: int,
    newly_disliked_activity_keys: list[str] | None = None,
) -> dict[str, Any]:
    decision = should_replace_current_mission_after_onboarding(student_id, newly_disliked_activity_keys)
    if not decision.get("should_replace"):
        return {
            **decision,
            "mission_changed": False,
            "replace_reason": None,
            "new_mission": None,
        }

    profile = decision["profile"]
    current_mission_id = int(decision["current_mission_id"])
    restricted = profile["restricted_activity_keys"]
    avoid = profile["avoid_activity_keys"]
    candidate_keys = profile["candidate_activity_keys"]

    preferred_candidates = [key for key in candidate_keys if key not in restricted and key not in avoid]
    replacement = _select_replacement(
        current_mission_id=current_mission_id,
        preferred_keys=preferred_candidates,
        excluded_keys=[*restricted, *avoid],
    )
    if not replacement:
        replacement = _select_replacement(
            current_mission_id=current_mission_id,
            preferred_keys=[],
            excluded_keys=[*restricted, *avoid],
        )

    if not replacement:
        return {
            **decision,
            "mission_changed": False,
            "replace_reason": None,
            "new_mission": None,
            "warning": "no_safe_replacement_mission",
        }

    save_mission_adjustment(student_id, current_mission_id, replacement["mission_id"])
    try:
        save_mission_change_log(student_id, current_mission_id, "onboarding_auto_replace")
    except Exception as exc:
        print(f"[OnboardingReplace] reason log failed: {type(exc).__name__}: {exc}")

    return {
        **decision,
        "mission_changed": True,
        "replace_reason": decision.get("replace_reason") or "입력한 정보를 반영해서 오늘 미션을 바꿨어",
        "new_mission": {
            "mission_id": replacement.get("mission_id"),
            "mission_name": replacement.get("mission_name"),
            "mission_rule": replacement.get("mission_rule"),
            "activity_key": normalize_activity_key(replacement.get("activity_key")),
            "difficulty": replacement.get("difficulty"),
        },
    }


def replace_with_personalized_mission(
    student_id: int,
    current_mission_id: int | None = None,
    reason_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    today = _kst_today()
    current = get_student_mission_db(student_id, today)
    if not current:
        return {
            "mission_changed": False,
            "reason": "no current mission assigned today",
            "new_mission": None,
        }

    active_mission_id = int(current.get("mission_id"))
    if current_mission_id and int(current_mission_id) != active_mission_id:
        return {
            "mission_changed": False,
            "reason": "current mission has already changed",
            "new_mission": {
                "mission_id": active_mission_id,
                "mission_name": current.get("mission_name"),
                "mission_rule": current.get("mission_rule"),
                "activity_key": normalize_activity_key(current.get("activity_key")),
                "difficulty": current.get("difficulty"),
            },
        }

    if has_checkin_today(student_id):
        return {
            "mission_changed": False,
            "reason": "current mission already submitted today",
            "new_mission": None,
        }

    if get_last_action_type(student_id) == "adjustment":
        return {
            "mission_changed": False,
            "reason": "current mission was already changed today",
            "new_mission": None,
        }

    profile = calculate_personalization_profile(student_id)
    restricted = profile["restricted_activity_keys"]
    avoid = profile["avoid_activity_keys"]
    candidate_keys = [
        key
        for key in profile["candidate_activity_keys"]
        if key not in restricted and key not in avoid
    ]

    replacement = _select_replacement(
        current_mission_id=active_mission_id,
        preferred_keys=candidate_keys,
        excluded_keys=[*restricted, *avoid],
    )
    if not replacement:
        replacement = _select_replacement(
            current_mission_id=active_mission_id,
            preferred_keys=[],
            excluded_keys=[*restricted, *avoid],
        )

    if not replacement:
        return {
            "mission_changed": False,
            "reason": "no safe personalized replacement mission",
            "new_mission": None,
            "profile": profile,
        }

    save_mission_adjustment(student_id, active_mission_id, replacement["mission_id"])
    try:
        save_mission_change_log(student_id, active_mission_id, "personalized_change")
    except Exception as exc:
        print(f"[PersonalizedChange] reason log failed: {type(exc).__name__}: {exc}")

    return {
        "mission_changed": True,
        "reason": (reason_context or {}).get("source_reason") or "personalized_change",
        "profile": profile,
        "new_mission": {
            "mission_id": replacement.get("mission_id"),
            "mission_name": replacement.get("mission_name"),
            "mission_rule": replacement.get("mission_rule"),
            "activity_key": normalize_activity_key(replacement.get("activity_key")),
            "difficulty": replacement.get("difficulty"),
        },
    }


def assign_generated_mission_to_today(
    student_id: int,
    generated: dict[str, Any],
    current_mission_id: int | None = None,
    source_reason: str | None = None,
) -> dict[str, Any]:
    today = _kst_today()
    current = get_student_mission_db(student_id, today)
    if not current:
        return {
            "mission_changed": False,
            "reason": "no current mission assigned today",
            "new_mission": None,
        }

    active_mission_id = int(current.get("mission_id"))
    if current_mission_id and int(current_mission_id) != active_mission_id:
        return {
            "mission_changed": False,
            "reason": "current mission has already changed",
            "new_mission": None,
        }

    if has_checkin_today(student_id):
        return {
            "mission_changed": False,
            "reason": "current mission already submitted today",
            "new_mission": None,
        }

    if get_last_action_type(student_id) == "adjustment":
        return {
            "mission_changed": False,
            "reason": "current mission was already changed today",
            "new_mission": None,
        }

    inserted = insert_generated_mission(generated)
    if not inserted:
        return {
            "mission_changed": False,
            "reason": "generated mission insert failed",
            "new_mission": None,
        }

    save_mission_adjustment(student_id, active_mission_id, inserted["mission_id"])
    try:
        save_generated_mission_assignment(
            student_id,
            generated,
            inserted["mission_id"],
            source_reason=source_reason,
            status="assigned",
        )
    except Exception as exc:
        print(f"[GeneratedMission] audit log failed: {type(exc).__name__}: {exc}")
    try:
        save_mission_change_log(student_id, active_mission_id, "generated_change")
    except Exception as exc:
        print(f"[GeneratedMission] reason log failed: {type(exc).__name__}: {exc}")

    return {
        "mission_changed": True,
        "reason": "generated_change",
        "new_mission": {
            "mission_id": inserted.get("mission_id"),
            "mission_name": inserted.get("mission_name"),
            "mission_rule": inserted.get("mission_rule"),
            "activity_key": normalize_activity_key(inserted.get("activity_key")),
            "difficulty": inserted.get("difficulty"),
        },
    }
