import requests
import csv
import json
import time

URL = "http://127.0.0.1:8000/chat"
SESSION_ID = "test-session-001"

TEST_CASES = [
    # submit_mission_result
    (1,  "오늘 목표 다 채워서 제출하려고요", "submit_mission_result", {"result_type": "success"}),
    (2,  "오늘 미션 완전 성공입니다. 오늘 할당량 다 채웠어요!", "submit_mission_result", {"result_type": "success"}),
    (3,  "오늘 미션 조금 하긴 했는데 다 못 했어요", "submit_mission_result", {"result_type": "partial"}),
    (4,  "거의 못 하고 조금만 했어요", "submit_mission_result", {"result_type": "partial"}),
    (5,  "오늘 수행 하나도 못 했네요..", "submit_mission_result", {"result_type": "fail"}),
    (6,  "오늘 미션 실패했어요..죄송합니다..", "submit_mission_result", {"result_type": "fail"}),

    # get_mission_info
    (7,  "오늘 해야 할 미션 뭐로 나왔어요?", "get_mission_info", {"query_type": "today"}),
    (8,  "지금 진행해야 하는 미션 내용 알려줘요", "get_mission_info", {"query_type": "today"}),
    (9,  "미션 제출 기한이 몇 시까지죠?", "get_mission_info", {"query_type": "deadline"}),
    (10, "이거 오늘 몇 시 전에 끝내야 해요?", "get_mission_info", {"query_type": "deadline"}),
    (11, "미션 진행 방식 자세히 설명해 주세요", "get_mission_info", {"query_type": "general_rule"}),

    # request_mission_adjustment
    (12, "미션 난이도가 너무 높아서 그런데 쉽게해주실 수 있나요?", "request_mission_adjustment", {"adjustment_type": "easier"}),
    (13, "미션 조금 더 빡센 걸로 바꿔보고 싶어요 ㅋㅋ", "request_mission_adjustment", {"adjustment_type": "harder"}),
    (14, "저 아까 넘어져서 다리 다쳐서 그런데 혹시 몸 안 쓰는 미션으로 바꿔줄 수 있나요?", "request_mission_adjustment", {"adjustment_type": "change"}),

    # check_mission_equivalency
    (15, "걷기 대신 계단 오르기로 해도 인정되나요?", "check_mission_equivalency", {"equivalency_type": "behavior"}),
    (16, "운동장 말고 실내 체육관에서 해도 괜찮나요?", "check_mission_equivalency", {"equivalency_type": "location"}),
    (17, "정해진 시간 지나서 해도 인정돼요?", "check_mission_equivalency", {"equivalency_type": "time"}),

    # check_certification_info
    (18, "인증은 어떤 방식으로 남기면 되죠?", "check_certification_info", {"info_type": "method"}),
    (19, "미션 성공 결과 업로드는 어디에서 해요?", "check_certification_info", {"info_type": "location"}),

    # request_mission_exception
    (20, "몸살 기운 있어서 오늘 수행 어려울 것 같아요", "request_mission_exception", {"exception_type": "health"}),
    (21, "오늘 학원 일정이 꽉 차 있어서 시간이 안 나요", "request_mission_exception", {"exception_type": "schedule"}),
    (22, "날씨가 너무 안 좋아서 밖에서 못 하겠어요..", "request_mission_exception", {"exception_type": "environment"}),

    # report_submission_issue
    (23, "제출하려고 했는데 시간이 지나버렸어요.. 지금이라도 낼 수 있나요?", "report_submission_issue", {"issue_type": "late_submission"}),
    (24, "앱 오류 때문에 업로드가 안 됐습니다", "report_submission_issue", {"issue_type": "device_issue"}),

    # support_mission_help
    (25, "이 미션 수행 방법을 잘 모르겠어요", "support_mission_help", {}),

    # get_weather_info
    (26, "오늘 야외 활동하기 괜찮은 날씨인가요?", "get_weather_info", {}),

    # get_health_info
    (27, "운동할 때 수분 섭취는 얼마나 해야 하나요?", "get_health_info", {"topic_type": "water"}),

    # get_user_history
    (28, "최근에 내가 어떤 미션 했는지 확인하고 싶어요", "get_user_history", {"query_type": "recent_history"}),

    # cancel_mission_action
    (29, "방금 한 제출 취소하고 다시 하고 싶어요", "cancel_mission_action", {"action_type": "submit"}),

    # no_function
    (30, "오늘 하루 너무 힘들었어요", "no_function", {}),
    (31, "지금 기분이 별로예요", "no_function", {}),
]


def extract_tool_info(data: dict) -> tuple:
    """
    응답에서 첫 번째 tool 이름과 arguments를 추출.
    - tool_called / tool_called_list 두 필드 모두 확인
    - {"name": ..., "arguments": ...} 또는
      {"function": {"name": ..., "arguments": ...}} 구조 모두 대응
    - arguments가 문자열이면 json.loads() 처리
    """
    raw_list = data.get("tool_called") or data.get("tool_called_list")

    if not raw_list:
        return None, {}

    first = raw_list[0]

    # 구조 파싱: flat 또는 function-wrapped
    if "function" in first:
        fn_name = first["function"].get("name")
        fn_args = first["function"].get("arguments", {})
    else:
        fn_name = first.get("name")
        fn_args = first.get("arguments", {})

    # arguments가 문자열로 올 경우 dict로 변환
    if isinstance(fn_args, str):
        try:
            fn_args = json.loads(fn_args)
        except json.JSONDecodeError:
            fn_args = {}
    if fn_args is None:
        fn_args = {}

    return fn_name, fn_args


def judge(expected_fn, expected_args, actual_fn, actual_args):
    """
    정답 판정.
    - expected가 no_function → actual_fn이 None이면 통과
    - 그 외 → 함수명 + arguments 값 모두 일치해야 통과
    """
    if expected_fn == "no_function":
        return "✅" if actual_fn is None else "❌"

    if actual_fn != expected_fn:
        return "❌"

    args_match = all(actual_args.get(k) == v for k, v in expected_args.items())
    return "✅" if args_match else "❌"


def run_test(test_id, input_text, expected_fn, expected_args):
    try:
        resp = requests.post(
            URL,
            json={"message": input_text, "session_id": SESSION_ID},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {
            "test_id": test_id,
            "input_text": input_text,
            "expected_function": expected_fn,
            "expected_arguments": json.dumps(expected_args, ensure_ascii=False),
            "actual_function": "ERROR",
            "actual_arguments": str(e),
            "actual_tool_calls_raw": "",
            "final_response": "",
            "pass": "ERROR",
        }

    actual_fn, actual_args = extract_tool_info(data)
    verdict = judge(expected_fn, expected_args, actual_fn, actual_args)

    return {
        "test_id": test_id,
        "input_text": input_text,
        "expected_function": expected_fn,
        "expected_arguments": json.dumps(expected_args, ensure_ascii=False),
        "actual_function": actual_fn or "None",
        "actual_arguments": json.dumps(actual_args, ensure_ascii=False),
        "actual_tool_calls_raw": json.dumps(
            data.get("tool_called") or data.get("tool_called_list"),
            ensure_ascii=False
        ),
        "final_response": data.get("response", "")[:80],
        "pass": verdict,
    }


def main():
    results = []

    print(f"\n{'='*100}")
    print(f"{'#':<4} {'':4} {'INPUT':<24} {'EXPECTED':<32} {'ACTUAL'}")
    print(f"{'='*100}")

    for test_id, input_text, expected_fn, expected_args in TEST_CASES:
        result = run_test(test_id, input_text, expected_fn, expected_args)
        results.append(result)

        print(
            f"[{result['pass']}] #{result['test_id']:02d} | "
            f"{result['input_text'][:22]:<22} | "
            f"{result['expected_function']:<32} | "
            f"{result['actual_function']}"
        )
        time.sleep(0.3)

    # 요약
    total  = len(results)
    passed = sum(1 for r in results if r["pass"] == "✅")
    errors = sum(1 for r in results if r["pass"] == "ERROR")
    print(f"\n{'='*100}")
    print(f"통과: {passed}/{total}  ({passed/total*100:.1f}%)  |  오류: {errors}건")
    print(f"※ 현재 판정은 단일 함수 호출 기준 (멀티 함수 테스트는 별도 스크립트 필요)")
    print(f"{'='*100}")

    # CSV 저장
    csv_path = "function_calling_test_result.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"\nCSV 저장 완료: {csv_path}")


if __name__ == "__main__":
    main()
