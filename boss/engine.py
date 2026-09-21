"""投递引擎:编排"推荐列表 → 职位详情 → 立即沟通"的批量流程。"""
from __future__ import annotations

import logging

from uiautomator2 import Device

from .config import AppConfig
from .filters import JobFilter
from .pages.home import HomePage
from .pages.job_detail import JobDetailPage
from .pages.chat import ChatPage
from .state import State


class ApplyEngine:
    def __init__(self, d: Device, cfg: AppConfig, state: State, log: logging.Logger):
        self.d = d
        self.cfg = cfg
        self.state = state
        self.log = log
        self.filter = JobFilter(cfg.filters)

        self.home = HomePage(d, cfg.timing, log)
        self.detail = JobDetailPage(d, cfg.timing, log)
        self.chat = ChatPage(d, cfg.timing, log)

    def _within_limits(self, applied_this_run: int) -> bool:
        if applied_this_run >= self.cfg.limits.max_apply_per_run:
            self.log.info("达到单次运行上限 %d,停止", self.cfg.limits.max_apply_per_run)
            return False
        if self.state.applied_today >= self.cfg.limits.max_apply_per_day:
            self.log.info("达到每日上限 %d,停止", self.cfg.limits.max_apply_per_day)
            return False
        return True

    def _key(self, title: str, salary: str, company: str = "") -> str:
        return f"{title}|{salary}|{company}".strip()

    def _process_card(self, card, applied_this_run: int) -> int:
        """处理单个卡片;返回更新后的本次已投递数。"""
        title = card.title
        salary = card.salary
        company = card.company
        if not title:
            return applied_this_run

        key = self._key(title, salary, company)
        if self.state.is_seen(key):
            self.log.debug("已处理过,跳过: %s", title)
            return applied_this_run

        # 卡片级预过滤,命中排除规则的职位不点进详情,减少跳转与风控暴露
        decision = self.filter.check(title, salary)
        if not decision.accept:
            self.log.info("跳过[%s] %s (%s)", decision.reason, title, salary)
            self.state.mark_skipped(key)
            return applied_this_run

        card.click()
        self.home.human_delay()

        # 详情页兜底读取(卡片未取到薪资时)
        detail_salary = self.detail.salary() or salary
        detail_title = self.detail.title() or title

        if not self.detail.communicate():
            self.log.warning("未找到'立即沟通'按钮,跳过: %s", detail_title)
            self.home.back()
            return applied_this_run

        self.detail.handle_after_communicate()

        if self.cfg.greeting.send_manual and self.chat.in_chat():
            self.chat.send_greeting(self.cfg.greeting.messages)

        self.state.mark_applied(self._key(detail_title, detail_salary, company))
        applied_this_run += 1
        self.log.info(
            "已建立沟通 (%d/%d, 今日 %d): %s %s",
            applied_this_run,
            self.cfg.limits.max_apply_per_run,
            self.state.applied_today,
            detail_title,
            detail_salary,
        )

        self.home.back()
        return applied_this_run

    def run(self) -> int:
        self.log.info("开始批量沟通,单次上限 %d,今日已投 %d",
                      self.cfg.limits.max_apply_per_run, self.state.applied_today)
        if not self.home.open_recommend():
            self.log.error("无法进入推荐页,请检查 App 是否已登录并在首页")
            return 0

        applied = 0
        empty_rounds = 0
        max_scrolls = 50

        for scroll in range(max_scrolls):
            if not self._within_limits(applied):
                break

            cards = self.home.job_cards()
            if not cards:
                empty_rounds += 1
                self.log.info("当前屏无职位卡片,下滑加载 (%d)", empty_rounds)
                if empty_rounds >= 3:
                    self.log.warning("连续多屏无卡片,可能选择器需校准,停止")
                    break
                self.home.scroll()
                continue

            empty_rounds = 0
            self.log.info("第 %d 屏,发现 %d 个卡片", scroll + 1, len(cards))

            for card in cards:
                if not self._within_limits(applied):
                    break
                try:
                    applied = self._process_card(card, applied)
                except Exception as exc:  # 单个职位失败不影响整体
                    self.log.error("处理卡片出错: %s", exc)
                    self.d.press("back")
                    self.home.human_delay()
                self.home.job_delay()

            if self._within_limits(applied):
                self.home.scroll()

        self.log.info("本次运行结束,共建立沟通 %d 个,今日累计 %d", applied, self.state.applied_today)
        return applied
