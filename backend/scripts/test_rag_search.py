#
# RAG 검색 테스트 스크립트
# chunk 5개, faq 3개 검색해서 출력해줌
# 간단히 검색 테스트용! 딱히 기능은 없음
# 
from __future__ import annotations

import os
from dotenv import load_dotenv
import psycopg2
from sentence_transformers import SentenceTransformer

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
MODEL_NAME = os.getenv('EMBEDDING_MODEL', 'jhgan/ko-sroberta-multitask')
if not DATABASE_URL:
    raise ValueError('DATABASE_URL이 없습니다. backend/.env 확인')


def to_pgvector(vec: list[float]) -> str:
    return '[' + ','.join(f'{v:.8f}' for v in vec) + ']'


def main() -> None:
    query = input('검색 질문 입력: ').strip()
    if not query:
        raise ValueError('질문을 입력해야 합니다.')

    model = SentenceTransformer(MODEL_NAME)
    query_vec = model.encode([query], normalize_embeddings=True)[0].tolist()
    query_vec_str = to_pgvector(query_vec)

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            print('\n[FAQ 상위 3개]')
            cur.execute(
                '''
                SELECT faq_id, question, answer
                FROM faqs
                ORDER BY embedding <=> %s::vector
                LIMIT 3
                ''',
                (query_vec_str,),
            )
            for faq_id, question, answer in cur.fetchall():
                print(f'- {faq_id} | {question}')
                print(f'  {answer[:160]}...')

            print('\n[Chunk 상위 5개]')
            cur.execute(
                '''
                SELECT chunk_id, title, chunk_intent, chunk_text
                FROM chunks
                ORDER BY embedding <=> %s::vector
                LIMIT 5
                ''',
                (query_vec_str,),
            )
            for chunk_id, title, intent, chunk_text in cur.fetchall():
                print(f'- {chunk_id} | {title} | {intent}')
                print(f'  {chunk_text[:180]}...')


if __name__ == '__main__':
    main()
