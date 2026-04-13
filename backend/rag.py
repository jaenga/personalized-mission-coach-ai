#RAG 검색 모듈
#유저의 메시지를 임베딩 → NeonDB에서 관련 chunks/faqs 벡터 검색 → 프롬프트용 컨텍스트 반환

from __future__ import annotations

import os
import psycopg2
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

_model: SentenceTransformer | None = None

CHUNK_THRESHOLD = 0.75
FAQ_THRESHOLD = 0.65  
FAQ_LIMIT = 2



def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"[RAG] 임베딩 모델 로드 중: {MODEL_NAME}")
        _model = SentenceTransformer(MODEL_NAME)
        print("[RAG] 모델 로드 완료")
    return _model


def preload_model():
    _get_model()


def _to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def search_rag(query: str) -> dict:
    model = _get_model()
    vec = model.encode([query], normalize_embeddings=True)[0].tolist()
    vec_str = _to_pgvector(vec)

    chunks: list[dict] = []
    faqs: list[dict] = []

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT chunk_id, title, chunk_intent, chunk_text,
                       embedding <=> %s::vector AS distance
                FROM chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_str, vec_str, CHUNK_LIMIT),
            )
            for chunk_id, title, intent, text, dist in cur.fetchall():
                if dist <= CHUNK_THRESHOLD:
                    chunks.append({
                        "chunk_id": chunk_id,
                        "title": title,
                        "intent": intent,
                        "text": text,
                        "distance": round(float(dist), 4),
                    })

            cur.execute(
                """
                SELECT faq_id, title, question, answer,
                       embedding <=> %s::vector AS distance
                FROM faqs
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_str, vec_str, FAQ_LIMIT),
            )
            for faq_id, title, question, answer, dist in cur.fetchall():
                if dist <= FAQ_THRESHOLD:
                    faqs.append({
                        "faq_id": faq_id,
                        "title": title,
                        "question": question,
                        "answer": answer,
                        "distance": round(float(dist), 4),
                    })

    context = _format_context(chunks, faqs)
    return {"chunks": chunks, "faqs": faqs, "context": context}


def _format_context(chunks: list[dict], faqs: list[dict]) -> str:
    if not chunks and not faqs:
        return ""

    parts: list[str] = []

    if faqs:
        parts.append("[자주 묻는 질문]")
        for f in faqs:
            parts.append(f"Q: {f['question']}\nA: {f['answer']}")

    if chunks:
        parts.append("[관련 건강 정보]")
        for c in chunks:
            header = f"[{c['title']}]" + (f" — {c['intent']}" if c["intent"] else "")
            parts.append(f"{header}\n{c['text']}")

    return "\n\n".join(parts)
