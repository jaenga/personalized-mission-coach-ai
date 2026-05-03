# RAG 데이터 임베딩 스크립트
# create_rag_tables.py로 테이블 만든 다음에 이 스크립트로 임베딩한다

from __future__ import annotations

import os
from dotenv import load_dotenv
import psycopg2
from sentence_transformers import SentenceTransformer

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
MODEL_NAME = os.getenv('EMBEDDING_MODEL', 'BAAI/bge-m3')
EMBEDDING_DIM = int(os.getenv('EMBEDDING_DIM', 1024))
if not DATABASE_URL:
    raise ValueError('DATABASE_URL이 없습니다. backend/.env 확인')


def to_pgvector(vec: list[float]) -> str:
    return '[' + ','.join(f'{v:.8f}' for v in vec) + ']'


def update_chunks(model: SentenceTransformer) -> int:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT chunk_id, chunk_text FROM chunks WHERE embedding IS NULL ORDER BY chunk_id')
            rows = cur.fetchall()
            if not rows:
                return 0
            ids = [r[0] for r in rows]
            texts = [r[1] for r in rows]
            vectors = model.encode(texts, normalize_embeddings=True)
            for chunk_id, vec in zip(ids, vectors):
                cur.execute(
                    """
                    UPDATE chunks
                    SET embedding = %s::vector,
                        embedding_model = %s
                    WHERE chunk_id = %s
                    """,
                    (to_pgvector(vec.tolist()), MODEL_NAME, chunk_id),
                )
        conn.commit()
    return len(rows)


def update_faqs(model: SentenceTransformer) -> int:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT faq_id, question, answer FROM faqs WHERE embedding IS NULL ORDER BY faq_id')
            rows = cur.fetchall()
            if not rows:
                return 0
            ids = [r[0] for r in rows]
            texts = [f'질문: {r[1]} 답변: {r[2]}' for r in rows]
            vectors = model.encode(texts, normalize_embeddings=True)
            for faq_id, vec in zip(ids, vectors):
                cur.execute(
                    """
                    UPDATE faqs
                    SET embedding = %s::vector,
                        embedding_model = %s
                    WHERE faq_id = %s
                    """,
                    (to_pgvector(vec.tolist()), faq_id),
                )
        conn.commit()
    return len(rows)


def main() -> None:
    print(f'임베딩 모델 로드: {MODEL_NAME}')
    model = SentenceTransformer(MODEL_NAME)
    actual_dim = model.get_sentence_embedding_dimension()
    print("임베딩 차원:", actual_dim)
    if actual_dim != EMBEDDING_DIM:
        raise ValueError(
            f"EMBEDDING_DIM 불일치: env={EMBEDDING_DIM}, model={actual_dim}"
        )
    chunk_count = update_chunks(model)
    faq_count = update_faqs(model)
    print(f'chunks 임베딩 업데이트: {chunk_count}건')
    print(f'faqs 임베딩 업데이트:   {faq_count}건')


if __name__ == '__main__':
    main()
