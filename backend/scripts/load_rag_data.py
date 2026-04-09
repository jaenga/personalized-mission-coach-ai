# RAG 데이터 적재 스크립트! 테이블에 csv에서 읽은 데이터를 넣어준다. 
# create_rag_tables.py로 테이블 만든 다음에 이 스크립트로 적재한다

from __future__ import annotations

from pathlib import Path
import os
import pandas as pd
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / 'data' / 'processed'

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError('DATABASE_URL이 없습니다. backend/.env 확인')


def upsert_documents(cur, df: pd.DataFrame) -> None:
    rows = list(df.itertuples(index=False, name=None))
    sql = '''
    INSERT INTO documents (doc_id, title, source_org, source_url, topic, sub_topic, trust_level, collected_date)
    VALUES %s
    ON CONFLICT (doc_id) DO UPDATE SET
        title = EXCLUDED.title,
        source_org = EXCLUDED.source_org,
        source_url = EXCLUDED.source_url,
        topic = EXCLUDED.topic,
        sub_topic = EXCLUDED.sub_topic,
        trust_level = EXCLUDED.trust_level,
        collected_date = EXCLUDED.collected_date;
    '''
    execute_values(cur, sql, rows, page_size=200)


def upsert_chunks(cur, df: pd.DataFrame) -> None:
    rows = list(df.itertuples(index=False, name=None))
    sql = '''
    INSERT INTO chunks (chunk_id, doc_id, source_org, title, topic, sub_topic, chunk_index, chunk_intent, chunk_text)
    VALUES %s
    ON CONFLICT (chunk_id) DO UPDATE SET
        doc_id = EXCLUDED.doc_id,
        source_org = EXCLUDED.source_org,
        title = EXCLUDED.title,
        topic = EXCLUDED.topic,
        sub_topic = EXCLUDED.sub_topic,
        chunk_index = EXCLUDED.chunk_index,
        chunk_intent = EXCLUDED.chunk_intent,
        chunk_text = EXCLUDED.chunk_text;
    '''
    execute_values(cur, sql, rows, page_size=200)


def upsert_faqs(cur, df: pd.DataFrame) -> None:
    rows = list(df.itertuples(index=False, name=None))
    sql = '''
    INSERT INTO faqs (faq_id, doc_id, title, question, answer)
    VALUES %s
    ON CONFLICT (faq_id) DO UPDATE SET
        doc_id = EXCLUDED.doc_id,
        title = EXCLUDED.title,
        question = EXCLUDED.question,
        answer = EXCLUDED.answer;
    '''
    execute_values(cur, sql, rows, page_size=200)


def main() -> None:
    documents = pd.read_csv(DATA_DIR / 'documents_clean.csv')
    chunks = pd.read_csv(DATA_DIR / 'chunks_clean.csv')
    faqs = pd.read_csv(DATA_DIR / 'faqs_clean.csv')

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            upsert_documents(cur, documents)
            upsert_chunks(cur, chunks)
            upsert_faqs(cur, faqs)
        conn.commit()

    print('Neon 적재 완료')
    print(f' - documents: {len(documents)}건')
    print(f' - chunks:    {len(chunks)}건')
    print(f' - faqs:      {len(faqs)}건')


if __name__ == '__main__':
    main()
