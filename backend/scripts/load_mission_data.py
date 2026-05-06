from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


BASE_DIR = Path(__file__).resolve().parent.parent
CSV_FILE = BASE_DIR / "data" / "processed" / "missions_clean.csv"

load_dotenv(BASE_DIR / ".env")
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL이 .env에 없습니다.")


def main() -> None:
    df = pd.read_csv(CSV_FILE)

    # NaN -> None
    df = df.where(pd.notnull(df), None)

    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:
        # 1) 기존 데이터 삭제
        conn.execute(text("""
            TRUNCATE TABLE mission_changes, checkin_log, student_daily_missions, missions
            RESTART IDENTITY CASCADE
        """))

        # 2) insert
        insert_sql = text("""
            INSERT INTO missions (
                mission_id,
                mission_name,
                category,
                mission_description,
                difficulty,
                is_active,
                main_category,
                sub_category,
                mission_location,
                reward_xp,
                mission_group,
                mission_rule,
                activity_key
            )
            VALUES (
                :mission_id,
                :mission_name,
                :category,
                :mission_description,
                :difficulty,
                :is_active,
                :main_category,
                :sub_category,
                :mission_location,
                :reward_xp,
                :mission_group,
                :mission_rule,
                :activity_key
            )
        """)

        rows = []
        for _, row in df.iterrows():
            rows.append(
                {
                    "mission_id": int(row["mission_id"]),
                    "mission_name": row["mission_name"],
                    "category": row["main_category"],              # 기존 category <- main_category
                    "mission_description": row["mission_rule"],    # 기존 mission_description <- mission_rule
                    "difficulty": row["difficulty"],
                    "is_active": True,
                    "main_category": row["main_category"],
                    "sub_category": row["sub_category"],
                    "mission_location": row["mission_location"],
                    "reward_xp": (
                        int(row["reward_xp"]) if row["reward_xp"] is not None else None
                    ),
                    "mission_group": row["mission_group"],
                    "mission_rule": row["mission_rule"],
                    "activity_key": row["activity_key"] if "activity_key" in df.columns else None,
                }
            )

        conn.execute(insert_sql, rows)

        # 3) 시퀀스 보정
        conn.execute(text("""
            SELECT setval(
                pg_get_serial_sequence('missions', 'mission_id'),
                (SELECT COALESCE(MAX(mission_id), 1) FROM missions)
            )
        """))

    print("missions 테이블 적재 완료")
    print(f"삽입 행 수: {len(df)}")


if __name__ == "__main__":
    main()
