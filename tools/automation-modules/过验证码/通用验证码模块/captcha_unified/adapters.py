#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 视觉识别适配器。"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict

from .config import AIConfig, ApiType


class BaseAdapter(ABC):
    """所有 AI 适配器的基类。"""

    def __init__(self, config: AIConfig):
        self.config = config

    @abstractmethod
    def recognize(self, image_b64: str, prompt: str) -> str:
        """调用 AI 识别图片内容。"""

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """测试 API 连接。"""

    @staticmethod
    def _ensure_data_uri(image_b64: str, default_mime: str = "image/png") -> str:
        if image_b64.startswith("data:"):
            return image_b64
        return f"data:{default_mime};base64,{image_b64}"

    @staticmethod
    def _strip_data_uri(image_b64: str) -> tuple[str, str]:
        if image_b64.startswith("data:"):
            import re

            match = re.match(r"^data:([^;]+);base64,(.+)$", image_b64)
            if match:
                return match.group(1), match.group(2)
        return "image/png", image_b64


class OpenAIAdapter(BaseAdapter):
    """OpenAI Chat Completions 视觉接口，兼容同格式服务。"""

    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def _base_url(self) -> str:
        return self.config.effective_base_url or self.DEFAULT_BASE_URL

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        headers.update(self.config.custom_headers)
        return headers

    def _post(self, path: str, body: dict) -> dict:
        import urllib.error
        import urllib.request

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url()}{path}",
            data=data,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                message = json.loads(raw).get("error", {}).get("message", str(exc))
            except Exception:
                message = str(exc)
            raise RuntimeError(f"OpenAI API 错误 HTTP {exc.code}: {message}") from exc

    def recognize(self, image_b64: str, prompt: str) -> str:
        body = {
            "model": self.config.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": self._ensure_data_uri(image_b64), "detail": "high"}},
                ],
            }],
            "max_tokens": self.config.max_tokens,
            "temperature": 1,
        }
        data = self._post("/chat/completions", body)
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("OpenAI API 返回结果为空")
        return (choices[0].get("message", {}).get("content") or "").strip()

    def test_connection(self) -> Dict[str, Any]:
        body = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": 'Respond with "OK" to confirm the connection.'}],
            "max_tokens": 10,
        }
        data = self._post("/chat/completions", body)
        return {"success": True, "message": "连接成功", "model": data.get("model", self.config.model)}


class GeminiAdapter(BaseAdapter):
    """Google Gemini generateContent 接口适配器。"""

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def _base_url(self) -> str:
        return self.config.effective_base_url or self.DEFAULT_BASE_URL

    def _post(self, path: str, body: dict) -> dict:
        import urllib.error
        import urllib.request

        url = f"{self._base_url()}{path}?key={self.config.api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                message = json.loads(raw).get("error", {}).get("message", str(exc))
            except Exception:
                message = str(exc)
            raise RuntimeError(f"Gemini API 错误 HTTP {exc.code}: {message}") from exc

    def recognize(self, image_b64: str, prompt: str) -> str:
        mime_type, pure_b64 = self._strip_data_uri(image_b64)
        body = {
            "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": mime_type, "data": pure_b64}}]}],
            "generationConfig": {"temperature": 1, "maxOutputTokens": self.config.max_tokens},
        }
        data = self._post(f"/models/{self.config.model}:generateContent", body)
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini API 返回结果为空")
        parts = candidates[0].get("content", {}).get("parts", [])
        return (parts[0].get("text") or "").strip() if parts else ""

    def test_connection(self) -> Dict[str, Any]:
        self._post(
            f"/models/{self.config.model}:generateContent",
            {"contents": [{"parts": [{"text": 'Respond with "OK" to confirm the connection.'}]}]},
        )
        return {"success": True, "message": "连接成功", "model": self.config.model}


class ClaudeAdapter(BaseAdapter):
    """Anthropic Claude Messages 接口适配器。"""

    DEFAULT_BASE_URL = "https://api.anthropic.com"

    def _base_url(self) -> str:
        return self.config.effective_base_url or self.DEFAULT_BASE_URL

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
        }
        headers.update(self.config.custom_headers)
        return headers

    def _post(self, path: str, body: dict) -> dict:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            f"{self._base_url()}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                message = json.loads(raw).get("error", {}).get("message", str(exc))
            except Exception:
                message = str(exc)
            raise RuntimeError(f"Claude API 错误 HTTP {exc.code}: {message}") from exc

    def recognize(self, image_b64: str, prompt: str) -> str:
        media_type, pure_b64 = self._strip_data_uri(image_b64)
        body = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": pure_b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        }
        data = self._post("/v1/messages", body)
        for block in data.get("content", []):
            if block.get("type") == "text":
                return (block.get("text") or "").strip()
        return ""

    def test_connection(self) -> Dict[str, Any]:
        data = self._post(
            "/v1/messages",
            {
                "model": self.config.model,
                "max_tokens": 50,
                "messages": [{"role": "user", "content": 'Respond with "OK" to confirm the connection.'}],
            },
        )
        return {"success": True, "message": "连接成功", "model": data.get("model", self.config.model)}


class ZhipuAdapter(BaseAdapter):
    """智谱 AI 原生 SDK 适配器。"""

    def __init__(self, config: AIConfig):
        super().__init__(config)
        try:
            from zhipuai import ZhipuAI
        except ImportError as exc:
            raise ImportError("ZhipuAdapter 需要安装 zhipuai：pip install zhipuai") from exc
        self._client = ZhipuAI(api_key=config.api_key)

    def recognize(self, image_b64: str, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.config.model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": self._ensure_data_uri(image_b64)}},
                ],
            }],
        )
        return (resp.choices[0].message.content or "").strip()

    def call_text(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.config.zhipu_text_model,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.choices[0].message.content or "").strip()

    def test_connection(self) -> Dict[str, Any]:
        self._client.chat.completions.create(
            model=self.config.model,
            messages=[{"role": "user", "content": [{"type": "text", "text": "回复 OK"}]}],
        )
        return {"success": True, "message": "连接成功", "model": self.config.model}


def create_adapter(config: AIConfig) -> BaseAdapter:
    """根据配置创建对应适配器。"""

    mapping = {
        ApiType.OPENAI: OpenAIAdapter,
        ApiType.GEMINI: GeminiAdapter,
        ApiType.CLAUDE: ClaudeAdapter,
        ApiType.ZHIPU: ZhipuAdapter,
    }
    adapter_cls = mapping.get(config.api_type)
    if adapter_cls is None:
        raise ValueError(f"不支持的 api_type: {config.api_type}")
    return adapter_cls(config)
