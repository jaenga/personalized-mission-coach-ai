from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate missions.activity_key backfill SQL.")
    parser.add_argument("xlsx_path", help="Path to the mission workbook with an activity_key column.")
    parser.add_argument(
        "--output",
        default="backend/scripts/backfill_activity_keys.sql",
        help="Output SQL path.",
    )
    args = parser.parse_args()

    df = pd.read_excel(args.xlsx_path, sheet_name="미션 목록")
    required = {"mission_id", "activity_key"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    rows = []
    for _, row in df[["mission_id", "activity_key"]].dropna().iterrows():
        mission_id = int(row["mission_id"])
        activity_key = str(row["activity_key"]).strip()
        if activity_key:
            rows.append(f"        ({mission_id}, {sql_quote(activity_key)})")

    if not rows:
        raise ValueError("No activity_key rows found.")

    sql = "\n".join([
        "-- Backfill missions.activity_key from 미션 데이터셋_activity_key_매칭본.xlsx.",
        "-- Run location:",
        "--   psql \"$DATABASE_URL\" -f backend/scripts/backfill_activity_keys.sql",
        "",
        "BEGIN;",
        "",
        "ALTER TABLE missions",
        "ADD COLUMN IF NOT EXISTS activity_key TEXT;",
        "",
        "UPDATE missions AS m",
        "SET activity_key = v.activity_key",
        "FROM (",
        "    VALUES",
        ",\n".join(rows),
        ") AS v(mission_id, activity_key)",
        "WHERE m.mission_id = v.mission_id;",
        "",
        "COMMIT;",
        "",
    ])

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(sql, encoding="utf-8")
    print(f"wrote {output} ({len(rows)} mappings)")


if __name__ == "__main__":
    main()
