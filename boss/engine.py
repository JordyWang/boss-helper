"""投递引擎:编排"推荐列表 → 职位详情 → 立即沟通"的批量流程。"""
from __future__ import annotations

import logging
from typing import Tuple

from uiautomator2 import Device

from .config import AppConfig
from .filters import JobFilter
from .pages.home import HomePage
from .pages.job_detail import JobDetailPage
from .pages.chat import ChatPage
from .records import Recorder
from .state import State, make_key


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
        path = cfg.safety.records_db
        self.recorder = Recorder(path) if path else None
        self._stop = False

    def _confirm(self, title: str, salary: str, company: str) -> str:
        """终端手动确认。返回 'y'(投递)/'n'(跳过)/'q'(停止)。"""
        prompt = (
            f"\n>>> 是否沟通该职位? {title} | {salary} | {company}\n"
            "    [y]投递 / [n]跳过 / [q]停止: "
        )
        while True:
            try:
                ans = input(prompt).strip().lower()
            except (EOFError, KeyboardInterrupt):
                return "q"
            if ans in ("y", "yes"):
                return "y"
            if ans in ("n", "no", "skip", ""):
                return "n"
            if ans in ("q", "quit", "stop"):
                return "q"
            print("    请输入 y / n / q")

    def _within_limits(self, applied_this_run: int) -> bool:
        if applied_this_run >= self.cfg.limits.max_apply_per_run:
            self.log.info("达到单次运行上限 %d,停止", self.cfg.limits.max_apply_per_run)
            return False
        if self.state.applied_today >= self.cfg.limits.max_apply_per_day:
            self.log.info("达到每日上限 %d,停止", self.cfg.limits.max_apply_per_day)
            return False
        return True

    def _record(
        self,
        action: str,
        title: str = "",
        salary: str = "",
        company: str = "",
        note: str = "",
    ) -> None:
        if self.recorder is not None:
            self.recorder.add(action, title, salary, company, note)

    def _process_card(self, card, applied_this_run: int) -> Tuple[int, bool]:
        """处理单个卡片;返回 (本次已投递数, 是否发生了页面跳转)。
        跳转后旧的 UiObject 引用可能失效,外层应重新扫屏。"""
        title = card.title
        salary = card.salary
        company = card.company
        if not title:
            return applied_this_run, False

        # 卡片 key 与详情页 key 都算同一个职位;任一命中即跳过
        card_key = make_key(title, salary, company)
        if self.state.is_seen(card_key):
            self.log.debug("已处理过(卡片键),跳过: %s", title)
            return applied_this_run, False

        # 卡片级预过滤,命中排除规则的职位不点进详情,减少跳转与风控暴露
        decision = self.filter.check(title, salary)
        if not decision.accept:
            self.log.info("跳过[%s] %s (%s)", decision.reason, title, salary)
            self.state.mark_skipped(card_key)
            self._record("filtered", title, salary, company, decision.reason)
            return applied_this_run, False

        if self.cfg.safety.confirm_before_apply:
            choice = self._confirm(title, salary, company)
            if choice == "q":
                self.log.info("用户选择停止,结束本次运行")
                self._stop = True
                return applied_this_run, False
            if choice != "y":
                self.log.info("用户跳过: %s", title)
                self.state.mark_skipped(card_key)
                self._record("skipped", title, salary, company, "用户手动跳过")
                return applied_this_run, False

        card.click()
        self.home.human_delay()

        detail_salary = self.detail.salary() or salary
        detail_title = self.detail.title() or title
        detail_key = make_key(detail_title, detail_salary, company)

        # 卡片读到的字段可能与详情页不一致;这里再校验一次
        if self.state.is_seen(detail_key):
            self.log.info("已处理过(详情页键),返回: %s", detail_title)
            self.state.mark_skipped(card_key)  # 记住这张卡,避免再次点进来
            self.home.back_to_list()
            return applied_this_run, True

        if not self.detail.communicate():
            self.log.warning("未找到'立即沟通'按钮,跳过: %s", detail_title)
            self._record("error", detail_title, detail_salary, company, "未找到'立即沟通'按钮")
            # 同一坑位反复读到错误字段时会一直命中这条错误,把两个键都标记为已见
            self.state.mark_skipped([card_key, detail_key])
            self.home.back_to_list()
            return applied_this_run, True

        self.detail.handle_after_communicate()

        # 进入会话后先扫描历史,避免重复打招呼/重复发简历
        if self.chat.in_chat():
            msgs = self.chat.read_messages()
            self.log.info("会话现状: %s", self.chat.summarize(msgs))
            if self.cfg.greeting.send_manual:
                if self.chat.should_send_greeting(msgs):
                    self.chat.send_greeting(self.cfg.greeting.messages)
                    # 发送后重新扫一次,供简历判定使用最新状态
                    msgs = self.chat.read_messages(settle_seconds=0.6)
                else:
                    self.log.info("已打过招呼或领先≥1条,跳过重复招呼语")
            already_sent_resume = self.chat.has_sent_resume(msgs)
            self.chat.handle_resume_dialog(
                self.cfg.greeting.send_resume, already_sent=already_sent_resume
            )

        # 同一职位在卡片与详情页文本可能微差,两个键都登记,避免下次重复点击
        self.state.mark_applied([card_key, detail_key])
        applied_this_run += 1
        self.log.info(
            "已建立沟通 (%d/%d, 今日 %d): %s %s",
            applied_this_run,
            self.cfg.limits.max_apply_per_run,
            self.state.applied_today,
            detail_title,
            detail_salary,
        )
        self._record("applied", detail_title, detail_salary, company)

        if not self.home.back_to_list():
            self.log.warning("投递后未能回到列表,停止本次运行")
            self._stop = True
        return applied_this_run, True

    def run(self) -> int:
        self.log.info(
            "开始批量沟通,单次上限 %d,今日已投 %d",
            self.cfg.limits.max_apply_per_run,
            self.state.applied_today,
        )
        if not self.home.open_recommend():
            self.log.error("无法进入推荐页,请检查 App 是否已登录并在首页")
            return 0

        applied = 0
        empty_rounds = 0
        max_rounds = 80

        try:
            for _round in range(max_rounds):
                if self._stop or not self._within_limits(applied):
                    break

                cards = self.home.job_cards()
                if not cards:
                    empty_rounds += 1
                    self.log.info("当前屏无职位卡片,下滑加载 (%d)", empty_rounds)
                    if empty_rounds >= 3:
                        self.log.warning("连续多屏无卡片,判定已到底,停止")
                        break
                    self.home.scroll()
                    continue

                empty_rounds = 0
                navigated = False
                for card in cards:
                    if self._stop or not self._within_limits(applied):
                        break
                    try:
                        applied, navigated = self._process_card(card, applied)
                    except Exception as exc:
                        self.log.error("处理卡片出错: %s", exc)
                        try:
                            self._record(
                                "error",
                                card.title,
                                card.salary,
                                card.company,
                                f"异常:{exc}",
                            )
                        except Exception:
                            pass
                        self.d.press("back")
                        self.home.human_delay()
                        self.home.back_to_list()
                    if navigated:
                        break  # 页面已变,外层重扫
                    self.home.job_delay()

                if not navigated:
                    self.log.info("本屏 %d 个卡片均无需处理,下滑", len(cards))
                    self.home.scroll()
        finally:
            if self.recorder is not None:
                self.recorder.close()
                self.recorder = None

        self.log.info(
            "本次运行结束,共建立沟通 %d 个,今日累计 %d",
            applied,
            self.state.applied_today,
        )
        return applied
