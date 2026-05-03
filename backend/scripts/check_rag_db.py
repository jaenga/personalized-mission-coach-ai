#
# RAG 데이터베이스 상태를 확인하는 스크립트! 
# 그냥 확인용임 딱히 기능은 없음
# 삭제해도 되는 파일입니다!!
from __future__ import annotations

import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
if not DATABASE_URL:
    raise ValueError('DATABASE_URL이 없습니다. backend/.env 확인')

QUERIES = {
    'documents': 'SELECT COUNT(*) FROM documents;',
    'chunks': 'SELECT COUNT(*) FROM chunks;',
    'faqs': 'SELECT COUNT(*) FROM faqs;',
    'chunks_with_embedding': 'SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL;',
    'faqs_with_embedding': 'SELECT COUNT(*) FROM faqs WHERE embedding IS NOT NULL;',
    # 현재 모델로 임베딩된 데이터 수
    "chunks_with_current_model": "SELECT COUNT(*) FROM chunks WHERE embedding_model = %s;",
    "faqs_with_current_model": "SELECT COUNT(*) FROM faqs WHERE embedding_model = %s;",
}


def main() -> None:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for name, sql in QUERIES.items():
                if "%s" in sql:
                    cur.execute(sql, (MODEL_NAME,))
                else:
                    cur.execute(sql)
                count = cur.fetchone()[0]
                print(f'{name}: {count}')


if __name__ == '__main__':
    main()
