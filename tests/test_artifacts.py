import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from boss.artifacts import RunArtifacts, RunInProgressError
from boss.domain import Message


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
            messages = artifacts.save_messages(
                [Message("你好", "them", "text"), Message("收到", "me", "text")]
            )
            self.assertEqual(Path(dump).name, "001_dump.xml")
            self.assertEqual(Path(screenshot).name, "002_screenshot.png")
            self.assertEqual(Path(messages).name, "003_messages.json")
            self.assertTrue(Path(dump).read_text(encoding="utf-8"))
            saved = Path(messages).read_text(encoding="utf-8")
            self.assertIn("你好", saved)
            self.assertIn('"dedup_key"', saved)
            artifacts.close()
            self.assertFalse(Path(tmp, ".run.lock").exists())

            next_run = RunArtifacts.create(tmp, now=now)
            self.assertEqual(next_run.run_id, "20260921_123000_02")
            next_run.close()

    def test_messages_preserve_server_id_alias_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = RunArtifacts.create(Path(tmp), now=datetime(2026, 1, 2, 3, 4, 5))
            try:
                path = artifacts.save_messages(
                    [
                        {
                            "id": "srv-7",
                            "text": "同一条消息",
                            "sender": "them",
                            "kind": "text",
                            "createdAt": "2026-01-02T03:04:05Z",
                        }
                    ],
                    conversation_id="conversation-1",
                )
                rows = json.loads(Path(path).read_text(encoding="utf-8"))
                self.assertEqual(rows[0]["message_id"], "srv-7")
                self.assertEqual(rows[0]["timestamp"], "2026-01-02T03:04:05Z")
                self.assertEqual(rows[0]["dedup_source"], "server_id")
            finally:
                artifacts.close()

    def test_conversation_archive_contains_preview_and_message_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = RunArtifacts.create(Path(tmp))
            try:
                path = artifacts.save_conversation(
                    {
                        "schema_version": 1,
                        "conversation_id": "company=甲公司|job_title=工程师",
                        "list_preview": {"name": "甲先生"},
                        "messages": [Message("你好", "them", "text")],
                    }
                )
                payload = json.loads(Path(path).read_text(encoding="utf-8"))
                self.assertEqual(payload["list_preview"]["name"], "甲先生")
                self.assertEqual(payload["messages"][0]["text"], "你好")
                self.assertEqual(
                    payload["messages"][0]["conversation_id"],
                    "company=甲公司|job_title=工程师",
                )
            finally:
                artifacts.close()


if __name__ == "__main__":
    unittest.main()
