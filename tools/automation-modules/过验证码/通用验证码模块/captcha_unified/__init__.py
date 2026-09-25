#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用验证码模块：AI 图片识别、GeeTest 页面验证码调度与滑块识别。"""

from .config import AIConfig, ApiType
from .solver import (
    AIVisionClient,
    CaptchaDispatcher,
    EasingFunctions,
    GridSolver,
    SliderSolver,
    TextClickSolver,
    identify_slider_gap,
    image_to_base64,
)

__all__ = [
    "AIConfig",
    "ApiType",
    "AIVisionClient",
    "CaptchaDispatcher",
    "EasingFunctions",
    "GridSolver",
    "SliderSolver",
    "TextClickSolver",
    "identify_slider_gap",
    "image_to_base64",
]
