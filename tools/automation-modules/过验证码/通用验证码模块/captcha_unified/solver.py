#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用验证码识别和 Playwright 页面调度。"""

from __future__ import annotations

import base64
import io
import json
import random
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Union

from .adapters import BaseAdapter, ZhipuAdapter, create_adapter
from .config import AIConfig

try:
    from PIL import Image as _PILImage
except ImportError:
    _PILImage = None  # type: ignore


def image_to_base64(src: Union[bytes, str, Path, object], mime: str = "image/png") -> str:
    """将 bytes、路径、PIL.Image 或 data URI 统一转为 data URI base64。"""

    if isinstance(src, str) and src.startswith("data:"):
        return src
    if isinstance(src, (str, Path)):
        path = Path(src)
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        raw = path.read_bytes()
        return f"data:{mime_map.get(path.suffix.lower(), 'image/png')};base64,{base64.b64encode(raw).decode()}"
    if _PILImage is not None and isinstance(src, _PILImage.Image):
        buf = io.BytesIO()
        src.save(buf, format="PNG")
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
    if isinstance(src, bytes):
        return f"data:{mime};base64,{base64.b64encode(src).decode()}"
    raise TypeError(f"image_to_base64: 不支持的输入类型 {type(src)}")


class AIVisionClient:
    """统一 AI 视觉识别客户端。"""

    DEFAULT_CAPTCHA_PROMPT = (
        "请识别这张验证码图片中的文字或数字。"
        "只返回识别出的验证码内容，不要有解释。"
        "如果是数学运算验证码，请计算并只返回最终结果。"
        "如果无法识别，请返回“无法识别”。"
    )

    def __init__(self, config: AIConfig):
        self.config = config
        self.adapter: BaseAdapter = create_adapter(config)

    def recognize(self, image: Union[bytes, str, Path, object], prompt: Optional[str] = None) -> str:
        """识别图片内容，失败时按 retry_count 重试。"""

        image_b64 = image_to_base64(image)
        final_prompt = prompt or self.DEFAULT_CAPTCHA_PROMPT
        last_error: Optional[Exception] = None

        for attempt in range(1, self.config.retry_count + 1):
            try:
                result = self.adapter.recognize(image_b64, final_prompt)
                if result:
                    return result
            except Exception as exc:
                last_error = exc
                print(f"  [AIVisionClient] 第 {attempt} 次识别失败: {exc}")
                if attempt < self.config.retry_count:
                    time.sleep(attempt)

        if last_error:
            print(f"  [AIVisionClient] 全部重试失败: {last_error}")
        return ""

    def call_text(self, prompt: str) -> str:
        """调用文本模型；非智谱适配器回退到视觉模型文本请求。"""

        if isinstance(self.adapter, ZhipuAdapter):
            try:
                return self.adapter.call_text(prompt)
            except Exception as exc:
                print(f"  [AIVisionClient] 文本模型调用失败: {exc}")
                return ""
        transparent_png = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        )
        try:
            return self.adapter.recognize(transparent_png, prompt)
        except Exception:
            return ""

    def test_connection(self) -> dict:
        """测试 API 连接。"""

        return self.adapter.test_connection()

    @staticmethod
    def _safe_json(text: str):
        try:
            match = re.search(r"\[.*?\]", text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return json.loads(text)
        except Exception:
            return None

    def identify_captcha_target(self, image: Union[bytes, str]) -> str:
        """识别题目图中的目标物体名称。"""

        result = self.recognize(image, "图中是什么物体？只回答物体名称，不要带标点。")
        return re.sub(r"[^\w]", "", result)

    def identify_grid_row(self, row_image: Union[bytes, str], row_index: int = 0) -> List[str]:
        """识别九宫格单行中的 3 个物体名称。"""

        prompt = (
            "这是验证码的一行图片，包含3个格子。"
            "请从左到右识别这3个格子的物体名称，只返回 JSON 字符串数组，"
            "例如：[\"猫\", \"狗\", \"汽车\"]。不要解释。"
        )
        result = self.recognize(row_image, prompt)
        print(f"  [AI-Grid] 第 {row_index + 1} 行识别: {result}")
        parsed = self._safe_json(result)
        if isinstance(parsed, list):
            return (parsed + ["未知", "未知", "未知"])[:3]
        return ["未知", "未知", "未知"]

    def semantic_match(self, target: str, descriptions: List[str]) -> List[int]:
        """根据题目目标，从 9 个描述中选出应点击的序号。"""

        items = "\n".join(f"{idx + 1}. {desc}" for idx, desc in enumerate(descriptions))
        prompt = (
            f"题目是：找出图片中所有的【{target}】。\n"
            f"当前 9 个格子的识别结果如下：\n{items}\n"
            "请判断哪些序号（1-9）最符合题目要求。只返回 JSON 数组，如 [1, 3, 5]。"
            "如果没有符合的，返回 []。"
        )
        result = self.call_text(prompt)
        print(f"  [AI-Grid] 语义裁判: {result}")
        parsed = self._safe_json(result)
        return parsed if isinstance(parsed, list) else []

    def identify_text_positions(self, captcha_image: Union[bytes, str], target_chars: str) -> List[dict]:
        """识别文字点选验证码中目标文字的归一化坐标。"""

        prompt = (
            f"这是一张文字点选验证码图片。请找出图中所有【{target_chars}】这几个字，"
            "按顺序返回每个字相对图片左上角的位置，x 和 y 为 0 到 1 的比例。"
            "只返回 JSON 数组，格式如：[{\"char\":\"绿\",\"x\":0.25,\"y\":0.6}]。"
        )
        result = self.recognize(captcha_image, prompt)
        print(f"  [AI-Text] 文字坐标识别: {result}")
        parsed = self._safe_json(result)
        return parsed if isinstance(parsed, list) else []


class EasingFunctions:
    """常用鼠标缓动曲线。"""

    @staticmethod
    def ease_in_out_quad(n: float) -> float:
        if n < 0.5:
            return 2 * n * n
        n = n * 2 - 1
        return -0.5 * (n * (n - 2) - 1)

    @staticmethod
    def ease_out_quad(n: float) -> float:
        return -n * (n - 2)

    @staticmethod
    def ease_in_out_cubic(n: float) -> float:
        if n < 0.5:
            return 4 * n * n * n
        n = n * 2 - 2
        return 0.5 * n * n * n + 1


def identify_slider_gap(bg_img_bytes: bytes, slider_img_bytes: Optional[bytes] = None) -> int:
    """识别滑块验证码缺口 X 坐标，优先 captcha-recognizer，降级 ddddocr。"""

    try:
        import numpy as np
        from captcha_recognizer.slider import Slider

        if _PILImage is None:
            raise ImportError("Pillow 未安装")
        bg_arr = np.array(_PILImage.open(io.BytesIO(bg_img_bytes)))
        box, confidence = Slider().identify(source=bg_arr, show=False)
        if box and len(box) >= 4:
            gap_x = int(box[0])
            print(f"  [Slider] captcha-recognizer 识别成功: x={gap_x}px, 置信度={confidence:.2f}")
            return gap_x
    except ImportError:
        print("  [Slider] captcha-recognizer 未安装，降级至 ddddocr")
    except Exception as exc:
        print(f"  [Slider] captcha-recognizer 异常: {exc}，降级至 ddddocr")

    try:
        import ddddocr

        det = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
        if slider_img_bytes:
            result = det.slide_match(slider_img_bytes, bg_img_bytes)
        else:
            result = det.slide_match(bg_img_bytes, bg_img_bytes)
        x = result.get("target", [0])[0] if isinstance(result, dict) else 0
        if x > 0:
            print(f"  [Slider] ddddocr 识别成功: x={x}px")
            return int(x)
    except ImportError:
        print("  [Slider] ddddocr 未安装")
    except Exception as exc:
        print(f"  [Slider] ddddocr 异常: {exc}")

    return 0


class BaseSolver(ABC):
    """验证码破解策略基类。"""

    @abstractmethod
    def solve(self, page) -> bool:
        """尝试处理当前页面验证码。"""


class SliderSolver(BaseSolver):
    """GeeTest 滑块验证码处理策略。"""

    SLIDER_SELECTORS = [".geetest_slider_button", ".geetest_slider_knob", ".geetest_btn"]
    BG_CANVAS_SELECTORS = [".geetest_canvas_bg", "canvas.geetest_canvas_bg"]

    def solve(self, page) -> bool:
        print("  [SliderSolver] 开始处理滑块验证码")
        slider_btn = self._first_visible(page, self.SLIDER_SELECTORS)
        if not slider_btn:
            print("  [SliderSolver] 未找到滑块按钮")
            return False

        btn_box = slider_btn.bounding_box()
        if not btn_box:
            return False
        btn_x = btn_box["x"] + btn_box["width"] / 2
        btn_y = btn_box["y"] + btn_box["height"] / 2

        bg_canvas = self._first_visible(page, self.BG_CANVAS_SELECTORS)
        if not bg_canvas:
            print("  [SliderSolver] 未找到背景画布")
            return False
        bg_bytes = bg_canvas.screenshot()

        gap_x = identify_slider_gap(bg_bytes)
        if gap_x <= 0:
            print("  [SliderSolver] 缺口识别失败")
            return False

        canvas_box = bg_canvas.bounding_box()
        offset_correction = btn_box["x"] - canvas_box["x"] if canvas_box else 0
        drag_dist = gap_x + offset_correction + random.uniform(-4.0, 4.0)
        target_x = btn_x + drag_dist

        try:
            page.mouse.move(btn_x, btn_y)
            time.sleep(random.uniform(0.08, 0.15))
            page.mouse.down()
            steps = random.randint(22, 32)
            easing = random.choice([
                EasingFunctions.ease_in_out_quad,
                EasingFunctions.ease_out_quad,
                EasingFunctions.ease_in_out_cubic,
            ])
            for step in range(steps):
                progress = easing(step / steps)
                page.mouse.move(
                    btn_x + drag_dist * progress + random.uniform(-1.5, 1.5),
                    btn_y + random.uniform(-2.0, 2.0),
                )
                time.sleep(random.uniform(0.004, 0.035))
            page.mouse.move(target_x, btn_y)
            time.sleep(random.uniform(0.12, 0.22))
            page.mouse.up()
            time.sleep(2)
            try:
                return not page.locator(".geetest_slider").is_visible(timeout=1200)
            except Exception:
                return True
        except Exception as exc:
            print(f"  [SliderSolver] 拖拽异常: {exc}")
            return False

    @staticmethod
    def _first_visible(page, selectors: List[str]):
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=1500):
                    return locator
            except Exception:
                continue
        return None


class GridSolver(BaseSolver):
    """GeeTest 九宫格点选验证码处理策略。"""

    GRID_CONTAINER_SELECTORS = [".geetest_table_box", ".geetest_grid"]
    TIP_IMG_SELECTOR = ".geetest_tip_img"
    TIP_TEXT_SELECTOR = ".geetest_tip_content"
    CONFIRM_SELECTORS = [".geetest_commit", "text=确认", ".geetest_submit"]
    REFRESH_SELECTOR = ".geetest_refresh"

    def __init__(self, client: AIVisionClient):
        self.client = client

    def solve(self, page) -> bool:
        print("  [GridSolver] 开始处理九宫格点选验证码")
        grid_container = SliderSolver._first_visible(page, self.GRID_CONTAINER_SELECTORS)
        if not grid_container:
            print("  [GridSolver] 未找到九宫格容器")
            return False

        target = self._read_target(page)
        print(f"  [GridSolver] 题目: {target}")
        descriptions: List[str] = []

        try:
            if _PILImage is None:
                raise ImportError("Pillow 未安装")
            grid_img = _PILImage.open(io.BytesIO(grid_container.screenshot()))
            width, height = grid_img.size
            for row in range(3):
                crop = grid_img.crop((0, row * height / 3, width, (row + 1) * height / 3))
                buf = io.BytesIO()
                crop.save(buf, format="PNG")
                descriptions.extend(self.client.identify_grid_row(buf.getvalue(), row))
        except Exception as exc:
            print(f"  [GridSolver] 截图或识别失败: {exc}")
            return False

        click_indices = self.client.semantic_match(target, descriptions)
        if not click_indices:
            try:
                page.locator(self.REFRESH_SELECTOR).first.click()
                time.sleep(2)
            except Exception:
                pass
            return False

        try:
            box = grid_container.bounding_box()
            cell_w, cell_h = box["width"] / 3, box["height"] / 3
            for idx in click_indices:
                val = int(idx)
                if 1 <= val <= 9:
                    row, col = (val - 1) // 3, (val - 1) % 3
                    page.mouse.click(box["x"] + col * cell_w + cell_w / 2, box["y"] + row * cell_h + cell_h / 2)
                    time.sleep(random.uniform(0.28, 0.50))
        except Exception as exc:
            print(f"  [GridSolver] 点击格子异常: {exc}")
            return False

        return self._click_confirm(page)

    def _read_target(self, page) -> str:
        target = ""
        try:
            tip_img = page.locator(self.TIP_IMG_SELECTOR).first
            if tip_img.is_visible(timeout=1500):
                target = self.client.identify_captcha_target(tip_img.screenshot())
        except Exception:
            pass
        if not target:
            try:
                target = page.locator(self.TIP_TEXT_SELECTOR).first.inner_text()
            except Exception:
                pass
        return re.sub(r"[^\w]", "", target)

    def _click_confirm(self, page) -> bool:
        for selector in self.CONFIRM_SELECTORS:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    return True
            except Exception:
                continue
        return False


class TextClickSolver(BaseSolver):
    """GeeTest 文字点选验证码处理策略。"""

    CAPTCHA_CONTAINER_SELECTORS = [".geetest_window", ".geetest_panel", ".geetest_box"]
    TIP_TEXT_SELECTORS = [".geetest_tip_content", ".geetest_tip_text", ".geetest_notice"]
    CONFIRM_SELECTORS = [".geetest_commit", "text=确认", ".geetest_submit"]

    def __init__(self, client: AIVisionClient):
        self.client = client

    def solve(self, page) -> bool:
        print("  [TextClickSolver] 开始处理文字点选验证码")
        target_chars = self._read_target_chars(page)
        if not target_chars:
            print("  [TextClickSolver] 未能识别题目文字")
            return False

        container = SliderSolver._first_visible(page, self.CAPTCHA_CONTAINER_SELECTORS)
        if not container:
            print("  [TextClickSolver] 未找到验证码容器")
            return False

        box = container.bounding_box()
        positions = self.client.identify_text_positions(container.screenshot(), target_chars)
        if not positions:
            print("  [TextClickSolver] AI 未识别到文字坐标")
            return False

        for pos in positions:
            try:
                abs_x = box["x"] + float(pos.get("x", 0)) * box["width"]
                abs_y = box["y"] + float(pos.get("y", 0)) * box["height"]
                page.mouse.click(abs_x, abs_y)
                time.sleep(random.uniform(0.3, 0.6))
            except Exception as exc:
                print(f"  [TextClickSolver] 点击异常: {exc}")

        for selector in self.CONFIRM_SELECTORS:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    return True
            except Exception:
                continue
        return False

    def _read_target_chars(self, page) -> str:
        for selector in self.TIP_TEXT_SELECTORS:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=1500):
                    return re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", el.inner_text())
            except Exception:
                continue
        return ""


class CaptchaDispatcher:
    """自动检测验证码类型并分派到对应策略。"""

    DETECT_MAP = {
        "grid": [".geetest_table_box", ".geetest_grid"],
        "slider": [".geetest_slider", ".geetest_slider_button", ".geetest_canvas_bg"],
        "textclick": [".geetest_winlinor", ".geetest_ques_text", ".geetest_notice"],
    }

    def __init__(self, client: Optional[AIVisionClient] = None, max_retries: int = 3):
        self.client = client
        self.max_retries = max_retries
        self._solvers = {"slider": SliderSolver()}
        if client:
            self._solvers["grid"] = GridSolver(client)
            self._solvers["textclick"] = TextClickSolver(client)

    def detect_type(self, page) -> str:
        """检测页面验证码类型。"""

        for captcha_type, selectors in self.DETECT_MAP.items():
            for selector in selectors:
                try:
                    if page.locator(selector).is_visible(timeout=1500):
                        return captcha_type
                except Exception:
                    continue
        return "unknown"

    def solve(self, page) -> bool:
        """自动检测并破解验证码。"""

        if page is None:
            print("  [CaptchaDispatcher] page 为 None，跳过")
            return False

        captcha_type = self.detect_type(page)
        if captcha_type == "unknown":
            print("  [CaptchaDispatcher] 未检测到已知验证码")
            return False

        solver = self._solvers.get(captcha_type)
        if not solver:
            print(f"  [CaptchaDispatcher] 类型 {captcha_type} 无对应策略，可能缺少 AIVisionClient")
            return False

        for attempt in range(1, self.max_retries + 1):
            print(f"  [CaptchaDispatcher] {captcha_type} 第 {attempt}/{self.max_retries} 次尝试")
            if solver.solve(page):
                return True
            time.sleep(2)
        return False
