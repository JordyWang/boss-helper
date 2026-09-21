import unittest

from boss.domain import Message
from boss.message_identity import (
    deduplicate_messages,
    message_fingerprint,
    message_identity,
)
from boss.pages.chat import ChatPage


class MessageIdentityTest(unittest.TestCase):
    def test_ui_attribute_parser_does_not_confuse_resource_id_with_message_id(self):
        attrs = ChatPage._node_attrs(
            '<node text="hello" resource-id="pkg:id/tv_text" '
            'message-id="server-1" bounds="[0,0][1,1]" />'
        )
        self.assertEqual(attrs["id"], "")
        self.assertEqual(attrs["message-id"], "server-1")

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
