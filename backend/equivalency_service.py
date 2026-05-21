from __future__ import annotations

from dataclasses import dataclass
import re

from starlette.concurrency import run_in_threadpool

from database import _kst_today, get_student_mission_db
from equivalency_judgment import EquivalencyJudgment
from equivalency_metadata_matcher import apply_metadata_decision_override
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
    def _clarify_from_submit_validation(validation: SubmitValidationResult) -> EquivalencyJudgment:
        return EquivalencyJudgment(
            decision="clarify",
            reason=validation.reason,
            reply="조금만 더 알려줘야 정확히 볼 수 있어.",
            clarify_question="무엇을 얼마나 했는지 알려줄래?",
        )
