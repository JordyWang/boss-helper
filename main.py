#!/usr/bin/env python3
"""命令行入口。

用法:
    python main.py run              # 执行批量沟通投递
    python main.py dump             # dump 当前界面(校准选择器用)
    python main.py status           # 查看今日投递状态
    python main.py reset-today      # 清空今日计数(谨慎)
"""
from __future__ import annotations

import argparse
import sys

from boss.config import load_config
from boss.logger import setup_logger
from boss.state import State


def cmd_run(args) -> int:
    log = setup_logger()
    cfg = load_config(args.config)

    from boss.device import connect, ensure_app
    from boss.engine import ApplyEngine

    d = connect(cfg.serial, log)
    ensure_app(d, cfg.package, log)

    state = State()
    engine = ApplyEngine(d, cfg, state, log)
    engine.run()
    return 0


def cmd_op(args) -> int:
    """单独执行一个原子操作,便于逐个调试与校准。

    安全操作(可直接跑): recommend / detail / back / read
    有副作用(需 --yes): communicate(创建会话) / send(发送消息)
    """
    log = setup_logger()
    cfg = load_config(args.config)

    from boss.device import connect, ensure_app
    from boss.pages.home import HomePage
    from boss.pages.job_detail import JobDetailPage
    from boss.pages.chat import ChatPage

    d = connect(cfg.serial, log)
    ensure_app(d, cfg.package, log)
    home = HomePage(d, cfg.timing, log)
    detail = JobDetailPage(d, cfg.timing, log)
    chat = ChatPage(d, cfg.timing, log)

    op = args.op

    if op == "recommend":
        log.info("open_recommend -> %s", home.open_recommend())

    elif op == "detail":
        home.open_recommend()
        cards = home.job_cards()
        if not cards:
            log.error("未发现职位卡片")
            return 1
        idx = args.index or 0
        card = cards[idx]
        log.info("点进第 %d 个: %s | %s | %s", idx, card.title, card.salary, card.company)
        card.click()
        home.human_delay()
        log.info("详情页标题=%s 薪资=%s", detail.title(), detail.salary())

    elif op == "read":
        log.info("当前详情页: 标题=%s 薪资=%s boss=%s",
                 detail.title(), detail.salary(), detail.boss_name())

    elif op == "communicate":
        if not args.yes:
            log.error("communicate 会真实创建会话,确认请加 --yes")
            return 2
        log.info("点击立即沟通 -> %s", detail.communicate())
        detail.handle_after_communicate()

    elif op == "send":
        if not args.yes:
            log.error("send 会真实发送消息,确认请加 --yes")
            return 2
        text = args.text or (cfg.greeting.messages[0] if cfg.greeting.messages else "")
        if not text:
            log.error("无消息内容,用 --text 指定")
            return 1
        log.info("在会话页发送 -> %s", chat.send_message(text))

    elif op == "back":
        home.back()
        log.info("已返回")

    elif op == "home":
        log.info("back_to_list -> %s", home.back_to_list())

    else:
        log.error("未知操作: %s", op)
        return 1

    return 0



def cmd_dump(args) -> int:
    from tools.dump_ui import dump

    dump(args.config)
    return 0


def cmd_status(args) -> int:
    log = setup_logger()
    state = State()
    cfg = load_config(args.config)
    log.info("今日已投递: %d / %d", state.applied_today, cfg.limits.max_apply_per_day)
    log.info("历史处理职位数: %d", len(state.applied_keys()))
    return 0


def cmd_reset_today(args) -> int:
    log = setup_logger()
    state = State()
    state.data["applied_today"] = 0
    state.save()
    log.info("已重置今日计数")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Boss直聘自动化投递框架")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="执行批量沟通投递").set_defaults(func=cmd_run)
    sub.add_parser("dump", help="dump 当前界面用于校准选择器").set_defaults(func=cmd_dump)
    sub.add_parser("status", help="查看今日投递状态").set_defaults(func=cmd_status)
    sub.add_parser("reset-today", help="重置今日计数").set_defaults(func=cmd_reset_today)

    op = sub.add_parser("op", help="单独执行一个原子操作(调试用)")
    op.add_argument(
        "op",
        choices=["recommend", "detail", "read", "communicate", "send", "back", "home"],
        help="要执行的操作",
    )
    op.add_argument("--index", type=int, default=0, help="detail 操作点第几个卡片")
    op.add_argument("--text", default="", help="send 操作要发送的文字")
    op.add_argument(
        "--yes", action="store_true", help="确认执行有副作用的操作(communicate/send)"
    )
    op.set_defaults(func=cmd_op)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
