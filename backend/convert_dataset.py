import csv
import json
import uuid
from pathlib import Path
from collections import defaultdict

import sys
sys.path.insert(0, str(Path(__file__).parent))
from function_tools import TOOLS

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CSV_DIR  = Path("/Users/chaewon/Documents/2026-1/캡스톤/functiongemma 학습 데이터셋")
OUT_DIR  = BASE_DIR / "dataset"

# 허용된 함수명 및 enum 값 (function_tools.py 기준)
VALID_FUNCTION_NAMES = {t["function"]["name"] for t in TOOLS}
VALID_ENUMS = {}
for _t in TOOLS:
    _fn = _t["function"]
    _name = _fn["name"]
    _enums = {}
    for _arg, _schema in _fn["parameters"].get("properties", {}).items():
        if "enum" in _schema:
            _enums[_arg] = set(_schema["enum"])
    VALID_ENUMS[_name] = _enums

DEVELOPER_CONTENT = (
    "당신은 어린이 건강 습관 코치 앱의 AI입니다. "
    "사용자 발화를 보고 반드시 제공된 함수 중 하나를 호출해야 합니다. "
    "자연어 답변은 절대 생성하지 마세요. 함수 호출만 출력하세요."
)


def safe_parse_json(raw, fallback):
    if isinstance(raw, (dict, list)):
        return raw
    if not raw or str(raw).strip() in ("", "-"):
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


def make_tool_call_entry(name: str, arguments: dict) -> dict:
    """tool_calls 배열의 단일 항목 — FunctionGemma 요구 형식"""
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


def is_valid_call(name: str, arguments: dict) -> bool:
    """함수명 + enum 값 유효성 검사"""
    if name not in VALID_FUNCTION_NAMES:
        return False
    for arg_name, allowed in VALID_ENUMS.get(name, {}).items():
        val = arguments.get(arg_name)
        if val is not None and val not in allowed:
            return False
    return True


# ── 1. single_turn ────────────────────────────────────────────────────────────

def convert_single_turn(csv_path: Path, out_path: Path) -> tuple[int, int]:
    saved, skipped = 0, 0
    with (
        open(csv_path, encoding="utf-8-sig") as f,
        open(out_path, "w", encoding="utf-8") as out,
    ):
        reader = csv.DictReader(f)
        for row in reader:
            user_query    = row.get("user_query", "").strip().strip('"')
            function_name = row.get("function_name", "").strip()
            arguments     = safe_parse_json(row.get("arguments", "{}"), {})

            if not user_query or not function_name:
                skipped += 1
                continue
            if not is_valid_call(function_name, arguments):
                skipped += 1
                continue

            record = {
                "tools": TOOLS,
                "messages": [
                    {"role": "developer", "content": DEVELOPER_CONTENT},
                    {"role": "user",      "content": user_query},
                    {"role": "assistant", "tool_calls": [make_tool_call_entry(function_name, arguments)]},
                ],
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            saved += 1
    return saved, skipped


# ── 2. multi_function ─────────────────────────────────────────────────────────

def convert_multi_function(csv_path: Path, out_path: Path) -> tuple[int, int]:
    saved, skipped = 0, 0
    with (
        open(csv_path, encoding="utf-8-sig") as f,
        open(out_path, "w", encoding="utf-8") as out,
    ):
        reader = csv.DictReader(f)
        for row in reader:
            user_query     = row.get("user_query", "").strip().strip('"')
            function_calls = safe_parse_json(row.get("function_calls", "[]"), [])

            if not user_query or not function_calls:
                skipped += 1
                continue

            tool_calls = []
            valid = True
            for call in function_calls:
                name = call.get("name", "")
                args = safe_parse_json(call.get("arguments", {}), {})
                if not is_valid_call(name, args):
                    valid = False
                    break
                tool_calls.append(make_tool_call_entry(name, args))

            if not valid or not tool_calls:
                skipped += 1
                continue

            record = {
                "tools": TOOLS,
                "messages": [
                    {"role": "developer", "content": DEVELOPER_CONTENT},
                    {"role": "user",      "content": user_query},
                    {"role": "assistant", "tool_calls": tool_calls},
                ],
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            saved += 1
    return saved, skipped


# ── 3. multi_turn ─────────────────────────────────────────────────────────────

def convert_multi_turn(csv_path: Path, out_path: Path) -> tuple[int, int]:
    convs: dict[str, list[dict]] = defaultdict(list)

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            conv_id        = row.get("conv_id", "").strip()
            turn           = row.get("turn", "0").strip()
            role           = row.get("role", "").strip()
            content        = row.get("content", "").strip()
            function_calls = row.get("function_calls", "").strip()

            if not conv_id or not role:
                continue

            convs[conv_id].append({
                "turn":           int(turn) if turn.isdigit() else 0,
                "role":           role,
                "content":        content,
                "function_calls": function_calls,
            })

    saved, skipped = 0, 0
    with open(out_path, "w", encoding="utf-8") as out:
        for conv_id, turns in convs.items():
            turns.sort(key=lambda x: x["turn"])

            messages = [{"role": "developer", "content": DEVELOPER_CONTENT}]
            valid = True

            for t in turns:
                role    = t["role"]
                content = t["content"]
                fc_raw  = t["function_calls"]

                if role == "user":
                    if not content:
                        valid = False
                        break
                    messages.append({"role": "user", "content": content})

                elif role == "assistant":
                    parsed = safe_parse_json(fc_raw, None)
                    if parsed is None:
                        valid = False
                        break

                    # 단일 dict → 리스트로 정규화
                    calls_raw = [parsed] if isinstance(parsed, dict) else parsed
                    if not isinstance(calls_raw, list):
                        valid = False
                        break

                    tool_calls = []
                    for call in calls_raw:
                        name = call.get("name", "")
                        args = safe_parse_json(call.get("arguments", {}), {})
                        if not is_valid_call(name, args):
                            # no_function 등 유효하지 않은 함수 → 이 turn 포함 이후 전부 버림
                            valid = False
                            break
                        tool_calls.append(make_tool_call_entry(name, args))

                    if not valid:
                        # 유효하지 않은 turn 직전까지만 사용 (이전 turn들이 있으면 저장)
                        break

                    messages.append({"role": "assistant", "tool_calls": tool_calls})

            # developer + user + assistant 최소 3개, 마지막이 assistant여야 함
            if len(messages) < 3 or messages[-1].get("role") != "assistant":
                skipped += 1
                continue

            record = {"tools": TOOLS, "messages": messages}
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            saved += 1

    return saved, skipped


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tasks = [
        ("single_turn",    CSV_DIR / "single_turn.csv",    OUT_DIR / "single_turn.jsonl",    convert_single_turn),
        ("multi_function", CSV_DIR / "multi_function.csv", OUT_DIR / "multi_function.jsonl", convert_multi_function),
        ("multi_turn",     CSV_DIR / "multi_turn.csv",     OUT_DIR / "multi_turn.jsonl",     convert_multi_turn),
    ]

    print("=" * 50)
    print("CSV → JSONL 변환 (FunctionGemma 형식)")
    print("=" * 50)

    for name, csv_path, out_path, fn in tasks:
        if not csv_path.exists():
            print(f"[SKIP] {name}: 파일 없음 ({csv_path})")
            continue
        saved, skip = fn(csv_path, out_path)
        print(f"[OK]   {name}: {saved}개 저장 / {skip}개 제거 → {out_path.name}")

    print("=" * 50)
    print(f"출력 위치: {OUT_DIR}")


if __name__ == "__main__":
    main()
