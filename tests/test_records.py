import os
import sqlite3
import tempfile
import unittest

from boss.domain import Job, Message
from boss.pages.conversations import ConversationPreview
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

    def test_runtime_snapshots_are_saved_and_message_writes_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "records.db")
            entry = ConversationPreview(
                0,
                "甲先生",
                "甲公司",
                "工程师",
                preview="您好",
            )
            with Recorder(path, run_id="run-001", source="test") as recorder:
                recorder.save_job(Job("Python 工程师", "15K", "甲公司"), source="cards")
                conversation_id = recorder.save_conversation_preview(entry)
                rows = [Message("您好", "them", "text"), Message("同意", "system", "action")]
                self.assertEqual(recorder.save_messages(rows, conversation_id), 2)
                # 同一屏再次读取只更新 last_seen，不复制消息实体。
                self.assertEqual(recorder.save_messages(rows, conversation_id), 2)
                counts = recorder.counts_by_table()
                self.assertEqual(counts["jobs"], 1)
                self.assertEqual(counts["conversations"], 1)
                self.assertEqual(counts["messages"], 2)
                self.assertGreaterEqual(counts["observations"], 4)

            conn = sqlite3.connect(path)
            try:
                run = conn.execute(
                    "SELECT status FROM runs WHERE run_id=?", ("run-001",)
                ).fetchone()
                self.assertEqual(run[0], "completed")
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 2
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT kind FROM messages WHERE text=?", ("同意",)
                    ).fetchone()[0],
                    "action",
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
