#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""22.do 免费接码命令行入口。"""

from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

from src.receiver_22do_free import Receiver22DoFree, ReceiverError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="22.do 免费网页临时邮箱接码工具")
    parser.add_argument(
        "--action",
        choices=["create", "get-code", "change", "wait-code", "latest", "delete", "delay"],
        default="create",
    )
    parser.add_argument("--email", help="已有邮箱地址，wait-code/latest/delete/delay 时使用")
    parser.add_argument("--local", default="", help="自定义邮箱账号名，3-28 位字母或数字")
    parser.add_argument("--domain", default="", help="自定义域名，不填默认调用谷歌邮箱生成接口")
    parser.add_argument("--subject", default="", help="主题关键词过滤")
    parser.add_argument("--sender", default="", help="发件人关键词过滤")
    parser.add_argument("--pattern", default="", help="验证码正则")
    parser.add_argument("--timeout", type=int, default=0, help="等待超时时间，秒")
    parser.add_argument("--interval", type=int, default=0, help="轮询间隔，秒")
    return parser


def main() -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args()
    client = Receiver22DoFree()

    try:
        if args.action == "create":
            mailbox = client.create_email(local=args.local, domain=args.domain)
            print(f"邮箱地址: {mailbox['email']}")
            print(f"跳转地址: {mailbox['redirect']}")
            return 0

        if args.action == "get-code":
            mailbox = client.create_email(local=args.local, domain=args.domain) if not args.email else {"email": args.email}
            print(f"邮箱地址: {mailbox['email']}")
            if mailbox.get("redirect"):
                print(f"跳转地址: {mailbox['redirect']}")
            print("状态: 正在等待验证码...")
            code = client.wait_for_code(
                email_address=mailbox["email"],
                pattern=args.pattern or None,
                subject_filter=args.subject,
                sender_filter=args.sender,
                timeout=args.timeout or None,
                interval=args.interval or None,
            )
            if not code:
                print("未获取到验证码")
                return 2
            print(f"验证码: {code}")
            return 0

        if args.action == "change":
            result = client.change_email(args.email or "")
            print(f"邮箱地址: {result.get('email', '')}")
            print(f"剩余时间: {result.get('timeLeft', '')}")
            return 0

        if not args.email:
            raise ReceiverError(f"{args.action} 需要传入 --email")

        if args.action == "latest":
            message = client.get_latest_message(args.email)
            if not message:
                print("暂无邮件")
                return 2
            print(f"主题: {message.subject}")
            print(f"发件人: {message.sender}")
            print(f"正文: {message.text_body}")
            return 0

        if args.action == "wait-code":
            code = client.wait_for_code(
                email_address=args.email,
                pattern=args.pattern or None,
                subject_filter=args.subject,
                sender_filter=args.sender,
                timeout=args.timeout or None,
                interval=args.interval or None,
            )
            if not code:
                print("未获取到验证码")
                return 2
            print(f"验证码: {code}")
            return 0

        if args.action == "delete":
            print("删除结果:", "成功" if client.delete_email(args.email) else "失败")
            return 0

        if args.action == "delay":
            print(client.delay_email(args.email))
            return 0

        return 0
    except ReceiverError as exc:
        print(f"执行失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
