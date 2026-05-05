from __future__ import annotations

import sys
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from rag import search_rag, CHUNK_LIMIT, FAQ_LIMIT


question = "밥 먹고 바로 운동해도 돼요?"

result = search_rag(question)

context = result.get("context", "") or ""
chunks = result.get("chunks", []) or []
faqs = result.get("faqs", []) or []

print("=" * 80)
print("[질문]")
print(question)

print("\n[요약]")
print(f"context 길이: {len(context)}자 / 약 {len(context)//2}토큰")
print(f"chunks: {len(chunks)}/{CHUNK_LIMIT}")
print(f"faqs: {len(faqs)}/{FAQ_LIMIT}")

print("\n[FAQ]")
for idx, f in enumerate(faqs, start=1):
    print("-" * 80)
    print(f"FAQ {idx}")
    print(f"title: {f.get('title')}")
    print(f"distance: {f.get('distance')}")
    print(f"Q: {f.get('question')}")
    print(f"A: {f.get('answer')}")

print("\n[CHUNKS]")
for idx, c in enumerate(chunks, start=1):
    text = c.get("text", "") or ""
    print("-" * 80)
    print(f"CHUNK {idx}")
    print(f"chunk_id: {c.get('chunk_id')}")
    print(f"doc_id: {c.get('doc_id')}")
    print(f"title: {c.get('title')}")
    print(f"intent: {c.get('intent')}")
    print(f"distance: {c.get('distance')}")
    print(f"text 길이: {len(text)}자")
    print(text)

print("\n[RAG CONTEXT 전체]")
print("-" * 80)
print(context)
print("=" * 80)