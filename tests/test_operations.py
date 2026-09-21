import argparse
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from boss.artifacts import RunArtifacts
from boss.cli import build_parser, cmd_conversations, cmd_op
from boss.config import AppConfig
from boss.domain import Job
from boss.domain import Message
from boss.operations import (
    OPERATION_SPECS,
    OperationContext,
    op_conversations,
    op_dry_run,
    op_messages,
    op_resume,
)
from boss.logger import close_logger
from boss.pages.conversations import ConversationPreview


class _FakeDevice:
    def __init__(self):
        self.ensure_calls = 0

    def app_current(self):
        return {"package": "other.app", "activity": "OtherActivity"}

    def window_size(self):
        return (1080, 2400)

    @property
    def device_info(self):
        return {"version": "14", "model": "test-device"}


class _PreviewHome:
    def __init__(self):
        self.open_calls = 0
        self.cards_calls = 0
        self.scroll_calls = 0
        self.clicks = 0

    def open_recommend(self):
        self.open_calls += 1
        return True

    def job_cards(self):
        self.cards_calls += 1
        return [Job("Python 工程师", "15K", "甲公司")]

    def scroll(self, direction="up"):
        self.scroll_calls += 1

    def human_delay(self):
        self.clicks += 1


class _NoSideEffectDetail:
    def __getattr__(self, name):
        raise AssertionError("dry-run 不应访问详情页: %s" % name)


class _NoSideEffectChat:
    def __getattr__(self, name):
        raise AssertionError("dry-run 不应访问会话页: %s" % name)


class _ReadOnlyState:
    def __init__(self):
        self.applied_today = 0
        self.reads = []
        self.mutations = 0

    def is_seen(self, key):
        self.reads.append(key)
        return False

    def mark_skipped(self, keys):
        self.mutations += 1

    def mark_applied(self, keys):
        self.mutations += 1


class _ResumeChat:
    def __init__(self):
        self.actions = []

    def in_chat(self):
        return True

    def resume_dialog_visible(self):
        self.actions.append("inspect")
        return True

    def handle_resume_action(self, action, reason=""):
        self.actions.append((action, reason))
        return True


class _MessagesChat:
    def in_chat(self):
        return True

    def read_messages(self):
        return [
            type("Message", (), {"text": "你好", "sender": "them", "kind": "text"})(),
        ]

    def summarize(self, messages):
        return "我方 0 / 对方 1 / 领先 -1"

    def conversation_id(self):
        return "company=甲公司|job_title=Python工程师|recruiter=甲先生"


class _ConversationChat:
    def __init__(self):
        self.in_chat_calls = 0
        self.read_calls = 0

    def in_chat(self):
        self.in_chat_calls += 1
        return True

    def read_messages(self):
        self.read_calls += 1
        return [Message("你好", "them", "text")]

    def conversation_context(self):
        return {"company": "聊天页公司", "job_title": "聊天页职位", "recruiter": "聊天页联系人"}

    def conversation_id(self):
        return "company=聊天页公司|job_title=聊天页职位|recruiter=聊天页联系人"


class _ConversationListing:
    def __init__(self, entries):
        self.entries = list(entries)
        self.opened = []
        self.open_list_calls = 0
        self.back_calls = 0
        self.scroll_calls = 0

    def open_list(self):
        self.open_list_calls += 1
        return True

    def visible(self):
        return list(self.entries)

    def find_by_id(self, conversation_id, max_scrolls=8):
        return next((item for item in self.entries if item.conversation_id == conversation_id), None)

    def open_conversation(self, entry):
        self.opened.append(entry)
        return True

    def back_to_list(self):
        self.back_calls += 1
        return True

    def scroll(self):
        self.scroll_calls += 1


class OperationRegistryTest(unittest.TestCase):
    def test_registry_declares_expected_operations_and_dependencies(self):
        expected = {
            "recommend",
            "detail",
            "read",
            "communicate",
            "send",
            "messages",
            "conversations",
            "back",
            "home",
            "health",
            "cards",
            "screenshot",
            "scroll",
            "draft",
            "resume",
            "dismiss-popups",
            "dry-run",
            "filter-check",
        }
        self.assertEqual(set(OPERATION_SPECS), expected)
        self.assertFalse(OPERATION_SPECS["filter-check"].requires_device)
        self.assertFalse(OPERATION_SPECS["filter-check"].ensure_app)
        self.assertTrue(OPERATION_SPECS["health"].requires_device)
        self.assertFalse(OPERATION_SPECS["health"].ensure_app)
        self.assertTrue(OPERATION_SPECS["communicate"].requires_yes)
        self.assertTrue(OPERATION_SPECS["send"].requires_yes)
        self.assertIn("home", OPERATION_SPECS["dry-run"].pages)
        self.assertTrue(OPERATION_SPECS["dry-run"].requires_state)

    def test_parser_uses_registry_and_exposes_operation_options(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "op",
                "scroll",
                "--count",
                "3",
                "--direction",
                "down",
                "--name",
                "screen.png",
                "--rounds",
                "4",
                "--action",
                "inspect",
                "--title",
                "工程师",
                "--salary",
                "20K",
                "--company",
                "甲公司",
            ]
        )
        self.assertEqual(args.count, 3)
        self.assertEqual(args.direction, "down")
        self.assertEqual(args.name, "screen.png")
        self.assertEqual(args.rounds, 4)
        self.assertEqual(args.title, "工程师")
        self.assertIn("filter-check", parser.parse_args(["op", "filter-check"]).op)

    def test_conversation_shortcut_accepts_positional_id_and_aliases(self):
        parser = build_parser()
        conversation_id = "company=甲公司|job_title=工程师|recruiter=甲先生"
        args = parser.parse_args(["conversations", conversation_id, "-n", "2"])
        self.assertEqual(args.conversation_id_positional, conversation_id)
        self.assertEqual(args.count, 2)
        alias_args = parser.parse_args(["chat", "--id", conversation_id])
        self.assertEqual(alias_args.conversation_id_option, conversation_id)
        self.assertFalse(alias_args.list_only)

    def test_conversation_shortcut_delegates_to_conversation_operation(self):
        args = argparse.Namespace(
            conversation_id_positional="company=甲公司|job_title=工程师|recruiter=甲先生",
            conversation_id_option="",
            count=None,
            list_only=True,
            max_scrolls=8,
            name="",
        )
        with mock.patch("boss.cli.cmd_op", return_value=0) as operation:
            self.assertEqual(cmd_conversations(args), 0)
        self.assertEqual(args.op, "conversations")
        self.assertEqual(args.conversation_id, args.conversation_id_positional)
        operation.assert_called_once_with(args)


class OperationExecutionTest(unittest.TestCase):
    def _artifacts(self, root):
        return RunArtifacts.create(Path(root) / "logs")

    def test_filter_check_does_not_connect_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self._artifacts(tmp)
            args = argparse.Namespace(
                config=str(Path(tmp) / "missing.yaml"),
                op="filter-check",
                title="Python 工程师",
                salary="15K",
                company="甲公司",
                artifacts=artifacts,
            )
            try:
                with mock.patch("boss.device.connect", side_effect=AssertionError("不应连接设备")):
                    self.assertEqual(cmd_op(args), 0)
            finally:
                close_logger()
                artifacts.close()

    def test_health_connects_without_starting_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self._artifacts(tmp)
            args = argparse.Namespace(
                config=str(Path(tmp) / "missing.yaml"),
                op="health",
                artifacts=artifacts,
            )
            device = _FakeDevice()
            try:
                with mock.patch("boss.device.connect", return_value=device) as connect, mock.patch(
                    "boss.device.ensure_app", side_effect=AssertionError("health 不应启动 App")
                ) as ensure:
                    self.assertEqual(cmd_op(args), 0)
                connect.assert_called_once()
                ensure.assert_not_called()
            finally:
                close_logger()
                artifacts.close()

    def test_unconfirmed_send_is_rejected_before_connecting(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self._artifacts(tmp)
            args = argparse.Namespace(
                config=str(Path(tmp) / "missing.yaml"),
                op="send",
                text="hello",
                yes=False,
                artifacts=artifacts,
            )
            try:
                with mock.patch("boss.device.connect", side_effect=AssertionError("不应连接设备")):
                    self.assertEqual(cmd_op(args), 2)
            finally:
                close_logger()
                artifacts.close()

    def test_dry_run_only_reads_and_does_not_mutate_or_click(self):
        home = _PreviewHome()
        state = _ReadOnlyState()
        args = argparse.Namespace(rounds=1)
        ctx = OperationContext(
            args=args,
            cfg=AppConfig(),
            log=logging.getLogger("test-dry-run"),
            home=home,
            detail=_NoSideEffectDetail(),
            chat=_NoSideEffectChat(),
            state=state,
        )
        self.assertEqual(op_dry_run(ctx), 0)
        self.assertEqual(home.open_calls, 1)
        self.assertEqual(home.scroll_calls, 0)
        self.assertEqual(home.clicks, 0)
        self.assertEqual(state.mutations, 0)
        self.assertTrue(state.reads)

    def test_messages_are_saved_as_structured_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self._artifacts(tmp)
            ctx = OperationContext(
                args=argparse.Namespace(name=""),
                cfg=AppConfig(),
                log=logging.getLogger("test-messages"),
                chat=_MessagesChat(),
                artifacts=artifacts,
            )
            try:
                self.assertEqual(op_messages(ctx), 0)
                paths = list(Path(artifacts.directory).glob("*_messages.json"))
                self.assertEqual(len(paths), 1)
                with open(paths[0], "r", encoding="utf-8") as fh:
                    rows = json.load(fh)
                self.assertEqual(rows[0]["text"], "你好")
                self.assertEqual(rows[0]["sender"], "them")
                self.assertEqual(
                    rows[0]["conversation_id"],
                    "company=甲公司|job_title=Python工程师|recruiter=甲先生",
                )
                self.assertTrue(rows[0]["dedup_key"].startswith("content:"))
            finally:
                artifacts.close()

    def test_conversations_without_selector_only_lists_ids_and_does_not_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self._artifacts(tmp)
            entry = ConversationPreview(0, "甲先生", "甲公司", "工程师")
            listing = _ConversationListing([entry])
            chat = _ConversationChat()
            ctx = OperationContext(
                args=argparse.Namespace(
                    conversation_id="", list_only=False, count=None, max_scrolls=8
                ),
                cfg=AppConfig(),
                log=logging.getLogger("test-conversations-list-only"),
                conversations=listing,
                chat=chat,
                artifacts=artifacts,
            )
            try:
                self.assertEqual(op_conversations(ctx), 0)
                self.assertEqual(listing.opened, [])
                self.assertEqual(chat.read_calls, 0)
                self.assertEqual(listing.back_calls, 0)
            finally:
                artifacts.close()

    def test_conversations_match_id_and_keep_list_id_as_archive_primary_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self._artifacts(tmp)
            entry = ConversationPreview(0, "甲先生", "甲公司", "工程师")
            listing = _ConversationListing([entry])
            chat = _ConversationChat()
            ctx = OperationContext(
                args=argparse.Namespace(
                    conversation_id=entry.conversation_id,
                    list_only=False,
                    count=None,
                    max_scrolls=0,
                ),
                cfg=AppConfig(),
                log=logging.getLogger("test-conversations-target"),
                conversations=listing,
                chat=chat,
                artifacts=artifacts,
            )
            try:
                self.assertEqual(op_conversations(ctx), 0)
                self.assertEqual(listing.opened, [entry])
                self.assertEqual(chat.read_calls, 1)
                paths = list(Path(artifacts.directory).glob("*_conversation_001.json"))
                self.assertEqual(len(paths), 1)
                payload = json.loads(paths[0].read_text(encoding="utf-8"))
                self.assertEqual(payload["conversation_id"], entry.conversation_id)
                self.assertEqual(payload["conversation_id_source"], "list")
                self.assertEqual(payload["chat_conversation_id"], chat.conversation_id())
            finally:
                artifacts.close()

    def test_conversations_count_is_explicit_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self._artifacts(tmp)
            entries = [
                ConversationPreview(0, "甲先生", "甲公司", "工程师"),
                ConversationPreview(1, "乙女士", "乙公司", "产品经理"),
            ]
            listing = _ConversationListing(entries)
            chat = _ConversationChat()
            ctx = OperationContext(
                args=argparse.Namespace(
                    conversation_id="", list_only=False, count=1, max_scrolls=0
                ),
                cfg=AppConfig(),
                log=logging.getLogger("test-conversations-count"),
                conversations=listing,
                chat=chat,
                artifacts=artifacts,
            )
            try:
                self.assertEqual(op_conversations(ctx), 0)
                self.assertEqual(len(listing.opened), 1)
                self.assertEqual(chat.read_calls, 1)
            finally:
                artifacts.close()

    def test_resume_requires_explicit_confirmation_for_actions(self):
        chat = _ResumeChat()
        base = dict(
            cfg=AppConfig(),
            log=logging.getLogger("test-resume"),
            chat=chat,
        )
        self.assertEqual(
            op_resume(OperationContext(args=argparse.Namespace(action="agree", yes=False), **base)),
            2,
        )
        self.assertEqual(chat.actions, [])
        self.assertEqual(
            op_resume(OperationContext(args=argparse.Namespace(action="inspect", yes=False), **base)),
            0,
        )
        self.assertEqual(chat.actions, ["inspect"])
        self.assertEqual(
            op_resume(OperationContext(args=argparse.Namespace(action="agree", yes=True), **base)),
            0,
        )
        self.assertEqual(chat.actions[-1][0], "agree")


if __name__ == "__main__":
    unittest.main()
