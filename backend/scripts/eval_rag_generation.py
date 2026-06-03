"""
RAG + Gemma4 최종 답변 생성 평가 스크립트.

목적:
1. 평가 질문세트 CSV를 읽는다.
2. 전체 108개 질문 중, 분야별 대표 질문만 샘플링한다.
   - 기본값: 39개 분야 × 분야당 2개 = 총 78개
   - 각 분야의 2번째, 3번째 질문을 대표 질문으로 사용
3. 각 질문에 대해 search_rag()로 chunk/FAQ를 검색한다.
4. 검색된 RAG context를 system prompt에 넣는다.
5. Gemma4로 최종 답변을 생성한다.
6. 가져온 chunk/FAQ 번호, 근거 내용, 최종 답변, 생성 시간, 답변 길이를 CSV로 저장한다.

실행 위치:
backend 폴더

실행 명령:
python scripts/eval_rag_generation.py

결과 파일:
backend/data/eval/rag_generation_eval_result_for_report.csv
"""

from __future__ import annotations

import os
import sys
import csv
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv


# ---------------------------------------------------------------------
# import 경로 설정
# ---------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")


# ---------------------------------------------------------------------
# 프로젝트 내부 모듈 import
# ---------------------------------------------------------------------

from rag import search_rag
from pipeline import step_build_hints
from executor import ExecResults
from ollama_client import generate_chat_message, OLLAMA_MODEL


# ---------------------------------------------------------------------
# 설정값
# ---------------------------------------------------------------------

EVAL_CSV_PATH = os.path.join("data", "eval", "rag_eval_question_set.csv")
OUTPUT_CSV_PATH = os.path.join("data", "eval", "rag_generation_eval_result_for_report.csv")

# 생성 평가는 오래 걸리므로 전체 108개를 다 돌리지 않고 표본만 돌림.
# None이면 제한 없음.
MAX_QUESTIONS = None

# 분야별로 몇 개 질문을 생성 평가할지
# 1이면 39개 분야 × 1개 = 총 39개
# 2이면 39개 분야 × 2개 = 총 78개
QUESTIONS_PER_DOC = 2

# 각 분야에서 몇 번째 질문부터 뽑을지
# 0 = 분야별 1번째 질문
# 1 = 분야별 2번째 질문
# 2 = 분야별 3번째 질문
#
# 추천값: 2
# 이유: 1번째 질문은 너무 기본 질문일 가능성이 높아서,
#      3번째 질문을 대표 질문으로 사용
QUESTION_OFFSET_IN_DOC = 1

# 특정 키워드가 포함된 질문만 돌리고 싶을 때 사용
# 예: TARGET_KEYWORDS = ["키", "카페인", "다이어트"]
# 기본은 None으로 전체 분야 샘플링
TARGET_KEYWORDS: list[str] | None = None


# ---------------------------------------------------------------------
# 데이터 로드 및 샘플링
# ---------------------------------------------------------------------

def load_eval_questions(path: str) -> list[dict]:
    """
    평가 질문세트 CSV를 읽고, 생성 평가용 대표 질문만 샘플링한다.
    """

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"평가 질문 CSV가 없습니다: {path}\n"
            f"backend/data/eval/rag_eval_question_set.csv 위치를 확인하세요."
        )

    rows: list[dict] = []

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            question = row.get("question", "").strip()
            expected_doc_id = row.get("expected_doc_id", "").strip()

            if not question:
                continue

            rows.append(
                {
                    "test_id": row.get("test_id", ""),
                    "question": question,
                    "expected_doc_id": expected_doc_id,
                    "expected_title": row.get("expected_title", ""),
                    "topic": row.get("topic", ""),
                    "sub_topic": row.get("sub_topic", ""),
                    "question_type": row.get("question_type", ""),
                }
            )

    # 특정 키워드 필터가 있을 경우 먼저 적용
    if TARGET_KEYWORDS:
        rows = [
            row for row in rows
            if any(keyword in row["question"] for keyword in TARGET_KEYWORDS)
        ]

    # 분야별 대표 질문 샘플링
    # expected_doc_id 기준으로 묶어서 각 분야에서 N개만 선택
    if QUESTIONS_PER_DOC is not None:
        grouped: dict[str, list[dict]] = {}

        for row in rows:
            doc_id = row.get("expected_doc_id", "")
            if not doc_id:
                continue

            grouped.setdefault(doc_id, []).append(row)

        sampled_rows: list[dict] = []

        for doc_id, doc_rows in grouped.items():
            # 각 분야의 QUESTION_OFFSET_IN_DOC번째 질문부터 QUESTIONS_PER_DOC개 선택
            start_index = min(
                QUESTION_OFFSET_IN_DOC,
                max(0, len(doc_rows) - 1)
            )

            selected = doc_rows[start_index:start_index + QUESTIONS_PER_DOC]

            # 혹시 뒤쪽에 질문이 부족하면 앞쪽 질문으로 보충
            if len(selected) < QUESTIONS_PER_DOC:
                need = QUESTIONS_PER_DOC - len(selected)
                selected += doc_rows[:need]

            sampled_rows.extend(selected)

        rows = sampled_rows

    # 전체 개수 제한이 필요할 경우 적용
    if MAX_QUESTIONS is not None:
        rows = rows[:MAX_QUESTIONS]

    return rows


# ---------------------------------------------------------------------
# 검색 결과 요약 함수
# ---------------------------------------------------------------------

def summarize_chunks(chunks: list[dict]) -> list[dict]:
    """
    검색된 chunk 정보를 CSV에 저장하기 좋은 형태로 요약한다.
    """

    result = []

    for idx, c in enumerate(chunks, start=1):
        text = c.get("text", "") or ""

        result.append(
            {
                "rank": idx,
                "chunk_id": c.get("chunk_id", ""),
                "doc_id": c.get("doc_id", ""),
                "title": c.get("title", ""),
                "topic": c.get("topic", ""),
                "sub_topic": c.get("sub_topic", ""),
                "intent": c.get("intent", ""),
                "distance": c.get("distance", ""),
                "text_chars": len(text),
                "text_preview": text[:500],
            }
        )

    return result


def summarize_faqs(faqs: list[dict]) -> list[dict]:
    """
    검색된 FAQ 정보를 CSV에 저장하기 좋은 형태로 요약한다.
    """

    result = []

    for idx, f in enumerate(faqs, start=1):
        q = f.get("question", "") or ""
        a = f.get("answer", "") or ""

        result.append(
            {
                "rank": idx,
                "faq_id": f.get("faq_id", ""),
                "doc_id": f.get("doc_id", ""),
                "title": f.get("title", ""),
                "distance": f.get("distance", ""),
                "question": q,
                "answer_preview": a[:500],
                "qa_chars": len(q) + len(a),
            }
        )

    return result


def build_sources_text(chunks: list[dict], faqs: list[dict]) -> str:
    """
    사람이 CSV에서 바로 읽기 쉬운 검색 근거 요약 텍스트를 만든다.
    """

    lines: list[str] = []

    if faqs:
        lines.append("[FAQ]")
        for idx, f in enumerate(faqs, start=1):
            answer = f.get("answer", "") or ""

            lines.append(
                f"FAQ{idx}: "
                f"faq_id={f.get('faq_id')}, "
                f"doc_id={f.get('doc_id')}, "
                f"title={f.get('title')}, "
                f"distance={f.get('distance')}"
            )
            lines.append(f"Q: {f.get('question', '')}")
            lines.append(f"A: {answer[:300]}")

    if chunks:
        lines.append("\n[CHUNKS]")
        for idx, c in enumerate(chunks, start=1):
            text = c.get("text", "") or ""

            lines.append(
                f"CHUNK{idx}: "
                f"chunk_id={c.get('chunk_id')}, "
                f"doc_id={c.get('doc_id')}, "
                f"title={c.get('title')}, "
                f"intent={c.get('intent')}, "
                f"distance={c.get('distance')}"
            )
            lines.append(text[:300])

    return "\n".join(lines)


def normalize_doc_id(value) -> str:
    """
    doc_id 비교용 문자열을 만든다.
    """

    return str(value).strip() if value is not None else ""


def extract_doc_ids(items: list[dict]) -> list[str]:
    """
    검색 결과에서 빈 값을 제외한 doc_id 목록을 순서대로 추출한다.
    """

    doc_ids: list[str] = []

    for item in items:
        doc_id = normalize_doc_id(item.get("doc_id", ""))
        if doc_id:
            doc_ids.append(doc_id)

    return doc_ids


def dedupe_keep_order(values: list[str]) -> list[str]:
    """
    순서를 유지하면서 중복을 제거한다.
    """

    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        if value in seen:
            continue

        seen.add(value)
        result.append(value)

    return result


def build_manual_eval_columns() -> dict:
    """
    보고서 수동 평가용 빈 컬럼을 만든다.
    """

    return {
        "manual_answer_relevance": "",
        "manual_faithfulness": "",
        "manual_safe_response": "",
        "manual_child_friendly": "",
        "manual_rag_pass": "",
        "manual_note": "",
    }


# ---------------------------------------------------------------------
# 단일 질문 실행
# ---------------------------------------------------------------------

async def run_one(row: dict, index: int, total: int) -> dict:
    """
    질문 하나에 대해:
    RAG 검색 → system prompt 구성 → Gemma4 답변 생성 → 결과 dict 반환
    """

    question = row["question"]

    print("=" * 80)
    print(f"[{index}/{total}] 질문: {question}")

    # 1. RAG 검색
    rag_result = search_rag(question)

    chunks = rag_result.get("chunks", []) or []
    faqs = rag_result.get("faqs", []) or []
    rag_context = rag_result.get("context", "") or ""

    # 2. system prompt 구성
    # 실제 서비스에서 건강 지식 질문(intent C)일 때처럼 구성
    system_prompt = step_build_hints(
        student_id=None,
        fn_calls=[],
        exec_results=ExecResults(),
        combo=None,
        mission_title="오늘의 미션",
        rag_context=rag_context,
        intent="C",
        is_greet=False,
    )

    # 3. Gemma4 답변 생성
    messages = [
        {
            "role": "user",
            "content": question,
        }
    ]

    ai_message, llm_ms = await generate_chat_message(system_prompt, messages)

    # 4. 길이 계산
    answer_chars = len(ai_message)
    answer_est_tokens = max(1, answer_chars // 2) if ai_message else 0

    context_chars = len(rag_context)
    context_est_tokens = max(1, context_chars // 2) if rag_context else 0

    system_prompt_chars = len(system_prompt)
    system_prompt_est_tokens = max(1, system_prompt_chars // 2) if system_prompt else 0

    total_prompt_chars = system_prompt_chars + len(question)
    total_prompt_est_tokens = max(1, total_prompt_chars // 2)

    print(f"RAG context: {context_chars}자 / 약 {context_est_tokens} tokens")
    print(f"system prompt: {system_prompt_chars}자 / 약 {system_prompt_est_tokens} tokens")
    print(f"답변 길이: {answer_chars}자 / 약 {answer_est_tokens} tokens")
    print(f"생성 시간: {llm_ms}ms")
    print(f"답변 미리보기: {ai_message[:120]}...")

    chunk_details = summarize_chunks(chunks)
    faq_details = summarize_faqs(faqs)

    expected_doc_id = normalize_doc_id(row.get("expected_doc_id", ""))
    chunk_doc_ids = extract_doc_ids(chunks)
    faq_doc_ids = extract_doc_ids(faqs)
    retrieved_doc_ids = dedupe_keep_order(chunk_doc_ids + faq_doc_ids)
    top1_chunk_doc_id = normalize_doc_id(chunks[0].get("doc_id", "")) if chunks else ""
    top1_faq_doc_id = normalize_doc_id(faqs[0].get("doc_id", "")) if faqs else ""

    chunk_hit = bool(expected_doc_id) and expected_doc_id in chunk_doc_ids
    faq_hit = bool(expected_doc_id) and expected_doc_id in faq_doc_ids
    doc_hit = chunk_hit or faq_hit

    if chunk_hit and faq_hit:
        hit_source = "both"
    elif chunk_hit:
        hit_source = "chunk"
    elif faq_hit:
        hit_source = "faq"
    else:
        hit_source = "none"

    return {
        "index": index,
        "test_id": row.get("test_id", ""),
        "question": question,
        "expected_doc_id": expected_doc_id,
        "expected_title": row.get("expected_title", ""),
        "topic": row.get("topic", ""),
        "sub_topic": row.get("sub_topic", ""),
        "question_type": row.get("question_type", ""),

        # 검색 결과 개수
        "chunk_count": len(chunks),
        "faq_count": len(faqs),

        # 가져온 번호 요약
        "chunk_ids": ";".join(str(c.get("chunk_id", "")) for c in chunks),
        "chunk_doc_ids": ";".join(chunk_doc_ids),
        "faq_ids": ";".join(str(f.get("faq_id", "")) for f in faqs),
        "faq_doc_ids": ";".join(faq_doc_ids),

        # 자동 평가 컬럼
        "retrieved_doc_ids": ";".join(retrieved_doc_ids),
        "chunk_hit": chunk_hit,
        "faq_hit": faq_hit,
        "doc_hit": doc_hit,
        "hit_source": hit_source,
        "top1_chunk_doc_id": top1_chunk_doc_id,
        "top1_faq_doc_id": top1_faq_doc_id,

        # 사람이 보기 좋은 검색 근거 요약
        "sources_text": build_sources_text(chunks, faqs),

        # JSON 상세
        "chunk_details_json": json.dumps(chunk_details, ensure_ascii=False),
        "faq_details_json": json.dumps(faq_details, ensure_ascii=False),

        # RAG context
        "rag_context_chars": context_chars,
        "rag_context_est_tokens": context_est_tokens,
        "rag_context": rag_context,

        # system prompt 길이
        "system_prompt_chars": system_prompt_chars,
        "system_prompt_est_tokens": system_prompt_est_tokens,

        # 전체 프롬프트 길이 대략치
        "total_prompt_chars": total_prompt_chars,
        "total_prompt_est_tokens": total_prompt_est_tokens,

        # Gemma4 답변
        "model": OLLAMA_MODEL,
        "llm_ms": llm_ms,
        "answer_chars": answer_chars,
        "answer_est_tokens": answer_est_tokens,
        "answer": ai_message,

        # 에러 없음
        "error": "",
        **build_manual_eval_columns(),
    }


# ---------------------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------------------

async def main() -> None:
    rows = load_eval_questions(EVAL_CSV_PATH)
    total = len(rows)

    print("#" * 80)
    print("RAG + Gemma4 생성 평가 시작")
    print("#" * 80)
    print(f"평가 질문 수: {total}")
    print(f"모델: {OLLAMA_MODEL}")
    print(f"질문세트: {EVAL_CSV_PATH}")
    print(f"결과 저장 위치: {OUTPUT_CSV_PATH}")
    print(f"QUESTIONS_PER_DOC: {QUESTIONS_PER_DOC}")
    print(f"QUESTION_OFFSET_IN_DOC: {QUESTION_OFFSET_IN_DOC}")
    print(f"MAX_QUESTIONS: {MAX_QUESTIONS}")
    print(f"TARGET_KEYWORDS: {TARGET_KEYWORDS}")
    print()

    results: list[dict] = []

    for i, row in enumerate(rows, start=1):
        try:
            result = await run_one(row, i, total)
            results.append(result)

        except Exception as e:
            print(f"[ERROR] {i}번 질문 실패: {e}")

            results.append(
                {
                    "index": i,
                    "test_id": row.get("test_id", ""),
                    "question": row.get("question", ""),
                    "expected_doc_id": normalize_doc_id(row.get("expected_doc_id", "")),
                    "expected_title": row.get("expected_title", ""),
                    "topic": row.get("topic", ""),
                    "sub_topic": row.get("sub_topic", ""),
                    "question_type": row.get("question_type", ""),
                    "chunk_hit": False,
                    "faq_hit": False,
                    "doc_hit": False,
                    "hit_source": "none",
                    "error": str(e),
                    **build_manual_eval_columns(),
                }
            )

    # 결과 CSV 저장
    os.makedirs(os.path.dirname(OUTPUT_CSV_PATH), exist_ok=True)

    fieldnames = [
        "index",
        "test_id",
        "question",
        "expected_doc_id",
        "expected_title",
        "topic",
        "sub_topic",
        "question_type",

        "chunk_count",
        "faq_count",
        "chunk_ids",
        "chunk_doc_ids",
        "faq_ids",
        "faq_doc_ids",
        "retrieved_doc_ids",
        "chunk_hit",
        "faq_hit",
        "doc_hit",
        "hit_source",
        "top1_chunk_doc_id",
        "top1_faq_doc_id",

        "sources_text",
        "chunk_details_json",
        "faq_details_json",

        "rag_context_chars",
        "rag_context_est_tokens",
        "rag_context",

        "system_prompt_chars",
        "system_prompt_est_tokens",
        "total_prompt_chars",
        "total_prompt_est_tokens",

        "model",
        "llm_ms",
        "answer_chars",
        "answer_est_tokens",
        "answer",

        "error",

        "manual_answer_relevance",
        "manual_faithfulness",
        "manual_safe_response",
        "manual_child_friendly",
        "manual_rag_pass",
        "manual_note",
    ]

    with open(OUTPUT_CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            # 없는 key는 빈 값으로 채움
            csv_row = {key: result.get(key, "") for key in fieldnames}
            writer.writerow(csv_row)

    # 요약 출력
    print("\n" + "#" * 80)
    print("저장 완료")
    print("#" * 80)
    print(OUTPUT_CSV_PATH)

    success_rows = [r for r in results if not r.get("error")]

    def hit_rate(count: int, denominator: int) -> float:
        return (count / denominator * 100) if denominator else 0.0

    if success_rows:
        avg_llm_ms = sum(r["llm_ms"] for r in success_rows) / len(success_rows)
        max_llm_ms = max(r["llm_ms"] for r in success_rows)
        min_llm_ms = min(r["llm_ms"] for r in success_rows)

        avg_answer_chars = sum(r["answer_chars"] for r in success_rows) / len(success_rows)
        max_answer_chars = max(r["answer_chars"] for r in success_rows)
        min_answer_chars = min(r["answer_chars"] for r in success_rows)

        avg_rag_chars = sum(r["rag_context_chars"] for r in success_rows) / len(success_rows)
        max_rag_chars = max(r["rag_context_chars"] for r in success_rows)
        min_rag_chars = min(r["rag_context_chars"] for r in success_rows)

        avg_prompt_tokens = sum(r["total_prompt_est_tokens"] for r in success_rows) / len(success_rows)
        max_prompt_tokens = max(r["total_prompt_est_tokens"] for r in success_rows)

        doc_hit_count = sum(1 for r in success_rows if r.get("doc_hit") is True)
        chunk_hit_count = sum(1 for r in success_rows if r.get("chunk_hit") is True)
        faq_hit_count = sum(1 for r in success_rows if r.get("faq_hit") is True)

        print(f"전체 평가 질문 수: {len(results)}")
        print(f"에러 없는 성공 row 수: {len(success_rows)}")
        print(
            f"doc_hit=True: {doc_hit_count}/{len(success_rows)} "
            f"({hit_rate(doc_hit_count, len(success_rows)):.1f}%)"
        )
        print(
            f"chunk_hit=True: {chunk_hit_count}/{len(success_rows)} "
            f"({hit_rate(chunk_hit_count, len(success_rows)):.1f}%)"
        )
        print(
            f"faq_hit=True: {faq_hit_count}/{len(success_rows)} "
            f"({hit_rate(faq_hit_count, len(success_rows)):.1f}%)"
        )
        print(f"평균 llm_ms: {avg_llm_ms:.1f}ms")
        print(f"평균 answer_chars: {avg_answer_chars:.1f}자")
        print(f"평균 rag_context_chars: {avg_rag_chars:.1f}자")

        print("\n[답변 생성 시간]")
        print(f"평균: {avg_llm_ms:.1f}ms")
        print(f"최대: {max_llm_ms}ms")
        print(f"최소: {min_llm_ms}ms")

        print("\n[생성 답변 길이]")
        print(f"평균: {avg_answer_chars:.1f}자")
        print(f"최대: {max_answer_chars}자")
        print(f"최소: {min_answer_chars}자")

        print("\n[RAG context 길이]")
        print(f"평균: {avg_rag_chars:.1f}자")
        print(f"최대: {max_rag_chars}자")
        print(f"최소: {min_rag_chars}자")

        print("\n[전체 prompt 추정 토큰]")
        print(f"평균: {avg_prompt_tokens:.1f} tokens")
        print(f"최대: {max_prompt_tokens} tokens")

    else:
        print(f"전체 평가 질문 수: {len(results)}")
        print("에러 없는 성공 row 수: 0")
        print("doc_hit=True: 0/0 (0.0%)")
        print("chunk_hit=True: 0/0 (0.0%)")
        print("faq_hit=True: 0/0 (0.0%)")
        print("평균 llm_ms: 0.0ms")
        print("평균 answer_chars: 0.0자")
        print("평균 rag_context_chars: 0.0자")
        print("성공한 결과가 없습니다. error 컬럼을 확인하세요.")


if __name__ == "__main__":
    asyncio.run(main())
