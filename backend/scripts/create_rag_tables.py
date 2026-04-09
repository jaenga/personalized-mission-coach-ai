# RAG 테이블 생성 스크립트
# neonDB에 테이블 3개 생성해준다: documents, chunks, faqs

from __future__ import annotations

import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError('DATABASE_URL이 없습니다. backend/.env 확인')

SQLS = [
    'CREATE EXTENSION IF NOT EXISTS vector;',
    '''
    CREATE TABLE IF NOT EXISTS documents (
        doc_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        source_org TEXT NOT NULL,
        source_url TEXT,
        topic TEXT,
        sub_topic TEXT,
        trust_level TEXT,
        collected_date DATE
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
        source_org TEXT NOT NULL,
        title TEXT NOT NULL,
        topic TEXT,
        sub_topic TEXT,
        chunk_index INTEGER NOT NULL,
        chunk_intent TEXT,
        chunk_text TEXT NOT NULL,
        embedding vector(1024)
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS faqs (
        faq_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        embedding vector(1024)
    );
    ''',
    'CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);',
    'CREATE INDEX IF NOT EXISTS idx_faqs_doc_id ON faqs(doc_id);',
]


def main() -> None:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for sql in SQLS:
                cur.execute(sql)
        conn.commit()
    print('RAG 테이블 생성 완료')


if __name__ == '__main__':
    main()
