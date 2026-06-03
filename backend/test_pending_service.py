import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from executor import SubmitResult, SubmitStatus
from mission_meta import MISSION_META
from pending_service import (
    _direct_pending_decision,
    _handle_equivalency_clarify_confirmation,
    _prohibit_confirmation_message,
    classify_pending_reply,
)
from submit_validator import validate_submit_candidate


class PendingServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_casual_positive_replies_are_yes(self):
        for message in ("네", "넹", "ㅇㅇ", "넵"):
            with self.subTest(message=message):
                self.assertEqual(
                    await classify_pending_reply(message, "natural_language_confirmation"),
                    "yes",
                )
                self.assertEqual(_direct_pending_decision(message), "yes")

    def test_prohibit_yes_confirmation_validates_success(self):
        message = _prohibit_confirmation_message(MISSION_META[87], "yes")
        validation = validate_submit_candidate(
            message,
            "오늘은 과자 먹지 않기",
            87,
            {"result_type": "success"},
        )

        self.assertEqual(message, "과자 안 먹었어요")
        self.assertTrue(validation.should_execute)
        self.assertEqual(validation.result_type, "success")

    def test_prohibit_no_confirmation_validates_fail(self):
        message = _prohibit_confirmation_message(MISSION_META[87], "no")
        validation = validate_submit_candidate(
            message,
            "오늘은 과자 먹지 않기",
            87,
            {"result_type": "fail"},
        )

        self.assertEqual(message, "과자 먹었어요")
        self.assertTrue(validation.should_execute)
        self.assertEqual(validation.result_type, "fail")

    async def test_equivalency_clarify_non_numeric_submit_report_accepts(self):
        mission_name = "\uc5d8\ub9ac\ubca0\uc774\ud130 \ub300\uc2e0 \uacc4\ub2e8\uc73c\ub85c \uac77\uae30"
        mission_row = {"mission_id": 12, "mission_name": mission_name}
        payload = {
            "clarify_reason": "equivalency_clarify",
            "mission_id": 12,
            "mission_name": mission_name,
            "target_value": None,
            "target_unit": None,
            "target_metric": "behavior",
        }

        with (
            patch("pending_service.get_student_mission_db", return_value=mission_row),
            patch(
                "pending_service.execute_submit",
                return_value=SubmitResult(status=SubmitStatus.SAVED, result_type="success"),
            ) as execute_submit,
            patch("pending_service.resolve_pending") as resolve_pending,
        ):
            outcome = await _handle_equivalency_clarify_confirmation(
                15,
                119,
                payload,
                0,
                "\uc5d8\ub808\ubca0\uc774\ud130 \ub300\uc2e0 \uacc4\ub2e8\uc73c\ub85c \uac78\uc5c8\uc5b4",
            )

        self.assertEqual(outcome.status, "accepted")
        self.assertEqual(outcome.decision, "equivalency_success")
        execute_submit.assert_called_once_with(15, {"result_type": "success"})
        resolve_pending.assert_called_once_with(119, "accepted")

    async def test_equivalency_clarify_non_numeric_question_does_not_submit(self):
        mission_name = "\uc5d8\ub9ac\ubca0\uc774\ud130 \ub300\uc2e0 \uacc4\ub2e8\uc73c\ub85c \uac77\uae30"
        mission_row = {"mission_id": 12, "mission_name": mission_name}
        payload = {
            "clarify_reason": "equivalency_clarify",
            "mission_id": 12,
            "mission_name": mission_name,
            "target_value": None,
            "target_unit": None,
            "target_metric": "behavior",
            "clarify_question": "\ubb34\uc5c7\uc744 \uc5bc\ub9c8\ub098 \ud588\ub294\uc9c0 \uc54c\ub824\uc904\ub798?",
        }

        with (
            patch("pending_service.get_student_mission_db", return_value=mission_row),
            patch("pending_service.execute_submit") as execute_submit,
            patch("pending_service.increment_pending_retry", return_value={"retry_count": 1}),
        ):
            outcome = await _handle_equivalency_clarify_confirmation(
                15,
                119,
                payload,
                0,
                "\uacc4\ub2e8 \ud55c \uce35\ub9cc \uc62c\ub77c\uac00\ub3c4 \ub428?",
            )

        self.assertEqual(outcome.status, "retry_1")
        self.assertEqual(outcome.decision, "ambiguous")
        execute_submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
