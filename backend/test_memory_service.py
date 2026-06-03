import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory_service import _build_memory_extraction_prompt


class MemoryServiceTest(unittest.TestCase):
    def test_memory_prompt_preserves_json_examples(self):
        prompt = _build_memory_extraction_prompt()

        self.assertNotIn("{activity_keys}", prompt)
        self.assertIn('"subject"', prompt)
        self.assertIn('{"subject":null}', prompt.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
