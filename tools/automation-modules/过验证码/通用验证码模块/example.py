#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用验证码模块示例和 dry-run 自检。"""

from __future__ import annotations

import sys

from captcha_unified import AIConfig, ApiType, CaptchaDispatcher, EasingFunctions, image_to_base64
from captcha_unified.adapters import ClaudeAdapter, GeminiAdapter, OpenAIAdapter, create_adapter


def dry_run_test() -> None:
    """无需 API Key 和浏览器的基础自检。"""

    print("=" * 60)
    print("通用验证码模块 dry-run 自检")
    print("=" * 60)

    result = image_to_base64(b"\x89PNG\r\n\x1a\n")
    assert result.startswith("data:image/png;base64,"), "bytes 转 base64 失败"

    data_uri = "data:image/jpeg;base64,/9j/4AAQ"
    assert image_to_base64(data_uri) == data_uri, "data URI 直通失败"

    for api_type, key in [
        (ApiType.OPENAI, "sk-test"),
        (ApiType.GEMINI, "AIza-test"),
        (ApiType.CLAUDE, "sk-ant-test"),
        (ApiType.ZHIPU, "zhipu-test"),
    ]:
        cfg = AIConfig(api_type=api_type, api_key=key)
        assert cfg.model, f"{api_type} 默认模型为空"

    for name, func in [
        ("ease_in_out_quad", EasingFunctions.ease_in_out_quad),
        ("ease_out_quad", EasingFunctions.ease_out_quad),
        ("ease_in_out_cubic", EasingFunctions.ease_in_out_cubic),
    ]:
        values = [func(i / 10) for i in range(11)]
        assert all(0.0 <= value <= 1.0 for value in values), f"{name} 值域异常"

    assert CaptchaDispatcher().solve(None) is False, "solve(None) 应返回 False"

    assert isinstance(create_adapter(AIConfig(ApiType.OPENAI, "sk-test")), OpenAIAdapter)
    assert isinstance(create_adapter(AIConfig(ApiType.GEMINI, "AIza-test")), GeminiAdapter)
    assert isinstance(create_adapter(AIConfig(ApiType.CLAUDE, "sk-ant-test")), ClaudeAdapter)

    print("所有 dry-run 自检通过")


def print_demo() -> None:
    """打印常见用法。"""

    print(
        """
from captcha_unified import AIConfig, ApiType, AIVisionClient, CaptchaDispatcher

config = AIConfig(
    api_type=ApiType.OPENAI,
    api_key="sk-xxx",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    model="glm-4v-flash",
)
client = AIVisionClient(config)
print(client.recognize("captcha.png"))

dispatcher = CaptchaDispatcher(client, max_retries=3)
success = dispatcher.solve(page)
"""
    )


if __name__ == "__main__":
    dry_run_test()
    if "--demo" in sys.argv:
        print_demo()
    else:
        print("运行 `python example.py --demo` 查看集成示例")
