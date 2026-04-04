import json
from database import fetch_messages

# ── Ollama tool schema ────────────────────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "submit_mission_result",
            "description": (
                "미션 수행 결과를 보고할 때 호출합니다. "
                "사용자가 오늘 미션을 완료했는지, 일부만 했는지, 전혀 하지 못했는지를 말할 때 사용합니다. "
                "success: 다 했어요 / 완료했어요 / 오늘 미션 성공했어요 / 다 끝냈어요. "
                "partial: 반 정도 했어요 / 거의 다 했어요 / 조금 했어요 / 절반쯤 했어요. "
                "fail: 못 했어요 / 아예 안 했어요 / 오늘은 실패했어요 / 하나도 못 했어요. "
                "중요: 수행 결과가 명확히 표현되면 반드시 이 함수를 사용합니다. "
                "호출하면 안 되는 경우: 못 한 이유를 설명만 하는 경우 → request_mission_exception, "
                "다른 미션으로 바꿔달라는 경우 → request_mission_adjustment. "
                "헷갈리기 쉬운 차이: '비가 와서 못 했어요'는 결과 보고면 fail, 이유 설명이 중심이면 exception."
                "강제 규칙: '못 했다'가 결과 보고로 쓰이면 fail, 비·아픔·일정 같은 이유 설명이 중심이면 exception을 우선합니다."

            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "result_type": {
                        "type": "string",
                        "enum": ["success", "partial", "fail"],
                        "description": "success=완료, partial=일부 완료, fail=수행 실패",
                    }
                },
                "required": ["result_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mission_info",
            "description": (
                "미션 정보에 대해 질문할 때 호출합니다. "
                "오늘 해야 할 미션 내용(today), 제출 마감 시간(deadline), 미션 수행의 일반 규칙(general_rule)을 묻는 경우에 사용합니다. "
                "today: 오늘 미션 뭐예요? / 오늘 뭐 해야 돼요? / 오늘 할 일 알려주세요. "
                "deadline: 언제까지 제출해야 해요? / 몇 시까지예요? / 마감 시간이 언제예요? / 오늘 몇 시까지 해야 돼요? / 언제까지 내면 돼요? "
                "general_rule: 미션 규칙이 뭐예요? / 부분 수행도 인정되나요? / 꼭 다 해야 하나요? "
                "강제 규칙: '마감', '언제까지', '제출 시간'이 포함되면 deadline. 오늘 해야 할 내용 자체를 묻는 경우만 today. "
                "호출하면 안 되는 경우: 결과를 보고하는 경우 → submit_mission_result, 미션을 바꿔달라는 경우 → request_mission_adjustment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["today", "deadline", "general_rule"],
                        "description": "today=오늘의 미션, deadline=제출 마감, general_rule=일반 규칙",
                    }
                },
                "required": ["query_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_mission_adjustment",
            "description": (
                "미션을 변경하거나 난이도를 조정해달라고 요청할 때 호출합니다. "
                "사용자가 현재 미션 대신 다른 미션을 원하거나, 더 쉬운 미션 또는 더 어려운 미션을 원할 때 사용합니다. "
                "change: 다른 미션으로 바꿔주세요 / 이 미션 말고 다른 걸로 주세요 / 실내에서 할 수 있는 미션으로 바꿔주세요. "
                "easier: 좀 더 쉬운 걸로 해주세요 / 이건 너무 어려워요 / 더 쉽게 할 수 있는 걸로 해주세요. "
                "harder: 너무 쉬워요 / 더 어렵게 해주세요 / 난이도를 올려주세요. "
                "헷갈리기 쉬운 차이: '오늘 학원이 늦게 끝나요' → request_mission_exception, "
                "'오늘 학원이 늦게 끝나서 다른 미션으로 바꿔주세요' → request_mission_adjustment. "
                "호출하면 안 되는 경우: 수행이 어려운 사정만 설명 → request_mission_exception, "
                "대체 행동 인정 여부를 묻는 경우 → check_mission_equivalency."
                "강제 규칙: '바꿔주세요', '다른 걸로', '조정해 주세요', '쉽게', '어렵게' 같은 직접 요청 표현이 있으면 adjustment를 우선합니다."

            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "adjustment_type": {
                        "type": "string",
                        "enum": ["change", "easier", "harder"],
                        "description": "change=미션 변경, easier=난이도 하향, harder=난이도 상향",
                    }
                },
                "required": ["adjustment_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_mission_equivalency",
            "description": (
                "원래 미션 대신 다른 행동을 했을 때, 그것도 미션으로 인정되는지 물어볼 때 호출합니다. "
                "대체 행동, 장소, 시간 조건 변경이 원래 미션과 비슷한지 확인하려는 질문에 사용합니다. "
                "behavior: 줄넘기 대신 자전거 타면 인정돼요? / 스쿼트 대신 계단 오르기 했는데 괜찮아요? / 물 대신 우유 마셔도 되나요? "
                "location: 밖 말고 집에서 하면 인정돼요? / 운동장을 못 가서 집에서 해도 돼요? / 학원에서 하면 괜찮아요? "
                "time: 아침 대신 저녁에 하면 되나요? / 오늘 말고 내일 하면 안 돼요? / 지금 못 하고 나중에 하면 인정돼요? "
                "중요: 이미 다른 행동을 했거나 다른 방식으로 해도 되는지 '인정 여부'를 묻는 경우 equivalency. "
                "단순히 못 해서 바꿔달라는 건 adjustment. 오늘 미션 내용을 묻는 경우 → get_mission_info."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "equivalency_type": {
                        "type": "string",
                        "enum": ["behavior", "location", "time"],
                        "description": "behavior=행동/대상 변경, location=장소 변경, time=시간/조건 변경",
                    }
                },
                "required": ["equivalency_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_certification_info",
            "description": (
                "미션 완료 후 어떻게 인증하는지, 어디에 제출하는지 물어볼 때 호출합니다. "
                "method: 인증샷 어떻게 찍어요? / 어떻게 인증해요? / 사진으로 찍으면 되나요? / 영상도 되나요? "
                "location: 어디에 올려요? / 어디로 제출해요? / 인증은 어디서 해요? / 앱에서 어디 눌러요? "
                "중요: 인증 방법을 물으면 method, 제출 위치나 채널을 물으면 location."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "info_type": {
                        "type": "string",
                        "enum": ["method", "location"],
                        "description": "method=인증 방법, location=인증 위치/채널",
                    }
                },
                "required": ["info_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_submission_issue",
            "description": (
                "미션을 수행했음에도 정상적인 인증 절차를 밟지 못한 문제가 발생했을 때 호출합니다. "
                "제출 기한을 놓쳐 뒤늦게 보고하거나(late_submission), "
                "앱 오류나 네트워크 장애 등 기술적 결함(device_issue)으로 제출에 실패한 모든 상황입니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_type": {
                        "type": "string",
                        "enum": ["late_submission", "device_issue"],
                        "description": "late_submission=시간 지연, device_issue=시스템/기술 오류",
                    }
                },
                "required": ["issue_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_mission_exception",
            "description": (
                "미션을 수행하기 어려운 개인적인 사정이나 이유를 설명할 때 호출합니다. "
                "건강 문제, 일정 문제, 날씨나 장소 같은 환경 문제 때문에 미션 수행이 어렵다고 말하는 경우에 사용합니다. "
                "health: 독감 걸렸어요 / 다리가 아파요 / 몸이 안 좋아요 / 배가 아파서 못 하겠어요 / 다쳐서 운동 못 해요. "
                "schedule: 오늘 학원이 늦게 끝나요 / 오늘 일정이 너무 많아요 / 시간이 없어요 / 오늘 너무 바빠요. "
                "environment: 비가 와서 밖에 못 나가요 / 날씨가 너무 안 좋아요 / 미세먼지가 심해요 / 운동할 장소가 없어요. "
                "중요: '못 한다', '어렵다', '상황이 안 된다'처럼 수행 불가 이유를 설명하는 경우 exception. "
                "아직 미션을 바꿔달라고 직접 요청하지 않았다면 adjustment가 아니라 exception. "
                "헷갈리기 쉬운 차이: '비가 와서 밖에 못 나가요' → exception, '비가 와서 다른 미션으로 바꿔주세요' → adjustment. "
                "호출하면 안 되는 경우: 미션 변경 요청 → request_mission_adjustment, 결과 제출 → submit_mission_result, 날씨 자체 질문 → get_weather_info."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "exception_type": {
                        "type": "string",
                        "enum": ["health", "schedule", "environment"],
                        "description": "health=질병/부상, schedule=일정, environment=날씨/장소",
                    }
                },
                "required": ["exception_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "support_mission_help",
            "description": (
                "미션의 의미가 모호하거나, 구체적으로 어떻게 행동해야 할지 막막하여 도움을 요청할 때 호출합니다. "
                '"어떻게 하는 건지 모르겠어요", "이 말이 무슨 뜻이에요?", "좀 더 자세히 설명해 주세요" 등입니다.'
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_info",
            "description": (
                "야외 미션 수행이 가능한지 판단하기 위해 날씨나 예보를 물어볼 때 호출합니다. "
                '"오늘 비 와요?", "미세먼지 어때요?", "밖에서 운동해도 될 날씨인가요?" 등의 질문입니다.'
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_health_info",
            "description": (
                "운동, 식단, 수분 섭취 등 일반적인 건강 상식이나 생활 습관 관련 지식을 물어볼 때 호출합니다. "
                '"물은 얼마나 많이 마셔야 해요?", "운동 얼마나 해야 좋아요?" 등의 지식 질문입니다.'
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_type": {
                        "type": "string",
                        "enum": ["food", "water", "exercise", "sleep", "general"],
                        "description": "food=식단, water=수분, exercise=운동, sleep=수면, general=일반 건강 상식",
                    }
                },
                "required": ["topic_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_history",
            "description": (
                "본인의 과거 미션 기록이나 누적 활동을 확인하고 싶을 때 호출합니다. "
                "recent_history: 최근 기록 보여줘 / 내가 최근에 뭘 했어요? / 최근 활동 알려줘. "
                "weekly_summary: 이번 주 활동 요약해줘 / 이번 주 기록 보여줘 / 이번 주 얼마나 했어요? "
                "monthly_summary: 이번 달 기록 보여줘 / 월간 요약해줘 / 이번 달 활동 알려줘. "
                "success_count: 지금까지 몇 번 성공했어요? / 총 성공 횟수가 몇 번이에요? / 내가 몇 번 성공했는지 알려줘. "
                "중요: 과거 기록, 누적 통계, 요약, 성공 횟수는 전부 history 계열입니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["recent_history", "weekly_summary", "monthly_summary", "success_count"],
                        "description": "recent_history=최근 기록, weekly_summary=주간 요약, monthly_summary=월간 요약, success_count=총 성공 횟수",
                    }
                },
                "required": ["query_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_mission_action",
            "description": (
                "사용자가 이전에 요청하거나 수행한 행동을 취소하고 싶을 때 호출합니다. "
                "결과 제출 취소(submit), 미션 변경/조정 취소(adjustment), 예외 신청 철회(exception) 시 사용합니다. "
                '"방금 제출한 거 취소할게요", "미션 바꾸는 거 취소해주세요", "예외 신청 취소할게요" 등입니다.'
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": ["submit", "adjustment", "exception"],
                        "description": "submit=결과 제출 취소, adjustment=미션 변경/조정 취소, exception=예외 신청 취소",
                    }
                },
                "required": ["action_type"],
            },
        },
    },
]


# ── Tool 실행기 ───────────────────────────────────────────────────────────────
# 각 함수는 실제 데이터를 context에서 꺼내거나 DB에서 조회해서 반환.
# get_weather_info는 외부 API 연동 전까지 플레이스홀더를 반환.

def execute_tool(name: str, arguments: dict, context: dict) -> str:
    """
    tool name + arguments + context를 받아 함수를 실행하고 결과를 JSON 문자열로 반환.

    context keys:
        mission    : dict  (id, title, description)
        session_id : str
    Side-effects:
        submit_mission_result 호출 시 context["submitted_result"] 에 결과 기록
        cancel_mission_action 호출 시 context["cancelled_action"] 에 기록
    """
    # 미션 결과 저장
    if name == "submit_mission_result":
        result_type = arguments.get("result_type", "success")
        label = {"success": "완료", "partial": "일부 완료", "fail": "수행 실패"}.get(result_type, result_type)
        context["submitted_result"] = {"result_type": result_type}
        return json.dumps({"status": "ok", "result_type": result_type, "label": label}, ensure_ascii=False)

    # 미션 정보 조회 (마감, 규칙)
    if name == "get_mission_info":
        mission = context.get("mission", {})
        query_type = arguments.get("query_type", "today")
        # today은 미션 제목과 설명
        if query_type == "today":
            return json.dumps(
                {"title": mission.get("title"), "description": mission.get("description")},
                ensure_ascii=False,
            )
        # deadline은 고정된 마감 시간 (일단 11시로 해둠)
        if query_type == "deadline":
            return json.dumps({"deadline": "오늘 오후 11시 00분"}, ensure_ascii=False)
        # general_rule은 미션 수행의 일반적인 규칙 (하루 1회, 부분 수행 허용 등)
        if query_type == "general_rule":
            return json.dumps(
                {"rule": "미션은 하루 1회 수행하며, 부분 수행도 partial로 제출할 수 있습니다."},
                ensure_ascii=False,
            )

    # 미션 조정 요청 (아직 실제로 바꿔주지는 못함)
    if name == "request_mission_adjustment":
        adjustment_type = arguments.get("adjustment_type")
        label = {"change": "미션 변경", "easier": "난이도 하향", "harder": "난이도 상향"}.get(adjustment_type, adjustment_type)
        return json.dumps({"status": "received", "adjustment_type": adjustment_type, "label": label}, ensure_ascii=False)

    # 미션 대체 인정 여부 확인
    if name == "check_mission_equivalency":
        equivalency_type = arguments.get("equivalency_type")
        return json.dumps(
            {"equivalency_type": equivalency_type, "eligible": True, "note": "담당 선생님이 최종 인정 여부를 확인합니다."},
            ensure_ascii=False,
        )

    # 인증 방법/위치 안내
    if name == "check_certification_info":
        info_type = arguments.get("info_type")
        if info_type == "method":
            return json.dumps({"method": "미션 수행 사진 또는 영상을 촬영하여 제출합니다."}, ensure_ascii=False)
        if info_type == "location":
            return json.dumps({"location": "앱 내 '인증하기' 버튼을 통해 제출합니다."}, ensure_ascii=False)

    # 제출 문제 보고 (시간 지연, 시스템 오류 등)
    if name == "report_submission_issue":
        issue_type = arguments.get("issue_type")
        label = {"late_submission": "시간 지연 제출", "device_issue": "기기/시스템 오류"}.get(issue_type, issue_type)
        return json.dumps({"status": "received", "issue_type": issue_type, "label": label}, ensure_ascii=False)

    # 미션 수행 예외 신청 (건강 문제, 일정, 날씨 등)
    if name == "request_mission_exception":
        exception_type = arguments.get("exception_type")
        label = {"health": "질병/부상", "schedule": "일정", "environment": "날씨/장소"}.get(exception_type, exception_type)
        return json.dumps({"status": "received", "exception_type": exception_type, "label": label}, ensure_ascii=False)

    # 미션 도움 요청 (미션 어떻게 하는지 모를 때)
    if name == "support_mission_help":
        mission = context.get("mission", {})
        return json.dumps(
            {"title": mission.get("title"), "description": mission.get("description"), "hint": "미션을 단계별로 나눠서 조금씩 도전해 보세요!"},
            ensure_ascii=False,
        )

    # 날씨 정보 조회 (외부 API 연동 전)
    if name == "get_weather_info":
        return json.dumps({"note": "날씨 정보를 불러오려면 외부 API 연동이 필요합니다."}, ensure_ascii=False)

    # 건강 정보 조회 (RAG 구현 필요함)
    if name == "get_health_info":
        topic_type = arguments.get("topic_type", "general")
        tips = {
            "food": "운동 전후 가벼운 탄수화물과 단백질을 섭취하면 좋습니다.",
            "water": "하루 8잔(약 2L) 이상의 물을 마시는 것이 권장됩니다.",
            "exercise": "초등학생은 하루 60분 이상의 중강도 신체 활동이 권장됩니다.",
            "sleep": "초등학생은 하루 9~11시간의 수면이 권장됩니다.",
            "general": "규칙적인 생활 습관이 건강의 기본입니다.",
        }
        return json.dumps({"topic_type": topic_type, "tip": tips.get(topic_type, tips["general"])}, ensure_ascii=False)

    # 사용자 활동 기록 조회 (DB에서 메시지 기록을 가져와서 간단히 요약해서 반환)
    if name == "get_user_history":
        session_id = context.get("session_id", "")
        messages = fetch_messages(session_id)
        query_type = arguments.get("query_type", "recent_history")
        recent = messages[-10:]
        return json.dumps(
            {"query_type": query_type, "total_messages": len(messages), "recent_sample": len(recent)},
            ensure_ascii=False,
        )

    # 미션 관련 행동 취소 (결과 제출, 미션 조정, 예외 신청 등)
    if name == "cancel_mission_action":
        action_type = arguments.get("action_type")
        label = {"submit": "결과 제출 취소", "adjustment": "미션 변경/조정 취소", "exception": "예외 신청 취소"}.get(action_type, action_type)
        context["cancelled_action"] = {"action_type": action_type}
        return json.dumps({"status": "cancelled", "action_type": action_type, "label": label}, ensure_ascii=False)

    return json.dumps({"error": f"알 수 없는 함수: {name}"}, ensure_ascii=False)
