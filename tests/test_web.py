import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest import mock
from urllib.request import ProxyHandler, build_opener

from boss.cli import main
from boss.domain import Message
from boss.pages.conversations import ConversationPreview
from boss.web import (
    ConversationWebService,
    WebSettings,
    make_handler,
)


class _Device:
    pass


class _ListPage:
    entries = [ConversationPreview(0, "甲先生", "甲公司", "工程师")]

    def __init__(self, device, timing, log, artifacts):
        self.opened = []
        self.back_calls = 0

    def open_list(self):
        return True

    def visible(self):
        return list(self.entries)

    def find_by_id(self, conversation_id, max_scrolls=8):
        return next(
            (entry for entry in self.entries if entry.conversation_id == conversation_id),
            None,
        )

    def open_conversation(self, entry):
        self.opened.append(entry)
        return True

    def back_to_list(self):
        self.back_calls += 1
        return True

    def scroll(self):
        return None


class _ChatPage:
    def __init__(self, device, timing, log, artifacts):
        self.read_calls = 0

    def in_chat(self):
        return True

    def read_messages(self):
        self.read_calls += 1
        return [Message("你好", "them", "text"), Message("同意", "system", "action")]

    def conversation_context(self):
        return {"company": "甲公司", "job_title": "工程师", "recruiter": "甲先生"}

    def conversation_id(self):
        return "company=聊天页公司|job_title=工程师|recruiter=甲先生"


class WebServiceTest(unittest.TestCase):
    def _service(self, root):
        return ConversationWebService(
            WebSettings(logs_dir=str(Path(root) / "logs")),
            device_factory=lambda serial, log: _Device(),
            list_page_factory=_ListPage,
            chat_page_factory=_ChatPage,
        )

    def _device_patches(self):
        return mock.patch.multiple(
            "boss.device",
            record_app_version=mock.Mock(),
            ensure_app=mock.Mock(),
        )

    def test_list_conversations_is_read_only_and_creates_run_log(self):
        with tempfile.TemporaryDirectory() as tmp, self._device_patches():
            result = self._service(tmp).list_conversations()
            self.assertTrue(result["ok"])
            self.assertFalse(result["opened"])
            self.assertEqual(result["entries"][0]["conversation_id"], "company=甲公司|job_title=工程师|recruiter=甲先生")
            self.assertTrue(Path(result["log_path"]).exists())
            self.assertFalse(Path(tmp, "logs", ".run.lock").exists())

    def test_archive_uses_list_id_as_primary_and_keeps_action_message(self):
        with tempfile.TemporaryDirectory() as tmp, self._device_patches():
            entry = _ListPage.entries[0]
            result = self._service(tmp).archive_conversations(entry.conversation_id)
            self.assertTrue(result["ok"])
            self.assertEqual(result["saved_count"], 1)
            self.assertEqual(result["conversation_id"], entry.conversation_id)
            self.assertEqual(result["messages"][1]["kind"], "action")
            archive = next(Path(tmp, "logs", result["run_id"]).glob("*_conversation*.json"))
            payload = json.loads(archive.read_text(encoding="utf-8"))
            self.assertEqual(payload["conversation_id_source"], "list")

    def test_archive_requires_explicit_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._service(tmp).archive_conversations()
            self.assertFalse(result["ok"])
            self.assertIn("请选择", result["error"])
            self.assertFalse(Path(tmp, "logs").exists())

    def test_batch_requires_explicit_confirmation_before_connecting(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            with mock.patch.object(
                service,
                "_device_factory",
                side_effect=AssertionError("不应连接设备"),
            ):
                result = service.run_batch(3, confirmation="")
            self.assertFalse(result["ok"])
            self.assertIn("明确确认", result["error"])

    def test_http_root_and_dashboard_are_available_without_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            server = HTTPServer(("127.0.0.1", 0), make_handler(service))
            thread = threading.Thread(target=server.serve_forever)
            thread.daemon = True
            thread.start()
            try:
                base = "http://127.0.0.1:%d" % server.server_port
                opener = build_opener(ProxyHandler({}))
                with opener.open(base + "/", timeout=2) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("可视化操作台", html)
                with opener.open(base + "/api/dashboard", timeout=2) as response:
                    dashboard = json.loads(response.read().decode("utf-8"))
                self.assertTrue(dashboard["ok"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_ui_command_does_not_hold_run_lock_for_server_lifetime(self):
        with mock.patch("boss.web.serve", return_value=None) as serve:
            self.assertEqual(main(["ui", "--no-browser"]), 0)
        serve.assert_called_once()


if __name__ == "__main__":
    unittest.main()
