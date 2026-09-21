"""职位详情页。"""
from __future__ import annotations

from .base import BasePage
from .. import selectors as S


class JobDetailPage(BasePage):
    def title(self) -> str:
        return self.text_of(S.DETAIL["title"], timeout=4.0)

    def salary(self) -> str:
        return self.text_of(S.DETAIL["salary"], timeout=3.0)

    def boss_name(self) -> str:
        return self.text_of(S.DETAIL["boss_name"], timeout=3.0)

    def communicate(self) -> bool:
        """点击"立即沟通"(btn_chat),返回是否成功。"""
        self.dismiss_popups(S.GLOBAL_POPUP_CLOSE)
        return self.click(S.DETAIL["communicate_btn"], timeout=6.0)

    def handle_after_communicate(self) -> None:
        """处理点击沟通后可能弹出的确认框(发送简历/继续沟通等)。"""
        if self.exists(S.DETAIL["confirm_send_resume"], timeout=2.0):
            self.log.info("弹出发送简历确认")
        if self.exists(S.DETAIL["continue_chat"], timeout=1.5):
            self.click(S.DETAIL["continue_chat"], timeout=2.0)
