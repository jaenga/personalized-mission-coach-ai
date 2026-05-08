#RAG 검색 모듈
#유저 메시지를 임베딩 → NeonDB에서 관련 chunks/faqs 벡터 검색 → 프롬프트용 컨텍스트 반환

from __future__ import annotations

import os
import time
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

_model = None
_sentence_transformer_cls = None
_sentence_transformer_import_failed = False

CHUNK_THRESHOLD = 0.75
FAQ_THRESHOLD = 0.50 
CHUNK_LIMIT = 2
FAQ_LIMIT = 1

# FAQ 후보는 넉넉히 가져온 뒤, chunk doc_id와 같은 것만 남기는 방식
FAQ_CANDIDATE_LIMIT = 5

# 최종 프롬프트 길이 제한
MAX_CHUNK_CHARS = 400
MAX_FAQ_CHARS = 300
MAX_CONTEXT_CHARS = 1200

def _get_sentence_transformer_cls():
    global _sentence_transformer_cls, _sentence_transformer_import_failed
    if _sentence_transformer_cls is not None or _sentence_transformer_import_failed:
        return _sentence_transformer_cls
    try:
        from sentence_transformers import SentenceTransformer

        _sentence_transformer_cls = SentenceTransformer
    except ModuleNotFoundError as e:
        _sentence_transformer_import_failed = True
        print(f"[RAG] sentence_transformers 없음 - RAG 검색 비활성화: {e}")
    return _sentence_transformer_cls


def _get_model():
    global _model
    if _model is None:
        sentence_transformer_cls = _get_sentence_transformer_cls()
        if sentence_transformer_cls is None:
            raise RuntimeError("sentence_transformers is not installed")
        print(f"[RAG] 임베딩 모델 로드 중: {MODEL_NAME}")
        _model = sentence_transformer_cls(MODEL_NAME)
        print("[RAG] 모델 로드 완료")
    return _model


def preload_model():
    try:
        _get_model()
    except RuntimeError as e:
        print(f"[RAG] preload skipped: {e}")


def _to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"

def _truncate_text(text: str, max_chars: int) -> str:
    """
    문장 경계에 가깝게 자르는 함수.
    단순히 글자 수만 자르면 문장 중간에서 끊기므로,
    가능한 한 '다.', '요.', '.', '?', '!' 뒤에서 자른다.
    """
    if not text:
        return ""

    text = text.strip()

    if len(text) <= max_chars:
        return text

    cut = text[:max_chars].rstrip()

    candidates = [
        cut.rfind("다."),
        cut.rfind("요."),
        cut.rfind("."),
        cut.rfind("?"),
        cut.rfind("!"),
        cut.rfind("\n"),
    ]
    last = max(candidates)

    if last >= int(max_chars * 0.55):
        return cut[:last + 1].rstrip() + "..."

    return cut + "..."

def search_rag(query: str) -> dict:
    t0 = time.perf_counter()
    try:
        model = _get_model()
    except RuntimeError as e:
        print(f"[RAG] 검색 스킵: {e}")
        return {"chunks": [], "faqs": [], "context": ""}
    vec = model.encode([query], normalize_embeddings=True)[0].tolist()
    embed_ms = round((time.perf_counter() - t0) * 1000)
    vec_str = _to_pgvector(vec)

    chunks: list[dict] = []
    faqs: list[dict] = []

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT chunk_id, doc_id, title, topic, sub_topic, chunk_intent, chunk_text,
                    embedding <=> %s::vector AS distance
                FROM chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_str, vec_str, CHUNK_LIMIT),
            )
            for chunk_id, doc_id, title, topic, sub_topic, intent, text, dist in cur.fetchall():
                if dist <= CHUNK_THRESHOLD:
                    chunks.append({
                        "chunk_id": chunk_id,
                        "doc_id": doc_id,
                        "title": title,
                        "topic": topic,
                        "sub_topic": sub_topic,
                        "intent": intent,
                        "text": text,
                        "distance": round(float(dist), 4),
                    })

            # chunk에서 잡힌 문서 doc_id를 바탕으로 일치하는 FAQ만 선별
            chunk_doc_ids = {c["doc_id"] for c in chunks}

            cur.execute(
                """
                SELECT faq_id, doc_id, title, question, answer,
                    embedding <=> %s::vector AS distance
                FROM faqs
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_str, vec_str, FAQ_CANDIDATE_LIMIT),
            )

            faq_candidates: list[dict] = []

            for faq_id, doc_id, title, question, answer, dist in cur.fetchall():
                if dist <= FAQ_THRESHOLD:
                    faq_candidates.append({
                        "faq_id": faq_id,
                        "doc_id": doc_id,
                        "title": title,
                        "question": question,
                        "answer": answer,
                        "distance": round(float(dist), 4),
                    })

            # 핵심: chunk가 찾은 문서와 같은 doc_id의 FAQ만 사용
            if chunk_doc_ids:
                matched_faqs = [
                    f for f in faq_candidates
                    if f["doc_id"] in chunk_doc_ids
                ]
                faqs = matched_faqs[:FAQ_LIMIT]
            else:
                faqs = faq_candidates[:FAQ_LIMIT]

    total_ms = round((time.perf_counter() - t0) * 1000)
    context = _format_context(chunks, faqs)

    print(
        f"[RAG] 검색 결과: "
        f"chunks={len(chunks)}/{CHUNK_LIMIT}, "
        f"faqs={len(faqs)}/{FAQ_LIMIT}, "
        f"context_chars={len(context)}, "
        f"context_est_tokens={len(context)//2} "
        f"| embed={embed_ms}ms, 총={total_ms}ms"
    )

    return {"chunks": chunks, "faqs": faqs, "context": context}


def _format_context(chunks: list[dict], faqs: list[dict]) -> str:
    if not chunks and not faqs:
        return ""

    parts: list[str] = []

    if chunks:
        parts.append("[건강정보]")
        for c in chunks:
            title = c.get("title", "")
            intent = c.get("intent", "")
            header = f"[{title}]"
            if intent:
                header += f" {intent}"

            chunk_text = _truncate_text(c.get("text", ""), MAX_CHUNK_CHARS)
            parts.append(f"{header}\n{chunk_text}")

    if faqs:
        parts.append("[관련 질문]")
        for f in faqs:
            faq_text = f"Q: {f.get('question', '')}\nA: {f.get('answer', '')}"
            faq_text = _truncate_text(faq_text, MAX_FAQ_CHARS)
            parts.append(faq_text)

    context = "\n\n".join(parts)

    if len(context) > MAX_CONTEXT_CHARS:
        context = _truncate_text(context, MAX_CONTEXT_CHARS)

    return context
