import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from submit_validator import (
    build_submit_validation_response,
    should_promote_to_submit_path,
    validate_submit_candidate,
)


class SubmitValidatorTest(unittest.TestCase):
    def test_quantity_question_does_not_submit_water_mission(self):
        message = "1리터가 몇 컵이야"

        self.assertFalse(
            should_promote_to_submit_path(message, "물 1리터 마시기", 71)
        )
        validation = validate_submit_candidate(
            message,
            "물 1리터 마시기",
            71,
            {"result_type": "success"},
        )
        self.assertEqual(validation.action, "block")
        self.assertEqual(validation.reason, "block_question")

    def test_numeric_water_report_still_submits(self):
        message = "물 5컵 마셨어"

        self.assertTrue(
            should_promote_to_submit_path(message, "물 1리터 마시기", 71)
        )
        validation = validate_submit_candidate(
            message,
            "물 1리터 마시기",
            71,
            {"result_type": "success"},
        )
        self.assertTrue(validation.should_execute)
        self.assertEqual(validation.result_type, "success")

    def test_water_goal_confirmation_does_not_submit(self):
        message = "오늘 미션 그럼 5.6컵 마시는건가"

        self.assertFalse(
            should_promote_to_submit_path(message, "물 1리터 마시기", 71)
        )
        validation = validate_submit_candidate(
            message,
            "물 1리터 마시기",
            71,
            {"result_type": "success"},
        )
        self.assertEqual(validation.action, "block")
        self.assertEqual(validation.reason, "block_question")

    def test_conditional_success_question_does_not_submit(self):
        message = "5컵 마시면 성공인가"

        self.assertFalse(
            should_promote_to_submit_path(message, "물 1리터 마시기", 71)
        )
        validation = validate_submit_candidate(
            message,
            "물 1리터 마시기",
            71,
            {"result_type": "success"},
        )
        self.assertEqual(validation.action, "block")
        self.assertEqual(validation.reason, "block_question")

    def test_healthy_substitute_for_snack_prohibition_submits_success(self):
        message = "오늘 견과류 먹엇어요 과자 대신"

        self.assertTrue(
            should_promote_to_submit_path(message, "오늘은 과자 먹지 않기", 87)
        )
        validation = validate_submit_candidate(
            message,
            "오늘은 과자 먹지 않기",
            87,
            {"result_type": "success"},
        )
        self.assertTrue(validation.should_execute)
        self.assertEqual(validation.result_type, "success")
        self.assertEqual(validation.reason, "validated_prohibit_substitute")

    def test_snack_prohibition_consumed_target_still_fails(self):
        message = "과자 먹었어요"

        self.assertTrue(
            should_promote_to_submit_path(message, "오늘은 과자 먹지 않기", 87)
        )
        validation = validate_submit_candidate(
            message,
            "오늘은 과자 먹지 않기",
            87,
            {"result_type": "success"},
        )

        self.assertTrue(validation.should_execute)
        self.assertEqual(validation.result_type, "fail")

    def test_snack_prohibition_casual_negation_submits_success(self):
        for message in ("오늘 과자 하나도 안 먹음", "과자 안 먹음"):
            with self.subTest(message=message):
                validation = validate_submit_candidate(
                    message,
                    "오늘은 과자 먹지 않기",
                    87,
                    {"result_type": "fail"},
                )

                self.assertTrue(validation.should_execute)
                self.assertEqual(validation.result_type, "success")
                self.assertEqual(validation.reason, "validated_prohibit_negation")

    def test_snack_prohibition_partial_consumption_fails(self):
        validation = validate_submit_candidate(
            "오늘 과자 아주 조금 먹었는데",
            "오늘은 과자 먹지 않기",
            87,
            {"result_type": "success"},
        )

        self.assertTrue(validation.should_execute)
        self.assertEqual(validation.result_type, "fail")
        self.assertEqual(validation.reason, "validated_prohibit_consumed")

    def test_snack_prohibition_partial_negation_still_succeeds(self):
        validation = validate_submit_candidate(
            "과자 조금도 안 먹었어",
            "오늘은 과자 먹지 않기",
            87,
            {"result_type": "fail"},
        )

        self.assertTrue(validation.should_execute)
        self.assertEqual(validation.result_type, "success")
        self.assertEqual(validation.reason, "validated_prohibit_negation")

    def test_success_question_gets_mission_criteria_response(self):
        validation = validate_submit_candidate(
            "그럼 오늘 미션 성공?",
            "오늘은 과자 먹지 않기",
            87,
            {"result_type": "success"},
        )

        self.assertEqual(validation.action, "block")
        response = build_submit_validation_response(
            validation,
            "오늘은 과자 먹지 않기",
            "그럼 오늘 미션 성공?",
            87,
        )
        self.assertIn("과자를 먹지 않았으면 성공", response)
        self.assertIn("기록하려면", response)

    def test_homework_before_game_order_violation_fails(self):
        for message in (
            "나 사실.. 게임을 먼저 했어 숙제 하기 전에...",
            "숙제 하기 전에 게임 먼저 했어",
        ):
            with self.subTest(message=message):
                validation = validate_submit_candidate(
                    message,
                    "게임하기 전 숙제 먼저 하기",
                    159,
                    {"result_type": "success"},
                )

                self.assertTrue(validation.should_execute)
                self.assertEqual(validation.result_type, "fail")
                self.assertEqual(validation.reason, "validated_homework_after_distraction")

    def test_homework_before_game_success_still_succeeds(self):
        for message in (
            "게임하기 전에 숙제 먼저 했어",
            "숙제 먼저 하고 게임했어",
            "나 숙제 먼저 함! 게임 안 했어요 오늘",
            "게임 안 하고 숙제 먼저 했어요",
            "나 게임 안 하고 숙제 다 함",
        ):
            with self.subTest(message=message):
                self.assertTrue(
                    should_promote_to_submit_path(
                        message,
                        "게임하기 전 숙제 먼저 하기",
                        159,
                    )
                )
                validation = validate_submit_candidate(
                    message,
                    "게임하기 전 숙제 먼저 하기",
                    159,
                    {"result_type": "success"},
                )

                self.assertTrue(validation.should_execute)
                self.assertEqual(validation.result_type, "success")

    def test_shorts_alias_limit_mission_fails_over_threshold(self):
        for message in (
            "나 아침에 숏츠 60분 봄..",
            "숏츠 60분 봤어 ㅠㅠ",
            "60분! 숏츠 봤다고",
        ):
            with self.subTest(message=message):
                self.assertTrue(
                    should_promote_to_submit_path(
                        message,
                        "쇼츠 30분 이하 보기",
                        168,
                    )
                )
                validation = validate_submit_candidate(
                    message,
                    "쇼츠 30분 이하 보기",
                    168,
                    {"result_type": "success"},
                )

                self.assertTrue(validation.should_execute)
                self.assertEqual(validation.result_type, "fail")
                self.assertEqual(validation.reason, "validated_limit_numeric")


if __name__ == "__main__":
    unittest.main()
