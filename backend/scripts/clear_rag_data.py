from __future__ import annotations

import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL이 없습니다. backend/.env 확인")

def main() -> None:
    confirm = input("정말 documents/chunks/faqs 데이터를 모두 비울까요? yes 입력 시 진행: ")

    if confirm != "yes":
        print("취소했습니다.")
        return

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE faqs, chunks, documents CASCADE;")
        conn.commit()

    print("RAG 데이터 초기화 완료")

if __name__ == "__main__":
    main()