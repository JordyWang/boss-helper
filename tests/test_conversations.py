import logging
import unittest

from boss.config import Timing
from boss.pages.conversations import ConversationListPage, ConversationPreview


class _Element:
    def __init__(self, text="", result=True):
        self.text = text
        self.result = result
        self.clicked = False

    def wait(self, timeout):
        return self.result

    def get_text(self):
        return self.text

    def click(self):
        self.clicked = True


class _Row:
    def __init__(self, values):
        self.values = values
        self.clicked = False
        self.info = {"clickable": True, "enabled": True}

    def child(self, **selector):
        rid = selector.get("resourceId", "")
        return _Element(self.values.get(rid, ""))

    def click(self):
        self.clicked = True


class _Rows:
    def __init__(self, rows):
        self.rows = rows
        self.count = len(rows)

    def __getitem__(self, index):
        return self.rows[index]


class _List:
    def __init__(self, rows):
        self.rows = _Rows(rows)
        self.count = len(rows)

    def wait(self, timeout):
        return True

    def child(self, **selector):
        return self.rows


class _Device:
    def __init__(self, rows):
        self.list = _List(rows)
        self.tab = _Element()

    def __call__(self, **selector):
        if selector.get("resourceId", "").endswith("recyclerView"):
            return self.list
        return self.tab


class ConversationListPageTest(unittest.TestCase):
    def _page(self, rows):
        return ConversationListPage(
            _Device(rows),
            Timing((0, 0), (0, 0)),
            logging.getLogger("test-conversation-list"),
        )

    def test_visible_splits_company_and_job_and_reads_preview(self):
        row = _Row(
            {
                "com.hpbr.bosszhipin:id/tv_name": "丘先生",
                "com.hpbr.bosszhipin:id/tv_position": "三横科技 | 全栈工程师",
                "com.hpbr.bosszhipin:id/tv_time": "18-25K",
                "com.hpbr.bosszhipin:id/tv_msg": "你好",
                "com.hpbr.bosszhipin:id/tv_time_v2": "06:47",
            }
        )
        entries = self._page([row]).visible()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].company, "三横科技")
        self.assertEqual(entries[0].job_title, "全栈工程师")
        self.assertEqual(entries[0].name, "丘先生")
        self.assertEqual(entries[0].context_id, "company=三横科技|job_title=全栈工程师|recruiter=丘先生")
        self.assertIs(entries[0].row, row)

    def test_position_without_separator_is_kept_as_job_title(self):
        row = _Row(
            {
                "com.hpbr.bosszhipin:id/tv_name": "联系人",
                "com.hpbr.bosszhipin:id/tv_position": "未标注职位",
            }
        )
        entry = self._page([row]).visible()[0]
        self.assertEqual(entry.company, "")
        self.assertEqual(entry.job_title, "未标注职位")

    def test_open_list_does_not_reclick_when_already_in_list(self):
        row = _Row(
            {
                "com.hpbr.bosszhipin:id/tv_name": "联系人",
                "com.hpbr.bosszhipin:id/tv_position": "公司 | 职位",
            }
        )
        page = self._page([row])
        self.assertTrue(page.open_list())
        self.assertFalse(page.d.tab.clicked)

    def test_conversation_id_is_stable_and_context_id_is_compatibility_alias(self):
        entry = ConversationPreview(
            index=4,
            name="张先生",
            company="甲|乙",
            job_title="Python 工程师",
            preview="最近消息会变化",
        )
        expected = "company=甲\\|乙|job_title=Python 工程师|recruiter=张先生"
        self.assertEqual(entry.conversation_id, expected)
        self.assertEqual(entry.local_id, expected)
        self.assertEqual(entry.context_id, expected)
        self.assertIn(expected, entry.match_ids())
        self.assertEqual(entry.as_dict()["conversation_id"], expected)

    def test_find_by_id_checks_visible_pages_without_opening_chat(self):
        first = ConversationPreview(0, "甲先生", "甲公司", "工程师")
        second = ConversationPreview(1, "乙女士", "乙公司", "产品经理")
        page = self._page([])
        screens = [[first], [second]]
        scrolls = []

        page.visible = lambda: screens[min(len(scrolls), len(screens) - 1)]
        page.scroll = lambda: scrolls.append(True)

        found = page.find_by_id(second.conversation_id, max_scrolls=3)
        self.assertIs(found, second)
        self.assertEqual(len(scrolls), 1)

    def test_find_by_id_does_not_scroll_when_target_is_not_on_first_screen(self):
        first = ConversationPreview(0, "甲先生", "甲公司", "工程师")
        page = self._page([])
        scrolls = []
        page.visible = lambda: [first]
        page.scroll = lambda: scrolls.append(True)

        self.assertIsNone(page.find_by_id("company=不存在|job_title=工程师|recruiter=乙", max_scrolls=5))
        # 同一屏没有变化，有限查找会立即停止，不会盲目滑满上限。
        self.assertEqual(len(scrolls), 1)


if __name__ == "__main__":
    unittest.main()
