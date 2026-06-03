import unittest

from chat_service import _fixed_volume_conversion_response


class VolumeConversionGuardTest(unittest.TestCase):
    def test_liter_to_cups_is_fixed_response(self):
        response = _fixed_volume_conversion_response("1리터가 몇 컵이야")

        self.assertIsNotNone(response)
        self.assertIn("1000ml", response)
        self.assertIn("5컵", response)
        self.assertNotIn("100컵", response)

    def test_numeric_mission_report_is_not_conversion_question(self):
        self.assertIsNone(_fixed_volume_conversion_response("물 5컵 마셨어"))

    def test_water_goal_confirmation_is_answered_without_recording(self):
        response = _fixed_volume_conversion_response("오늘 미션 그럼 5.6컵 마시는건가")

        self.assertIsNotNone(response)
        self.assertIn("5컵", response)
        self.assertIn("5.6컵", response)
        self.assertIn("기록은 아직 하지 않을게", response)


if __name__ == "__main__":
    unittest.main()
