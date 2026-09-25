from __future__ import annotations

import os
import sys

from loguru import logger

from client import TaxinClient


def main() -> int:
    username = os.getenv("TAXIN_USERNAME", "").strip()
    password = os.getenv("TAXIN_PASSWORD", "").strip()
    project_id = os.getenv("TAXIN_PROJECT_ID", "").strip()
    dev_name = os.getenv("TAXIN_DEV_NAME", "").strip() or None
    if not username or not password or not project_id:
        logger.error("请在 .env 中设置 TAXIN_USERNAME、TAXIN_PASSWORD 和 TAXIN_PROJECT_ID")
        return 2

    client = TaxinClient(username=username, password=password, dev_name=dev_name)
    if not client.login():
        return 1

    balance = client.get_balance()
    if balance:
        logger.info("余额查询成功")

    phone = client.get_phone(project_id)
    if not phone:
        return 1
    logger.success("成功获取号码")
    try:
        message = client.get_message(project_id, phone)
        if message:
            logger.info("验证码获取成功")
            return 0
        client.cancel(project_id, phone)
        logger.info("未收到短信，号码已释放")
        return 1
    except KeyboardInterrupt:
        client.cancel(project_id, phone)
        logger.info("用户中断，号码已释放")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
