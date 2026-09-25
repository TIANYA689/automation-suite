#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""22.do 免费网页临时邮箱客户端。"""

from __future__ import annotations

import base64
import html
import io
import json
import logging
import os
import random
import re
import string
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logger = logging.getLogger("receiver_22do_free")


class ReceiverError(Exception):
    """22.do 接码模块错误。"""


@dataclass(frozen=True)
class ReceiverConfig:
    """运行配置，环境变量优先。"""

    base_url: str = os.getenv("RECEIVER_22DO_BASE_URL", "https://22.do").rstrip("/")
    language: str = os.getenv("RECEIVER_22DO_LANGUAGE", "en-US")
    default_domain: str = os.getenv("RECEIVER_22DO_DOMAIN", "googlemail.com").strip()
    bearer: str = os.getenv("RECEIVER_22DO_BEARER", "").strip()
    cf_token: str = os.getenv("RECEIVER_22DO_CF_TOKEN", "").strip()
    visitor_id: str = os.getenv("RECEIVER_22DO_VISITOR_ID", "").strip()
    timeout: int = int(os.getenv("RECEIVER_22DO_TIMEOUT", "20"))
    max_retries: int = int(os.getenv("RECEIVER_22DO_MAX_RETRIES", "3"))
    poll_timeout: int = int(os.getenv("RECEIVER_22DO_POLL_TIMEOUT", "180"))
    poll_interval: int = int(os.getenv("RECEIVER_22DO_POLL_INTERVAL", "8"))
    code_pattern: str = os.getenv("RECEIVER_22DO_CODE_PATTERN", r"\d{4,8}")


@dataclass
class MailMessage:
    """邮件详情。"""

    email: str = ""
    content_id: str = ""
    view_id: str = ""
    subject: str = ""
    sender: str = ""
    time_text: str = ""
    html_body: str = ""
    text_body: str = ""
    raw_html: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "email": self.email,
            "content_id": self.content_id,
            "view_id": self.view_id,
            "subject": self.subject,
            "sender": self.sender,
            "time": self.time_text,
            "html": self.html_body,
            "text": self.text_body,
        }


class Receiver22DoFree:
    """22.do 免费网页接码客户端。"""

    GOOGLE_DOMAINS = ["googlemail.com", "gmail.com"]
    DOMAINS = [
        "googlemail.com",
        "gmail.com",
        "linshiyou.com",
        "colabeta.com",
        "youxiang.dev",
        "colaname.com",
        "usdtbeta.com",
        "tnbeta.com",
        "fft.edu.do",
    ]
    RESERVED_NAMES = {
        "admin",
        "root",
        "webmaster",
        "support",
        "mail",
        "postmaster",
        "www",
        "master",
        "about",
        "noreply",
    }

    def __init__(self, config: Optional[ReceiverConfig] = None):
        self.config = config or ReceiverConfig()
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        retry = Retry(
            total=self.config.max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        session = requests.Session()
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.trust_env = False
        session.headers.update(
            {
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                "Content-Type": "application/json",
                "User-Agent": self._random_user_agent(),
                "Referer": f"{self.config.base_url}/inbox/",
            }
        )
        return session

    @staticmethod
    def _random_user_agent() -> str:
        chrome = random.choice(["120.0.0.0", "121.0.0.0", "122.0.0.0", "123.0.0.0"])
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome} Safari/537.36"
        )

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return urljoin(f"{self.config.base_url}/", path.lstrip("/"))

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.post(self._url(path), json=payload, timeout=self.config.timeout)
        except requests.RequestException as exc:
            raise ReceiverError(f"请求失败: {exc}") from exc

        if response.status_code >= 400:
            raise ReceiverError(f"接口返回错误: HTTP {response.status_code} {response.text[:200]}")
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ReceiverError(f"接口响应不是 JSON: {response.text[:200]}") from exc
        if not isinstance(data, dict):
            raise ReceiverError(f"接口响应格式异常: {data}")
        return data

    def _get_text(self, path: str) -> str:
        try:
            response = self.session.get(self._url(path), timeout=self.config.timeout)
        except requests.RequestException as exc:
            raise ReceiverError(f"请求失败: {exc}") from exc
        if response.status_code >= 400:
            raise ReceiverError(f"页面返回错误: HTTP {response.status_code} {response.text[:200]}")
        response.encoding = response.encoding or "utf-8"
        return response.text

    def create_email(self, local: str = "", domain: str = "") -> dict[str, str]:
        """创建或切换到一个免费临时邮箱，默认使用谷歌邮箱域名。"""
        if not local and (not domain or domain.lower() in self.GOOGLE_DOMAINS):
            generated = self.generate_gmail()
            mailbox = self.login(generated["email"])
            mailbox.update(generated)
            return mailbox
        address = self.build_email(local=local, domain=domain)
        return self.login(address)

    def generate_gmail(self) -> dict[str, str]:
        """调用 fake-gmail-generator 新接口生成谷歌邮箱。"""
        data = self._post_json("/action/mailbox/gmail", {"type": "random"})
        if not data.get("status"):
            raise ReceiverError(f"生成谷歌邮箱失败: {data}")
        result = data.get("data") if isinstance(data.get("data"), dict) else {}
        email_address = str(result.get("email") or "").strip()
        account = str(result.get("account") or "").strip()
        domain = str(result.get("domain") or "").strip()
        if not email_address:
            raise ReceiverError(f"谷歌邮箱接口未返回 email: {data}")
        return {"email": email_address, "account": account, "domain": domain, "type": str(result.get("type") or "gmail")}

    def build_email(self, local: str = "", domain: str = "") -> str:
        """生成邮箱地址，不发起网络请求。"""
        local_part = (local or self._random_local()).strip().lower()
        selected_domain = (domain or self.config.default_domain).strip().lower()
        if not self._is_valid_local(local_part):
            raise ReceiverError("邮箱账号名需为 3-28 位字母或数字，且不能是保留名称")
        if selected_domain not in self.DOMAINS and not selected_domain.endswith(".com"):
            raise ReceiverError(f"域名不在已知域名池中: {selected_domain}")
        return f"{local_part}@{selected_domain}"

    def change_email(self, email_address: str = "") -> dict[str, Any]:
        """调用新接口随机切换邮箱，网页默认会返回谷歌邮箱。"""
        payload = {"email": email_address} if email_address else {}
        data = self._post_json("/action/mailbox/change", payload)
        if not data.get("status"):
            raise ReceiverError(f"切换邮箱失败: {data}")
        result = data.get("data") if isinstance(data.get("data"), dict) else data
        return result

    def set_account(self, email_address: str) -> dict[str, Any]:
        """调用新接口设置当前邮箱账号。"""
        data = self._post_json("/action/mailbox/account", {"email": email_address})
        if not data.get("status"):
            raise ReceiverError(f"设置邮箱失败: {data}")
        result = data.get("data") if isinstance(data.get("data"), dict) else data
        return result

    def login(self, email_address: str) -> dict[str, str]:
        """登录或打开指定临时邮箱。"""
        payload = {"email": email_address, "language": self.config.language}
        data = self._post_json("/action/mailbox/login", payload)
        if not data.get("status"):
            message = data.get("message") or data.get("msg") or data
            raise ReceiverError(f"登录邮箱失败: {message}")
        redirect = str(data.get("redirect") or "")
        content_id = self._content_id_from_url(redirect)
        return {"email": email_address, "redirect": redirect, "content_id": content_id}

    def delete_email(self, email_address: str) -> bool:
        """删除当前临时邮箱。"""
        data = self._post_json(
            "/action/mailbox/delete",
            {"email": email_address, "language": self.config.language},
        )
        return bool(data.get("status"))

    def delay_email(self, email_address: str) -> dict[str, Any]:
        """延长邮箱有效期。"""
        data = self._post_json("/action/mailbox/delay", {"email": email_address})
        if not data.get("status"):
            raise ReceiverError(f"延期失败: {data}")
        return data.get("data") if isinstance(data.get("data"), dict) else data

    def list_messages(self, email_address: str, last_time: int = 0, bearer: str = "") -> list[dict[str, Any]]:
        """读取新接口邮件列表。该接口需要网页 Bearer Token。"""
        token = bearer or self.config.bearer or self.apply_token()
        if not token:
            raise ReceiverError("新邮件列表接口需要 RECEIVER_22DO_BEARER；网页端通过 Turnstile 申请 Token")
        data = self._auth_post_json(
            "/action/mailbox/message",
            {"email": email_address, "lastime": last_time},
            token,
        )
        if not data.get("status"):
            raise ReceiverError(f"读取邮件列表失败: {data}")
        items = data.get("data", [])
        return items if isinstance(items, list) else []

    def delete_message(self, message_id: str, bearer: str = "") -> bool:
        """删除单封邮件。该接口需要网页 Bearer Token。"""
        token = bearer or self.config.bearer or self.apply_token()
        if not token:
            raise ReceiverError("删除邮件接口需要 RECEIVER_22DO_BEARER")
        data = self._auth_post_json("/action/mailbox/deleteMessage", {"messageId": message_id}, token)
        return bool(data.get("status", True))

    def apply_token(self) -> str:
        """使用 Turnstile cfToken 申请网页 Bearer Token。"""
        if not self.config.cf_token:
            return ""
        visitor_id = self.config.visitor_id or self._random_visitor_id()
        data = self._post_json(
            "/action/mailbox/applyToken",
            {"uuid": visitor_id, "cfToken": self.config.cf_token},
        )
        if not data.get("status"):
            raise ReceiverError(f"申请网页 Token 失败: {data.get('msg') or data}")
        result = data.get("data") if isinstance(data.get("data"), dict) else {}
        token = str(result.get("token") or "").strip()
        if not token:
            raise ReceiverError(f"申请网页 Token 未返回 token: {data}")
        return token

    def get_message_by_content_id(self, content_id: str) -> MailMessage:
        """通过 /content/{id} 读取邮件详情。"""
        raw_html = self._get_text(f"/content/{content_id}")
        return self.parse_content_page(raw_html, content_id=content_id)

    def get_latest_message(self, email_address: str) -> Optional[MailMessage]:
        """打开邮箱并尝试读取最新邮件。"""
        mailbox = self.login(email_address)
        content_id = mailbox.get("content_id", "")
        if not content_id:
            return None
        message = self.get_message_by_content_id(content_id)
        if message.view_id:
            message.html_body = self.get_view_html(message.view_id)
            message.text_body = self.html_to_text(message.html_body)
        return message

    def get_view_html(self, view_id: str) -> str:
        """读取 iframe 中的邮件正文。"""
        text = self._get_text(f"/view/{view_id}")
        decoded = self._decode_possible_base64_html(text)
        return decoded

    def download_eml(self, view_id: str) -> bytes:
        """下载邮件 eml 原文。"""
        try:
            response = self.session.post(
                self._url("/action/mailbox/download"),
                json={"viewId": view_id},
                timeout=self.config.timeout,
            )
        except requests.RequestException as exc:
            raise ReceiverError(f"下载邮件失败: {exc}") from exc
        if response.status_code >= 400:
            raise ReceiverError(f"下载邮件失败: HTTP {response.status_code}")
        return response.content

    def wait_for_email(
        self,
        email_address: str,
        subject_filter: str = "",
        sender_filter: str = "",
        timeout: Optional[int] = None,
        interval: Optional[int] = None,
    ) -> Optional[MailMessage]:
        """轮询等待邮件。"""
        if not self.config.bearer and not self.config.cf_token:
            raise ReceiverError("22.do 新收件接口需要 RECEIVER_22DO_BEARER 或 RECEIVER_22DO_CF_TOKEN，无法自动轮询收信")
        deadline = time.time() + (timeout or self.config.poll_timeout)
        poll_interval = interval or self.config.poll_interval
        subject_filter = subject_filter.lower()
        sender_filter = sender_filter.lower()

        while time.time() < deadline:
            message = self._get_latest_message_compat(email_address)
            if message and self._match_message(message, subject_filter, sender_filter):
                return message
            self._human_delay(poll_interval)
        return None

    def wait_for_code(
        self,
        email_address: str,
        pattern: Optional[str] = None,
        subject_filter: str = "",
        sender_filter: str = "",
        timeout: Optional[int] = None,
        interval: Optional[int] = None,
    ) -> Optional[str]:
        """轮询等待并提取验证码。"""
        message = self.wait_for_email(
            email_address=email_address,
            subject_filter=subject_filter,
            sender_filter=sender_filter,
            timeout=timeout,
            interval=interval,
        )
        if not message:
            return None
        return self.extract_code(message, pattern=pattern)

    def get_verification_code(
        self,
        email_address: str = "",
        pattern: Optional[str] = None,
        subject_filter: str = "",
        sender_filter: str = "",
        timeout: Optional[int] = None,
        interval: Optional[int] = None,
    ) -> dict[str, Any]:
        """一站式接码流程：创建邮箱或复用邮箱，然后等待验证码。"""
        mailbox = {"email": email_address}
        if not email_address:
            mailbox = self.create_email()
            email_address = mailbox["email"]
        code = self.wait_for_code(
            email_address=email_address,
            pattern=pattern,
            subject_filter=subject_filter,
            sender_filter=sender_filter,
            timeout=timeout,
            interval=interval,
        )
        return {"email": email_address, "code": code or "", "mailbox": mailbox}

    def extract_code(self, message: MailMessage | dict[str, Any], pattern: Optional[str] = None) -> Optional[str]:
        """从主题和正文中提取验证码。"""
        regex = pattern or self.config.code_pattern
        if isinstance(message, MailMessage):
            texts = [message.subject, message.text_body, self.html_to_text(message.html_body)]
        else:
            texts = [
                str(message.get("subject") or ""),
                str(message.get("text") or ""),
                self.html_to_text(str(message.get("html") or "")),
            ]
        for text in texts:
            match = re.search(regex, text)
            if match:
                return match.group(0)
        return None

    def parse_content_page(self, raw_html: str, content_id: str = "") -> MailMessage:
        """解析 /content 页面中的邮件元信息。"""
        resolved_content_id = content_id or self._content_id_from_html(raw_html)
        email_address = self._first_match(r'let\s+email\s*=\s*"([^"]+)"', raw_html)
        view_id = self._first_match(r"viewId:\s*'([^']+)'", raw_html)
        if not view_id:
            view_url = self._first_match(r'<iframe[^>]+src="([^"]+/view/[^"]+)"', raw_html)
            view_id = urlparse(html.unescape(view_url)).path.rsplit("/", 1)[-1] if view_url else ""

        detail_block = self._first_match(r'<div class="email-detail[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>', raw_html, re.S)
        subject = self._clean_html(self._first_match(r"<h5[^>]*>(.*?)</h5>", detail_block or raw_html, re.S))
        sender = self._clean_html(self._first_match(r'<span class="con">(.*?)</span>', detail_block or raw_html, re.S))
        time_text = self._clean_html(self._first_match(r'class="localTime"[^>]*>(.*?)</', raw_html, re.S))
        return MailMessage(
            email=email_address,
            content_id=resolved_content_id,
            view_id=view_id,
            subject=subject,
            sender=sender,
            time_text=time_text,
            raw_html=raw_html,
        )

    def _auth_post_json(self, path: str, payload: dict[str, Any], bearer: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {bearer}"}
        try:
            response = self.session.post(self._url(path), json=payload, headers=headers, timeout=self.config.timeout)
        except requests.RequestException as exc:
            raise ReceiverError(f"请求失败: {exc}") from exc
        if response.status_code >= 400:
            raise ReceiverError(f"接口返回错误: HTTP {response.status_code} {response.text[:200]}")
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ReceiverError(f"接口响应不是 JSON: {response.text[:200]}") from exc
        return data if isinstance(data, dict) else {}

    def _get_latest_message_compat(self, email_address: str) -> Optional[MailMessage]:
        if self.config.bearer or self.config.cf_token:
            items = self.list_messages(email_address)
            if items:
                item = items[0]
                message_id = str(item.get("messageId") or item.get("id") or "")
                message = MailMessage(
                    email=email_address,
                    content_id=message_id,
                    subject=str(item.get("subject") or ""),
                    sender=str(item.get("from") or ""),
                    time_text=str(item.get("time") or ""),
                )
                if message_id:
                    try:
                        detail = self.get_message_by_content_id(message_id)
                        detail.email = detail.email or email_address
                        detail.subject = detail.subject or message.subject
                        detail.sender = detail.sender or message.sender
                        if detail.view_id:
                            detail.html_body = self.get_view_html(detail.view_id)
                            detail.text_body = self.html_to_text(detail.html_body)
                        return detail
                    except ReceiverError:
                        return message
                return message
        return self.get_latest_message(email_address)

    @classmethod
    def _is_valid_local(cls, value: str) -> bool:
        return bool(re.fullmatch(r"[a-z0-9]{3,28}", value)) and value not in cls.RESERVED_NAMES

    @staticmethod
    def _random_local(length: int = 10) -> str:
        first = random.choice(string.ascii_lowercase)
        rest = "".join(random.choices(string.ascii_lowercase + string.digits, k=length - 1))
        return first + rest

    @staticmethod
    def _random_visitor_id() -> str:
        return "".join(random.choices("0123456789abcdef", k=32))

    @staticmethod
    def _first_match(pattern: str, text: str, flags: int = 0) -> str:
        match = re.search(pattern, text or "", flags)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _clean_html(value: str) -> str:
        value = re.sub(r'<a[^>]+class="__cf_email__"[^>]+data-cfemail="([^"]+)"[^>]*>.*?</a>', lambda m: Receiver22DoFree.decode_cfemail(m.group(1)), value, flags=re.S)
        value = re.sub(r"<[^>]+>", " ", value)
        value = html.unescape(value)
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def html_to_text(value: str) -> str:
        value = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", value, flags=re.I)
        value = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", value, flags=re.I)
        return Receiver22DoFree._clean_html(value)

    @staticmethod
    def decode_cfemail(encoded: str) -> str:
        """解码 Cloudflare 邮箱保护字段。"""
        try:
            key = int(encoded[:2], 16)
            chars = [chr(int(encoded[i : i + 2], 16) ^ key) for i in range(2, len(encoded), 2)]
            return "".join(chars)
        except ValueError:
            return ""

    @staticmethod
    def _decode_possible_base64_html(text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return ""
        if stripped.startswith("<"):
            return stripped
        try:
            padded = stripped + "=" * (-len(stripped) % 4)
            decoded = base64.b64decode(padded, validate=True).decode("utf-8", errors="replace")
            return decoded if decoded.lstrip().startswith("<") else stripped
        except Exception:
            return stripped

    @staticmethod
    def _content_id_from_url(url: str) -> str:
        path = urlparse(url).path
        if "/content/" not in path:
            return ""
        return path.rsplit("/", 1)[-1]

    @staticmethod
    def _content_id_from_html(raw_html: str) -> str:
        content_url = Receiver22DoFree._first_match(r'<link rel="canonical" href="([^"]+/content/[^"]+)"', raw_html)
        return Receiver22DoFree._content_id_from_url(content_url)

    @staticmethod
    def _match_message(message: MailMessage, subject_filter: str, sender_filter: str) -> bool:
        if subject_filter and subject_filter not in message.subject.lower():
            return False
        if sender_filter and sender_filter not in message.sender.lower():
            return False
        return bool(message.view_id or message.subject or message.text_body)

    @staticmethod
    def _human_delay(base_interval: int) -> None:
        time.sleep(max(2.0, base_interval + random.uniform(-1.0, 1.5)))
