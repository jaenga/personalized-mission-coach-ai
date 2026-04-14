"""
Qwen LoRA 펑션콜링 클라이언트

로드 순서:
1. load_dotenv() → FUNCTION_BASE_MODEL, FUNCTION_ADAPTER_PATH 읽기
2. AutoTokenizer.from_pretrained(base_model)
3. AutoModelForCausalLM.from_pretrained(base_model)  ← CPU에 로드
4. PeftModel.from_pretrained(base, adapter_path)       ← LoRA 붙이기
5. merge_and_unload()                                  ← LoRA 가중치 흡수
6. model.to(device)                                    ← MPS/CPU로 이동
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

_model = None
_tokenizer = None
_device = None

_BASE_MODEL: str = os.getenv("FUNCTION_BASE_MODEL", "Qwen/Qwen3-0.6B")
_ADAPTER_PATH: str = os.getenv(
    "FUNCTION_ADAPTER_PATH",
    str(Path(__file__).parent / "qwen-lora-finetuned_3"),
)

# 어댑터 경로가 상대경로면 backend/ 기준으로 절대경로 변환
if not os.path.isabs(_ADAPTER_PATH):
    _ADAPTER_PATH = str(Path(__file__).parent / _ADAPTER_PATH)

# 앱에서 호출 가능한 함수 목록
AVAILABLE_FUNCTIONS: list[dict] = [
    {
        "name": "submit_mission_result",
        "description": (
            "미션 수행 결과를 확정해서 보고할 때 호출합니다.\n"
            "- success: 완료 (다 했어요)\n"
            "- fail: 수행 못함 (못 했어요, 조금 했어요)\n"
            "- 사용하지 않는 경우: 규칙 질문, 미션 변경 요청, 인정 여부 질문"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "result_type": {
                    "type": "string",
                    "enum": ["success", "fail"],
                    "description": "미션 달성 정도 (값: success[완료], fail[수행 실패])",
                },
            },
            "required": ["result_type"],
        },
    },
    {
        "name": "get_mission_info",
        "description": (
            "미션 관련 정보(오늘 미션, 마감 시간, 규칙)를 물어볼 때 호출합니다.\n"
            "- today: 오늘 미션의 내용, 수행 방법, 주의사항, 수행 조건을 물을 때 (오늘 뭐 해야 돼요?, 오늘 미션 어떻게 해요?)\n"
            "- deadline: 제출 마감, 기한을 물을 때 (언제까지예요?)\n"
            "- general_rule: 앱/시스템 차원의 제출·인증·판정·운영 규칙을 물을 때 (부분 수행도 인정돼요?, 어디에 제출해요?)\n"
            "- 사용하지 않는 경우: 결과 보고, 미션 변경 요청, 대체 수행 가능 여부 질문"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": ["today", "deadline", "general_rule"],
                    "description": "조회할 정보의 종류 (값: today[오늘의 미션], deadline[제출 마감 시간], general_rule[일반 규칙/가이드])",
                },
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "request_mission_adjustment",
        "description": (
            "미션을 바꾸거나 난이도를 조정해 달라고 요청할 때 호출합니다.\n"
            "- change: 다른 미션 요청 (다른 걸로 바꿔주세요)\n"
            "- easier: 더 쉬운 미션 요청 (너무 어려워요)\n"
            "- harder: 더 어려운 미션 요청 (너무 쉬워요)\n"
            "- 사용하지 않는 경우: 결과 보고, 인정 여부 질문, 규칙 질문"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "adjustment_type": {
                    "type": "string",
                    "enum": ["change", "easier", "harder"],
                    "description": "미션 내용 조정 종류 (값: change[미션 변경], easier[난이도 하향], harder[난이도 상향])",
                },
            },
            "required": ["adjustment_type"],
        },
    },
    {
        "name": "check_mission_equivalency",
        "description": (
            "다른 행동/장소/시간으로 수행해도 인정되는지 물어볼 때 호출합니다.\n"
            "구체적인 대체안이 있는 경우에만 사용합니다. (없으면 general_rule)\n"
            "- behavior: 행동 변경 (자전거로 해도 돼요?)\n"
            "- place: 장소 변경 (집에서 해도 돼요?)\n"
            "- time: 시간 변경 (저녁에 하면 되나요?)\n"
            "- 사용하지 않는 경우: 일반 규칙 질문 (인정돼요?), 미션 변경 요청"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "equivalency_type": {
                    "type": "string",
                    "enum": ["behavior", "place", "time"],
                    "description": "학생이 제안한 대체 행동 내용 (값: behavior[행동/대상 변경], place[장소 변경], time[시간/조건 변경])",
                },
            },
            "required": ["equivalency_type"],
        },
    },
    {
        "name": "get_user_history",
        "description": (
            "미션 수행 기록을 조회할 때 호출합니다.\n"
            "- weekly_summary: 이번 주 기록 (이번 주 얼마나 했어요?)\n"
            "- monthly_summary: 이번 달 기록 (이번 달 기록 보여줘)\n"
            "기록이 없으면 이전 기간 기록을 함께 제공할 수 있습니다.\n"
            "- 사용하지 않는 경우: 기간이 불명확한 질문"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": ["weekly_summary", "monthly_summary"],
                    "description": "조회할 기록의 범위 (값: weekly_summary[주간 요약], monthly_summary[월간 요약])",
                },
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "cancel_mission_action",
        "description": (
            "가장 최근 행동을 취소할 때 호출합니다.\n"
            "예: 방금 제출 취소 / 바꾼 거 없던 걸로\n"
            "- 사용하지 않는 경우: 새 요청 수행, 정보 조회"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]


def _select_device() -> str:
    import torch
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"

#서버 시작 시 모델 로드: CPU 로드 → LoRA merge → MPS/GPU 이동
def preload_qwen() -> None:
    global _model, _tokenizer, _device
    if _model is not None:
        return

    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        _device = _select_device()
        print(f"[Qwen] 디바이스: {_device}")
        print(f"[Qwen] 베이스 모델: {_BASE_MODEL}")
        print(f"[Qwen] 어댑터 경로: {_ADAPTER_PATH}")

        # 1. 토크나이저
        _tokenizer = AutoTokenizer.from_pretrained(_BASE_MODEL)

        # 2. 베이스 모델 CPU 로드
        base = AutoModelForCausalLM.from_pretrained(
            _BASE_MODEL,
            torch_dtype=torch.float32,
        )

        # 3. LoRA 어댑터 붙이기
        peft_model = PeftModel.from_pretrained(base, _ADAPTER_PATH)

        # 4. LoRA 가중치 흡수 → 일반 모델로 변환
        print("[Qwen] LoRA merge 중...")
        _model = peft_model.merge_and_unload()

        # 5. 타겟 디바이스로 이동
        _model = _model.to(_device)
        _model.eval()
        print(f"[Qwen] 로드 완료 → {_device}")

    except Exception as e:
        print(f"[Qwen] 모델 로드 실패 (펑션콜링 비활성화): {e}")
        _model = None
        _tokenizer = None
        _device = None


def call_function(
    user_message: str,
) -> tuple[str | None, dict[str, Any], int]:
    if _model is None or _tokenizer is None:
        print("[Qwen] 모델 미로드 상태 — 펑션콜링 스킵")
        return None, {}, 0

    try:
        import torch

        messages = [
            {
                "role": "system",
                "content": "너는 초등학생 AI 코치 앱 도우미야. 사용자 요청에 맞는 함수를 tool_call 형식으로 호출해.",
            },
            {"role": "user", "content": user_message},
        ]

        text = _tokenizer.apply_chat_template(
            messages,
            tools=AVAILABLE_FUNCTIONS,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = _tokenizer(text, return_tensors="pt").to(_device)

        t0 = time.perf_counter()
        with torch.no_grad():
            output_ids = _model.generate(
                **inputs,
                max_new_tokens=128,
                do_sample=False,
                pad_token_id=_tokenizer.eos_token_id,
            )
        elapsed_ms = round((time.perf_counter() - t0) * 1000)

        new_tokens = output_ids[0][inputs["input_ids"].shape[1]:]
        decoded = _tokenizer.decode(new_tokens, skip_special_tokens=True)
        print(f"[Qwen] raw output: {decoded[:200]}")

        fn_name, args = _parse_tool_call(decoded)
        print(f"[Qwen] 펑션콜: {fn_name}({args}) — {elapsed_ms}ms")
        return fn_name, args, elapsed_ms

    except Exception as e:
        print(f"[Qwen] 추론 실패: {e}")
        return None, {}, 0


def _parse_tool_call(text: str) -> tuple[str | None, dict]:
    """<tool_call>{...}</tool_call> 형식에서 함수명과 인자 파싱."""
    match = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(1))
            return obj.get("name"), obj.get("arguments", {})
        except json.JSONDecodeError:
            pass

    # fallback: JSON 블록만 있는 경우
    match = re.search(r'\{"name"\s*:\s*"([^"]+)".*?"arguments"\s*:\s*(\{[^}]*\})', text, re.DOTALL)
    if match:
        try:
            return match.group(1), json.loads(match.group(2))
        except json.JSONDecodeError:
            pass

    return None, {}
