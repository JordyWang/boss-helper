"""会话 / 聊天页。每个方法都是一个可单独调用的原子操作。"""
from __future__ import annotations

import random
import time
from typing import List, Optional

from .base import BasePage
from .. import selectors as S


class ChatPage(BasePage):
    def in_chat(self) -> bool:
        """是否处于会话页(以输入框存在为准)。"""
        return self.exists(S.CHAT["chat_flag"], timeout=4.0)

    def _input(self):
        box = self.el(S.CHAT["input"])
        if not box.wait(timeout=5.0):
            self.log.warning("未找到聊天输入框")
            return None
        return box

    def _find_send_button(self, input_bounds: dict):
        """发送按钮无 resource-id:输入行内、输入框右侧、可点击的最右 ImageView。
        必须在已输入文字时调用(空输入时该位置是 +号 mMoreIcon)。"""
        cy = (input_bounds["top"] + input_bounds["bottom"]) // 2
        best = None
        for e in self.d(className="android.widget.ImageView", clickable=True):
            b = e.info["bounds"]
            if b["left"] > input_bounds["right"] - 5 and b["top"] <= cy <= b["bottom"]:
                if best is None or b["right"] > best.info["bounds"]["right"]:
                    best = e
        return best

    def type_text(self, text: str) -> bool:
        """仅输入文字,不发送(可用于校验/草稿)。"""
        box = self._input()
        if box is None:
            return False
        box.click()
        box.set_text(text)
        time.sleep(0.6)
        return True

    def send_message(self, text: str) -> bool:
        """在会话框输入并发送一条消息。返回是否成功点击发送。"""
        if not text:
            return False
        box = self._input()
        if box is None:
            return False

        box.click()
        box.set_text(text)
        time.sleep(0.8)

        bounds = box.info["bounds"]
        btn = self._find_send_button(bounds)
        if btn is None:
            self.log.warning("未定位到发送按钮,改用 IME send 动作兜底")
            self.d.send_action("send")
            self.human_delay()
        else:
            btn.click()
            self.human_delay()

        self.log.info("已发送消息: %s", text)
        return True

    def send_greeting(self, messages: List[str]) -> bool:
        """随机选一条招呼语并发送。"""
        if not messages:
            self.log.info("未配置招呼语,跳过发送(App 可能已自动发送预设招呼语)")
            return False
        return self.send_message(random.choice(messages))
