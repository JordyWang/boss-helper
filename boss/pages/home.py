"""首页 / 推荐列表页。"""
from __future__ import annotations

from typing import List

from .base import BasePage
from .. import selectors as S


class JobCard:
    """推荐流中的一个职位卡片。"""

    def __init__(self, element, index: int):
        self.el = element
        self.index = index

    def _child_text(self, sel) -> str:
        try:
            c = self.el.child(**sel)
            if c.exists:
                return c.get_text() or ""
        except Exception:
            pass
        return ""

    @property
    def title(self) -> str:
        # tv_position_name 末尾常带图标占位符(如 &@),清掉以免污染去重 key
        return self._child_text(S.HOME["job_card_title"]).strip().rstrip("&@・·").strip()

    @property
    def salary(self) -> str:
        return self._child_text(S.HOME["job_card_salary"])

    @property
    def company(self) -> str:
        return self._child_text(S.HOME["job_card_company"])

    def click(self) -> None:
        self.el.click()


class HomePage(BasePage):
    def go_job_list(self) -> bool:
        """点击底部导航"职位"Tab 进入职位列表页。"""
        nav = self.el(S.HOME["job_nav"])
        if not nav.wait(timeout=6.0):
            self.log.warning("未找到底部'职位'导航")
            return False
        # 底部导航在屏幕下方;若匹配到多个,取最靠下的那个,避免误点
        target = nav
        try:
            n = nav.count
            if n > 1:
                best_top = -1
                for i in range(n):
                    top = nav[i].info["bounds"]["top"]
                    if top > best_top:
                        best_top, target = top, nav[i]
        except Exception:
            pass
        target.click()
        self.human_delay()
        return True

    def open_recommend(self) -> bool:
        """进入职位列表并切到"推荐"子 Tab(存在时)。"""
        self.dismiss_popups(S.GLOBAL_POPUP_CLOSE)
        if not self.go_job_list():
            return False
        # 顶部"推荐"子 Tab 可能已默认选中而不单独出现,存在才点
        if self.exists(S.HOME["recommend_tab"], timeout=2.0):
            self.click(S.HOME["recommend_tab"], timeout=2.0)
        return self.wait(S.HOME["job_card"], timeout=6.0)

    def job_cards(self) -> List[JobCard]:
        container = self.d(**S.HOME["job_card"])
        count = container.count
        return [JobCard(container[i], i) for i in range(count)]

    def scroll(self) -> None:
        self.swipe_up()

    def back_to_list(self, max_backs: int = 5) -> bool:
        """连续返回,直到确认回到 MainActivity 且推荐列表卡片可见。
        注意:ChatRoomActivity 里也嵌有 view_job_card,单看元素会误判。"""
        for _ in range(max_backs):
            if self._is_on_list():
                return True
            self.d.press("back")
            self.human_delay()
        ok = self._is_on_list()
        if not ok:
            self.log.warning("连续返回 %d 次仍未回到列表", max_backs)
        return ok

    def _is_on_list(self) -> bool:
        try:
            act = self.d.app_current().get("activity") or ""
        except Exception:
            return False
        if "MainActivity" not in act:
            return False
        return self.d(**S.HOME["job_card"]).count > 0
