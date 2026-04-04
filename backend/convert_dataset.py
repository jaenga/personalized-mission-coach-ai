import csv
import json
from pathlib import Path
from collections import defaultdict

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CSV_DIR  = Path("/Users/chaewon/Documents/2026-1/캡스톤/functiongemma 학습 데이터셋")
OUT_DIR  = BASE_DIR / "dataset"


def safe_parse_json(raw, fallback):
    """문자열이면 json.loads, 실패 시 fallback 반환."""
    if isinstance(raw, dict) or isinstance(raw, list):
        return raw
    if not raw or str(raw).strip() in ("", "-"):
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


def make_tool_call(name: str, arguments: dict) -> dict:
    return {"name": name, "arguments": arguments}


# ── 1. single_turn ────────────────────────────────────────────────────────────

def convert_single_turn(csv_path: Path, out_path: Path) -> int:
    count = 0
    with (
        open(csv_path, encoding="utf-8-sig") as f,
        open(out_path, "w", encoding="utf-8") as out,
    ):
        reader = csv.DictReader(f)
        for row in reader:
            user_query   = row.get("user_query", "").strip().strip('"')
            function_name = row.get("function_name", "").strip()
            arguments    = safe_parse_json(row.get("arguments", "{}"), {})

            if not user_query or not function_name:
                continue

            assistant_content = json.dumps(
                make_tool_call(function_name, arguments),
                ensure_ascii=False,
            )

            record = {
                "messages": [
                    {"role": "user",      "content": user_query},
                    {"role": "assistant", "content": assistant_content},
                ]
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


# ── 2. multi_function ─────────────────────────────────────────────────────────

def convert_multi_function(csv_path: Path, out_path: Path) -> int:
    count = 0
    with (
        open(csv_path, encoding="utf-8-sig") as f,
        open(out_path, "w", encoding="utf-8") as out,
    ):
        reader = csv.DictReader(f)
        for row in reader:
            user_query   = row.get("user_query", "").strip().strip('"')
            function_calls = safe_parse_json(row.get("function_calls", "[]"), [])

            if not user_query or not function_calls:
                continue

            # 각 call을 {"name": ..., "arguments": ...} 형식으로 정규화
            normalized = []
            for call in function_calls:
                name = call.get("name", "")
                args = safe_parse_json(call.get("arguments", {}), {})
                normalized.append(make_tool_call(name, args))

            assistant_content = json.dumps(normalized, ensure_ascii=False)

            record = {
                "messages": [
                    {"role": "user",      "content": user_query},
                    {"role": "assistant", "content": assistant_content},
                ]
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


# ── 3. multi_turn ─────────────────────────────────────────────────────────────

def convert_multi_turn(csv_path: Path, out_path: Path) -> int:
    # conv_id 기준으로 turn을 수집
    convs: dict[str, list[dict]] = defaultdict(list)

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            conv_id       = row.get("conv_id", "").strip()
            turn          = row.get("turn", "0").strip()
            role          = row.get("role", "").strip()
            content       = row.get("content", "").strip()
            function_calls = row.get("function_calls", "").strip()

            if not conv_id or not role:
                continue

            convs[conv_id].append({
                "turn":           int(turn) if turn.isdigit() else 0,
                "role":           role,
                "content":        content,
                "function_calls": function_calls,
            })

    count = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for conv_id, turns in convs.items():
            turns.sort(key=lambda x: x["turn"])

            messages = []
            for t in turns:
                role    = t["role"]
                content = t["content"]
                fc_raw  = t["function_calls"]

                if role == "assistant":
                    parsed = safe_parse_json(fc_raw, None)
                    if parsed is not None:
                        # function_calls가 dict(단일)이면 리스트로 감싸지 않고 그대로
                        if isinstance(parsed, dict):
                            content = json.dumps(
                                make_tool_call(
                                    parsed.get("name", ""),
                                    safe_parse_json(parsed.get("arguments", {}), {}),
                                ),
                                ensure_ascii=False,
                            )
                        elif isinstance(parsed, list):
                            normalized = [
                                make_tool_call(
                                    c.get("name", ""),
                                    safe_parse_json(c.get("arguments", {}), {}),
                                )
                                for c in parsed
                            ]
                            content = json.dumps(normalized, ensure_ascii=False)
                    # parsed가 None이면 content 그대로 사용

                if content:
                    messages.append({"role": role, "content": content})

            if len(messages) >= 2:
                record = {"messages": messages}
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

    return count


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tasks = [
        (
            "single_turn",
            CSV_DIR / "single_turn.csv",
            OUT_DIR / "single_turn.jsonl",
            convert_single_turn,
        ),
        (
            "multi_function",
            CSV_DIR / "multi_function.csv",
            OUT_DIR / "multi_function.jsonl",
            convert_multi_function,
        ),
        (
            "multi_turn",
            CSV_DIR / "multi_turn.csv",
            OUT_DIR / "multi_turn.jsonl",
            convert_multi_turn,
        ),
    ]

    print("=" * 50)
    print("CSV → JSONL 변환 시작")
    print("=" * 50)

    for name, csv_path, out_path, fn in tasks:
        if not csv_path.exists():
            print(f"[SKIP] {name}: 파일 없음 ({csv_path})")
            continue
        count = fn(csv_path, out_path)
        print(f"[OK]   {name}: {count}개 → {out_path.name}")

    print("=" * 50)
    print(f"출력 위치: {OUT_DIR}")


if __name__ == "__main__":
    main()
