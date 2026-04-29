"""
RAG threshold / retrieval 평가 스크립트.

목적:
1. 평가 질문세트 CSV를 읽는다.
2. 각 질문을 임베딩한다.
3. chunks, faqs에서 top-k 검색한다.
4. expected_doc_id와 실제 검색 doc_id를 비교한다.
5. Hit@1, Hit@3, coverage를 출력한다.

실행 위치:
backend 폴더에서 실행

실행 명령:
python scripts/test_thresholds.py
"""

from __future__ import annotations

import os
import csv
import psycopg2
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

CHUNK_THRESHOLD = 0.75
FAQ_THRESHOLD = 0.65

EVAL_CSV_PATH = os.path.join("data", "eval", "rag_eval_question_set.csv")


def to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def load_eval_questions(path: str) -> list[dict]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"평가 질문 CSV가 없습니다: {path}\n"
            f"backend/data/eval/rag_eval_question_set.csv 위치에 저장했는지 확인하세요."
        )

    rows: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            question = row.get("question", "").strip()
            expected_doc_id = row.get("expected_doc_id", "").strip()

            if not question or not expected_doc_id:
                continue

            rows.append(row)

    return rows


def search_chunks(cur, vec_str: str, limit: int = 3) -> list[dict]:
    cur.execute(
        """
        SELECT chunk_id, doc_id, title, chunk_intent,
               embedding <=> %s::vector AS distance
        FROM chunks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (vec_str, vec_str, limit),
    )

    results = []
    for chunk_id, doc_id, title, intent, dist in cur.fetchall():
        results.append(
            {
                "id": chunk_id,
                "doc_id": doc_id,
                "title": title,
                "intent": intent,
                "distance": float(dist),
            }
        )
    return results


def search_faqs(cur, vec_str: str, limit: int = 3) -> list[dict]:
    cur.execute(
        """
        SELECT faq_id, doc_id, title, question,
               embedding <=> %s::vector AS distance
        FROM faqs
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (vec_str, vec_str, limit),
    )

    results = []
    for faq_id, doc_id, title, question, dist in cur.fetchall():
        results.append(
            {
                "id": faq_id,
                "doc_id": doc_id,
                "title": title,
                "question": question,
                "distance": float(dist),
            }
        )
    return results


def judge(expected_doc_id: str, results: list[dict], threshold: float) -> dict:
    """
    expected_doc_id가 검색 결과 안에 있는지 평가한다.
    threshold를 넘는 결과는 실제 context에 안 들어간다고 보고 제외한다.
    """
    passed = [r for r in results if r["distance"] <= threshold]

    top1_doc_id = passed[0]["doc_id"] if passed else ""
    top3_doc_ids = [r["doc_id"] for r in passed[:3]]

    hit1 = 1 if top1_doc_id == expected_doc_id else 0
    hit3 = 1 if expected_doc_id in top3_doc_ids else 0
    coverage = 1 if len(passed) > 0 else 0

    return {
        "top1_doc_id": top1_doc_id,
        "top3_doc_ids": top3_doc_ids,
        "hit1": hit1,
        "hit3": hit3,
        "coverage": coverage,
        "top1_distance": passed[0]["distance"] if passed else None,
    }


def main() -> None:
    questions = load_eval_questions(EVAL_CSV_PATH)

    print(f"평가 질문 수: {len(questions)}")
    print(f"모델 로드 중: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)
    print(f"threshold: chunk={CHUNK_THRESHOLD}, faq={FAQ_THRESHOLD}")
    print()

    chunk_hit1 = 0
    chunk_hit3 = 0
    chunk_coverage = 0

    faq_hit1 = 0
    faq_hit3 = 0
    faq_coverage = 0

    total = len(questions)

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for i, row in enumerate(questions, start=1):
                question = row["question"].strip()
                expected_doc_id = row["expected_doc_id"].strip()

                vec = model.encode([question], normalize_embeddings=True)[0].tolist()
                vec_str = to_pgvector(vec)

                chunk_results = search_chunks(cur, vec_str, limit=3)
                faq_results = search_faqs(cur, vec_str, limit=3)

                chunk_judge = judge(expected_doc_id, chunk_results, CHUNK_THRESHOLD)
                faq_judge = judge(expected_doc_id, faq_results, FAQ_THRESHOLD)

                chunk_hit1 += chunk_judge["hit1"]
                chunk_hit3 += chunk_judge["hit3"]
                chunk_coverage += chunk_judge["coverage"]

                faq_hit1 += faq_judge["hit1"]
                faq_hit3 += faq_judge["hit3"]
                faq_coverage += faq_judge["coverage"]

                print("=" * 80)
                print(f"[{i}/{total}] {question}")
                print(f"정답 doc_id: {expected_doc_id}")

                print(
                    f"chunk top1: {chunk_judge['top1_doc_id']} "
                    f"dist={chunk_judge['top1_distance']}"
                )
                print(f"chunk top3: {chunk_judge['top3_doc_ids']}")
                print(
                    f"chunk hit@1={chunk_judge['hit1']}, "
                    f"hit@3={chunk_judge['hit3']}, "
                    f"coverage={chunk_judge['coverage']}"
                )

                print(
                    f"faq top1: {faq_judge['top1_doc_id']} "
                    f"dist={faq_judge['top1_distance']}"
                )
                print(f"faq top3: {faq_judge['top3_doc_ids']}")
                print(
                    f"faq hit@1={faq_judge['hit1']}, "
                    f"hit@3={faq_judge['hit3']}, "
                    f"coverage={faq_judge['coverage']}"
                )

    print("\n" + "#" * 80)
    print("최종 요약")
    print("#" * 80)

    print("[chunks]")
    print(f"Hit@1: {chunk_hit1}/{total} = {chunk_hit1 / total:.3f}")
    print(f"Hit@3: {chunk_hit3}/{total} = {chunk_hit3 / total:.3f}")
    print(f"Coverage: {chunk_coverage}/{total} = {chunk_coverage / total:.3f}")

    print("\n[faqs]")
    print(f"Hit@1: {faq_hit1}/{total} = {faq_hit1 / total:.3f}")
    print(f"Hit@3: {faq_hit3}/{total} = {faq_hit3 / total:.3f}")
    print(f"Coverage: {faq_coverage}/{total} = {faq_coverage / total:.3f}")


if __name__ == "__main__":
    main()