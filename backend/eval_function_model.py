"""
FunctionGemma 파인튜닝 전후 성능 비교 평가 스크립트.

사용법:
    python eval_function_model.py

환경변수 (선택):
    BASE_MODEL     : 베이스 모델명   (기본: functiongemma)
    TUNED_MODEL    : 파인튜닝 모델명 (기본: functiongemma-finetuned)
    OLLAMA_BASE_URL: Ollama 주소     (기본: http://localhost:11434)
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
BASE_MODEL  = os.getenv("BASE_MODEL",  "functiongemma")
TUNED_MODEL = os.getenv("TUNED_MODEL", "functiongemma-finetuned")

# ── 평가용 시스템 프롬프트 (prompts.py 와 동일하게 유지) ──────────────────────
from prompts import FUNCTION_SYSTEM_PROMPT
from function_tools import TOOLS

# ── 테스트 케이스 ─────────────────────────────────────────────────────────────
# (input_text, expected_function, expected_arg_key, expected_arg_value)
# expected_arg_key / value 가 None 이면 함수 이름만 체크
@dataclass
class TestCase:
    input: str
    expected_fn: str
    expected_arg_key: str | None = None
    expected_arg_value: str | None = None
    category: str = "general"

TEST_CASES: list[TestCase] = [
    # ── submit_mission_result ──────────────────────────────────────────────────
    TestCase("다 했어요",                        "submit_mission_result", "result_type", "success",  "submit"),
    TestCase("오늘 미션 완료했어요!",              "submit_mission_result", "result_type", "success",  "submit"),
    TestCase("반 정도 했어요",                    "submit_mission_result", "result_type", "partial",  "submit"),
    TestCase("물 두 잔 마셨어요",                  "submit_mission_result", "result_type", "partial",  "submit"),
    TestCase("오늘 하나도 못 했어요",              "submit_mission_result", "result_type", "fail",     "submit"),
    TestCase("못 했어요",                         "submit_mission_result", "result_type", "fail",     "submit"),

    # ── get_mission_info ───────────────────────────────────────────────────────
    TestCase("오늘 미션이 뭐예요?",               "get_mission_info", "query_type", "today",        "mission_info"),
    TestCase("오늘 뭐 해야 돼요?",               "get_mission_info", "query_type", "today",        "mission_info"),
    TestCase("언제까지 제출해야 해요?",            "get_mission_info", "query_type", "deadline",     "mission_info"),
    TestCase("마감 시간이 언제예요?",             "get_mission_info", "query_type", "deadline",     "mission_info"),
    TestCase("부분 수행도 인정되나요?",            "get_mission_info", "query_type", "general_rule", "mission_info"),

    # ── request_mission_adjustment ─────────────────────────────────────────────
    TestCase("다른 미션으로 바꿔주세요",           "request_mission_adjustment", "adjustment_type", "change",  "adjustment"),
    TestCase("이 미션 너무 어려워요. 쉬운 걸로 해주세요", "request_mission_adjustment", "adjustment_type", "easier", "adjustment"),
    TestCase("더 어려운 미션 주세요",             "request_mission_adjustment", "adjustment_type", "harder",  "adjustment"),

    # ── check_mission_equivalency ──────────────────────────────────────────────
    TestCase("줄넘기 대신 자전거 타면 인정돼요?",  "check_mission_equivalency", "equivalency_type", "behavior", "equivalency"),
    TestCase("집에서 해도 되나요?",               "check_mission_equivalency", "equivalency_type", "location", "equivalency"),
    TestCase("저녁에 해도 되나요?",               "check_mission_equivalency", "equivalency_type", "time",     "equivalency"),

    # ── request_mission_exception ──────────────────────────────────────────────
    TestCase("오늘 배가 아파서 못 하겠어요",       "request_mission_exception", "exception_type", "health",      "exception"),
    TestCase("오늘 학원이 늦게 끝나요",            "request_mission_exception", "exception_type", "schedule",    "exception"),
    TestCase("비가 와서 밖에 못 나가요",           "request_mission_exception", "exception_type", "environment", "exception"),

    # ── check_certification_info ───────────────────────────────────────────────
    TestCase("인증샷 어떻게 찍어요?",             "check_certification_info", "info_type", "method",   "cert"),
    TestCase("어디에 올려요?",                    "check_certification_info", "info_type", "location", "cert"),

    # ── report_submission_issue ────────────────────────────────────────────────
    TestCase("제출 기한 지났는데 늦게 올려도 돼요?","report_submission_issue", "issue_type", "late_submission", "issue"),
    TestCase("앱이 오류 나서 제출을 못 했어요",    "report_submission_issue", "issue_type", "device_issue",    "issue"),

    # ── support_mission_help ───────────────────────────────────────────────────
    TestCase("어떻게 하는 건지 잘 모르겠어요",     "support_mission_help", None, None, "help"),
    TestCase("물 4잔이 정확히 어느 정도예요?",     "support_mission_help", None, None, "help"),

    # ── get_weather_info ───────────────────────────────────────────────────────
    TestCase("오늘 비 와요?",                     "get_weather_info", None, None, "weather"),
    TestCase("미세먼지 어때요?",                  "get_weather_info", None, None, "weather"),

    # ── get_health_info ────────────────────────────────────────────────────────
    TestCase("물은 얼마나 마셔야 해요?",           "get_health_info", "topic_type", "water",    "health_info"),
    TestCase("운동 얼마나 해야 좋아요?",           "get_health_info", "topic_type", "exercise", "health_info"),
    TestCase("잠은 몇 시간 자야 해요?",            "get_health_info", "topic_type", "sleep",    "health_info"),

    # ── get_user_history ───────────────────────────────────────────────────────
    TestCase("최근 기록 보여줘",                  "get_user_history", "query_type", "recent_history",  "history"),
    TestCase("이번 주 얼마나 했어요?",             "get_user_history", "query_type", "weekly_summary",  "history"),
    TestCase("지금까지 몇 번 성공했어요?",          "get_user_history", "query_type", "success_count",   "history"),

    # ── cancel_mission_action ──────────────────────────────────────────────────
    TestCase("방금 제출한 거 취소할게요",           "cancel_mission_action", "action_type", "submit",     "cancel"),
    TestCase("미션 바꾸는 거 취소해주세요",         "cancel_mission_action", "action_type", "adjustment", "cancel"),
    TestCase("예외 신청 취소할게요",               "cancel_mission_action", "action_type", "exception",  "cancel"),

    # ── no_function (함수 호출 안 해야 하는 케이스) ────────────────────────────
    TestCase("안녕하세요",                        "NO_FUNCTION", None, None, "no_function"),
    TestCase("고마워요",                          "NO_FUNCTION", None, None, "no_function"),
    TestCase("오늘 날씨 정말 좋다",               "NO_FUNCTION", None, None, "no_function"),
    TestCase("힘들어요",                          "NO_FUNCTION", None, None, "no_function"),
    TestCase("배고파요",                          "NO_FUNCTION", None, None, "no_function"),
]


# ── 단일 케이스 실행 ──────────────────────────────────────────────────────────
_TOOL_NAMES = [t["function"]["name"] for t in TOOLS]

def _parse_fn_from_text(text: str) -> tuple[str, dict]:
    """raw 텍스트에서 함수명과 인자를 추출."""
    import re
    # call:fn_name{...} 또는 fn_name{...} 패턴 탐색
    for name in _TOOL_NAMES:
        if name in text:
            # 인자 추출 시도
            m = re.search(rf'{re.escape(name)}\{{([^}}]*)\}}', text)
            args = {}
            if m:
                raw = m.group(1)
                # <escape>value<escape> 또는 "value" 파싱
                for kv in re.findall(r'(\w+):\s*(?:<escape>)?([^<,\}]+?)(?:<escape>)?(?=[,\}])', raw):
                    args[kv[0].strip()] = kv[1].strip()
            return name, args
    return "NO_FUNCTION", {}


async def run_one(model: str, tc: TestCase, client: httpx.AsyncClient) -> dict:
    full_prompt = (
        "<start_of_turn>developer\n"
        "You are a function-calling classifier. "
        "Use the provided tools to decide the correct function call.\n"
        f"{json.dumps(TOOLS, ensure_ascii=False)}"
        "<end_of_turn>\n"
        f"<start_of_turn>user\n{tc.input}<end_of_turn>\n"
        "<start_of_turn>model\n"
    )

    payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": True,
        "options": {
            "num_predict": 80,
            "temperature": 0,
            "stop": ["<end_of_turn>", "<end_function_call>"],
        },
    }
    t0 = time.perf_counter()
    content_parts = []

    async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=60.0) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue
            if data.get("response"):
                content_parts.append(data["response"])
            if data.get("done"):
                break

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    raw_content = "".join(content_parts).strip()

    predicted_fn, raw_args = _parse_fn_from_text(raw_content)
    predicted_arg = raw_args.get(tc.expected_arg_key) if tc.expected_arg_key else None

    if predicted_fn == "NO_FUNCTION" and raw_content:
        print(f"    [RAW] {raw_content[:120]!r}")

    fn_correct  = (predicted_fn == tc.expected_fn)
    arg_correct = (
        True
        if tc.expected_arg_key is None
        else (predicted_arg == tc.expected_arg_value)
    )
    fully_correct = fn_correct and arg_correct

    return {
        "input":         tc.input,
        "category":      tc.category,
        "expected_fn":   tc.expected_fn,
        "expected_arg":  tc.expected_arg_value,
        "predicted_fn":  predicted_fn,
        "predicted_arg": predicted_arg,
        "fn_correct":    fn_correct,
        "arg_correct":   arg_correct,
        "fully_correct": fully_correct,
        "elapsed_ms":    elapsed_ms,
    }


# ── 모델 전체 평가 ────────────────────────────────────────────────────────────
async def evaluate_model(model: str) -> list[dict]:
    results = []
    async with httpx.AsyncClient() as client:
        for tc in TEST_CASES:
            try:
                r = await run_one(model, tc, client)
            except Exception as e:
                print(f"  [ERROR 상세] {type(e).__name__}: {e}")
                r = {
                    "input": tc.input, "category": tc.category,
                    "expected_fn": tc.expected_fn, "expected_arg": tc.expected_arg_value,
                    "predicted_fn": "ERROR", "predicted_arg": None,
                    "fn_correct": False, "arg_correct": False, "fully_correct": False,
                    "elapsed_ms": 0, "error": str(e),
                }
            results.append(r)
            status = "✅" if r["fully_correct"] else "❌"
            print(f"  {status} [{r['elapsed_ms']:5d}ms] {r['input'][:35]:<35} "
                  f"→ {r['predicted_fn']}")
    return results


# ── 결과 요약 출력 ─────────────────────────────────────────────────────────────
def summarize(model_name: str, results: list[dict]) -> dict:
    total     = len(results)
    fn_ok     = sum(r["fn_correct"]    for r in results)
    full_ok   = sum(r["fully_correct"] for r in results)
    avg_ms    = round(sum(r["elapsed_ms"] for r in results) / total) if total else 0

    # no_function 케이스 분리
    no_fn_cases = [r for r in results if r["expected_fn"] == "NO_FUNCTION"]
    fn_cases    = [r for r in results if r["expected_fn"] != "NO_FUNCTION"]

    fp = sum(r["predicted_fn"] != "NO_FUNCTION" for r in no_fn_cases)  # false positive
    fn_acc = sum(r["fully_correct"] for r in fn_cases) / len(fn_cases) * 100 if fn_cases else 0

    # 카테고리별 정확도
    categories: dict[str, list] = {}
    for r in results:
        categories.setdefault(r["category"], []).append(r["fully_correct"])
    cat_acc = {cat: round(sum(v)/len(v)*100, 1) for cat, v in categories.items()}

    print(f"\n{'='*60}")
    print(f"  모델: {model_name}")
    print(f"{'='*60}")
    print(f"  전체 정확도    : {full_ok}/{total} ({full_ok/total*100:.1f}%)")
    print(f"  함수명 정확도  : {fn_ok}/{total}  ({fn_ok/total*100:.1f}%)")
    print(f"  함수 케이스 acc: {fn_acc:.1f}%  ({len(fn_cases)}개)")
    print(f"  False Positive : {fp}/{len(no_fn_cases)}  ({fp/len(no_fn_cases)*100:.1f}%  ← 낮을수록 좋음)")
    print(f"  평균 응답 시간 : {avg_ms}ms")
    print(f"\n  카테고리별 정확도:")
    for cat, acc in sorted(cat_acc.items()):
        bar = "█" * int(acc // 5) + "░" * (20 - int(acc // 5))
        print(f"    {cat:<20} {bar} {acc:5.1f}%")
    print(f"{'='*60}")

    return {"fn_acc": fn_acc, "full_acc": full_ok/total*100, "fp_rate": fp/len(no_fn_cases)*100 if no_fn_cases else 0, "avg_ms": avg_ms}


# ── 오답 출력 ─────────────────────────────────────────────────────────────────
def print_errors(model_name: str, results: list[dict]):
    errors = [r for r in results if not r["fully_correct"]]
    if not errors:
        print(f"\n  {model_name}: 오답 없음 🎉")
        return
    print(f"\n  {model_name} 오답 목록 ({len(errors)}개):")
    for r in errors:
        exp = f"{r['expected_fn']}({r['expected_arg']})" if r['expected_arg'] else r['expected_fn']
        got = f"{r['predicted_fn']}({r['predicted_arg']})" if r['predicted_arg'] else r['predicted_fn']
        print(f"    입력: {r['input'][:45]:<45}")
        print(f"          기대: {exp}  /  실제: {got}")


# ── 비교 요약 ─────────────────────────────────────────────────────────────────
def print_comparison(base_stats: dict, tuned_stats: dict):
    print(f"\n{'='*60}")
    print("  파인튜닝 전후 비교")
    print(f"{'='*60}")
    metrics = [
        ("전체 정확도(%)",    "full_acc", True),
        ("함수 케이스 acc(%)", "fn_acc",  True),
        ("False Positive(%)", "fp_rate", False),  # 낮을수록 좋음
        ("평균 응답시간(ms)",  "avg_ms",  False),
    ]
    for label, key, higher_better in metrics:
        b, t = base_stats[key], tuned_stats[key]
        diff = t - b
        direction = "▲" if diff > 0 else ("▼" if diff < 0 else "─")
        good = (diff > 0) == higher_better
        mark = "✅" if good and diff != 0 else ("⚠️ " if not good and diff != 0 else "")
        print(f"  {label:<22}: {b:6.1f} → {t:6.1f}  {direction}{abs(diff):.1f}  {mark}")
    print(f"{'='*60}")


# ── 결과 JSON 저장 ─────────────────────────────────────────────────────────────
def save_results(base_results, tuned_results, base_stats, tuned_stats):
    out = {
        "base_model":  BASE_MODEL,
        "tuned_model": TUNED_MODEL,
        "base_stats":  base_stats,
        "tuned_stats": tuned_stats,
        "base_results":  base_results,
        "tuned_results": tuned_results,
    }
    path = os.path.join(os.path.dirname(__file__), "eval_results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  결과 저장됨: {path}")


# ── 메인 ──────────────────────────────────────────────────────────────────────
async def main():
    print(f"\n베이스 모델 평가 중: {BASE_MODEL}")
    print("-" * 60)
    base_results = await evaluate_model(BASE_MODEL)
    base_stats   = summarize(BASE_MODEL, base_results)
    print_errors(BASE_MODEL, base_results)

    print(f"\n파인튜닝 모델 평가 중: {TUNED_MODEL}")
    print("-" * 60)
    tuned_results = await evaluate_model(TUNED_MODEL)
    tuned_stats   = summarize(TUNED_MODEL, tuned_results)
    print_errors(TUNED_MODEL, tuned_results)

    print_comparison(base_stats, tuned_stats)
    save_results(base_results, tuned_results, base_stats, tuned_stats)


if __name__ == "__main__":
    asyncio.run(main())
