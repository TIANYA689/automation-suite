"""呈现层（`teardown_render.py`）的离线测试。

呈现层的失效方式很特别：它**不会报错**，只会让表格歪掉、让行号跟文件名黏在一起。
而"看起来不可信"和"不可信"在交接时的后果一样——所以列宽与截断要单独钉住。

夹具与沙箱基类在 `_teardown_support.py`。引擎用例在 `test_script_teardown.py`。
"""

from __future__ import annotations

import unittest

from _teardown_support import READABLE_PY, SECRET_PY, SandboxCase, _write  # noqa: E402
from script_teardown import analyze  # noqa: E402
from teardown_render import (  # noqa: E402
    clip,
    clip_where,
    display_width,
    pad,
    render,
)
from teardown_rules import TIERS  # noqa: E402


class TestColumnClipping(unittest.TestCase):
    """长名字不能顶穿列宽。

    实测原形：`雨云每日签到+自动提现（自动过验证.py` 显示宽度 36，
    在 34 列里把整张表挤歪，行号跟文件名黏在一起——
    **表格歪掉就等于不可读**，而"看起来不可信"和"不可信"在交接时后果一样。
    """

    LONG_CJK = "雨云每日签到+自动提现（自动过验证.py"

    def test_clip_short_text_is_untouched(self):
        self.assertEqual(clip("abc.py", 10), "abc.py")

    def test_clip_respects_display_width(self):
        clipped = clip(self.LONG_CJK, 34)
        self.assertLessEqual(display_width(clipped), 34)
        self.assertTrue(clipped.endswith("…"))

    def test_clip_counts_cjk_as_two_columns(self):
        # 按字符数截会截出双倍宽度：20 个中文字符占 36 列。
        self.assertLess(display_width(clip(self.LONG_CJK, 34)), 35)
        self.assertGreater(display_width(clip(self.LONG_CJK, 34)), 25)

    def test_clip_where_keeps_the_line_number(self):
        # 行号是唯一能被逐条复核的证据，截掉它这条命中就没法核了。
        clipped = clip_where(f"{self.LONG_CJK}:1612", 26)
        self.assertTrue(clipped.endswith(":1612"))
        self.assertLessEqual(display_width(clipped), 26)

    def test_clip_where_without_line_number_falls_back_to_clip(self):
        self.assertLessEqual(display_width(clip_where(self.LONG_CJK, 20)), 20)

    def test_long_filename_keeps_the_table_aligned(self):
        report = {
            "targets": ["x"],
            "scope": {},
            "counts": {"files": 1, "readable": 1, "minified": 0, "obfuscated": 0, "vendor": 0, "unreadable": 0},
            "skipped": {},
            "files": [
                {
                    "path": "x",
                    "name": self.LONG_CJK,
                    "language": "python",
                    "kind": "readable",
                    "confidence": "high",
                    "why": [],
                    "lines": 2127,
                    "parse_ok": True,
                    "symbols": [],
                    "features": [],
                    "risks": [],
                }
            ],
            "features": [],
            "reuse": {tier: [] for tier in TIERS},
            "non_reference": [],
            "gaps": [],
            "risks": [],
            "notes": [],
            "confidence": "heuristic",
            "disclosure": "d",
        }
        text = render(report)
        section = text.split("1. 结构清单", 1)[1].split("2. 能力矩阵", 1)[0]
        rows = [line for line in section.splitlines() if "可读" in line]
        self.assertEqual(len(rows), 1, rows)
        for line in rows + [section.splitlines()[1]]:
            self.assertLessEqual(display_width(line), 66, line)
        # 类型列落在同一显示列上：表头与数据行的 `类型`/`可读` 起始列必须一致。
        header, row = section.splitlines()[1], rows[0]
        self.assertEqual(
            display_width(header[: header.index("类型")]),
            display_width(row[: row.index("可读")]),
        )


# ---------------------------------------------------------------- 渲染


class TestRendering(SandboxCase):
    def setUp(self):
        self.directory = self.case_dir("render")
        _write(self.directory, "signin.py", READABLE_PY)
        _write(self.directory, "leak.py", SECRET_PY)
        self.report = analyze([self.directory])

    def test_render_names_the_tool_and_the_scope(self):
        text = render(self.report)
        self.assertIn("第三方脚本静态拆解", text)
        self.assertIn("未导入、未执行、未联网", text)

    def test_render_has_all_sections(self):
        text = render(self.report)
        for section in ("1. 结构清单", "2. 能力矩阵", "3. 复用候选", "4. 缺口"):
            with self.subTest(section=section):
                self.assertIn(section, text)

    def test_render_shows_risk_section_when_risks_exist(self):
        self.assertIn("5. 风险与拒绝吸收", render(self.report))

    def test_ascii_mode_uses_ascii_rules(self):
        text = render(self.report, box=False)
        self.assertIn("+===", text)
        self.assertNotIn("═", text)

    def test_unicode_mode_uses_box_rules(self):
        self.assertIn("═", render(self.report, box=True))

    def test_top_caps_the_listing(self):
        for index in range(4):
            _write(self.directory, f"extra{index}.py", READABLE_PY)
        text = render(analyze([self.directory]), top=1)
        self.assertIn("--top 可调", text)

    def test_delivery_hit_has_no_line_number_suffix(self):
        _write(self.directory, "README.md", "# x\n")
        text = render(analyze([self.directory]))
        self.assertIn("README.md ", text)
        self.assertNotIn("README.md:0", text)


class TestDisplayWidth(unittest.TestCase):
    """对齐是"报告可信"的一部分：整列歪掉的表会被当成随手拼的输出。"""

    def test_cjk_counts_as_two_columns(self):
        self.assertEqual(display_width("配置集中"), 8)
        self.assertEqual(display_width("abcd"), 4)

    def test_pad_fills_by_display_width(self):
        self.assertEqual(display_width(pad("配置集中", 14)), 14)
        self.assertEqual(display_width(pad("abcd", 14)), 14)

    def test_pad_never_truncates(self):
        self.assertEqual(pad("配置集中", 2), "配置集中")

    def test_pad_right_aligns(self):
        self.assertEqual(pad("7", 3, "right"), "  7")


class TestReuseSummary(unittest.TestCase):
    """复用候选的汇总行不能把同一个标签重复列举。

    实测原形（第二轮真用，17 个样本）：`代理凭据明文` 在三个文件里各命中一次，
    汇总成「拒绝吸收 7 项  硬编码凭据、会话凭据离开 CookieJar、硬编码凭据、
    代理凭据明文、硬编码凭据、代理凭据明文、代理凭据明文」——
    同一句话重复三遍且**没有归属**，读者既看不出有几类、也看不出哪个是哪个。
    """

    def _report(self, refuse_items: list[dict]) -> dict:
        return {
            "targets": ["x"],
            "scope": {},
            "counts": {
                "files": 1,
                "readable": 1,
                "minified": 0,
                "obfuscated": 0,
                "vendor": 0,
                "unreadable": 0,
            },
            "skipped": {},
            "files": [],
            "features": [],
            "reuse": {
                tier: (refuse_items if tier == "refuse" else []) for tier in TIERS
            },
            "non_reference": [],
            "gaps": [],
            "risks": [],
            "notes": [],
            "confidence": "heuristic",
            "disclosure": "d",
        }

    def _summary_line(self, text: str) -> str:
        section = text.split("3. 复用候选", 1)[1].split("4. 缺口", 1)[0]
        return next(line for line in section.splitlines() if "拒绝吸收" in line)

    def test_repeated_labels_are_deduped(self):
        items = [
            {"id": "hardcoded_secret", "label": "硬编码凭据", "pattern_ref": "—", "files": ["a.py"]},
            {"id": "hardcoded_secret", "label": "硬编码凭据", "pattern_ref": "—", "files": ["b.py"]},
            {"id": "proxy_credential_in_url", "label": "代理凭据明文", "pattern_ref": "—", "files": ["c.py"]},
        ]
        line = self._summary_line(render(self._report(items)))
        # 命中数与类数不等时两个都报：只说类数会丢掉"这条规则多个文件都犯了"，
        # 只说命中数会让人以为有三条不同的规则。
        self.assertIn("3 处 / 2 类", line)
        self.assertEqual(line.count("硬编码凭据"), 1)
        self.assertEqual(line.count("代理凭据明文"), 1)

    def test_distinct_labels_keep_the_plain_count(self):
        items = [
            {"id": "a", "label": "硬编码凭据", "pattern_ref": "—", "files": ["a.py"]},
            {"id": "b", "label": "代理凭据明文", "pattern_ref": "—", "files": ["b.py"]},
        ]
        line = self._summary_line(render(self._report(items)))
        self.assertIn("2 项", line)
        self.assertNotIn("类", line)


if __name__ == "__main__":
    unittest.main()
