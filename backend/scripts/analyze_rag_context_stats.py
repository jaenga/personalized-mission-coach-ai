"""
RAG context 길이/구성 통계 분석 스크립트.

목적:
1. 평가 질문세트 전체를 대상으로 search_rag() 실행
2. rag_context 평균/최대 길이 확인
3. 실제 서비스 기준 길이 분포 확인
4. chunk top-k, chunk 크기 확인

실행 위치:
backend 폴더

실행 명령:
python scripts/analyze_rag_context_stats.py
"""

from __future__ import annotations

import os
import sys
import csv
import statistics
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

load_dotenv()

from rag import search_rag, CHUNK_LIMIT, FAQ_LIMIT


EVAL_CSV_PATH = os.path.join("data", "eval", "rag_eval_question_set.csv")


def load_questions(path: str) -> list[dict]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"평가 질문 CSV가 없습니다: {path}")

    rows: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            question = row.get("question", "").strip()
            if question:
                rows.append(row)
    return rows


def avg(values: list[int | float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def percentile(values: list[int | float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = int((len(sorted_values) - 1) * p)
    return round(sorted_values[idx], 2)


def bucket_context_length(chars: int) -> str:
    if chars == 0:
        return "0"
    if chars <= 1000:
        return "1~1000"
    if chars <= 2000:
        return "1001~2000"
    if chars <= 3000:
        return "2001~3000"
    if chars <= 4000:
        return "3001~4000"
    return "4001+"


def main() -> None:
    rows = load_questions(EVAL_CSV_PATH)

    print(f"평가 질문 수: {len(rows)}")
    print(f"현재 top-k 설정: chunk={CHUNK_LIMIT}, faq={FAQ_LIMIT}")
    print("=" * 80)

    context_chars: list[int] = []
    context_tokens: list[int] = []
    chunk_counts: list[int] = []
    faq_counts: list[int] = []
    chunk_avg_chars: list[float] = []
    chunk_max_chars: list[int] = []

    distribution: dict[str, int] = {
        "0": 0,
        "1~1000": 0,
        "1001~2000": 0,
        "2001~3000": 0,
        "3001~4000": 0,
        "4001+": 0,
    }

    worst_cases: list[dict] = []

    for i, row in enumerate(rows, start=1):
        question = row["question"].strip()


        result = search_rag(question)

        context = result.get("context", "") or ""
        chunks = result.get("chunks", []) or []
        faqs = result.get("faqs", []) or []

        chunk_lengths = [
            len(c.get("text", "") or "")
            for c in chunks
        ]

        faq_lengths = [
            len(f"Q: {f.get('question', '')}\nA: {f.get('answer', '')}")
            for f in faqs
        ]

        chars = len(context)
        tokens = chars // 2

        chunk_count = len(chunks)
        faq_count = len(faqs)

        chunk_avg = round(sum(chunk_lengths) / len(chunk_lengths), 1) if chunk_lengths else 0
        chunk_max = max(chunk_lengths) if chunk_lengths else 0

        context_chars.append(chars)
        context_tokens.append(tokens)
        chunk_counts.append(chunk_count)
        faq_counts.append(faq_count)
        chunk_avg_chars.append(chunk_avg)
        chunk_max_chars.append(chunk_max)

        bucket = bucket_context_length(chars)
        distribution[bucket] += 1

        worst_cases.append(
            {
                "question": question,
                "context_chars": chars,
                "context_est_tokens": tokens,
                "chunk_count": chunk_count,
                "faq_count": faq_count,
                "chunk_text_max_chars": chunk_max,
            }
        )

        print(
            f"[{i}/{len(rows)}] "
            f"context_chars={chars}, "
            f"est_tokens={tokens}, "
            f"chunks={chunk_count}/{CHUNK_LIMIT}, "
            f"faqs={faq_count}/{FAQ_LIMIT}, "
            f"chunk_max_chars={chunk_max}"
        )

    worst_cases = sorted(worst_cases, key=lambda x: x["context_chars"], reverse=True)[:10]

    print("\n" + "#" * 80)
    print("RAG context 길이 통계")
    print("#" * 80)

    print(f"평균 rag_context 글자 수: {avg(context_chars)}")
    print(f"최대 rag_context 글자 수: {max(context_chars) if context_chars else 0}")
    print(f"중앙값 rag_context 글자 수: {statistics.median(context_chars) if context_chars else 0}")
    print(f"p90 rag_context 글자 수: {percentile(context_chars, 0.9)}")
    print(f"p95 rag_context 글자 수: {percentile(context_chars, 0.95)}")

    print(f"\n평균 rag_context 추정 토큰 수: {avg(context_tokens)}")
    print(f"최대 rag_context 추정 토큰 수: {max(context_tokens) if context_tokens else 0}")

    print("\n길이 분포:")
    for bucket, count in distribution.items():
        ratio = round(count / len(rows) * 100, 1) if rows else 0
        print(f"- {bucket}: {count}개 ({ratio}%)")

    print("\nchunk 개수:")
    print(f"- 설정 chunk top-k: {CHUNK_LIMIT}")
    print(f"- 평균 실제 chunk 개수: {avg(chunk_counts)}")
    print(f"- 최대 실제 chunk 개수: {max(chunk_counts) if chunk_counts else 0}")
    print("- 방식: 고정 top-k 검색 후 threshold 통과 결과만 사용")

    print("\nFAQ 개수:")
    print(f"- 설정 FAQ top-k: {FAQ_LIMIT}")
    print(f"- 평균 실제 FAQ 개수: {avg(faq_counts)}")
    print(f"- 최대 실제 FAQ 개수: {max(faq_counts) if faq_counts else 0}")

    print("\nchunk 크기:")
    print(f"- 평균 chunk 글자 수: {avg(chunk_avg_chars)}")
    print(f"- 최대 chunk 글자 수: {max(chunk_max_chars) if chunk_max_chars else 0}")
    print("- 현재 chunk는 DB에 저장된 chunk_text 기준이며, 코드상에서는 문장/문단 여부를 따로 판단하지 않음")

    print("\ncontext가 가장 긴 질문 TOP 10:")
    for item in worst_cases:
        print("-" * 80)
        print(f"질문: {item['question']}")
        print(
            f"context_chars={item['context_chars']}, "
            f"est_tokens={item['context_est_tokens']}, "
            f"chunks={item['chunk_count']}, "
            f"faqs={item['faq_count']}, "
            f"chunk_max_chars={item['chunk_text_max_chars']}"
        )


if __name__ == "__main__":
    main()