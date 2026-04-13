from __future__ import annotations

from pathlib import Path
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

INPUT_FILE = RAW_DIR / "미션 데이터셋 (2).xlsx"
OUTPUT_FILE = PROCESSED_DIR / "missions_clean.csv"
SHEET_NAME = "미션 목록"


def main() -> None:
    df = pd.read_excel(INPUT_FILE, sheet_name=SHEET_NAME)

    # 필요한 컬럼만 선택
    df = df[
        [
            "mission_id",
            "mission_name",
            "main_category",
            "sub_category",
            "mission_location",
            "difficulty",
            "reward_xp",
            "mission_group",
            "mission_rule",
        ]
    ].copy()

    # NaN -> None
    df = df.where(pd.notnull(df), None)

    # 타입 정리
    df["mission_id"] = pd.to_numeric(df["mission_id"], errors="raise").astype(int)
    df["mission_name"] = df["mission_name"].astype(str).str.strip()
    df["main_category"] = df["main_category"].astype(str).str.strip()
    df["sub_category"] = df["sub_category"].astype(str).str.strip()
    df["mission_location"] = df["mission_location"].astype(str).str.strip()
    df["difficulty"] = df["difficulty"].astype(str).str.strip()
    df["mission_group"] = df["mission_group"].astype(str).str.strip()

    # reward_xp는 비어있을 수 있으면 nullable int로 처리
    df["reward_xp"] = pd.to_numeric(df["reward_xp"], errors="coerce").astype("Int64")

    # mission_rule 줄바꿈 정리
    df["mission_rule"] = (
        df["mission_rule"]
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    # 중복 mission_id 체크
    if df["mission_id"].duplicated().any():
        dupes = df[df["mission_id"].duplicated(keep=False)]["mission_id"].tolist()
        raise ValueError(f"중복된 mission_id 발견: {dupes[:20]}")

    # 저장
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    print("미션 CSV 생성 완료")
    print(f"행 수: {len(df)}")
    print(f"저장 위치: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()