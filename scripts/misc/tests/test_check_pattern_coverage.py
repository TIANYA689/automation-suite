"""`check_pattern_coverage.py` 的回归网（F9）。

这个脚本是 CI 门禁，此前**没有任何测试**。它的空转守卫是 `bool(defined)`：
一个 P 标题都解析不到时 `ok` 必须是 `False`——否则「判据解析不到行」会与「覆盖齐全」
长得一模一样（规则 10 的老问题）。
"""

from __future__ import annotations

import atexit
import contextlib
import io
import itertools
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_pattern_coverage as cpc  # noqa: E402
from check_pattern_coverage import inspect_skill, ordered_unique, pattern_key  # noqa: E402

# 模块共用一个沙箱：热路径里没有 rmtree（规则 36）。
_TMP_ROOT = Path(__file__).resolve().parents[3] / "tmp"
_TMP_ROOT.mkdir(exist_ok=True)
_SANDBOX = Path(tempfile.mkdtemp(dir=_TMP_ROOT, prefix="patcov-test-"))
_COUNTER = itertools.count()

_REAL_ROOT = Path(cpc.__file__).resolve().parents[2]


def _cleanup(target: Path) -> None:
    """删不掉就留着，绝不把调用方带走（沙箱拦 rmtree 是预期）。"""
    try:
        shutil.rmtree(target, ignore_errors=True)
    except SystemExit:
        pass


atexit.register(_cleanup, _SANDBOX)


def _gate(rows: str) -> str:
    return (
        f"{cpc.START_MARKER}\n"
        "| Pattern | 状态 |\n|---|---|\n"
        f"{rows}"
        f"{cpc.END_MARKER}\n"
    )


def _skill(headings: str, rows: str) -> str:
    """拼一份技能正文。

    **不能用 `textwrap.dedent`**：`_gate()` 产出的行是顶格的，与缩进的三引号字面量
    拼在一起后，公共缩进变成空串，`### P1` 会保留前导空格而匹配不上 `^#{3,4}`
    ——第一版就是这么做然后整批翻红的。所以这里显式拼、不缩进。
    """
    return f"# 技能\n\n{headings}\n{_gate(rows)}"


FULL_ROWS = "| P1 | apply |\n| P1.1 | skip |\n| P2 | pending |\n"


class _SkillCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _SANDBOX / f"case-{next(_COUNTER)}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.relative = Path("skills/demo/SKILL.md")

    def _write(self, body: str) -> None:
        path = self.root / self.relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")

    def _inspect(self) -> dict:
        return inspect_skill(self.root, self.relative)


class PatternKeyTests(unittest.TestCase):
    def test_numeric_not_lexicographic(self) -> None:
        """`P10` 必须排在 `P2` 之后——按字符串排会得到 `P1, P10, P2`。"""
        self.assertLess(pattern_key("2"), pattern_key("10"))

    def test_nested_compares_by_segment(self) -> None:
        self.assertLess(pattern_key("1.2"), pattern_key("1.10"))
        self.assertLess(pattern_key("1"), pattern_key("1.1"))

    def test_ordered_unique_sorts_and_dedupes(self) -> None:
        self.assertEqual(ordered_unique(["2", "1.1", "10", "1.1"]), ["1.1", "2", "10"])


class InspectSkillTests(_SkillCase):
    def test_complete_coverage_passes(self) -> None:
        self._write(_skill("### P1 第一类\n### P1.1 子类\n### P2 第二类", FULL_ROWS))
        report = self._inspect()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["defined_count"], 3)
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["unknown"], [])

    def test_defined_but_not_covered_is_flagged(self) -> None:
        self._write(_skill("### P1 第一类\n### P2 第二类", "| P1 | apply |\n| skip | pending |\n"))
        report = self._inspect()
        self.assertFalse(report["ok"])
        self.assertEqual(report["missing"], ["P2"])

    def test_covered_but_not_defined_is_flagged(self) -> None:
        """反向也要报：覆盖清单里出现不存在的 Pattern，说明清单本身过期了。"""
        self._write(_skill("### P1 第一类", "| P1 | apply |\n| P9 | skip |\n| pending | |\n"))
        report = self._inspect()
        self.assertFalse(report["ok"])
        self.assertEqual(report["unknown"], ["P9"])

    def test_missing_markers_are_flagged(self) -> None:
        self._write("# 技能\n\n### P1 第一类\n")
        report = self._inspect()
        self.assertFalse(report["ok"])
        self.assertTrue(report["marker_error"])

    def test_missing_required_state_is_flagged(self) -> None:
        """三种状态（apply/skip/pending）缺一即红——它们是这套清单的语义，不是装饰。"""
        self._write(_skill("### P1 第一类", "| P1 | apply |\n"))
        report = self._inspect()
        self.assertFalse(report["ok"])
        self.assertIn("skip", report["missing_states"])
        self.assertIn("pending", report["missing_states"])

    def test_no_pattern_headings_must_not_pass(self) -> None:
        """**空转守卫**：一个 P 标题都解析不到时，`ok` 必须是 False。

        否则「判据解析不到行」会与「覆盖齐全」同形——这是本文件最该钉的一条。
        """
        self._write(_skill("没有任何 Pattern 标题。", "| apply | skip | pending |\n"))
        report = self._inspect()
        self.assertFalse(report["ok"], "解析不到 Pattern 却报 ok，判据等于空转")
        self.assertEqual(report["defined_count"], 0)

    def test_heading_level_five_is_not_a_pattern_heading(self) -> None:
        """标题级别是 `#{3,4}`：`##### P1` 是更深的小节，不算 Pattern 定义。"""
        self._write(_skill("##### P7 太深了", "| apply | skip | pending |\n"))
        self.assertEqual(self._inspect()["defined"], [])

    def test_heading_without_space_is_not_a_pattern_heading(self) -> None:
        """`###P1` 不是合法 ATX 标题（CommonMark 要求 `#` 后要有空格）。"""
        self._write(_skill("###P1 挤在一起", "| apply | skip | pending |\n"))
        self.assertEqual(self._inspect()["defined"], [])


class MainTests(_SkillCase):
    def _run_main(self, argv: list[str]) -> tuple[int, dict]:
        stream = io.StringIO()
        original = sys.argv
        sys.argv = ["check_pattern_coverage.py", *argv]
        try:
            with contextlib.redirect_stdout(stream):
                code = cpc.main()
        finally:
            sys.argv = original
        return code, json.loads(stream.getvalue())

    def test_exit_zero_when_covered(self) -> None:
        self._write(_skill("### P1 第一类", "| P1 | apply | skip | pending |\n"))
        code, report = self._run_main(["--root", str(self.root), "--skill", str(self.relative)])
        self.assertEqual(code, 0, report)
        self.assertTrue(report["ok"])

    def test_exit_nonzero_when_a_pattern_is_missing(self) -> None:
        self._write(_skill("### P1 第一类\n### P2 第二类", "| P1 | apply | skip | pending |\n"))
        code, report = self._run_main(["--root", str(self.root), "--skill", str(self.relative)])
        self.assertEqual(code, 1, "有缺口却 exit=0，门禁形同虚设")
        self.assertFalse(report["ok"])

    def test_report_writes_json_file_when_asked(self) -> None:
        self._write(_skill("### P1 第一类", "| P1 | apply | skip | pending |\n"))
        code, _ = self._run_main(
            ["--root", str(self.root), "--skill", str(self.relative), "--output", "out.json"]
        )
        self.assertEqual(code, 0)
        written = self.root / "out.json"
        self.assertTrue(written.is_file(), "--output 没有落盘")
        json.loads(written.read_text(encoding="utf-8"))


class RealRepositoryTests(unittest.TestCase):
    """打在真仓库上：门禁若指向空气，前面所有沙箱判据都是自娱自乐。"""

    def test_declared_skill_paths_exist(self) -> None:
        self.assertTrue(cpc.SKILL_PATHS, "技能清单为空则判据空转")
        for relative in cpc.SKILL_PATHS:
            self.assertTrue((_REAL_ROOT / relative).is_file(), f"{relative} 不存在了")

    def test_real_skills_pass(self) -> None:
        for relative in cpc.SKILL_PATHS:
            report = inspect_skill(_REAL_ROOT, relative)
            self.assertTrue(report["ok"], json.dumps(report, ensure_ascii=False))
            self.assertGreater(report["defined_count"], 0, "解析不到 Pattern = 判据空转")


if __name__ == "__main__":
    unittest.main()
