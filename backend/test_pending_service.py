import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mission_meta import MISSION_META
from pending_service import (
    _direct_pending_decision,
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


if __name__ == "__main__":
    unittest.main()
