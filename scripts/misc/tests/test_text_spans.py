"""散文区间（`text_spans.py`）的离线测试。

这一层决定拆解器能不能用：关键词出现在**注释与文档字符串**里时那是叙述，
不是代码证据。实测四处误报全在这一层（文档字符串里的示例命令、用法说明里的域名）。

两个层次各钉一遍：

- `TestProseSpansUnit` 直接钉两个纯函数的契约（区间识别、等长抹除）。
- `TestProseFiltering` 从 `analyze()` 走一遍，钉"过滤真的生效且被说明"。

夹具与沙箱基类在 `_teardown_support.py`。引擎用例在 `test_script_teardown.py`。
"""

from __future__ import annotations

import ast
import unittest

from _teardown_support import (  # noqa: E402  —— 必须最先导入：它负责把 scripts/misc 放进 sys.path
    EVIDENCE_PY,
    PROSE_BLOCK_JS,
    PROSE_JS,
    PROSE_PY,
    SLASH_IN_STRING_JS,
    SandboxCase,
    _write,
)
from script_teardown import analyze  # noqa: E402
from text_spans import blank_spans, prose_spans  # noqa: E402

class TestProseFiltering(SandboxCase):
    """注释与文档字符串里的关键词是**叙述**，不是代码证据。

    这一层是实测逼出来的：不过滤时，`scripts/automation` 自扫会产出 4 处误报，
    而误报会直接进"复用候选"——候选是给人照着做的，错了就是把人带沟里。
    """

    def _ids(self, report: dict) -> set[str]:
        return {bucket["id"] for bucket in report["features"]}

    def _gaps(self, report: dict) -> set[str]:
        return {item["id"] for item in report["gaps"]}

    def test_python_prose_keywords_are_not_evidence(self):
        directory = self.case_dir("prose_py")
        _write(directory, "sample.py", PROSE_PY)
        report = analyze([directory])
        self.assertNotIn("captcha", self._ids(report))
        self.assertNotIn("sms", self._ids(report))
        self.assertNotIn("device", self._ids(report))

    def test_filtered_dimensions_land_in_gaps_not_in_silence(self):
        # 过滤 ≠ 消失：该维度必须落到"缺口"里被人看见，
        # 否则读者会以为"扫过了、确实没有"，而真相是"有，但在注释里"。
        directory = self.case_dir("prose_gap")
        _write(directory, "sample.py", PROSE_PY)
        report = analyze([directory])
        self.assertIn("captcha", self._gaps(report))
        self.assertIn("device", self._gaps(report))

    def test_python_string_literal_is_still_evidence(self):
        directory = self.case_dir("evidence_py")
        _write(directory, "sample.py", EVIDENCE_PY)
        report = analyze([directory])
        self.assertIn("device", self._ids(report))

    def test_js_line_comment_is_filtered(self):
        directory = self.case_dir("prose_js_line")
        _write(directory, "sample.js", PROSE_JS)
        report = analyze([directory])
        self.assertNotIn("captcha", self._ids(report))

    def test_js_block_comment_is_filtered(self):
        directory = self.case_dir("prose_js_block")
        _write(directory, "sample.js", PROSE_BLOCK_JS)
        report = analyze([directory])
        self.assertNotIn("device", self._ids(report))

    def test_js_double_slash_inside_a_string_does_not_swallow_the_line(self):
        directory = self.case_dir("prose_js_url")
        _write(directory, "sample.js", SLASH_IN_STRING_JS)
        report = analyze([directory])
        self.assertIn("device", self._ids(report))

    def test_line_numbers_survive_blanking(self):
        # 行号是本工具唯一能被逐条复核的证据。用"删掉再匹配"的写法会整体前移，
        # 读者回看时看到的是另一行——所以 blank_spans 必须等长替换。
        directory = self.case_dir("prose_lines")
        _write(directory, "sample.py", EVIDENCE_PY)
        report = analyze([directory])
        bucket = next(b for b in report["features"] if b["id"] == "device")
        line = bucket["hits"][0]["line"]
        self.assertIn("User-Agent", EVIDENCE_PY.splitlines()[line - 1])

    def test_filtering_is_disclosed_with_a_count(self):
        directory = self.case_dir("prose_disclosed")
        _write(directory, "sample.py", PROSE_PY)
        report = analyze([directory])
        self.assertGreater(report["scope"]["prose_spans_masked"], 0)
        self.assertTrue(
            any("去散文过滤" in note for note in report["notes"]),
            "过滤必须被说明；静默剔除会让人以为这里本来就没有关键词",
        )

    def test_no_prose_means_no_disclosure_note(self):
        # 提示不能无条件出现，否则它变成背景噪声，真出问题时没人看。
        directory = self.case_dir("prose_none")
        _write(directory, "sample.py", EVIDENCE_PY)
        report = analyze([directory])
        self.assertEqual(report["scope"]["prose_spans_masked"], 0)
        self.assertFalse(any("去散文过滤" in note for note in report["notes"]))


class TestProseSpansUnit(unittest.TestCase):
    """直接钉住两个纯函数的契约，不经过扫描链路。"""

    def test_python_docstring_and_comment_spans(self):
        import ast as _ast

        text = PROSE_PY
        spans = prose_spans(text, "python", _ast.parse(text))
        self.assertEqual(len(spans), 2, "一条文档字符串 + 一条行注释")

    def test_js_block_comment_span_is_one_run(self):
        spans = prose_spans(PROSE_BLOCK_JS, "javascript", None)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0][0], 1)
        self.assertEqual(spans[0][2], 3)

    def test_blank_spans_preserves_length_and_newlines(self):
        text = PROSE_PY
        blanked = blank_spans(text, [(1, 0, 1, 20)])
        self.assertEqual(len(blanked), len(text))
        self.assertEqual(blanked.count("\n"), text.count("\n"))
        self.assertEqual(blanked.splitlines()[1:], text.splitlines()[1:])

    def test_blank_spans_with_no_spans_returns_input(self):
        self.assertEqual(blank_spans(PROSE_PY, []), PROSE_PY)

    def test_blank_spans_tolerates_out_of_range_rows(self):
        # 扫描器对畸形输入不能抛异常：宁可少抹一段，也不能把整次扫描带走。
        self.assertEqual(blank_spans("abc\n", [(99, 0, 99, 3)]), "abc\n")

if __name__ == "__main__":
    unittest.main()
