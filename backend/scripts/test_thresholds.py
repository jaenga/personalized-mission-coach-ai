#임계값 확인하려고 만든 스크립트라 기능이랑은 상관없습니다!

from __future__ import annotations

import os
import psycopg2
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
CHUNK_THRESHOLD = 0.75

QUERIES = [
    ("드림렌즈의 효과와 부작용",     "드림렌즈 끼면 어떤 부작용이 있어요?"),
    ("불규칙한 월경주기와 월경전증후군", "생리가 불규칙한 게 정상인가요?"),
    ("성장 장애",                 "키가 안 크는 이유가 뭐예요?"),
    ("소아 비만",                 "아이가 살이 많이 찌면 어떡하죠?"),
    ("소아청소년기 고혈압",          "어린이도 혈압이 높을 수 있나요?"),
    ("소아 청소년의 혈변 및 흑혈변",  "변에 피가 섞여 나오면 어떻게 해요?"),
    ("소아발진",                  "아이 피부에 발진이 생겼어요"),
    ("식이영양(소아/청소년)",        "청소년한테 필요한 영양소가 뭐예요?"),
    ("저신장",                   "우리 아이 키가 너무 작은 것 같아요"),
    ("정상 월경의 이해",            "초경이 언제 시작되는 게 정상이에요?"),
    ("정상청소년의 성장과 발달",      "사춘기는 언제 시작되나요?"),
    ("청소년과 다이어트 보조제",      "다이어트 약 먹어도 괜찮아요?"),
    ("청소년의 디지털 과의존",       "스마트폰을 너무 많이 쓰면 어떻게 돼요?"),
    ("청소년의 안전한 화장품 사용",   "화장품 많이 쓰면 피부에 안 좋아요?"),
    ("청소년의 제로 음료 섭취",      "제로 음료 마시면 뭐가 안 좋아요?"),
    ("청소년의 카페인 음료 섭취",    "카페인 음료가 왜 안 좋아요?"),
    ("특발성 저신장에서 성장호르몬",  "성장호르몬 주사 맞으면 효과 있어요?"),
    ("폐렴(소아)",                "아이가 폐렴에 걸리면 어떤 증상이 나요?"),
]


def to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def main() -> None:
    print(f"모델 로드 중: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)
    print(f"임계값: CHUNK={CHUNK_THRESHOLD}\n")
    print(f"{'문서 주제':<30} {'질문':<30} {'top1 dist':>10}  {'통과?':>6}")
    print("-" * 85)

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for doc_title, query in QUERIES:
                vec = model.encode([query], normalize_embeddings=True)[0].tolist()
                vec_str = to_pgvector(vec)
                cur.execute(
                    "SELECT embedding <=> %s::vector AS dist FROM chunks ORDER BY dist LIMIT 1",
                    (vec_str,),
                )
                row = cur.fetchone()
                dist = float(row[0]) if row else 99.0
                ok = "✅" if dist <= CHUNK_THRESHOLD else "❌"
                print(f"{doc_title:<30} {query:<30} {dist:>10.4f}  {ok:>6}")


if __name__ == "__main__":
    main()
