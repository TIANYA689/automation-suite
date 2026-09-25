#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@File    : chacuo_mail_client.py
@Time    : 2026-02-16
@Author  : wuyingzhishang
@Version : 1.0
@Desc    : 24mail.chacuo.net 临时邮箱接码客户端

功能说明:
    1. 生成随机临时邮箱（支持 chacuo.net / 027168.com 域名）
    2. 自定义邮箱用户名
    3. 轮询等待新邮件
    4. 读取邮件内容（HTML）
    5. 从邮件中提取验证码
    6. 一站式获取验证码（生成邮箱 + 等待 + 提取）
    7. 删除邮件 / 设置转发

使用说明:
    1. 无需 API Key, 直接使用
    2. pip install requests
    3. 示例:
        client = ChacuoMailClient()
        email = client.generate_email()
        code = client.get_verification_code()
"""

import re
import time
import json
import random
import logging
import requests
from typing import Optional, List, Dict, Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

# 支持的邮箱域名
SUPPORTED_DOMAINS = ["chacuo.net", "027168.com"]

# 默认 User-Agent 池
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
]


class ChacuoMailError(Exception):
    """24mail API 错误"""
    pass


class ChacuoMailClient:
    """24mail.chacuo.net 临时邮箱接码客户端

    使用示例:
        client = ChacuoMailClient()
        email = client.generate_email()  # 生成随机邮箱
        print(f"邮箱: {email}")

        # 一站式获取验证码
        code = client.get_verification_code(subject_filter="Verification")
        print(f"验证码: {code}")

    特点:
        - 无需 API Key, 完全免费
        - 邮箱有效期 24 小时
        - 支持 chacuo.net / 027168.com 两个域名
    """

    API_URL = "http://24mail.chacuo.net/"
    DEFAULT_TIMEOUT = 15
    DEFAULT_DOMAIN = "chacuo.net"

    def __init__(
        self,
        domain: str = None,
        timeout: int = None,
        proxy: Dict[str, str] = None,
    ):
        """初始化客户端

        Args:
            domain: 邮箱域名, 默认 chacuo.net, 可选 027168.com
            timeout: HTTP 请求超时时间(秒)
            proxy: 代理设置, 如 {"http": "http://ip:port", "https": "http://ip:port"}
        """
        self.domain = domain or self.DEFAULT_DOMAIN
        if self.domain not in SUPPORTED_DOMAINS:
            raise ValueError(f"不支持的域名: {self.domain}, 可选: {SUPPORTED_DOMAINS}")

        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.username = None  # 当前邮箱用户名
        self.email_address = None  # 完整邮箱地址

        # 初始化 Session
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "http://24mail.chacuo.net",
            "Referer": "http://24mail.chacuo.net/",
            "User-Agent": random.choice(UA_POOL),
            "Accept": "*/*",
        })

        if proxy:
            self.session.proxies = proxy

        logger.info(f"ChacuoMail 客户端初始化完成 | 域名: {self.domain}")

    # ==================== 内部方法 ====================

    def _encode_arg(self, **kwargs) -> str:
        """编码 arg 参数

        将 key=value 对编码为 24mail 格式:
        d=chacuo.net_f= → d%3Dchacuo.net_f%3D
        """
        parts = []
        for k, v in kwargs.items():
            encoded_v = str(v).replace("_", "%5F").replace("=", "%3D").replace("+", "%2B")
            parts.append(f"{k}%3D{encoded_v}")
        return "_".join(parts)

    def _post(self, data: str, type_: str, arg: str = "") -> Dict[str, Any]:
        """发送 POST 请求到 24mail API

        Args:
            data: 邮箱用户名
            type_: 操作类型 (refresh/renew/set/mailinfo/delmail/forward)
            arg: 附加参数

        Returns:
            解析后的 JSON 响应

        Raises:
            ChacuoMailError: API 调用失败
        """
        payload = {
            "data": data,
            "type": type_,
            "arg": arg,
        }

        try:
            resp = self.session.post(
                self.API_URL,
                data=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()

            result = resp.json()
            if result.get("status") != 1:
                raise ChacuoMailError(f"API 错误: {result.get('info', '未知错误')}")

            return result
        except requests.RequestException as e:
            raise ChacuoMailError(f"网络请求失败: {e}")
        except json.JSONDecodeError:
            raise ChacuoMailError(f"响应解析失败: {resp.text[:200]}")

    # ==================== 邮箱管理 ====================

    def _init_from_page(self) -> str:
        """通过 GET 首页获取初始分配的用户名

        服务器在首次访问时会分配一个随机用户名，
        保存在页面 HTML 的 id="converts" input 中。

        Returns:
            初始用户名

        Raises:
            ChacuoMailError: 获取失败
        """
        try:
            resp = self.session.get(self.API_URL, timeout=self.timeout)
            resp.raise_for_status()

            # 从 HTML 中提取 id="converts" 的 value
            match = re.search(r'id="converts"[^>]*value="([^"]+)"', resp.text)
            if match:
                username = match.group(1)
                logger.info(f"📥 获取初始用户名: {username}")
                return username

            raise ChacuoMailError("页面中未找到初始用户名 (converts)")
        except requests.RequestException as e:
            raise ChacuoMailError(f"获取首页失败: {e}")

    def generate_email(self, domain: str = None) -> str:
        """生成随机临时邮箱

        Args:
            domain: 可选, 指定域名 (chacuo.net / 027168.com)

        Returns:
            完整邮箱地址, 如 "abc12345@chacuo.net"
        """
        target_domain = domain or self.domain
        arg = self._encode_arg(d=target_domain, f="")

        # 首次调用: 需要先访问首页获取初始用户名
        if not self.username:
            self.username = self._init_from_page()
            self.email_address = f"{self.username}@{target_domain}"
            # 如果需要不同域名，再 renew 一次
            if target_domain == self.domain:
                logger.info(f"✅ 生成邮箱: {self.email_address}")
                return self.email_address

        # 使用当前用户名 renew 获取新的随机邮箱
        result = self._post(self.username, "renew", arg)
        new_username = result["data"][0]

        if not new_username or new_username is False:
            raise ChacuoMailError("生成邮箱失败: 服务器未返回有效用户名")

        self.username = new_username
        self.email_address = f"{new_username}@{target_domain}"

        logger.info(f"✅ 生成邮箱: {self.email_address}")
        return self.email_address

    def set_email(self, username: str, domain: str = None) -> bool:
        """设置自定义邮箱用户名

        Args:
            username: 自定义用户名
            domain: 可选, 指定域名

        Returns:
            是否设置成功 (False 表示已被占用或无变化)
        """
        target_domain = domain or self.domain
        arg = self._encode_arg(d=target_domain, f="")

        result = self._post(username, "set", arg)
        success = result["data"][0]

        if success:
            self.username = username
            self.email_address = f"{username}@{target_domain}"
            logger.info(f"✅ 设置邮箱成功: {self.email_address}")
        else:
            logger.warning(f"⚠️ 设置邮箱失败: {username}@{target_domain} (已被占用或无变化)")

        return bool(success)

    def set_forward(self, target_email: str) -> bool:
        """设置邮件转发

        Args:
            target_email: 转发目标邮箱地址

        Returns:
            是否设置成功
        """
        if not self.username:
            raise ChacuoMailError("请先生成或设置邮箱")

        arg = f"f={target_email}"
        result = self._post(self.username, "forward", arg)
        success = result["data"][0] is not False

        if success:
            logger.info(f"✅ 转发设置成功: → {target_email}")
        else:
            logger.warning(f"⚠️ 转发设置失败: {target_email}")

        return success

    # ==================== 邮件操作 ====================

    def get_emails(self) -> Dict[str, Any]:
        """获取邮件列表和用户信息

        Returns:
            包含以下字段的字典:
            {
                "user": {...},      # 用户信息 (UID, USER, ADDTIME, EXPIRETIME 等)
                "stat": {...},      # 统计信息
                "list": [...]       # 邮件列表
            }

        Raises:
            ChacuoMailError: 未设置邮箱或 API 调用失败
        """
        if not self.username:
            raise ChacuoMailError("请先调用 generate_email() 或 set_email() 设置邮箱")

        result = self._post(self.username, "refresh", "")
        return result["data"][0]

    def get_email_content(self, mid: int) -> Dict[str, Any]:
        """读取邮件内容

        Args:
            mid: 邮件 ID (从 get_emails 返回的 list 中每个元素的 MID 字段)

        Returns:
            邮件详情字典, 包含:
            {
                "SUBJECT": "邮件标题",
                "FROM": "发件人",
                "TO": "收件人",
                "SENDTIME": "发送时间",
                "DATA": ["纯文本内容", "HTML内容"],
                "RLINK": "原始链接"
            }
        """
        if not self.username:
            raise ChacuoMailError("请先设置邮箱")

        arg = f"f={mid}"
        result = self._post(self.username, "mailinfo", arg)

        # 响应格式: data: [[msg_info, [{"DATA": [text, html]}]]]
        raw = result["data"][0]
        msg = raw[0]
        content_data = raw[1][0]["DATA"] if len(raw) > 1 and raw[1] else ["", ""]

        return {
            "MID": msg.get("MID"),
            "SUBJECT": msg.get("SUBJECT", ""),
            "FROM": msg.get("FROM", ""),
            "TO": msg.get("TO", ""),
            "SENDTIME": msg.get("SENDTIME", ""),
            "DATA": content_data,
            "RLINK": msg.get("RLINK", ""),
        }

    def delete_email(self, mid: int) -> bool:
        """删除邮件

        Args:
            mid: 邮件 ID

        Returns:
            是否删除成功
        """
        if not self.username:
            raise ChacuoMailError("请先设置邮箱")

        try:
            arg = f"f={mid}"
            self._post(self.username, "delmail", arg)
            logger.info(f"✅ 邮件删除成功: MID={mid}")
            return True
        except ChacuoMailError as e:
            logger.error(f"❌ 邮件删除失败: {e}")
            return False

    def get_latest_email(self) -> Optional[Dict[str, Any]]:
        """获取最新一封邮件 (不等待)

        Returns:
            最新邮件字典 (包含 MID, SUBJECT, FROM, TO, SENDTIME 等), 无邮件返回 None
        """
        data = self.get_emails()
        mail_list = data.get("list", [])
        if not mail_list:
            return None
        return mail_list[0]

    # ==================== 等待和验证码 ====================

    def wait_for_email(
        self,
        timeout: int = 300,
        interval: int = 8,
        subject_filter: str = None,
        sender_filter: str = None,
        since_time: float = None,
    ) -> Optional[Dict[str, Any]]:
        """等待接收新邮件 (自动轮询)

        Args:
            timeout: 最大等待时间(秒), 默认 300
            interval: 轮询间隔(秒), 默认 8
            subject_filter: 邮件主题关键词过滤 (模糊匹配)
            sender_filter: 发件人关键词过滤 (模糊匹配)
            since_time: 只获取此时间戳之后的邮件 (Unix 时间戳)

        Returns:
            匹配的邮件字典, 超时返回 None
        """
        if not self.username:
            raise ChacuoMailError("请先设置邮箱")

        start_time = time.time()
        attempt = 0

        logger.info(f"⏳ 等待邮件中... | 邮箱: {self.email_address} | 超时: {timeout}s")

        while time.time() - start_time < timeout:
            attempt += 1
            elapsed = int(time.time() - start_time)

            try:
                data = self.get_emails()
                mail_list = data.get("list", [])

                for mail in mail_list:
                    # 主题过滤
                    if subject_filter and subject_filter.lower() not in mail.get("SUBJECT", "").lower():
                        continue
                    # 发件人过滤
                    if sender_filter and sender_filter.lower() not in mail.get("FROM", "").lower():
                        continue

                    logger.info(
                        f"📬 收到邮件! | 主题: {mail['SUBJECT'][:50]} | "
                        f"发件人: {mail['FROM'][:40]} | 耗时: {elapsed}s"
                    )
                    return mail

                logger.info(f"   轮询 #{attempt} | 暂无匹配邮件 | 已等待 {elapsed}s")

            except ChacuoMailError as e:
                logger.warning(f"⚠️ 轮询出错: {e}")

            # 加入随机抖动，避免被识别
            jitter = random.uniform(-1.0, 1.5)
            sleep_time = max(interval + jitter, 3)
            time.sleep(sleep_time)

        logger.error(f"⏰ 等待超时 ({timeout}s) | 邮箱: {self.email_address}")
        return None

    def extract_code(
        self,
        email: Dict[str, Any],
        pattern: str = r"\d{4,6}",
        source: str = "auto",
    ) -> Optional[str]:
        """从邮件内容中提取验证码

        Args:
            email: 邮件字典 (get_emails 返回的 list 中单个元素, 或 get_email_content 结果)
            pattern: 验证码正则表达式, 默认匹配 4-6 位数字
            source: 内容来源
                - "auto": 优先 HTML, 回退文本, 再回退主题
                - "text": 仅纯文本
                - "html": 仅 HTML
                - "subject": 仅邮件主题

        Returns:
            提取到的验证码字符串, 未找到返回 None
        """
        # 如果传入的是列表邮件（无 DATA），先获取完整内容
        if "DATA" not in email and "MID" in email:
            try:
                email = self.get_email_content(email["MID"])
            except ChacuoMailError:
                pass

        # 收集待搜索文本
        search_texts = []

        if source == "subject":
            search_texts = [email.get("SUBJECT", "")]
        elif source == "text":
            data = email.get("DATA", [])
            search_texts = [data[0]] if data else []
        elif source == "html":
            data = email.get("DATA", [])
            search_texts = [data[1]] if len(data) > 1 else []
        else:  # auto
            data = email.get("DATA", [])
            # 优先 HTML → 纯文本 → 主题
            if len(data) > 1 and data[1]:
                search_texts.append(data[1])
            if data and data[0]:
                search_texts.append(data[0])
            search_texts.append(email.get("SUBJECT", ""))

        # 正则提取
        for text in search_texts:
            if not text:
                continue
            match = re.search(pattern, text)
            if match:
                code = match.group()
                logger.info(f"🔑 提取验证码: {code}")
                return code

        logger.warning(f"⚠️ 未找到匹配验证码 | 模式: {pattern}")
        return None

    def get_verification_code(
        self,
        code_pattern: str = r"\d{4,6}",
        timeout: int = 300,
        interval: int = 8,
        subject_filter: str = None,
        sender_filter: str = None,
        since_time: float = None,
        delete_after: bool = False,
        source: str = "auto",
    ) -> Optional[str]:
        """一站式获取验证码 (等待邮件 + 提取验证码)

        Args:
            code_pattern: 验证码正则表达式
            timeout: 最大等待时间(秒)
            interval: 轮询间隔(秒)
            subject_filter: 邮件主题过滤
            sender_filter: 发件人过滤
            since_time: 只获取此时间戳之后的邮件
            delete_after: 获取后是否删除邮件
            source: 内容来源 ("auto" / "text" / "html" / "subject")

        Returns:
            验证码字符串, 失败返回 None

        使用示例:
            client = ChacuoMailClient()
            email_addr = client.generate_email()
            # ... 在目标网站用 email_addr 注册 ...
            code = client.get_verification_code(
                subject_filter="Verification",
                timeout=120,
            )
        """
        logger.info(f"🎯 开始获取验证码 | 邮箱: {self.email_address}")

        # 等待邮件
        email = self.wait_for_email(
            timeout=timeout,
            interval=interval,
            subject_filter=subject_filter,
            sender_filter=sender_filter,
            since_time=since_time,
        )

        if not email:
            logger.error(f"❌ 未收到邮件, 获取验证码失败 | 邮箱: {self.email_address}")
            return None

        # 提取验证码
        code = self.extract_code(email, pattern=code_pattern, source=source)

        # 获取后删除邮件
        if delete_after and code and email.get("MID"):
            self.delete_email(email["MID"])

        return code

    # ==================== 便捷方法 ====================

    def quick_get_code(
        self,
        domain: str = None,
        code_pattern: str = r"\d{4,6}",
        timeout: int = 120,
        subject_filter: str = None,
        sender_filter: str = None,
    ) -> tuple:
        """快捷方法: 生成邮箱 + 返回邮箱地址 (等外部注册后再调用获取验证码)

        Returns:
            (email_address, client_instance) 元组

        使用示例:
            client = ChacuoMailClient()
            email, _ = client.quick_get_code()
            # ... 用 email 去注册 ...
            code = client.get_verification_code(timeout=120)
        """
        email = self.generate_email(domain=domain)
        return email, self

    @property
    def current_email(self) -> Optional[str]:
        """获取当前邮箱地址"""
        return self.email_address

    def __repr__(self):
        return f"ChacuoMailClient(email={self.email_address}, domain={self.domain})"
