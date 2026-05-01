#!/usr/bin/env python3
"""Count prompt tokens with a HuggingFace processor chat template.

Examples:
  python backend/scripts/count_prompt_tokens.py --model-id google/gemma-4-E2B-it
  python backend/scripts/count_prompt_tokens.py --model-id google/gemma-4-E2B-it --intent C --rag-file /tmp/rag.txt
  python backend/scripts/count_prompt_tokens.py --model-id google/gemma-4-E2B-it --messages-json /tmp/messages.json
  python backend/scripts/count_prompt_tokens.py --model-id google/gemma-4-E2B-it --content-format parts
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from transformers import AutoProcessor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prompts import (  # noqa: E402
    CHAT_STYLE_PROMPT,
    COMMON_PERSONA_PROMPT,
    FUNCTION_RESULT_PROMPT,
    HEALTH_RAG_PROMPT,
    build_system_prompt,
)


PROMPT_MODULES = {
    "COMMON_PERSONA_PROMPT": COMMON_PERSONA_PROMPT,
    "CHAT_STYLE_PROMPT": CHAT_STYLE_PROMPT,
    "FUNCTION_RESULT_PROMPT": FUNCTION_RESULT_PROMPT,
    "HEALTH_RAG_PROMPT": HEALTH_RAG_PROMPT,
}


def _read_text(value: str, file_path: str) -> str:
    if file_path:
        return Path(file_path).read_text(encoding="utf-8")
    return value or ""


def _message(role: str, content: str, content_format: str) -> dict[str, Any]:
    if content_format == "parts":
        return {"role": role, "content": [{"type": "text", "text": content}]}
    return {"role": role, "content": content}


def _token_len(tokenized: Any) -> int:
    # AutoProcessor can return a BatchFeature, which supports key lookup but
    # raises on integer indexing. Pull input_ids out before list handling.
    if hasattr(tokenized, "keys") and "input_ids" in tokenized:
        tokenized = tokenized["input_ids"]

    if hasattr(tokenized, "shape"):
        return int(tokenized.shape[-1])

    if isinstance(tokenized, list):
        if tokenized and isinstance(tokenized[0], list):
            return len(tokenized[0])
        return len(tokenized)

    raise TypeError(f"Unsupported tokenized type: {type(tokenized)}")


def count_chat_tokens(
    processor: Any,
    messages: list[dict[str, Any]],
    add_generation_prompt: bool = True,
) -> int:
    tokenized = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=add_generation_prompt,
        return_dict=True,
    )
    return _token_len(tokenized)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-id",
        default=os.getenv("HF_PROCESSOR_MODEL", "google/gemma-4-E2B-it"),
        help="HuggingFace processor id. Override with HF_PROCESSOR_MODEL.",
    )
    parser.add_argument("--intent", default="A", choices=["A", "B", "C", "D"])
    parser.add_argument("--mission", default="물 5잔 마시기")
    parser.add_argument("--user", default="안녕")
    parser.add_argument("--assistant", default="", help="Optional previous assistant message.")
    parser.add_argument(
        "--messages-json",
        default="",
        help="Optional history/current messages JSON file, excluding system. Example: [{\"role\":\"user\",\"content\":\"안녕\"}]",
    )
    parser.add_argument("--hint", default="")
    parser.add_argument("--hint-file", default="")
    parser.add_argument("--rag-context", default="")
    parser.add_argument("--rag-file", default="")
    parser.add_argument("--clarify-hint", default="")
    parser.add_argument("--greeting", action="store_true")
    parser.add_argument(
        "--content-format",
        choices=["string", "parts"],
        default="string",
        help="Use 'parts' if the processor chat template expects multimodal content blocks.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    processor = AutoProcessor.from_pretrained(args.model_id)

    hint = _read_text(args.hint, args.hint_file)
    rag_context = _read_text(args.rag_context, args.rag_file)
    system_prompt = build_system_prompt(
        intent=args.intent,
        mission=args.mission,
        hint=hint,
        rag_context=rag_context,
        clarify_hint=args.clarify_hint,
        is_greeting=args.greeting,
    )

    module_counts = {}
    for name, text in PROMPT_MODULES.items():
        module_messages = [_message("system", text, args.content_format)]
        module_counts[name] = count_chat_tokens(
            processor,
            module_messages,
            add_generation_prompt=False,
        )

    messages = [_message("system", system_prompt, args.content_format)]
    if args.messages_json:
        history = json.loads(Path(args.messages_json).read_text(encoding="utf-8"))
        for item in history:
            messages.append(_message(item["role"], item["content"], args.content_format))
    else:
        if args.assistant:
            messages.append(_message("assistant", args.assistant, args.content_format))
        messages.append(_message("user", args.user, args.content_format))

    full_count = count_chat_tokens(
        processor,
        messages,
        add_generation_prompt=True,
    )

    result = {
        "model_id": args.model_id,
        "content_format": args.content_format,
        "intent": args.intent,
        "module_counts": module_counts,
        "actual_inference_tokens": full_count,
        "message_count": len(messages),
        "system_prompt_chars": len(system_prompt),
        "hint_chars": len(hint),
        "rag_context_chars": len(rag_context),
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"model_id: {result['model_id']}")
    print(f"content_format: {result['content_format']}")
    print("\n[module token counts]")
    for name, count in module_counts.items():
        print(f"- {name}: {count:,}")
    print("\n[actual inference]")
    print(f"- intent: {args.intent}")
    print(f"- message_count: {len(messages)}")
    print(f"- total tokens(system + history/user + chat template): {full_count:,}")
    print(f"- system_prompt_chars: {len(system_prompt):,}")
    print(f"- hint_chars: {len(hint):,}")
    print(f"- rag_context_chars: {len(rag_context):,}")


if __name__ == "__main__":
    main()
