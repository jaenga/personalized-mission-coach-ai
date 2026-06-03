from __future__ import annotations

from dataclasses import dataclass
import re

from starlette.concurrency import run_in_threadpool

from database import _kst_today, get_student_mission_db
from equivalency_judgment import EquivalencyJudgment
from equivalency_metadata_matcher import apply_metadata_decision_override
from equivalency_numeric import compare_numeric_target
from equivalency_response_hint import attach_response_hint
from executor import ExecResults, execute_submit
from hint_builder import build_equivalency_judge_prompt
from ollama_client import judge_mission_equivalency
from pipeline import is_equivalency_submit
from submit_validator import SubmitValidationResult, validate_submit_candidate


FunctionCall = tuple[str, dict]


@dataclass
class EquivalencyResult:
    judgment: EquivalencyJudgment | None = None
    pending_submit_args: dict | None = None
    submit_validation: SubmitValidationResult | None = None

    @property
    def json_mode(self) -> bool:
        return self.pending_submit_args is not None and self.judgment is None


class EquivalencyService:
    """Runs the dedicated equivalency judge and applies deterministic guards."""

    async def resolve(
        self,
        *,
        student_id: int | None,
        fn_calls: list[FunctionCall],
        pending_submit_args: dict | None,
        user_message: str,
        session_id: str | None = None,
        mission_title: str,
        mission_id: int | None,
        exec_results: ExecResults,
    ) -> EquivalencyResult:
        result = EquivalencyResult(pending_submit_args=pending_submit_args)
        if not student_id:
            return result

        eq_submit = is_equivalency_submit(fn_calls) if fn_calls else False
        eq_standalone = bool(fn_calls) and any(
            fn == "check_mission_equivalency" for fn, _ in fn_calls
        ) and not eq_submit
        if not ((eq_submit and pending_submit_args) or eq_standalone):
            return result

        judge_args = next(
            (args for fn, args in fn_calls if fn == "check_mission_equivalency"),
            {},
        )
        judge_prompt = await run_in_threadpool(
            build_equivalency_judge_prompt,
            student_id,
            judge_args,
            user_message,
            session_id,
        )
        if not judge_prompt:
            return result

        judgment = await judge_mission_equivalency(judge_prompt, user_message)
        mission_for_override = await run_in_threadpool(
            get_student_mission_db,
            student_id,
            _kst_today(),
        )
        judgment = apply_metadata_decision_override(
            judgment,
            user_message,
            mission_for_override,
        )
        judgment = self._apply_split_completion_override(
            judgment,
            user_message,
            mission_for_override,
        )
        judgment = self._apply_duration_split_override(
            judgment,
            user_message,
            mission_for_override,
        )
        judgment = attach_response_hint(
            judgment,
            user_message,
            mission_for_override,
        )
        judgment = EquivalencyJudgment.from_mapping(judgment)

        submit_validation = None
        if eq_submit and self._is_approved(judgment):
            submit_validation = await run_in_threadpool(
                self.validate_and_execute_submit,
                student_id,
                pending_submit_args,
                user_message,
                mission_title,
                mission_id,
                exec_results,
            )
            if submit_validation and not submit_validation.should_execute:
                judgment = self._clarify_from_submit_validation(submit_validation)
        elif eq_standalone and self._is_approved(judgment) and self._looks_like_completed_equivalency_report(user_message):
            exec_results.submit = await run_in_threadpool(
                execute_submit,
                student_id,
                {"result_type": "success"},
            )
            print("[Equivalency] standalone approved report -> submit executed")

        return EquivalencyResult(
            judgment=judgment,
            pending_submit_args=None if eq_submit else pending_submit_args,
            submit_validation=submit_validation,
        )

    @staticmethod
    def validate_and_execute_submit(
        student_id: int,
        pending_submit_args: dict,
        user_message: str,
        mission_title: str,
        mission_id: int | None,
        exec_results: ExecResults,
    ) -> SubmitValidationResult:
        validation = validate_submit_candidate(
            user_message=user_message,
            mission_name=mission_title,
            mission_id=mission_id,
            qwen_args=pending_submit_args,
        )
        print(
            "[Validator.submit] "
            f"action={validation.action} "
            f"result={validation.result_type or '-'} "
            f"reason={validation.reason or '-'}"
        )
        if validation.should_execute:
            exec_results.submit = execute_submit(
                student_id,
                {**pending_submit_args, "result_type": validation.result_type},
            )
        return validation

    @staticmethod
    def _is_approved(judgment: EquivalencyJudgment) -> bool:
        return judgment.approved and not judgment.need_clarification

    @staticmethod
    def _looks_like_completed_equivalency_report(user_message: str) -> bool:
        text = (user_message or "").replace(" ", "")
        return bool(
            re.search(r"(했어|했어요|했음|했는데|했|올라갔|내려갔|걸었|먹었|마셨|봤|탔|이용했|끝냈|완료)", text)
            and re.search(r"(성공|인정|맞아|되는|돼|되나|되나요|괜찮)", text)
        )

    @staticmethod
    def _apply_split_completion_override(
        judgment: dict | None,
        user_message: str,
        mission: dict | None,
    ) -> dict | None:
        if not mission:
            return judgment

        metric = str(mission.get("target_metric") or "").strip()
        if metric not in {"reps", "count"}:
            return judgment

        compact = (user_message or "").replace(" ", "")
        if not any(marker in compact for marker in ("나눠서", "나누어서", "나눠", "나누어", "씩", "쉬었다가", "쉬고", "쉬었다", "쉬어")):
            return judgment

        numeric = compare_numeric_target(user_message, mission)
        if numeric.get("status") != "meets_target":
            return judgment

        updated = dict(judgment or {})
        updated.update(
            {
                "decision": "approved",
                "approved": True,
                "need_clarification": False,
                "reason": "목표 횟수는 충족했고, 여러 번 나눠서 수행한 것은 동일 미션의 분할 수행으로 인정 가능함.",
                "reply": "좋아, 한 번에 못 해도 나눠서 총 횟수를 채웠으면 인정돼! 😊",
                "clarify_question": None,
                "split_completion_override": {
                    "numeric_status": numeric.get("status"),
                    "user_value": numeric.get("user_value"),
                    "target_value": numeric.get("target_value"),
                    "target_unit": numeric.get("target_unit"),
                },
            }
        )
        return updated

    @staticmethod
    def _apply_duration_split_override(
        judgment: dict | None,
        user_message: str,
        mission: dict | None,
    ) -> dict | None:
        if not mission:
            return judgment
        if str(mission.get("target_metric") or "").strip() != "duration":
            return judgment

        compact = (user_message or "").replace(" ", "")
        if not any(marker in compact for marker in ("나눠서", "나누어서", "나눠", "나누어", "씩", "쉬었다가", "쉬고", "쉬었다", "쉬어")):
            return judgment

        numeric = compare_numeric_target(user_message, mission)
        if numeric.get("status") != "meets_target":
            return judgment

        updated = dict(judgment or {})
        updated.update(
            {
                "decision": "approved",
                "approved": True,
                "need_clarification": False,
                "reason": "나눠서 수행하더라도 총 수행 시간이 목표 시간을 충족하면 인정 가능함.",
                "reply": "좋아, 나눠서 해도 총 시간이 채워지면 인정돼! 😊",
                "clarify_question": None,
                "duration_split_override": {
                    "numeric_status": numeric.get("status"),
                    "user_value": numeric.get("user_value"),
                    "target_value": numeric.get("target_value"),
                    "target_unit": numeric.get("target_unit"),
                },
            }
        )
        return updated

    @staticmethod
    def _clarify_from_submit_validation(validation: SubmitValidationResult) -> EquivalencyJudgment:
        return EquivalencyJudgment(
            decision="clarify",
            reason=validation.reason,
            reply="조금만 더 알려줘야 정확히 볼 수 있어.",
            clarify_question="무엇을 얼마나 했는지 알려줄래?",
        )
