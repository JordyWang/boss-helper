import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from boss.artifacts import RunArtifacts, RunInProgressError


class _Device:
    def screenshot(self, path):
        Path(path).write_bytes(b"png")

    def dump_hierarchy(self):
        return "<hierarchy />"


class RunArtifactsTest(unittest.TestCase):
    def test_directory_sequence_and_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2026, 9, 21, 12, 30, 0)
            artifacts = RunArtifacts.create(tmp, now=now)
            self.assertEqual(artifacts.run_id, "20260921_123000")
            self.assertTrue(Path(artifacts.log_path).exists())
            self.assertTrue(Path(tmp, ".run.lock").exists())

            with self.assertRaises(RunInProgressError):
                RunArtifacts.create(tmp, now=now)

            dump = artifacts.save_dump(_Device(), "dump.xml")
            screenshot = artifacts.save_screenshot(_Device(), "screenshot.png")
            self.assertEqual(Path(dump).name, "001_dump.xml")
            self.assertEqual(Path(screenshot).name, "002_screenshot.png")
            self.assertTrue(Path(dump).read_text(encoding="utf-8"))
            artifacts.close()
            self.assertFalse(Path(tmp, ".run.lock").exists())

            next_run = RunArtifacts.create(tmp, now=now)
            self.assertEqual(next_run.run_id, "20260921_123000_02")
            next_run.close()


if __name__ == "__main__":
    unittest.main()
