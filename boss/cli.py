"""命令行适配层。

命令函数只做参数转换和展示，设备/引擎组装委托给 ``runtime``，核心业务不
依赖 argparse。
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from typing import Any

from .artifacts import RunArtifacts, RunInProgressError
from .config import ConfigError, load_config
from .logger import close_logger, setup_logger
from .operations import (
    OPERATION_SPECS,
    OperationContext,
    operation_help,
    operation_requires_confirmation,
    run_operation,
)
from .runtime import create_engine
from .state import State


def _logger(args: Any):
    return setup_logger(artifacts=getattr(args, "artifacts", None))


def cmd_run(args: Any) -> int:
    log = _logger(args)
    cfg = load_config(args.config)
    if args.limit is not None:
        cfg.limits.max_apply_per_run = args.limit
        log.info("覆盖单次上限 -> %d", args.limit)

    artifacts = getattr(args, "artifacts", None)
    engine = create_engine(cfg, log, artifacts=artifacts)
    with engine:
        engine.run()
    return 0


def cmd_op(args: Any) -> int:
    """单独执行一个原子操作，便于逐个调试与校准。

    操作所需的设备、App 和页面对象由 ``OperationSpec`` 声明驱动。这样
    本地 ``filter-check`` 完全不连接设备，``health`` 只做诊断而不会启动
    App，其余操作才按需初始化真实页面对象。
    """
    log = _logger(args)
    cfg = load_config(args.config)

    operation_name = getattr(args, "op", None)
    spec = OPERATION_SPECS.get(operation_name)
    if spec is None:
        log.error("未知操作: %s", operation_name)
        return 1

    artifacts = getattr(args, "artifacts", None) or getattr(log, "run_artifacts", None)
    ctx = OperationContext(args=args, cfg=cfg, log=log, artifacts=artifacts)

    # 在连接/启动 App 之前拦截所有未确认的真实动作。
    if operation_requires_confirmation(spec, args):
        log.error("%s 会产生真实副作用,确认请加 --yes", spec.name)
        return 2

    if spec.requires_device:
        from .device import connect, ensure_app, record_app_version

        ctx.device = connect(cfg.serial, log)
        record_app_version(
            ctx.device,
            cfg.package,
            cfg.safety.app_version_path,
            log,
        )
        if spec.ensure_app:
            ensure_app(ctx.device, cfg.package, log)

    # 只为操作声明过的依赖创建对象，避免健康检查/本地过滤产生无关副作用。
    pages = set(spec.pages)
    if pages:
        from .pages.chat import ChatPage
        from .pages.home import HomePage
        from .pages.job_detail import JobDetailPage

    if "home" in pages:
        ctx.home = HomePage(ctx.device, cfg.timing, log, artifacts)
    if "detail" in pages:
        ctx.detail = JobDetailPage(ctx.device, cfg.timing, log, artifacts)
    if "chat" in pages:
        ctx.chat = ChatPage(ctx.device, cfg.timing, log, artifacts)
    if spec.requires_state:
        ctx.state = State(
            cfg.safety.state_path,
            read_only=spec.state_read_only,
        )

    return run_operation(ctx)


def cmd_dump(args: Any) -> int:
    from tools.dump_ui import dump

    log = _logger(args)
    path = dump(args.config, artifacts=getattr(args, "artifacts", None))
    log.info("UI dump 已保存: %s", path)
    return 0


def cmd_status(args: Any) -> int:
    log = _logger(args)
    cfg = load_config(args.config)
    state = State(cfg.safety.state_path)
    log.info("今日已投递: %d / %d", state.applied_today, cfg.limits.max_apply_per_day)
    log.info("历史处理职位数: %d", len(state.applied_keys()))
    log.info("本地记录: sqlite: %s", cfg.safety.records_db)
    return 0


def cmd_records(args: Any) -> int:
    log = _logger(args)
    cfg = load_config(args.config)
    path = cfg.safety.records_db
    if not path:
        log.error("未在配置中启用本地记录")
        return 1
    if not os.path.exists(path):
        log.info("暂无本地记录: %s", path)
        return 0

    from .records import Recorder

    rec = Recorder(path)
    try:
        counts = rec.counts()
        log.info(
            "%s  共 %d 条%s",
            path,
            rec.total(),
            f"  ({', '.join(f'{k}={v}' for k, v in counts.items())})" if counts else "",
        )
        if args.format == "csv":
            writer = csv.writer(sys.stdout, lineterminator="\n")
            writer.writerow(["时间", "动作", "职位", "薪资", "公司", "说明"])
            for row in rec.recent(args.tail):
                writer.writerow([item or "" for item in row])
        else:
            print("时间 | 动作 | 职位 | 薪资 | 公司 | 说明")
            for row in rec.recent(args.tail):
                print(" | ".join(str(item or "") for item in row))
    finally:
        rec.close()
    return 0


def cmd_reset_today(args: Any) -> int:
    log = _logger(args)
    cfg = load_config(args.config)
    state = State(cfg.safety.state_path)
    state.reset_today()
    log.info("已重置今日计数")
    return 0


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是整数") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("不能是负数")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Boss直聘自动化投递框架")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    runp = sub.add_parser("run", help="执行批量沟通投递")
    runp.add_argument(
        "--limit",
        type=_non_negative_int,
        default=None,
        help="覆盖 config 中的 max_apply_per_run(仅本次)",
    )
    runp.set_defaults(func=cmd_run)
    sub.add_parser("dump", help="dump 当前界面用于校准选择器").set_defaults(func=cmd_dump)
    sub.add_parser("status", help="查看今日投递状态").set_defaults(func=cmd_status)
    sub.add_parser("reset-today", help="重置今日计数").set_defaults(func=cmd_reset_today)

    records = sub.add_parser("records", help="查看本地投递记录 SQLite")
    records.add_argument("--tail", type=_non_negative_int, default=20, help="显示最后 N 条,默认 20")
    records.add_argument("--format", choices=["table", "csv"], default="table", help="输出格式")
    records.set_defaults(func=cmd_records)

    op = sub.add_parser(
        "op",
        help="单独执行一个原子操作(调试用)",
        description=operation_help(),
    )
    op.add_argument(
        "op",
        choices=tuple(OPERATION_SPECS),
        help="要执行的操作",
    )
    op.add_argument("--index", type=int, default=0, help="detail 操作点第几个卡片")
    op.add_argument("--text", default="", help="send/draft 操作使用的文字")
    op.add_argument("--yes", action="store_true", help="确认执行有副作用的操作")
    op.add_argument(
        "--count",
        type=_non_negative_int,
        default=1,
        help="scroll 操作滚动次数，默认 1",
    )
    op.add_argument(
        "--direction",
        choices=["up", "down"],
        default="up",
        help="scroll 操作方向，默认 up",
    )
    op.add_argument(
        "--name",
        default="",
        help="screenshot/messages 输出文件名（扩展名可选）",
    )
    op.add_argument(
        "--conversation-id",
        default="",
        help="messages 去重上下文覆盖值；默认使用公司+职位+招聘者",
    )
    op.add_argument(
        "--rounds",
        type=_non_negative_int,
        default=5,
        help="dry-run 扫描轮数，默认 5",
    )
    op.add_argument(
        "--action",
        choices=["inspect", "agree", "reject"],
        default="inspect",
        help="resume 操作：查看/同意/拒绝",
    )
    op.add_argument("--title", default="", help="filter-check 职位标题")
    op.add_argument("--salary", default="", help="filter-check 薪资")
    op.add_argument("--company", default="", help="filter-check 公司")
    op.set_defaults(func=cmd_op)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.artifacts = RunArtifacts.create()
    except RunInProgressError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except ConfigError as exc:
        logging.getLogger("boss").error("配置错误: %s", exc)
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        logging.getLogger("boss").error("执行失败: %s", exc)
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    finally:
        close_logger()
        args.artifacts.close()


__all__ = [
    "build_parser",
    "cmd_dump",
    "cmd_op",
    "cmd_records",
    "cmd_reset_today",
    "cmd_run",
    "cmd_status",
    "main",
]
