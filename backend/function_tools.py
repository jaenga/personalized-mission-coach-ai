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
                "완료(success), 일부(partial), 실패(fail)를 구분합니다."
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
                "미션 정보를 물어볼 때 호출합니다. "
                "오늘 미션(today), 마감(deadline), 일반 규칙(general_rule)을 구분합니다."
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
                "미션 변경이나 난이도 조정을 요청할 때 호출합니다. "
                "변경(change), 쉽게(easier), 어렵게(harder)를 구분합니다."
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
                "원래 미션 대신 다른 방식이 인정되는지 확인할 때 호출합니다. "
                "행동(behavior), 장소(location), 시간(time) 변경을 구분합니다."
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
                "미션 인증 방법이나 제출 위치를 물어볼 때 호출합니다. "
                "방법(method)과 위치(location)를 구분합니다."
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
                "미션 제출 과정에서 문제가 생겼을 때 호출합니다. "
                "지연 제출(late_submission)과 기기/시스템 문제(device_issue)를 구분합니다."
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
                "미션 수행이 어려운 사정을 설명할 때 호출합니다. "
                "건강(health), 일정(schedule), 환경(environment) 사유를 구분합니다."
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
                "미션의 의미나 수행 방법이 헷갈려 도움을 요청할 때 호출합니다."
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
                "날씨나 예보를 물어볼 때 호출합니다. "
                "야외 미션 가능 여부를 확인하는 질문에 사용합니다."
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
                "건강 상식이나 생활 습관 관련 지식을 물어볼 때 호출합니다. "
                "식단, 수분, 운동, 수면, 일반 건강 주제를 다룹니다."
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
                "사용자의 과거 미션 기록이나 누적 활동을 조회할 때 호출합니다. "
                "최근, 주간, 월간, 성공 횟수 조회를 구분합니다."
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
                "이전에 한 미션 관련 행동을 취소할 때 호출합니다. "
                "제출(submit), 조정(adjustment), 예외(exception) 취소를 구분합니다."
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
