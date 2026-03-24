"""
프롬프트 실험을 위한 모듈.
SYSTEM_PROMPT와 build_user_prompt만 수정하면 다양한 버전을 빠르게 비교할 수 있습니다.
"""

SYSTEM_PROMPT = """
너는 초등학생을 위한 생활습관 AI 코치야.
아이가 오늘 미션을 했는지, 못 했는지, 조금 했는지 이야기하면 짧고 따뜻하게 반응해 줘.

중요 규칙:
- 쉬운 말로, 짧게 2~3문장만 말하기
- 절대 혼내지 않기
- 아이의 말을 먼저 인정하고 공감하기
- 마지막에는 다음에 해볼 수 있는 아주 작은 행동 1개만 제안하기
- 사용자가 말하지 않은 사람(엄마, 아빠, 가족, 친구, 선생님 등)을 절대 언급하지 않기
- 사용자가 말하지 않은 감정 원인이나 상황을 추측해서 지어내지 않기
- 죄책감, 비교, 훈계, 압박, 과한 위로를 하지 않기
- 의학적 진단, 건강 정보 설명, 어른스러운 표현 사용하지 않기
- 반항적이거나 짧은 입력에도 차분하고 담백하게 반응하기
- 답변은 자연스럽고 간단하게 하기
- 이모지는 0~1개만 사용하기

추가 규칙:
- 뜻을 잘 모르겠는 말이면 추측하지 말고, 잘 모르겠다고 짧게 말하거나 다시 짧게 말해달라고 하기
- 병원, 금식, 아픔, 다침 같은 말이 나오면 미션 독려보다 상황 존중과 안전을 먼저 말하기
- 죽고 싶다, 너무 멍청하다, 너무 싫다 같은 위험하거나 자기비하가 심한 말이 나오면 미션 독려보다 먼저 위로하고 가까운 어른에게 말해보자고 하기
- 버튼 결과와 아이의 말이 서로 다르면 한쪽을 단정하지 말고 헷갈릴 수 있다고 부드럽게 반응하기
- 제안은 입력에 맞게 자연스럽게 바꾸고, 같은 표현을 반복하지 않기

답변 형식:
1. 공감 또는 인정 1문장
2. 짧은 피드백 1문장
3. 필요할 때만 작은 행동 1문장
""".strip()


RESULT_LABELS = {
    "success": "성공",
    "partial": "부분 성공",
    "failure": "실패",
}


def detect_reason_type(reason: str | None) -> str:
    if not reason:
        return "unknown"

    text = reason.strip()

    crisis_keywords = [
        "죽고", "죽어야", "사라지고", "없어지고 싶", "멍청", "바보", "게으르", "최악", "싫어 죽겠"
    ]
    medical_keywords = [
        "병원", "금식", "아파", "아픔", "머리 아파", "배 아파", "어지러", "다쳤", "약"
    ]
    resistance_keywords = [
        "왜 해야", "왜 해", "하기 싫", "싫어", "안 할", "못 하겠", "귀찮",
        "너가 해", "네가 해", "해주는 것도 없"
    ]
    difficulty_keywords = ["어려", "힘들", "많아", "부담", "너무 많"]
    forget_keywords = ["까먹", "잊", "깜빡"]
    time_keywords = ["시간", "바빠", "학원", "숙제", "늦어", "밖에"]
    partial_keywords = ["조금", "반만", "절반", "다 못", "일부", "좀 했", "거의"]
    vague_inputs = [
        "몰라", "음", "흠", "그냥", "야르", "응", "싫", "음...", "..."
    ]

    lowered = text.lower()

    if any(k in text for k in crisis_keywords):
        return "crisis"
    if any(k in text for k in medical_keywords):
        return "medical"
    if any(k in text for k in resistance_keywords):
        return "resistance"
    if any(k in text for k in difficulty_keywords):
        return "difficulty"
    if any(k in text for k in forget_keywords):
        return "forget"
    if any(k in text for k in time_keywords):
        return "time"
    if any(k in text for k in partial_keywords):
        return "partial_reason"
    if text in vague_inputs or len(text) <= 2 or lowered in {"ㅇㅇ", "ㄴㄴ", "ㅅㅂ"}:
        return "vague"
    return "general"


def detect_mismatch(result: str, reason: str | None) -> bool:
    if not reason:
        return False

    text = reason.strip()
    success_signals = ["성공", "다 했", "완료", "해냈", "끝냈"]
    failure_signals = ["못 했", "실패", "안 했", "하기 싫", "까먹", "귀찮"]

    if result == "failure" and any(k in text for k in success_signals):
        return True
    if result == "success" and any(k in text for k in failure_signals):
        return True
    return False


def build_user_prompt(mission: str, result: str, reason: str | None) -> str:
    label = RESULT_LABELS.get(result, result)
    reason_text = reason.strip() if reason else ""
    reason_type = detect_reason_type(reason)
    is_mismatch = detect_mismatch(result, reason)

    if result == "success" and not is_mismatch:
        return (
            f"오늘 미션은 '{mission}'이었어. 결과는 {label}야.\n"
            "아이에게 짧고 자연스럽게 칭찬해 줘.\n"
            "똑같은 표현을 반복하지 말고 2~3문장만 써 줘."
        )

    if is_mismatch:
        return (
            f"오늘 미션은 '{mission}'이었어. 버튼 결과는 {label}야.\n"
            f"그런데 아이는 이렇게 말했어: \"{reason_text}\"\n"
            "버튼 결과와 말이 서로 조금 달라 보여. 한쪽을 단정하지 말고, 헷갈릴 수 있다고 부드럽게 반응해 줘.\n"
            "짧게 다시 확인하거나 아주 중립적인 작은 제안만 해 줘.\n"
            "출력은 2~3문장만 해 줘."
        )

    if reason_type == "crisis":
        return (
            f"오늘 미션은 '{mission}'이었어. 결과는 {label}야.\n"
            f"아이가 이렇게 말했어: \"{reason_text}\"\n"
            "이 입력은 자기비하나 위험 신호가 섞여 있어.\n"
            "미션 독려보다 먼저 아이를 진정시키고, 혼자 참지 말고 가까운 어른에게 이야기해보자고 말해 줘.\n"
            "절대 무겁게 판단하거나 긴 설명을 하지 말고, 따뜻하고 짧게 2~3문장으로 답해 줘."
        )

    if reason_type == "medical":
        return (
            f"오늘 미션은 '{mission}'이었어. 결과는 {label}야.\n"
            f"아이가 이렇게 말했어: \"{reason_text}\"\n"
            "이 입력에는 병원, 금식, 아픔 같은 예외 상황이 있어.\n"
            "미션을 계속 하라고 밀지 말고, 오늘은 상황을 먼저 따르는 게 괜찮다고 말해 줘.\n"
            "안전과 상황 존중을 먼저 말하고, 무리 없는 짧은 답으로 2~3문장만 써 줘."
        )

    if reason_type == "resistance":
        return (
            f"오늘 미션은 '{mission}'이었어. 결과는 {label}야.\n"
            f"아이가 이렇게 말했어: \"{reason_text}\"\n"
            "이 입력은 실패 이유 설명이라기보다 하기 싫음, 반항, 저항이 섞인 말이야.\n"
            "절대 가족이나 다른 사람을 언급하지 말고, 감정 원인을 추측하지 마.\n"
            "짧게 '그럴 수 있어'라고 인정한 뒤, 부담 없는 아주 작은 선택지 1개만 제안해 줘.\n"
            "출력은 2~3문장만 해 줘."
        )

    if reason_type == "vague":
        return (
            f"오늘 미션은 '{mission}'이었어. 결과는 {label}야.\n"
            f"아이가 이렇게 말했어: \"{reason_text}\"\n"
            "이 말은 뜻이 불분명하거나 너무 짧아.\n"
            "추측하지 말고 잘 모르겠다고 짧게 말하거나, 다시 짧게 말해달라고 해 줘.\n"
            "필요하면 아주 안전한 작은 행동 1개만 덧붙여도 돼.\n"
            "출력은 2~3문장만 해 줘."
        )

    if not reason_text:
        return (
            f"오늘 미션은 '{mission}'이었어. 결과는 {label}야.\n"
            "아이는 자세한 이유를 말하지 않았어.\n"
            "이유를 추측하지 말고, 짧게 공감한 뒤 다음에 해볼 작은 행동 1개만 제안해 줘.\n"
            "출력은 2~3문장만 해 줘."
        )

    return (
        f"오늘 미션은 '{mission}'이었어. 결과는 {label}야.\n"
        f"아이가 말한 이유: \"{reason_text}\"\n"
        f"이 이유 유형은 '{reason_type}'이야.\n"
        "아이의 말만 바탕으로 짧게 공감하고, 부담 없는 작은 행동 1개만 제안해 줘.\n"
        "사용자가 말하지 않은 사람이나 상황은 언급하지 마.\n"
        "같은 제안을 반복하지 말고, 입력에 맞게 자연스럽게 답해 줘.\n"
        "출력은 2~3문장만 해 줘."
    )