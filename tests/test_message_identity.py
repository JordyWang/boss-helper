import logging
import textwrap
import unittest

from boss.config import Timing
from boss.domain import Message
from boss.message_identity import (
    deduplicate_messages,
    message_fingerprint,
    message_identity,
)
from boss.pages.chat import ChatPage


class _ContextElement:
    def __init__(self, text):
        self.text = text

    def wait(self, timeout):
        return True

    def get_text(self):
        return self.text


class _ContextDevice:
    def __init__(self):
        self.values = {
            "com.hpbr.bosszhipin:id/tv_title": "尚先生",
            "com.hpbr.bosszhipin:id/tv_sub_title": "梦虎网络 · ceo",
        }

    def __call__(self, **selector):
        return _ContextElement(self.values.get(selector.get("resourceId"), ""))


class _MessagesDevice:
    def __init__(self, xml):
        self.xml = xml

    def __call__(self, **selector):
        class _Input:
            def wait(self, timeout):
                return True

            @property
            def info(self):
                return {"bounds": {"top": 2200}}

        return _Input()

    def window_size(self):
        return (1080, 2400)

    def dump_hierarchy(self):
        return self.xml


class MessageIdentityTest(unittest.TestCase):
    def test_conversation_id_contains_company_job_and_recruiter(self):
        page = ChatPage(
            _ContextDevice(),
            Timing((0, 0), (0, 0)),
            logging.getLogger("test-conversation-context"),
        )
        self.assertEqual(
            page.conversation_context(),
            {
                "company": "梦虎网络",
                "job_title": "ceo",
                "recruiter": "尚先生",
                "subtitle": "",
            },
        )
        self.assertEqual(
            page.conversation_id(),
            "company=梦虎网络|job_title=ceo|recruiter=尚先生",
        )

    def test_conversation_subtitle_without_separator_is_not_called_company(self):
        device = _ContextDevice()
        device.values["com.hpbr.bosszhipin:id/tv_sub_title"] = "招聘顾问"
        page = ChatPage(
            device,
            Timing((0, 0), (0, 0)),
            logging.getLogger("test-conversation-fallback"),
        )
        self.assertEqual(
            page.conversation_id(),
            "recruiter=尚先生|subtitle=招聘顾问",
        )

    def test_ui_attribute_parser_does_not_confuse_resource_id_with_message_id(self):
        attrs = ChatPage._node_attrs(
            '<node text="hello" resource-id="pkg:id/tv_text" '
            'message-id="server-1" bounds="[0,0][1,1]" />'
        )
        self.assertEqual(attrs["id"], "")
        self.assertEqual(attrs["message-id"], "server-1")

    def test_message_reader_excludes_controls_and_decodes_xml_newlines(self):
        xml = textwrap.dedent(
            '''
            <hierarchy>
              <node text="换电话" resource-id="pkg:id/mTextView" class="android.widget.TextView" bounds="[20,300][100,340]" />
              <node text="09-11 15:25" resource-id="pkg:id/tv_text" class="android.widget.TextView" bounds="[100,400][300,440]" />
              <node text="真实消息&#10;第二行" resource-id="pkg:id/tv_text" class="android.widget.TextView" bounds="[100,500][500,600]" />
              <node text="复制微信号" resource-id="pkg:id/tv_button" class="android.widget.TextView" bounds="[100,700][500,740]" />
            </hierarchy>
            '''
        )
        page = ChatPage(
            _MessagesDevice(xml),
            Timing((0, 0), (0, 0)),
            logging.getLogger("test-message-reader"),
        )
        messages = page.read_messages(settle_seconds=0)
        self.assertEqual([message.text for message in messages], ["真实消息\n第二行"])

    def test_content_fingerprint_normalizes_whitespace_but_keeps_sender(self):
        first = Message("你好  世界", "them", "text")
        second = Message("你好\n世界", "them", "text")
        self.assertEqual(
            message_fingerprint(first, "会话 A"),
            message_fingerprint(second, "会话 A"),
        )
        self.assertNotEqual(
            message_fingerprint(first, "会话 A"),
            message_fingerprint(first, "会话 B"),
        )
        self.assertNotEqual(
            message_fingerprint(first, "会话 A"),
            message_fingerprint(Message("你好 世界", "me", "text"), "会话 A"),
        )

    def test_server_message_id_takes_priority_over_content(self):
        one = {"id": "m-17", "text": "旧内容", "sender": "them", "kind": "text"}
        two = {"messageId": "m-17", "text": "修订内容", "sender": "them", "kind": "text"}
        key, source = message_identity(one, "会话 A")
        self.assertEqual(source, "server_id")
        self.assertEqual(key, message_fingerprint(two, "会话 A"))
        self.assertNotEqual(key, message_fingerprint(one, "会话 B"))

    def test_deduplicate_preserves_order_and_documents_content_limit(self):
        messages = [
            Message("同一句", "them", "text"),
            Message("同一句", "them", "text"),
            Message("另一句", "them", "text"),
        ]
        result = deduplicate_messages(messages, "会话 A")
        self.assertEqual([item.text for item in result], ["同一句", "另一句"])


if __name__ == "__main__":
    unittest.main()
