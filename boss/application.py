"""批处理应用服务。

这里仅编排职位、过滤策略、状态仓库和页面端口；不直接导入
uiautomator2。真实设备的组装放在 :mod:`boss.engine`，因此这一层可以用
fake 页面对象独立验证。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Tuple

from .config import AppConfig
from .domain import Job, JobPreview, RunSummary
from .filters import JobFilter
from .ports import ChatPort, DetailPort, HomePort, RecorderPort, StatePort


class ApplyService:
    """执行“推荐列表 → 详情 → 沟通”的业务流程。"""

    max_rounds = 80
    max_empty_rounds = 3

    def __init__(
        self,
        home: HomePort,
        detail: DetailPort,
        chat: ChatPort,
        cfg: AppConfig,
        state: StatePort,
        log: logging.Logger,
        recorder: Optional[RecorderPort] = None,
        input_fn: Optional[Callable[[str], str]] = None,
        recover: Optional[Callable[[], None]] = None,
    ):
        self.home = home
        self.detail = detail
        self.chat = chat
        self.cfg = cfg
        self.state = state
        self.log = log
        self.filter = JobFilter(cfg.filters)
        self.recorder = recorder
        self.input_fn = input if input_fn is None else input_fn
        self.recover = recover
        self._stop = False
        self._last_result = "unknown"
        self.last_summary = RunSummary()

    def close(self) -> None:
        """关闭记录器；可安全重复调用。"""
        if self.recorder is not None:
            recorder, self.recorder = self.recorder, None
            try:
                recorder.close()
            except Exception as exc:
                self.log.warning("关闭本地记录失败: %s", exc)

    def __enter__(self) -> "ApplyService":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _confirm(self, title: str, salary: str, company: str) -> str:
        prompt = (
            f"\n>>> 是否沟通该职位? {title} | {salary} | {company}\n"
            "    [y]投递 / [n]跳过 / [q]停止: "
        )
        while True:
            try:
                answer = self.input_fn(prompt).strip().lower()
            except (EOFError, KeyboardInterrupt):
                return "q"
            if answer in ("y", "yes"):
                return "y"
            if answer in ("n", "no", "skip", ""):
                return "n"
            if answer in ("q", "quit", "stop"):
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
        if self.recorder is None:
            return
        try:
            self.recorder.add(action, title, salary, company, note)
        except Exception as exc:
            # 记录失败不应让真实沟通流程中断。
            self.log.warning("写入本地记录失败: %s", exc)

    @staticmethod
    def _job_from_card(card: Any) -> Tuple[Job, Any]:
        """将 UI 卡片或测试 double 转成领域对象。"""
        if isinstance(card, Job):
            return card, None
        to_job = getattr(card, "to_job", None)
        if callable(to_job):
            job = to_job()
            if isinstance(job, Job):
                return job, card
        return (
            Job.from_values(
                getattr(card, "title", ""),
                getattr(card, "salary", ""),
                getattr(card, "company", ""),
            ),
            card,
        )

    def _handle_chat(self) -> None:
        if not self.chat.in_chat():
            return
        messages = self.chat.read_messages()
        self.log.info("会话现状: %s", self.chat.summarize(messages))
        if self.cfg.greeting.send_manual:
            if self.chat.should_send_greeting(messages):
                self.chat.send_greeting(self.cfg.greeting.messages)
                messages = self.chat.read_messages(settle_seconds=0.6)
            else:
                self.log.info("已打过招呼或领先≥1条,跳过重复招呼语")
        already_sent_resume = self.chat.has_sent_resume(messages)
        self.chat.handle_resume_dialog(
            self.cfg.greeting.send_resume, already_sent=already_sent_resume
        )

    def _process_job(
        self, job: Job, card: Any, applied_this_run: int
    ) -> Tuple[int, bool, str]:
        """处理一个领域职位，返回 (已投递数, 是否跳转, 结果类型)。"""
        if not job.valid:
            return applied_this_run, False, "invalid"

        card_key = job.key
        if self.state.is_seen(card_key):
            self.log.debug("已处理过(卡片键),跳过: %s", job.title)
            return applied_this_run, False, "seen"

        decision = self.filter.check_job(job)
        if not decision.accept:
            self.log.info("跳过[%s] %s (%s)", decision.reason, job.title, job.salary)
            self.state.mark_skipped(card_key)
            self._record("filtered", job.title, job.salary, job.company, decision.reason)
            return applied_this_run, False, "filtered"

        if self.cfg.safety.confirm_before_apply:
            choice = self._confirm(job.title, job.salary, job.company)
            if choice == "q":
                self.log.info("用户选择停止,结束本次运行")
                self._stop = True
                return applied_this_run, False, "stopped"
            if choice != "y":
                self.log.info("用户跳过: %s", job.title)
                self.state.mark_skipped(card_key)
                self._record("skipped", job.title, job.salary, job.company, "用户手动跳过")
                return applied_this_run, False, "skipped"

        if card is not None:
            card.click()
            self.home.human_delay()

        detail_job = Job.from_values(
            self.detail.title() or job.title,
            self.detail.salary() or job.salary,
            job.company,
        )
        detail_key = detail_job.key

        if self.state.is_seen(detail_key):
            self.log.info("已处理过(详情页键),返回: %s", detail_job.title)
            self.state.mark_skipped(card_key)
            self.home.back_to_list()
            return applied_this_run, True, "seen"

        if not self.detail.communicate():
            note = "未找到'立即沟通'按钮"
            self.log.warning("%s,跳过: %s", note, detail_job.title)
            self._record("error", detail_job.title, detail_job.salary, job.company, note)
            self.state.mark_skipped([card_key, detail_key])
            self.home.back_to_list()
            return applied_this_run, True, "error"

        self.detail.handle_after_communicate()
        self._handle_chat()
        self.state.mark_applied([card_key, detail_key])
        applied_this_run += 1
        self.log.info(
            "已建立沟通 (%d/%d, 今日 %d): %s %s",
            applied_this_run,
            self.cfg.limits.max_apply_per_run,
            self.state.applied_today,
            detail_job.title,
            detail_job.salary,
        )
        self._record("applied", detail_job.title, detail_job.salary, job.company)

        if not self.home.back_to_list():
            self.log.warning("投递后未能回到列表,停止本次运行")
            self._stop = True
        return applied_this_run, True, "applied"

    def _process_card(self, card: Any, applied_this_run: int) -> Tuple[int, bool]:
        """兼容旧接口：处理卡片并返回 (已投递数, 是否跳转)。"""
        job, card_obj = self._job_from_card(card)
        applied, navigated, result = self._process_job(job, card_obj, applied_this_run)
        self._last_result = result
        return applied, navigated

    def _recover_after_error(self) -> None:
        if self.recover is not None:
            self.recover()
            return
        # 没有设备专属恢复器时，端口本身仍可能知道如何回到列表。
        self.home.back_to_list()

    def preview(self, max_rounds: int = 5) -> Tuple[JobPreview, ...]:
        """只扫描和评估职位，不点击卡片、不写入状态、不建立沟通。"""
        previews = []
        if max_rounds <= 0 or not self.home.open_recommend():
            return tuple(previews)

        empty_rounds = 0
        for _round in range(max_rounds):
            cards = self.home.job_cards()
            if not cards:
                empty_rounds += 1
                if empty_rounds >= self.max_empty_rounds:
                    break
                self.home.scroll()
                continue

            empty_rounds = 0
            for card in cards:
                job, _ = self._job_from_card(card)
                decision = self.filter.check_job(job)
                previews.append(
                    JobPreview(
                        job=job,
                        accepted=decision.accept,
                        reason=decision.reason,
                        seen=self.state.is_seen(job.key),
                    )
                )
            if _round + 1 < max_rounds:
                self.home.scroll()
        return tuple(previews)

    def run(self) -> int:
        self.log.info(
            "开始批量沟通,单次上限 %d,今日已投 %d",
            self.cfg.limits.max_apply_per_run,
            self.state.applied_today,
        )
        applied = 0
        filtered = 0
        skipped = 0
        errors = 0
        empty_rounds = 0

        try:
            if not self.home.open_recommend():
                self.log.error("无法进入推荐页,请检查 App 是否已登录并在首页")
                return 0

            for _round in range(self.max_rounds):
                if self._stop or not self._within_limits(applied):
                    break
                cards = self.home.job_cards()
                if not cards:
                    empty_rounds += 1
                    self.log.info("当前屏无职位卡片,下滑加载 (%d)", empty_rounds)
                    if empty_rounds >= self.max_empty_rounds:
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
                        self._last_result = "unknown"
                        applied, navigated = self._process_card(card, applied)
                        result = self._last_result
                        if result == "filtered":
                            filtered += 1
                        elif result == "skipped":
                            skipped += 1
                        elif result == "error":
                            errors += 1
                    except Exception as exc:
                        errors += 1
                        self.log.error("处理卡片出错: %s", exc)
                        try:
                            job, _ = self._job_from_card(card)
                            self._record(
                                "error",
                                job.title,
                                job.salary,
                                job.company,
                                f"异常:{exc}",
                            )
                        except Exception:
                            pass
                        try:
                            self._recover_after_error()
                        except Exception as recovery_exc:
                            self.log.warning("异常恢复失败: %s", recovery_exc)
                            self._stop = True
                    if navigated:
                        break
                    if not self._stop:
                        self.home.job_delay()

                if not navigated and not self._stop:
                    self.log.info("本屏 %d 个卡片均无需处理,下滑", len(cards))
                    self.home.scroll()
        finally:
            self.last_summary = RunSummary(
                applied=applied,
                filtered=filtered,
                skipped=skipped,
                errors=errors,
                stopped=self._stop,
            )
            self.close()

        self.log.info(
            "本次运行结束,共建立沟通 %d 个,今日累计 %d",
            applied,
            self.state.applied_today,
        )
        return applied


__all__ = ["ApplyService"]
