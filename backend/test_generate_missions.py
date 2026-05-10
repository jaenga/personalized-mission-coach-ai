import asyncio
import json
from mission_generator import generate_realtime_personalized_mission

TEST_CASES = [
    {
        "name": "과일 먹기 / normal",
        "candidate_activity_keys": ["과일 먹기"],
        "preferred_activity_keys": ["과일 먹기"],
        "avoid_activity_keys": [],
        "restricted_activity_keys": [],
        "difficulty_activity_keys": [],
        "difficulty_hint": "normal",
        "restriction_terms": [],
    },
    {
        "name": "과일 먹기 / easy",
        "candidate_activity_keys": ["과일 먹기"],
        "preferred_activity_keys": ["과일 먹기"],
        "avoid_activity_keys": [],
        "restricted_activity_keys": [],
        "difficulty_activity_keys": [],
        "difficulty_hint": "easy",
        "restriction_terms": [],
    },
    {
        "name": "물 마시기 / normal",
        "candidate_activity_keys": ["물 마시기"],
        "preferred_activity_keys": ["물 마시기"],
        "avoid_activity_keys": [],
        "restricted_activity_keys": [],
        "difficulty_activity_keys": [],
        "difficulty_hint": "normal",
        "restriction_terms": [],
    },
    {
        "name": "물 마시기 / hard",
        "candidate_activity_keys": ["물 마시기"],
        "preferred_activity_keys": ["물 마시기"],
        "avoid_activity_keys": [],
        "restricted_activity_keys": [],
        "difficulty_activity_keys": [],
        "difficulty_hint": "hard",
        "restriction_terms": [],
    },
    {
        "name": "스트레칭 / normal",
        "candidate_activity_keys": ["스트레칭"],
        "preferred_activity_keys": ["스트레칭"],
        "avoid_activity_keys": [],
        "restricted_activity_keys": [],
        "difficulty_activity_keys": [],
        "difficulty_hint": "normal",
        "restriction_terms": [],
    },
    {
        "name": "손 씻기 / normal",
        "candidate_activity_keys": ["손 씻기"],
        "preferred_activity_keys": ["손 씻기"],
        "avoid_activity_keys": [],
        "restricted_activity_keys": [],
        "difficulty_activity_keys": [],
        "difficulty_hint": "normal",
        "restriction_terms": [],
    },
    {
        "name": "채소 먹기 / normal",
        "candidate_activity_keys": ["채소 먹기"],
        "preferred_activity_keys": ["채소 먹기"],
        "avoid_activity_keys": [],
        "restricted_activity_keys": [],
        "difficulty_activity_keys": [],
        "difficulty_hint": "normal",
        "restriction_terms": [],
    },
    {
        "name": "운동 후보 여러 개 / 스트레칭 비선호",
        "candidate_activity_keys": ["스트레칭", "걷기", "줄넘기"],
        "preferred_activity_keys": ["걷기", "줄넘기"],
        "avoid_activity_keys": ["스트레칭"],
        "restricted_activity_keys": [],
        "difficulty_activity_keys": [],
        "difficulty_hint": "normal",
        "restriction_terms": [],
    },
    {
        "name": "야외 제한 / 실내 활동 후보",
        "candidate_activity_keys": ["걷기", "스트레칭", "손 씻기"],
        "preferred_activity_keys": ["스트레칭", "손 씻기"],
        "avoid_activity_keys": [],
        "restricted_activity_keys": ["걷기", "야외 놀이", "자전거 타기"],
        "difficulty_activity_keys": [],
        "difficulty_hint": "easy",
        "restriction_terms": ["오늘은 밖에 나가기 어려움"],
    },
    {
        "name": "음식 제한 / 과일 피하고 채소 후보",
        "candidate_activity_keys": ["과일 먹기", "채소 먹기", "물 마시기"],
        "preferred_activity_keys": ["채소 먹기", "물 마시기"],
        "avoid_activity_keys": ["과일 먹기"],
        "restricted_activity_keys": [],
        "difficulty_activity_keys": [],
        "difficulty_hint": "normal",
        "restriction_terms": ["과일은 오늘 먹기 어려움"],
    },
]


async def generate_one(case, index):
    profile = {
        "student_id": 63,
        "preferred_activity_keys": case["preferred_activity_keys"],
        "avoid_activity_keys": case["avoid_activity_keys"],
        "restricted_activity_keys": case["restricted_activity_keys"],
        "difficulty_activity_keys": case["difficulty_activity_keys"],
        "candidate_activity_keys": case["candidate_activity_keys"],
        "difficulty_hint": case["difficulty_hint"],
        "restriction_terms": case["restriction_terms"],
    }

    print(f"\n===== {index}. {case['name']} =====")
    print("[profile]")
    print(json.dumps(profile, ensure_ascii=False, indent=2))

    mission = await generate_realtime_personalized_mission(
        profile,
        max_attempts=2,
        timeout=80.0,
    )

    print("\n[validated mission]")
    if mission is None:
        print("None / validation_failed")
    else:
        print(json.dumps(mission, ensure_ascii=False, indent=2))


async def main():
    for index, case in enumerate(TEST_CASES, start=1):
        await generate_one(case, index)


asyncio.run(main())