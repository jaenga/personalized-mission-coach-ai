from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate personalized mission drafts.")
    parser.add_argument("--student-id", type=int, required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-llm", "--use-fallback", dest="use_fallback", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not os.getenv("DATABASE_URL"):
        print("ERROR: DATABASE_URL is required.")
        return 2
    if args.count < 1:
        print("ERROR: --count must be at least 1.")
        return 2

    from database import save_generated_mission_draft
    from mission_generator import generate_personalized_mission_draft_sync
    from mission_personalization import calculate_personalization_profile

    profile = calculate_personalization_profile(args.student_id)
    print(f"student_id={args.student_id}")
    print(f"candidate_activity_keys={profile.get('candidate_activity_keys', [])}")
    print(f"restricted_activity_keys={profile.get('restricted_activity_keys', [])}")
    print(f"avoid_activity_keys={profile.get('avoid_activity_keys', [])}")
    print(f"difficulty_hint={profile.get('difficulty_hint')}")

    saved_count = 0
    for idx in range(args.count):
        draft = generate_personalized_mission_draft_sync(
            profile,
            use_llm=not args.use_fallback,
            variant=idx,
        )
        print(
            f"[{idx + 1}] {draft['mission_title']} | "
            f"{draft['activity_keys']} | {draft['difficulty']}"
        )
        print(f"    {draft['mission_description']}")
        print(f"    reason: {draft['generation_reason']}")

        if args.dry_run:
            continue

        row = save_generated_mission_draft(
            student_id=args.student_id,
            mission_title=draft["mission_title"],
            mission_description=draft["mission_description"],
            activity_keys=draft["activity_keys"],
            difficulty=draft["difficulty"],
            generation_reason=draft["generation_reason"],
        )
        if row:
            saved_count += 1
            print(f"    saved generated_mission_id={row.get('id')} status={row.get('status')}")
        else:
            print("    skipped: draft did not pass DB save validation")

    if args.dry_run:
        print("dry-run complete: no generated_missions rows inserted.")
    else:
        print(f"saved_count={saved_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
