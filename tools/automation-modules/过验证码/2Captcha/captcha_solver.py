#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# 已弃用（2026-09-25）：请改用同级的「合规验证码挑战模块」。本文件保留仅为留档，
# 不要再把它接进任何流程。
#
# 为什么被取代：
#   1. 它把 reCAPTCHA 交给第三方打码农场。本仓库的立场是按「这一步是在搞清楚状态，
#      还是在改变状态」切片（见 docs/upstream-absorption.md），代做验证码属于
#      「让校验不生效」，明确剔除。合规模块改由操作者本人在同一授权流程里完成。
#   2. 它实现的是 reCAPTCHA v2 invisible 的流程（method=userrecaptcha 加 invisible 参数）。
#      碰到 v3 目标时参数对不上：v3 需要 version=v3 与 action。而且 v3 的分数是按
#      产生令牌的那个浏览器会话与 IP 评估的，农场产出的令牌通常低于站点阈值，
#      失败时表现为 HTTP 200 加一个业务错误码——正是本仓库记为「最坏那类」的静默失败。
#   3. 它没有任何授权模型：只有一把 API Key，没有目标白名单、没有审计、
#      没有一次性消费。合规模块这三样都有，而且已经在 CI 里（captcha_challenge 套件）。
#
# 替代品位置与用法：
#   tools/automation-modules/过验证码/合规验证码挑战模块/README.md
#   作业侧的接入例子：
#   projects/20260925-avalon-register-login/scripts/fetch_manual_inputs.py
# ---------------------------------------------------------------------------

"""
@File    : captcha_solver.py
@Time    : 2026-03-01
@Author  : wuyingzhishang
@Desc    : 2Captcha 通用打码模块

支持 reCAPTCHA v2/v3 以及普通打码的扩展。
将业务侧的打码逻辑与解耦，提升代码复用率。

依赖:
pip install requests
"""

import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)


class CaptchaSolver:
    """2Captcha reCAPTCHA v2 invisible 自动打码"""

    API_BASE = "http://2captcha.com"

    def __init__(self, api_key: str, poll_interval: int = 5, timeout: int = 120):
        """
        :param api_key: 2Captcha 的 API Key
        :param poll_interval: 轮询查询结果的间隔 (秒)
        :param timeout: 打码最大超时时间 (秒)
        """
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.session = requests.Session()

    def solve_recaptcha(self, site_key: str, page_url: str, invisible: int = 1) -> Optional[str]:
        """
        解决 reCAPTCHA v2 (Invisible / Normal)

        :param site_key: 目标网站的 site-key
        :param page_url: 目标网站 URL
        :param invisible: 1 表示 Invisible，0 表示普通版本
        :return: reCAPTCHA token 或 None
        """
        logger.info("🔓 正在解决 reCAPTCHA...")

        # 1. 提交任务
        try:
            resp = self.session.post(f"{self.API_BASE}/in.php", data={
                "key": self.api_key,
                "method": "userrecaptcha",
                "googlekey": site_key,
                "pageurl": page_url,
                "invisible": invisible,
                "json": 1,
            }, timeout=30)
            result = resp.json()

            if result.get("status") != 1:
                error = result.get("request", "未知错误")
                logger.error(f"❌ 提交打码任务失败: {error}")
                if "ERROR_WRONG_USER_KEY" in str(error) or "ERROR_KEY_DOES_NOT_EXIST" in str(error):
                    logger.error("   ⚠️ API Key 无效, 请检查传入的 API Key 是否正确配置")
                return None

            task_id = result["request"]
            logger.info(f"📤 打码任务已提交, ID: {task_id}")
        except Exception as e:
            logger.error(f"❌ 提交打码任务异常: {e}")
            return None

        # 2. 轮询结果
        start = time.time()
        time.sleep(15)  # reCAPTCHA 至少需要等待几秒

        while time.time() - start < self.timeout:
            try:
                resp = self.session.get(f"{self.API_BASE}/res.php", params={
                    "key": self.api_key,
                    "action": "get",
                    "id": task_id,
                    "json": 1,
                }, timeout=15)
                result = resp.json()

                if result.get("status") == 1:
                    token = result["request"]
                    elapsed = int(time.time() - start)
                    logger.info(f"✅ reCAPTCHA 已解决! 耗时: {elapsed}s")
                    return token
                elif result.get("request") == "CAPCHA_NOT_READY":
                    elapsed = int(time.time() - start)
                    logger.info(f"   ⏳ 等待打码结果... ({elapsed}s)")
                else:
                    logger.error(f"❌ 打码失败: {result.get('request', '未知')}")
                    return None
            except Exception as e:
                logger.warning(f"⚠️ 轮询异常: {e}")

            time.sleep(self.poll_interval)

        logger.error("❌ 打码超时")
        return None

    def solve_normal_captcha(self, image_base64: str, min_len: int = 3, max_len: int = 6) -> Optional[str]:
        """
        解决普通图片验证码（Base64 编码）

        :param image_base64: 图片的 Base64 字符串（可带或不带 data:image/png;base64, 前缀）
        :param min_len: 验证码最小长度
        :param max_len: 验证码最大长度
        :return: 验证码文本 或 None
        """
        logger.info("🔓 正在解决图片验证码...")

        if image_base64.startswith("data:image"):
            image_base64 = image_base64.split(",", 1)[1]

        try:
            resp = self.session.post(f"{self.API_BASE}/in.php", data={
                "key": self.api_key,
                "method": "base64",
                "body": image_base64,
                "min_len": min_len,
                "max_len": max_len,
                "json": 1,
            }, timeout=30)
            result = resp.json()

            if result.get("status") != 1:
                error = result.get("request", "未知错误")
                logger.error(f"❌ 提交打码任务失败: {error}")
                if "ERROR_WRONG_USER_KEY" in str(error) or "ERROR_KEY_DOES_NOT_EXIST" in str(error):
                    logger.error("   ⚠️ API Key 无效, 请检查传入的 API Key 是否正确配置")
                return None

            task_id = result["request"]
            logger.info(f"📤 打码任务已提交, ID: {task_id}")
        except Exception as e:
            logger.error(f"❌ 提交打码任务异常: {e}")
            return None

        start = time.time()
        time.sleep(5)

        while time.time() - start < self.timeout:
            try:
                resp = self.session.get(f"{self.API_BASE}/res.php", params={
                    "key": self.api_key,
                    "action": "get",
                    "id": task_id,
                    "json": 1,
                }, timeout=15)
                result = resp.json()

                if result.get("status") == 1:
                    code = result["request"]
                    elapsed = int(time.time() - start)
                    logger.info(f"✅ 图片验证码已解决! 结果: {code} | 耗时: {elapsed}s")
                    return code
                elif result.get("request") == "CAPCHA_NOT_READY":
                    elapsed = int(time.time() - start)
                    logger.info(f"   ⏳ 等待打码结果... ({elapsed}s)")
                else:
                    logger.error(f"❌ 打码失败: {result.get('request', '未知')}")
                    return None
            except Exception as e:
                logger.warning(f"⚠️ 轮询异常: {e}")

            time.sleep(self.poll_interval)

        logger.error("❌ 打码超时")
        return None

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    # 测试代码，需要有效 API Key 才能验证
    # solver = CaptchaSolver("YOUR_TEST_API_KEY")
    # print(solver.solve_recaptcha("SITE_KEY", "PAGE_URL"))
    print("CaptchaSolver 通用模块可以被外部调用，配置完整。")
