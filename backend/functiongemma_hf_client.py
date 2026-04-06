import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import torch
from dotenv import load_dotenv
from transformers import AutoModelForCausalLM, AutoTokenizer

from function_tools import TOOLS
from prompts import FUNCTION_SYSTEM_PROMPT

try:
    from peft import PeftModel
except Exception:  # pragma: no cover - optional dependency import surface
    PeftModel = None


load_dotenv()
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FunctionGemmaConfig:
    base_model: str
    adapter_path: str | None
    device: str
    dtype: str
    max_new_tokens: int
    merge_adapter: bool


def _tool_enum_index(tools: list[dict[str, Any]]) -> dict[str, dict[str, set[str]]]:
    idx: dict[str, dict[str, set[str]]] = {}
    for tool in tools:
        fn = tool.get("function", {})
        fn_name = fn.get("name")
        if not fn_name:
            continue
        props = fn.get("parameters", {}).get("properties", {})
        arg_enum_map: dict[str, set[str]] = {}
        for arg_name, spec in props.items():
            enum_values = spec.get("enum") or []
            arg_enum_map[arg_name] = {str(v) for v in enum_values}
        idx[fn_name] = arg_enum_map
    return idx


class FunctionGemmaHFClient:
    def __init__(self, config: FunctionGemmaConfig):
        self.config = config
        self.device = self._select_device(config.device)
        self.dtype = self._select_dtype(config.dtype, self.device)
        self.tokenizer = None
        self.model = None
        self.tool_names = {t["function"]["name"] for t in TOOLS if "function" in t}
        self.tool_enum_index = _tool_enum_index(TOOLS)

    @staticmethod
    def _select_device(device_cfg: str) -> str:
        if device_cfg and device_cfg.lower() != "auto":
            return device_cfg.lower()
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    @staticmethod
    def _select_dtype(dtype_cfg: str, device: str) -> torch.dtype:
        cfg = (dtype_cfg or "auto").lower()
        if cfg == "float16":
            return torch.float16
        if cfg == "bfloat16":
            return torch.bfloat16
        if cfg == "float32":
            return torch.float32

        if device == "cuda":
            return torch.float16
        if device == "mps":
            return torch.float16
        return torch.float32

    def load(self) -> None:
        logger.info(
            "Loading FunctionGemma base model='%s' adapter='%s' device='%s' dtype='%s'",
            self.config.base_model,
            self.config.adapter_path,
            self.device,
            self.dtype,
        )

        self.tokenizer = AutoTokenizer.from_pretrained(self.config.base_model)
        base_model = AutoModelForCausalLM.from_pretrained(
            self.config.base_model,
            torch_dtype=self.dtype,
        )

        if self.config.adapter_path:
            if PeftModel is None:
                raise RuntimeError(
                    "peft 패키지를 불러올 수 없습니다. `pip install peft` 후 다시 실행하세요."
                )

            peft_model = PeftModel.from_pretrained(base_model, self.config.adapter_path)
            if self.config.merge_adapter:
                logger.info("Merging LoRA adapter into base model.")
                model = peft_model.merge_and_unload()
            else:
                logger.info("Using LoRA adapter without merge.")
                model = peft_model
        else:
            logger.warning("FUNCTION_ADAPTER_PATH is not set; base model only will be used.")
            model = base_model

        self.model = model.to(self.device)
        self.model.eval()

    def _assert_loaded(self) -> None:
        if self.model is None or self.tokenizer is None:
            raise RuntimeError("FunctionGemma 모델이 로드되지 않았습니다. initialize_functiongemma_client()를 먼저 호출하세요.")

    @staticmethod
    def _strip_escapes(value: str) -> str:
        cleaned = value.replace("<escape>", "").strip()
        if len(cleaned) >= 2 and ((cleaned[0] == '"' and cleaned[-1] == '"') or (cleaned[0] == "'" and cleaned[-1] == "'")):
            return cleaned[1:-1]
        return cleaned

    def _parse_argument_blob(self, blob: str) -> dict[str, Any]:
        blob = blob.strip()
        if not blob:
            return {}

        json_like = blob.replace("<escape>", '"')
        try:
            parsed = json.loads(json_like)
            if isinstance(parsed, dict):
                return {str(k): v for k, v in parsed.items()}
        except json.JSONDecodeError:
            pass

        args: dict[str, Any] = {}

        # key:<escape>value<escape>
        for k, v in re.findall(r"(\w+)\s*:\s*<escape>(.*?)<escape>", blob, flags=re.DOTALL):
            args[k] = v.strip()

        # key:"value" or key:'value'
        for k, q, v in re.findall(r"(\w+)\s*:\s*([\"'])(.*?)\2", blob, flags=re.DOTALL):
            _ = q
            args[k] = v.strip()

        # fallback: key:value (up to comma or end)
        fallback_blob = re.sub(r"(\w+)\s*:\s*<escape>.*?<escape>", "", blob, flags=re.DOTALL)
        fallback_blob = re.sub(r"(\w+)\s*:\s*[\"'].*?[\"']", "", fallback_blob, flags=re.DOTALL)
        for k, v in re.findall(r"(\w+)\s*:\s*([^,}]+)", fallback_blob):
            if k in args:
                continue
            raw_v = v.strip()
            lower = raw_v.lower()
            if lower == "true":
                args[k] = True
            elif lower == "false":
                args[k] = False
            elif re.fullmatch(r"-?\d+", raw_v):
                args[k] = int(raw_v)
            elif re.fullmatch(r"-?\d+\.\d+", raw_v):
                args[k] = float(raw_v)
            else:
                args[k] = self._strip_escapes(raw_v)

        return args

    def _validate_enums(self, name: str, arguments: dict[str, Any], raw_output: str) -> None:
        enum_map = self.tool_enum_index.get(name, {})
        for arg_name, value in arguments.items():
            allowed = enum_map.get(arg_name)
            if not allowed:
                continue
            if str(value) not in allowed:
                logger.warning(
                    "Enum mismatch from FunctionGemma: fn=%s arg=%s value=%r allowed=%s raw=%r",
                    name,
                    arg_name,
                    value,
                    sorted(allowed),
                    raw_output,
                )

    @staticmethod
    def _normalize_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "request_mission_exception" and arguments.get("exception_type") == "weather":
            arguments["exception_type"] = "environment"
        return arguments

    def parse_function_call(self, raw_output: str) -> dict[str, Any] | None:
        text = raw_output.strip()
        if not text:
            return None

        if "no_function" in text.lower():
            return None

        block_match = re.search(
            r"<start_function_call>\s*(.*?)\s*<end_function_call>",
            text,
            flags=re.DOTALL,
        )
        target = block_match.group(1).strip() if block_match else text

        call_match = re.search(r"call\s*:\s*([a-zA-Z0-9_]+)\s*(\{.*\})?", target, flags=re.DOTALL)
        if not call_match:
            fn_only_match = re.search(r"\b([a-zA-Z0-9_]+)\s*(\{.*\})", target, flags=re.DOTALL)
            if not fn_only_match:
                logger.debug("Function parse failed: raw_output=%r", raw_output)
                return None
            name = fn_only_match.group(1)
            arg_blob_with_brace = fn_only_match.group(2)
        else:
            name = call_match.group(1)
            arg_blob_with_brace = call_match.group(2) or "{}"

        if name == "no_function":
            return None

        if name not in self.tool_names:
            logger.warning("Unknown function name predicted: %s raw=%r", name, raw_output)

        arg_blob = arg_blob_with_brace.strip()
        if arg_blob.startswith("{") and arg_blob.endswith("}"):
            arg_blob = arg_blob[1:-1]

        try:
            arguments = self._parse_argument_blob(arg_blob)
        except Exception:
            logger.exception("Failed to parse function arguments: raw_output=%r", raw_output)
            arguments = {}

        arguments = self._normalize_arguments(name, arguments)
        self._validate_enums(name, arguments, raw_output)
        return {"name": name, "arguments": arguments}

    def predict_with_raw(self, user_text: str) -> tuple[str, dict[str, Any] | None]:
        self._assert_loaded()
        messages = [
            {"role": "developer", "content": FUNCTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]

        model_inputs = self.tokenizer.apply_chat_template(
            messages,
            tools=TOOLS,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        model_inputs = {k: v.to(self.device) for k, v in model_inputs.items()}

        with torch.inference_mode():
            output = self.model.generate(
                **model_inputs,
                max_new_tokens=self.config.max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )

        input_len = model_inputs["input_ids"].shape[1]
        gen_tokens = output[:, input_len:]
        raw_output = self.tokenizer.decode(gen_tokens[0], skip_special_tokens=False).strip()

        parsed = self.parse_function_call(raw_output)
        if parsed is None and raw_output:
            logger.debug("No function call parsed. raw_output=%r", raw_output)
        return raw_output, parsed

    def predict_function_call(self, user_text: str) -> dict[str, Any] | None:
        _, parsed = self.predict_with_raw(user_text)
        return parsed


_CLIENT: FunctionGemmaHFClient | None = None


def _build_config_from_env() -> FunctionGemmaConfig:
    return FunctionGemmaConfig(
        base_model=os.getenv("FUNCTION_BASE_MODEL", "google/functiongemma-270m-it"),
        adapter_path=os.getenv("FUNCTION_ADAPTER_PATH") or None,
        device=os.getenv("FUNCTION_DEVICE", "auto"),
        dtype=os.getenv("FUNCTION_DTYPE", "auto"),
        max_new_tokens=int(os.getenv("FUNCTION_MAX_NEW_TOKENS", "96")),
        merge_adapter=os.getenv("FUNCTION_MERGE_ADAPTER", "true").lower() in {"1", "true", "yes"},
    )


def initialize_functiongemma_client() -> FunctionGemmaHFClient:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    config = _build_config_from_env()
    if not config.base_model:
        raise RuntimeError("FUNCTION_BASE_MODEL 환경변수가 비어 있습니다.")
    if not config.adapter_path:
        raise RuntimeError(
            "FUNCTION_ADAPTER_PATH 환경변수가 필요합니다. "
            "파인튜닝된 LoRA adapter 경로를 절대경로로 지정하세요."
        )
    if not os.path.exists(config.adapter_path):
        raise RuntimeError(f"FUNCTION_ADAPTER_PATH 경로를 찾을 수 없습니다: {config.adapter_path}")

    client = FunctionGemmaHFClient(config)
    try:
        client.load()
    except Exception as exc:
        raise RuntimeError(
            "FunctionGemma HF 모델 로딩에 실패했습니다. "
            "FUNCTION_BASE_MODEL / FUNCTION_ADAPTER_PATH / 환경 의존성(torch, transformers, peft)을 확인하세요. "
            f"원인: {exc}"
        ) from exc

    _CLIENT = client
    return _CLIENT


def get_functiongemma_client() -> FunctionGemmaHFClient:
    if _CLIENT is None:
        return initialize_functiongemma_client()
    return _CLIENT


def predict_function_call(user_text: str) -> dict[str, Any] | None:
    client = get_functiongemma_client()
    return client.predict_function_call(user_text)
