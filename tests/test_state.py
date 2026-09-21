import json
import os
import tempfile
import unittest

from boss.state import State, make_key


class StateTest(unittest.TestCase):
    def test_bare_filename_and_equivalent_keys_only_count_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                state = State("state.json")
                card_key = make_key("Python 工程师", "10 K", "甲公司")
                detail_key = make_key("Python工程师", "10K", "甲公司")
                state.mark_applied([card_key, detail_key])
                state.mark_applied([card_key, "Python工程师|10K|乙公司"])
                self.assertEqual(state.applied_today, 1)
                self.assertTrue(state.is_seen("Python  工程师|10K|甲公司"))
                self.assertTrue(os.path.exists("state.json"))
            finally:
                os.chdir(old_cwd)

    def test_corrupt_file_is_repaired_and_reset_preserves_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("not json")
            state = State(path)
            state.mark_applied("职位|10K|公司")
            state.reset_today()
            self.assertEqual(state.applied_today, 0)
            self.assertEqual(len(state.applied_keys()), 1)
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["applied_today"], 0)

    def test_read_only_state_does_not_repair_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing", "state.json")
            state = State(path, read_only=True)
            self.assertFalse(os.path.exists(path))
            self.assertEqual(state.applied_today, 0)
            with self.assertRaises(RuntimeError):
                state.mark_skipped("职位|10K|公司")
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
