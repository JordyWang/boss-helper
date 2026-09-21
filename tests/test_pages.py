import logging
import unittest

from boss.config import Timing
from boss.pages.base import BasePage


class _Element:
    def __init__(self, result, text=""):
        self.result = result
        self.text = text
        self.clicked = False

    def wait(self, timeout):
        return self.result

    def get_text(self):
        return self.text

    def click(self):
        self.clicked = True


class _Device:
    def __init__(self, element):
        self.element = element

    def __call__(self, **selector):
        return self.element


class BasePageTest(unittest.TestCase):
    def test_wait_false_is_not_treated_as_exists(self):
        page = BasePage(
            _Device(_Element(False)),
            Timing((0, 0), (0, 0)),
            logging.getLogger("test-page"),
        )
        self.assertFalse(page.exists({}))
        self.assertFalse(page.wait({}))
        self.assertEqual(page.text_of({}), "")
        self.assertFalse(page.click({}))


if __name__ == "__main__":
    unittest.main()
