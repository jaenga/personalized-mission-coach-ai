HEALTH_RISK_KEYWORDS = [
    "아파",
    "아프",
    "통증",
    "배아",
    "머리아",
    "열나",
    "열이",
    "약",
    "약먹",
    "약 먹",
    "병",
    "병원",
    "치료",
    "주사",
    "어지러",
    "어지럽",
    "토",
    "토했",
    "토할",
    "구토",
    "피",
    "출혈",
    "피나",
    "피가",
    "죽",
    "죽고",
    "죽을",
    "죽을 것",
    "굶",
    "굶어",
    "굶기",
    "다이어트",
    "살빼",
    "살 빼",
    "살빠",
    "살 빠",
]

SAFETY_SUFFIX = "이건 내가 정확하게 판단하기 어려운 부분이야. 아프거나 불편하면 가까운 어른이나 병원에 꼭 말해줘."


def detect_health_risk_signal(message: str) -> dict:
    text = (message or "").strip().lower()
    matched_keywords = [keyword for keyword in HEALTH_RISK_KEYWORDS if keyword in text]

    if not matched_keywords:
        return {
            "has_risk": False,
            "matched_keywords": [],
            "risk_level": "none",
        }

    return {
        "has_risk": True,
        "matched_keywords": matched_keywords,
        "risk_level": "caution",
    }


def append_health_safety_suffix(response: str, risk_signal: dict, intent: str) -> str:
    if not response:
        response = ""

    if not risk_signal.get("has_risk"):
        return response

    if intent != "C":
        return response

    if SAFETY_SUFFIX in response:
        return response

    if "정확하게 판단하기 어려운" in response and "가까운 어른" in response and "병원" in response:
        return response

    return response.rstrip() + "\n\n" + SAFETY_SUFFIX
