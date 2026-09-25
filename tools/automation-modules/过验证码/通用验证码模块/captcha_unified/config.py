#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 视觉识别配置。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


class ApiType:
    """支持的 AI API 类型。"""

    OPENAI = "openai"
    GEMINI = "gemini"
    CLAUDE = "claude"
    ZHIPU = "zhipu"


DEFAULT_MODELS: Dict[str, str] = {
    ApiType.OPENAI: "gpt-4o",
    ApiType.GEMINI: "gemini-1.5-flash",
    ApiType.CLAUDE: "claude-3-5-sonnet-20241022",
    ApiType.ZHIPU: "glm-4v-flash",
}

ZHIPU_DEFAULT_TEXT_MODEL = "glm-4-flash"


@dataclass
class AIConfig:
    """统一 AI API 配置。"""

    api_type: str
    api_key: str
    model: str = ""
    base_url: str = ""
    max_tokens: int = 500
    timeout: int = 30
    retry_count: int = 3
    custom_headers: Dict[str, str] = field(default_factory=dict)
    zhipu_text_model: str = ""

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError(f"AIConfig: api_key 不能为空（api_type={self.api_type}）")
        if self.api_type not in (ApiType.OPENAI, ApiType.GEMINI, ApiType.CLAUDE, ApiType.ZHIPU):
            raise ValueError("AIConfig: api_type 仅支持 openai / gemini / claude / zhipu")
        if not self.model:
            self.model = DEFAULT_MODELS[self.api_type]
        if not self.zhipu_text_model:
            self.zhipu_text_model = ZHIPU_DEFAULT_TEXT_MODEL

    @property
    def effective_base_url(self) -> str:
        """返回去除尾部斜杠的 base_url。"""

        return self.base_url.rstrip("/")
