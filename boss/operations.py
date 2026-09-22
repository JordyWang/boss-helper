"""可单独调试的原子操作注册表。

CLI 不再维护一串难以扩展的 ``if/elif``。每个操作声明是否需要设备、是否
会启动 App、以及是否需要 ``--yes``，执行前后由同一套入口处理。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from .application import ApplyService
from .capture import (
    record_observation,
    save_conversation,
    save_job,
    save_messages,
)
from .config import AppConfig
from .device import health as device_health
from .domain import Job, Message
from .filters import JobFilter
from .message_identity import normalize_message_value
from .pages.chat import ChatPage
from .pages.conversations import ConversationListPage
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
    conversations: Optional[ConversationListPage] = None
    state: Optional[StatePort] = None
    artifacts: Optional[Any] = None
    # SQLite Recorder/兼容的数据采集仓库。保持可选，便于无设备单元测试和
    # 外部调用方继续使用旧版 OperationContext。
    recorder: Optional[Any] = None


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


def _conversations(ctx: OperationContext) -> ConversationListPage:
    if ctx.conversations is None:
        raise RuntimeError("该操作未初始化会话列表页")
    return ctx.conversations


def _run_id(ctx: OperationContext) -> str:
    artifacts = ctx.artifacts or getattr(ctx.log, "run_artifacts", None)
    return str(getattr(artifacts, "run_id", "") or "")


def _save_job(ctx: OperationContext, job: Any, source: str) -> None:
    save_job(ctx.recorder, job, source=source, run_id=_run_id(ctx), log=ctx.log)


def _save_conversation_preview(ctx: OperationContext, entry: Any, source: str = "list") -> None:
    # ConversationPreview.as_dict() 是稳定的可序列化快照；若外部 fake 没有
    # 该方法，capture 层仍会安全跳过，不影响原有操作。
    payload: Any = entry
    try:
        as_dict = getattr(entry, "as_dict", None)
        if callable(as_dict):
            payload = as_dict()
    except Exception:
        payload = entry
    save_conversation(
        ctx.recorder,
        payload,
        run_id=_run_id(ctx),
        source=source,
        include_messages=False,
        log=ctx.log,
    )


def _save_chat_messages(ctx: OperationContext, messages: Any, conversation_id: str = "") -> int:
    return save_messages(
        ctx.recorder,
        messages,
        conversation_id,
        run_id=_run_id(ctx),
        log=ctx.log,
    )


def _safe_object_value(obj: Any, name: str, default: Any = "") -> Any:
    """读取页面对象属性，兼容方法、普通属性和测试 double。"""
    try:
        value = getattr(obj, name, default)
        if callable(value):
            value = value()
        return default if value is None else value
    except Exception:
        return default


def _observe(ctx: OperationContext, entity_type: str, entity_id: str, payload: Any) -> None:
    record_observation(
        ctx.recorder,
        entity_type,
        entity_id,
        payload,
        run_id=_run_id(ctx),
        log=ctx.log,
    )


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
    for visible_card in cards:
        try:
            _save_job(ctx, _job_from_card(visible_card), "detail_screen")
        except Exception as exc:
            ctx.log.debug("保存详情页职位屏幕快照失败: %s", exc)
    index = getattr(ctx.args, "index", 0)
    if index < 0 or index >= len(cards):
        ctx.log.error("卡片索引越界: %d (当前共有 %d 张)", index, len(cards))
        return 1
    card = cards[index]
    job = _job_from_card(card)
    _save_job(ctx, job, "detail_card")
    ctx.log.info("点进第 %d 个: %s | %s | %s", index, job.title, job.salary, job.company)
    card.click()
    home.human_delay()
    detail_title = detail.title()
    detail_salary = detail.salary()
    detail_company = _safe_object_value(detail, "company", job.company)
    _save_job(
        ctx,
        Job.from_values(detail_title or job.title, detail_salary or job.salary, detail_company or job.company),
        "detail",
    )
    _observe(
        ctx,
        "job_detail",
        job.key,
        {
            "title": detail_title or job.title,
            "salary": detail_salary or job.salary,
            "company": detail_company or job.company,
        },
    )
    ctx.log.info("详情页标题=%s 薪资=%s", detail_title, detail_salary)
    return 0


def op_read(ctx: OperationContext) -> int:
    detail = _detail(ctx)
    title = detail.title()
    salary = detail.salary()
    boss_name = detail.boss_name()
    _save_job(
        ctx,
        Job.from_values(title, salary, _safe_object_value(detail, "company", "")),
        "detail_read",
    )
    _observe(
        ctx,
        "job_detail",
        Job.from_values(title, salary, _safe_object_value(detail, "company", "")).key,
        {"title": title, "salary": salary, "boss_name": boss_name},
    )
    ctx.log.info(
        "当前详情页: 标题=%s 薪资=%s boss=%s",
        title,
        salary,
        boss_name,
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
    if ok:
        # 发送成功本身也是会话数据；若随后设备断开，仍保留我方这条消息。
        conversation_id = str(getattr(ctx.args, "conversation_id", "") or "")
        if not conversation_id:
            getter = getattr(chat, "conversation_id", None)
            if callable(getter):
                try:
                    conversation_id = str(getter() or "")
                except Exception:
                    conversation_id = ""
        _save_chat_messages(ctx, [Message(text, "me", "text")], conversation_id)
    ctx.log.info("在会话页发送 -> %s", ok)
    return 0 if ok else 1


def op_messages(ctx: OperationContext) -> int:
    chat = _chat(ctx)
    if not chat.in_chat():
        ctx.log.error("当前不在会话页")
        return 1
    messages = chat.read_messages()
    conversation_id = getattr(ctx.args, "conversation_id", "") or ""
    if not conversation_id:
        getter = getattr(chat, "conversation_id", None)
        if callable(getter):
            try:
                conversation_id = str(getter() or "")
            except Exception:
                conversation_id = ""
    # 先写 SQLite，再生成本次运行的 JSON 归档；这样即使后续文件归档失败，
    # 已经从设备读到的消息仍然可查询。
    _save_chat_messages(ctx, messages, conversation_id)
    try:
        summary = chat.summarize(messages)
    except Exception:
        summary = "摘要失败"
    ctx.log.info("读到 %d 条气泡 (%s)", len(messages), summary)
    context = _safe_object_value(chat, "conversation_context", {})
    if isinstance(context, dict) or conversation_id:
        save_conversation(
            ctx.recorder,
            {
                "conversation_id": conversation_id,
                "context": context if isinstance(context, dict) else {},
            },
            run_id=_run_id(ctx),
            source="messages",
            include_messages=False,
            log=ctx.log,
        )
    artifacts = ctx.artifacts or getattr(ctx.log, "run_artifacts", None)
    if artifacts is not None:
        path = artifacts.save_messages(
            messages,
            getattr(ctx.args, "name", "") or None,
            conversation_id=conversation_id,
        )
        ctx.log.info("聊天消息已保存: %s", path)
    for index, message in enumerate(messages):
        ctx.log.info("  [%d] %s | %s | %s", index, message.sender, message.kind, message.text[:60])
    return 0


def _conversation_entry_id(entry: Any) -> str:
    """读取列表项 ID，并兼容旧的 ``context_id`` 字段。"""
    for name in ("conversation_id", "context_id", "local_id"):
        try:
            value = getattr(entry, name, "")
            if callable(value):
                value = value()
        except Exception:
            value = ""
        if value:
            return str(value)
    return ""


def _conversation_entry_key(entry: Any) -> str:
    identity = _conversation_entry_id(entry)
    if identity:
        return identity
    try:
        value = getattr(entry, "key", "")
        if callable(value):
            value = value()
    except Exception:
        value = ""
    return str(value or f"object:{id(entry)}")


def _conversation_entry_dict(entry: Any) -> dict:
    try:
        value = entry.as_dict()
        return dict(value) if isinstance(value, dict) else {}
    except Exception:
        return {}


def _safe_chat_value(chat: Any, name: str, default: Any) -> Any:
    try:
        value = getattr(chat, name, default)
        if callable(value):
            value = value()
        return default if value is None else value
    except Exception:
        return default


def _capture_conversation(
    ctx: OperationContext,
    listing: ConversationListPage,
    chat: ChatPage,
    entry: Any,
    ordinal: int,
    requested_id: str = "",
) -> Tuple[bool, bool]:
    """打开一个列表项、读取并保存，然后返回 ``(saved, back_ok)``。"""
    entry_id = _conversation_entry_id(entry)
    label = getattr(entry, "name", "") or entry_id or "<未知会话>"
    _save_conversation_preview(ctx, entry)
    if not listing.open_conversation(entry):
        ctx.log.warning("会话打开失败，跳过: %s", label)
        return False, True

    saved = False
    back_ok = True
    try:
        if not chat.in_chat():
            raise RuntimeError("打开后未进入聊天页")
        context = _safe_chat_value(chat, "conversation_context", {})
        if not isinstance(context, dict):
            context = {}
        chat_id = str(_safe_chat_value(chat, "conversation_id", "") or "")

        # 列表 ID 是匹配主键；聊天页标题可能因职位/公司展示变化而变化，
        # 只能作为辅助信息保存，不能覆盖列表中已经匹配到的 ID。
        conversation_id = entry_id or chat_id
        if not conversation_id:
            ctx.log.warning("会话没有可用 ID，将保存但无法稳定回查: %s", label)
        # 设备返回的消息一旦拿到就写入 SQLite；JSON 归档仍作为本次运行的
        # 可移交文件保留。读取上下文在前只为尽早拿到正确的去重会话 ID。
        messages = list(chat.read_messages() or [])
        message_count = _save_chat_messages(ctx, messages, conversation_id)
        artifacts = ctx.artifacts or getattr(ctx.log, "run_artifacts", None)
        if artifacts is None:
            raise RuntimeError("当前运行没有归档上下文")
        preview = _conversation_entry_dict(entry)
        requested_name = str(getattr(ctx.args, "name", "") or "").strip()
        archive_name = requested_name or f"conversation_{ordinal:03d}"
        payload = {
            "schema_version": 1,
            "conversation_id": conversation_id,
            "conversation_id_source": "list" if entry_id else ("chat" if chat_id else "unknown"),
            "requested_conversation_id": requested_id,
            "chat_conversation_id": chat_id,
            "context": context,
            "list_preview": preview,
            "messages": messages,
        }
        # 会话摘要和完整消息一起幂等写入 SQLite；消息已经在上一步落库，
        # 这里的调用主要补充公司/职位/联系人等上下文。
        save_conversation(
            ctx.recorder,
            payload,
            run_id=_run_id(ctx),
            source="chat",
            include_messages=message_count == 0,
            log=ctx.log,
        )
        path = artifacts.save_conversation(
            payload, name=archive_name
        )
        saved = True
        ctx.log.info("会话已保存: %s（%d 条消息，id=%s）", path, len(messages), conversation_id or "-")
    except Exception as exc:
        ctx.log.error("读取/保存会话失败[%s]: %s", label, exc)
    finally:
        try:
            back_ok = bool(listing.back_to_list())
        except Exception as exc:
            ctx.log.error("返回消息列表异常[%s]: %s", label, exc)
            back_ok = False
        if not back_ok:
            ctx.log.error("无法返回消息列表，停止会话归档")
    return saved, back_ok


def _list_conversation_ids(ctx: OperationContext, listing: ConversationListPage) -> int:
    """只列出当前可见会话 ID，不点击任何聊天行。"""
    entries = listing.visible()
    if not entries:
        ctx.log.warning("当前没有可读取的会话行")
        return 0
    for index, entry in enumerate(entries, 1):
        _save_conversation_preview(ctx, entry)
        ctx.log.info(
            "会话[%d] id=%s | %s | %s | %s",
            index,
            _conversation_entry_id(entry) or "<无稳定ID>",
            getattr(entry, "name", "") or "<未知联系人>",
            getattr(entry, "company", "") or "-",
            getattr(entry, "job_title", "") or "-",
        )
    ctx.log.info("已列出 %d 个当前可见会话（未打开聊天）", len(entries))
    return 0


def _archive_first_conversations(
    ctx: OperationContext,
    listing: ConversationListPage,
    chat: ChatPage,
    target: int,
    max_scrolls: int,
) -> int:
    seen = set()
    saved = 0
    scroll_rounds = 0
    while saved < target and scroll_rounds <= max_scrolls:
        entries = listing.visible()
        if not entries:
            ctx.log.warning("当前没有可读取的会话行")
            break
        progress = False
        for entry in entries:
            if saved >= target:
                break
            key = _conversation_entry_key(entry)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            progress = True
            ctx.log.info(
                "打开会话 [%d/%d]: %s | %s | %s | id=%s",
                saved + 1,
                target,
                getattr(entry, "name", "") or "<未知联系人>",
                getattr(entry, "company", "") or "-",
                getattr(entry, "job_title", "") or "-",
                key or "<无稳定ID>",
            )
            ok, back_ok = _capture_conversation(ctx, listing, chat, entry, saved + 1)
            if ok:
                saved += 1
            if not back_ok:
                ctx.log.error("返回列表失败，已停止会话归档")
                ctx.log.info("会话归档完成: %d/%d", saved, target)
                return 0 if saved else 1

        if saved >= target:
            break
        # 显式 count 模式允许有限滚动查找更多条目，但永远受 max_scrolls
        # 约束；没有新条目时下一轮会很快结束，不会无限操作设备。
        if not progress:
            break
        if scroll_rounds >= max_scrolls:
            break
        listing.scroll()
        scroll_rounds += 1

    ctx.log.info("会话归档完成: %d/%d", saved, target)
    return 0 if saved else 1


def op_conversations(ctx: OperationContext) -> int:
    """管理已有会话：列出 ID，或按 ID/显式数量只读归档。"""
    listing = _conversations(ctx)
    target_id = str(getattr(ctx.args, "conversation_id", "") or "").strip()
    list_only = bool(getattr(ctx.args, "list_only", False))
    count_value = getattr(ctx.args, "count", None)

    # 显式 --count 0 是安全的空操作，连列表都不必打开；没有 --count
    # 时 count=None，继续走默认“只列 ID”路径。
    if not target_id and not list_only and count_value is not None:
        try:
            if int(count_value) <= 0:
                ctx.log.info("会话归档数量为 0，跳过")
                return 0
        except (TypeError, ValueError):
            pass

    # 没有明确选择目标时默认只列 ID，避免一次命令把所有聊天逐个打开。
    if not listing.open_list():
        ctx.log.error("无法打开消息列表")
        return 1
    if list_only or (not target_id and count_value is None):
        return _list_conversation_ids(ctx, listing)
    if target_id:
        max_scrolls = getattr(ctx.args, "max_scrolls", 8)
        finder = getattr(listing, "find_by_id", None)
        if callable(finder):
            try:
                entry = finder(
                    target_id,
                    max_scrolls=max_scrolls,
                    on_visible=lambda rows: [
                        _save_conversation_preview(ctx, row) for row in rows
                    ],
                )
            except TypeError:
                # 兼容只接受一个位置参数的轻量列表页适配器。
                try:
                    entry = finder(target_id, max_scrolls=max_scrolls)
                except TypeError:
                    entry = finder(target_id)
        else:
            # 兼容外部调用方传入的旧列表页实现：只在当前屏查找，绝不
            # 退化成无界遍历或自动打开其他会话。
            entry = next(
                (
                    item
                    for item in listing.visible()
                    if normalize_message_value(_conversation_entry_id(item))
                    == normalize_message_value(target_id)
                ),
                None,
            )
        if entry is None:
            ctx.log.error("未找到会话 ID: %s", target_id)
            return 1
        ok, back_ok = _capture_conversation(
            ctx, listing, _chat(ctx), entry, 1, requested_id=target_id
        )
        return 0 if ok and back_ok else 1

    try:
        target = int(count_value)
    except (TypeError, ValueError):
        target = 0
    if target <= 0:
        ctx.log.info("会话归档数量为 0，跳过")
        return 0
    max_scrolls = getattr(ctx.args, "max_scrolls", None)
    try:
        max_scrolls = max(0, int(max_scrolls))
    except (TypeError, ValueError):
        max_scrolls = max(2, target + 2)
    return _archive_first_conversations(ctx, listing, _chat(ctx), target, max_scrolls)


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
    _observe(ctx, "device_health", str(info.get("package", "") or ""), info)
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
        _save_job(ctx, job, "cards")
        _print_job(ctx, index, job, state.is_seen(job.key))
    return 0


def op_screenshot(ctx: OperationContext) -> int:
    path = _home(ctx).screenshot(getattr(ctx.args, "name", "") or None)
    _observe(ctx, "screenshot", path, {"path": path})
    ctx.log.info("截图已保存: %s", path)
    return 0


def op_scroll(ctx: OperationContext) -> int:
    home = _home(ctx)
    count = getattr(ctx.args, "count", None)
    count = 1 if count is None else count
    direction = getattr(ctx.args, "direction", "up")
    for _ in range(count):
        home.scroll(direction)
    ctx.log.info("已滚动 %d 次,方向=%s", count, direction)
    cards = home.job_cards()
    ctx.log.info("滚动后当前有 %d 张职位卡片", len(cards))
    for card in cards:
        _save_job(ctx, _job_from_card(card), "scroll")
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
    if ok:
        label = "同意" if action == "agree" else "拒绝"
        conversation_id = str(getattr(ctx.args, "conversation_id", "") or "")
        if not conversation_id:
            getter = getattr(chat, "conversation_id", None)
            if callable(getter):
                try:
                    conversation_id = str(getter() or "")
                except Exception:
                    conversation_id = ""
        _save_chat_messages(
            ctx, [Message(label, "system", "action")], conversation_id
        )
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
        recorder=ctx.recorder,
    )
    previews = service.preview(getattr(ctx.args, "rounds", 5))
    accepted = 0
    for index, preview in enumerate(previews):
        _save_job(ctx, preview.job, "dry_run")
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
    "conversations": OperationSpec(
        "conversations",
        op_conversations,
        "列出会话 ID，或按 ID/显式数量只读保存对话",
        side_effect="read",
        pages=("conversations", "chat"),
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
