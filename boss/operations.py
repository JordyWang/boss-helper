"""可单独调试的原子操作注册表。

CLI 不再维护一串难以扩展的 ``if/elif``。每个操作声明是否需要设备、是否
会启动 App、以及是否需要 ``--yes``，执行前后由同一套入口处理。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from .application import ApplyService
from .config import AppConfig
from .device import health as device_health
from .domain import Job
from .filters import JobFilter
from .pages.chat import ChatPage
from .pages.home import HomePage
from .pages.job_detail import JobDetailPage
from .ports import StatePort
from .selectors import GLOBAL_POPUP_CLOSE
from .state import State


@dataclass
class OperationContext:
    args: Any
    cfg: AppConfig
    log: logging.Logger
    device: Optional[Any] = None
    home: Optional[HomePage] = None
    detail: Optional[JobDetailPage] = None
    chat: Optional[ChatPage] = None
    state: Optional[StatePort] = None
    artifacts: Optional[Any] = None


@dataclass(frozen=True)
class OperationSpec:
    name: str
    handler: Callable[[OperationContext], int]
    description: str
    side_effect: str = "read"
    requires_device: bool = True
    ensure_app: bool = True
    requires_yes: bool = False
    # 由 CLI 根据声明按需组装页面对象；这样 ``health`` 等诊断操作不会
    # 创建页面，``filter-check`` 更不会触碰设备。
    pages: Tuple[str, ...] = ()
    requires_state: bool = False
    state_read_only: bool = False


def _job_from_card(card: Any) -> Job:
    to_job = getattr(card, "to_job", None)
    if callable(to_job):
        job = to_job()
        if isinstance(job, Job):
            return job
    return Job.from_values(
        getattr(card, "title", ""),
        getattr(card, "salary", ""),
        getattr(card, "company", ""),
    )


def _print_job(ctx: OperationContext, index: int, job: Job, seen: bool = False) -> None:
    decision = JobFilter(ctx.cfg.filters).check_job(job)
    status = "已处理" if seen else ("通过" if decision.accept else decision.reason)
    ctx.log.info(
        "[%d] %s | %s | %s | %s",
        index,
        job.title or "<无标题>",
        job.salary or "-",
        job.company or "-",
        status,
    )


def _home(ctx: OperationContext) -> HomePage:
    if ctx.home is None:
        raise RuntimeError("该操作未初始化首页")
    return ctx.home


def _detail(ctx: OperationContext) -> JobDetailPage:
    if ctx.detail is None:
        raise RuntimeError("该操作未初始化详情页")
    return ctx.detail


def _chat(ctx: OperationContext) -> ChatPage:
    if ctx.chat is None:
        raise RuntimeError("该操作未初始化会话页")
    return ctx.chat


def op_recommend(ctx: OperationContext) -> int:
    ok = _home(ctx).open_recommend()
    ctx.log.info("open_recommend -> %s", ok)
    return 0 if ok else 1


def op_detail(ctx: OperationContext) -> int:
    home = _home(ctx)
    detail = _detail(ctx)
    if not home.open_recommend():
        return 1
    cards = home.job_cards()
    index = getattr(ctx.args, "index", 0)
    if index < 0 or index >= len(cards):
        ctx.log.error("卡片索引越界: %d (当前共有 %d 张)", index, len(cards))
        return 1
    card = cards[index]
    job = _job_from_card(card)
    ctx.log.info("点进第 %d 个: %s | %s | %s", index, job.title, job.salary, job.company)
    card.click()
    home.human_delay()
    ctx.log.info("详情页标题=%s 薪资=%s", detail.title(), detail.salary())
    return 0


def op_read(ctx: OperationContext) -> int:
    detail = _detail(ctx)
    ctx.log.info(
        "当前详情页: 标题=%s 薪资=%s boss=%s",
        detail.title(),
        detail.salary(),
        detail.boss_name(),
    )
    return 0


def op_communicate(ctx: OperationContext) -> int:
    detail = _detail(ctx)
    ok = detail.communicate()
    ctx.log.info("点击立即沟通 -> %s", ok)
    if ok:
        detail.handle_after_communicate()
    return 0 if ok else 1


def op_send(ctx: OperationContext) -> int:
    chat = _chat(ctx)
    text = getattr(ctx.args, "text", "") or (
        ctx.cfg.greeting.messages[0] if ctx.cfg.greeting.messages else ""
    )
    if not text:
        ctx.log.error("无消息内容,用 --text 指定")
        return 1
    ok = chat.send_message(text)
    ctx.log.info("在会话页发送 -> %s", ok)
    return 0 if ok else 1


def op_messages(ctx: OperationContext) -> int:
    chat = _chat(ctx)
    if not chat.in_chat():
        ctx.log.error("当前不在会话页")
        return 1
    messages = chat.read_messages()
    ctx.log.info("读到 %d 条气泡 (%s)", len(messages), chat.summarize(messages))
    artifacts = ctx.artifacts or getattr(ctx.log, "run_artifacts", None)
    if artifacts is not None:
        conversation_id = getattr(ctx.args, "conversation_id", "") or ""
        if not conversation_id:
            # 标题只是上下文，不是 Boss 的官方会话 ID；如果调用方能拿到
            # 服务端 ID，应通过 --conversation-id 或 API 数据显式传入。
            getter = getattr(chat, "conversation_id", None)
            if callable(getter):
                try:
                    conversation_id = str(getter() or "")
                except Exception:
                    conversation_id = ""
        path = artifacts.save_messages(
            messages,
            getattr(ctx.args, "name", "") or None,
            conversation_id=conversation_id,
        )
        ctx.log.info("聊天消息已保存: %s", path)
    for index, message in enumerate(messages):
        ctx.log.info("  [%d] %s | %s | %s", index, message.sender, message.kind, message.text[:60])
    return 0


def op_back(ctx: OperationContext) -> int:
    _home(ctx).back()
    ctx.log.info("已返回")
    return 0


def op_home(ctx: OperationContext) -> int:
    ok = _home(ctx).back_to_list()
    ctx.log.info("back_to_list -> %s", ok)
    return 0 if ok else 1


def op_health(ctx: OperationContext) -> int:
    info = device_health(ctx.device, ctx.cfg.package)
    ctx.log.info(
        "设备: package=%s activity=%s android=%s model=%s window=%s",
        info.get("package", "?"),
        info.get("activity", "?"),
        info.get("android_version", "?"),
        info.get("model", "?"),
        info.get("window_size", "?"),
    )
    if ctx.cfg.package:
        ctx.log.info("目标 App 前台: %s", info.get("package_ok", False))
    return 0


def op_cards(ctx: OperationContext) -> int:
    home = _home(ctx)
    if not home.open_recommend():
        return 1
    cards = home.job_cards()
    state = ctx.state or State(ctx.cfg.safety.state_path, read_only=True)
    ctx.log.info("当前发现 %d 张职位卡片", len(cards))
    for index, card in enumerate(cards):
        job = _job_from_card(card)
        _print_job(ctx, index, job, state.is_seen(job.key))
    return 0


def op_screenshot(ctx: OperationContext) -> int:
    path = _home(ctx).screenshot(getattr(ctx.args, "name", "") or None)
    ctx.log.info("截图已保存: %s", path)
    return 0


def op_scroll(ctx: OperationContext) -> int:
    home = _home(ctx)
    count = getattr(ctx.args, "count", 1)
    direction = getattr(ctx.args, "direction", "up")
    for _ in range(count):
        home.scroll(direction)
    ctx.log.info("已滚动 %d 次,方向=%s", count, direction)
    cards = home.job_cards()
    ctx.log.info("滚动后当前有 %d 张职位卡片", len(cards))
    return 0


def op_draft(ctx: OperationContext) -> int:
    chat = _chat(ctx)
    if not chat.in_chat():
        ctx.log.error("当前不在会话页")
        return 1
    text = getattr(ctx.args, "text", "")
    if not text:
        ctx.log.error("无草稿内容,用 --text 指定")
        return 1
    ok = chat.type_text(text)
    ctx.log.info("草稿写入 -> %s（不会发送）", ok)
    return 0 if ok else 1


def op_resume(ctx: OperationContext) -> int:
    chat = _chat(ctx)
    if not chat.in_chat():
        ctx.log.error("当前不在会话页")
        return 1
    action = getattr(ctx.args, "action", "inspect")
    if action == "inspect":
        visible = chat.resume_dialog_visible()
        ctx.log.info("索要简历弹窗: %s", "存在" if visible else "不存在")
        return 0
    if not getattr(ctx.args, "yes", False):
        ctx.log.error("resume=%s 会处理真实弹窗,确认请加 --yes", action)
        return 2
    ok = chat.handle_resume_action(action, reason="命令行显式操作")
    ctx.log.info("简历弹窗处理(%s) -> %s", action, ok)
    return 0 if ok else 1


def op_dismiss_popups(ctx: OperationContext) -> int:
    count = _home(ctx).dismiss_popups(GLOBAL_POPUP_CLOSE)
    ctx.log.info("已关闭 %d 个弹窗", count)
    return 0


def op_dry_run(ctx: OperationContext) -> int:
    service = ApplyService(
        home=_home(ctx),
        detail=_detail(ctx),
        chat=_chat(ctx),
        cfg=ctx.cfg,
        state=ctx.state or State(ctx.cfg.safety.state_path, read_only=True),
        log=ctx.log,
    )
    previews = service.preview(getattr(ctx.args, "rounds", 5))
    accepted = 0
    for index, preview in enumerate(previews):
        status = "已处理" if preview.seen else ("通过" if preview.accepted else preview.reason)
        if preview.accepted and not preview.seen:
            accepted += 1
        ctx.log.info(
            "[%d] %s | %s | %s | %s",
            index,
            preview.job.title or "<无标题>",
            preview.job.salary or "-",
            preview.job.company or "-",
            status,
        )
    ctx.log.info("dry-run 完成: 扫描 %d 个,预计可沟通 %d 个", len(previews), accepted)
    return 0


def op_filter_check(ctx: OperationContext) -> int:
    title = str(getattr(ctx.args, "title", "") or "").strip()
    if not title:
        ctx.log.error("缺少 --title")
        return 1
    job = Job.from_values(
        title,
        getattr(ctx.args, "salary", ""),
        getattr(ctx.args, "company", ""),
    )
    decision = JobFilter(ctx.cfg.filters).check_job(job)
    ctx.log.info(
        "过滤结果: %s | 标题=%s | 薪资=%s | 原因=%s",
        "通过" if decision.accept else "跳过",
        job.title,
        job.salary or "-",
        decision.reason,
    )
    # 命令本身执行成功；是否通过由日志中的结果表达，便于脚本继续处理。
    return 0


OPERATION_SPECS: Dict[str, OperationSpec] = {
    "recommend": OperationSpec(
        "recommend", op_recommend, "进入推荐列表", side_effect="navigate", pages=("home",)
    ),
    "detail": OperationSpec(
        "detail", op_detail, "打开指定职位详情", side_effect="navigate", pages=("home", "detail")
    ),
    "read": OperationSpec("read", op_read, "读取当前详情", side_effect="read", pages=("detail",)),
    "communicate": OperationSpec(
        "communicate",
        op_communicate,
        "建立职位沟通",
        side_effect="send",
        requires_yes=True,
        pages=("detail",),
    ),
    "send": OperationSpec(
        "send",
        op_send,
        "发送聊天消息",
        side_effect="send",
        requires_yes=True,
        pages=("chat",),
    ),
    "messages": OperationSpec(
        "messages", op_messages, "读取聊天消息", side_effect="read", pages=("chat",)
    ),
    "back": OperationSpec("back", op_back, "返回上一页", side_effect="navigate", pages=("home",)),
    "home": OperationSpec("home", op_home, "返回职位列表", side_effect="navigate", pages=("home",)),
    "health": OperationSpec(
        "health", op_health, "检查设备和 App 状态", side_effect="read", ensure_app=False
    ),
    "cards": OperationSpec(
        "cards",
        op_cards,
        "列出当前职位卡片",
        side_effect="read",
        pages=("home",),
        requires_state=True,
        state_read_only=True,
    ),
    "screenshot": OperationSpec(
        "screenshot", op_screenshot, "保存当前截图", side_effect="read", pages=("home",)
    ),
    "scroll": OperationSpec(
        "scroll", op_scroll, "滚动职位列表", side_effect="navigate", pages=("home",)
    ),
    "draft": OperationSpec(
        "draft", op_draft, "写入聊天草稿但不发送", side_effect="draft", pages=("chat",)
    ),
    "resume": OperationSpec(
        "resume", op_resume, "查看或处理简历弹窗", side_effect="send", pages=("chat",)
    ),
    "dismiss-popups": OperationSpec(
        "dismiss-popups",
        op_dismiss_popups,
        "关闭常见弹窗",
        side_effect="navigate",
        pages=("home",),
    ),
    "dry-run": OperationSpec(
        "dry-run",
        op_dry_run,
        "扫描并评估职位但不沟通",
        side_effect="read",
        pages=("home", "detail", "chat"),
        requires_state=True,
        state_read_only=True,
    ),
    "filter-check": OperationSpec(
        "filter-check",
        op_filter_check,
        "本地检查职位过滤结果",
        side_effect="read",
        requires_device=False,
        ensure_app=False,
    ),
}


def operation_help() -> str:
    return "; ".join(
        f"{spec.name}({spec.side_effect}): {spec.description}"
        for spec in OPERATION_SPECS.values()
    )


def run_operation(ctx: OperationContext) -> int:
    operation_name = getattr(ctx.args, "op", None)
    try:
        spec = OPERATION_SPECS[operation_name]
    except KeyError as exc:
        raise ValueError(f"未知操作: {operation_name!r}") from exc
    if operation_requires_confirmation(spec, ctx.args):
        ctx.log.error("%s 会产生真实副作用,确认请加 --yes", spec.name)
        return 2
    return spec.handler(ctx)


def operation_requires_confirmation(spec: OperationSpec, args: Any) -> bool:
    """判断一次操作是否必须显式确认。

    ``resume inspect`` 是只读动作，而 ``agree/reject`` 会点击真实弹窗，
    因此它的确认条件由参数决定，不能只靠一个静态 ``requires_yes`` 字段。
    该函数同时供 CLI 做设备连接前的预检，避免误操作即使连接/启动 App。
    """
    if spec.requires_yes:
        return not getattr(args, "yes", False)
    if spec.name == "resume":
        return getattr(args, "action", "inspect") != "inspect" and not getattr(
            args, "yes", False
        )
    return False


__all__ = [
    "OPERATION_SPECS",
    "OperationContext",
    "OperationSpec",
    "operation_requires_confirmation",
    "operation_help",
    "run_operation",
]
