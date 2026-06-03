from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from qwen_client import (
    detect_history_call,
    detect_mission_info_call,
    detect_mission_adjustment_call,
    detect_strong_equivalency_call,
    detect_submit_report_call,
    detect_weak_equivalency_call,
)


FunctionCall = tuple[str, dict]
Detector = Callable[[str], FunctionCall | None]
_PAST_RESULT_TIME_RE = re.compile(r"어제|그저께|엊그제|지난번|저번|예전|수요일|월요일|화요일|목요일|금요일|토요일|일요일")
_RESULT_HINT_RE = re.compile(r"성공|실패|했|먹|마셨|봤|봄|안\s*먹|안\s*봤|바꿔|변경")


@dataclass(frozen=True)
class RouteDecision:
    intent: str
    fn_calls: list[FunctionCall]
    detected_function: str | None
    fn_args: dict
    log_message: str


@dataclass(frozen=True)
class RouteRule:
    name: str
    detector: Detector
    log_message: str


class MissionRouter:
    """Deterministic route overrides before the LLM function caller.

    Order is intentionally configurable here because small priority changes
    have a large behavior impact for equivalency vs submit-report utterances.
    """

    def __init__(self, rules: list[RouteRule] | None = None) -> None:
        self.rules = rules or [
            RouteRule(
                "strong_equivalency",
                detect_strong_equivalency_call,
                "[Route] strong equivalency forced to check_mission_equivalency",
            ),
            RouteRule(
                "submit_report",
                detect_submit_report_call,
                "[Route] submit report forced to submit_mission_result",
            ),
            RouteRule(
                "history",
                detect_history_call,
                "[Route] history query forced to get_user_history",
            ),
            RouteRule(
                "mission_info",
                detect_mission_info_call,
                "[Route] mission info query forced to get_mission_info",
            ),
            RouteRule(
                "mission_adjustment",
                detect_mission_adjustment_call,
                "[Route] mission adjustment forced to request_mission_adjustment",
            ),
            RouteRule(
                "weak_equivalency",
                detect_weak_equivalency_call,
                "[Route] weak equivalency forced to check_mission_equivalency (fallback)",
            ),
        ]
        self.pre_intent_rules = [
            RouteRule(
                "history",
                detect_history_call,
                "[Route] pre-intent history forced to get_user_history",
            ),
            RouteRule(
                "mission_info",
                detect_mission_info_call,
                "[Route] pre-intent mission info forced to get_mission_info",
            ),
            RouteRule(
                "mission_adjustment",
                detect_mission_adjustment_call,
                "[Route] pre-intent mission adjustment forced to request_mission_adjustment",
            ),
        ]

    def decide_before_intent(self, user_message: str) -> RouteDecision | None:
        if _PAST_RESULT_TIME_RE.search(user_message or "") and _RESULT_HINT_RE.search(user_message or ""):
            return None

        for rule in self.pre_intent_rules:
            call = rule.detector(user_message)
            if not call:
                continue

            fn, args = call
            return RouteDecision(
                intent="B",
                fn_calls=[call],
                detected_function=fn,
                fn_args=args,
                log_message=rule.log_message,
            )

        return None

    def decide(self, user_message: str, existing_calls: list[FunctionCall] | None = None) -> RouteDecision | None:
        if existing_calls:
            return None
        history_call = detect_history_call(user_message)
        if history_call:
            fn, args = history_call
            return RouteDecision(
                intent="B",
                fn_calls=[history_call],
                detected_function=fn,
                fn_args=args,
                log_message="[Route] history query forced to get_user_history",
            )
        if _PAST_RESULT_TIME_RE.search(user_message or "") and _RESULT_HINT_RE.search(user_message or ""):
            return None

        for rule in self.rules:
            call = rule.detector(user_message)
            if not call:
                continue

            fn, args = call
            return RouteDecision(
                intent="B",
                fn_calls=[call],
                detected_function=fn,
                fn_args=args,
                log_message=rule.log_message,
            )

        return None
