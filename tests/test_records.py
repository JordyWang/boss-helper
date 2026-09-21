import os
import tempfile
import unittest

from boss.records import Recorder


class RecorderTest(unittest.TestCase):
    def test_context_counts_and_recent_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "records.db")
            with Recorder(path) as recorder:
                recorder.add("filtered", "职位 A")
                recorder.add("applied", "职位 B")
                self.assertEqual(recorder.total(), 2)
                self.assertEqual(recorder.counts(), {"applied": 1, "filtered": 1})
                self.assertEqual(recorder.recent(1)[0][2], "职位 B")
                self.assertEqual(recorder.recent(0), [])

    def test_empty_action_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Recorder(os.path.join(tmp, "records.db")) as recorder:
                with self.assertRaises(ValueError):
                    recorder.add("")


if __name__ == "__main__":
    unittest.main()
