"""交叉引用校验的测试。"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_doc_refs  # noqa: E402
from check_doc_refs import EXEMPTIONS, run, slugify  # noqa: E402


class SlugTests(unittest.TestCase):
    def test_ascii_heading(self) -> None:
        self.assertEqual(slugify("Gates — clear these first"), "gates--clear-these-first")

    def test_chinese_punctuation_is_dropped(self) -> None:
        """顿号是 Po 类标点，GitHub 会丢掉它；按"CJK 就保留"写会永远匹配不上。"""
        self.assertEqual(
            slugify("P5.4 多邮箱适配、故障切换与验证码来源过滤"),
            "p54-多邮箱适配故障切换与验证码来源过滤",
        )

    def test_inline_code_and_links_are_unwrapped(self) -> None:
        """链接取渲染后的文本，URL 不参与锚点。"""
        self.assertEqual(slugify("`code` 与 [文本](x.md)"), "code-与-文本")

    def test_uppercase_is_lowered(self) -> None:
        self.assertEqual(slugify("P1.3 Health-Aware Pool"), "p13-health-aware-pool")


class ReferenceDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        (self.root / "kb" / "demo" / "techniques").mkdir(parents=True)
        (self.root / "kb" / "demo" / "techniques" / "01-real.md").write_text(
            "# 真篇目\n\n## 小节标题\n", encoding="utf-8"
        )
        self._original = check_doc_refs.ROOT
        check_doc_refs.ROOT = self.root
        check_doc_refs._ANCHOR_CACHE.clear()

    def tearDown(self) -> None:
        check_doc_refs.ROOT = self._original
        check_doc_refs._ANCHOR_CACHE.clear()
        self._temp.cleanup()

    def _run(self, markdown: str) -> dict:
        doc = self.root / "README.md"
        doc.write_text(textwrap.dedent(markdown), encoding="utf-8")
        check_doc_refs._ANCHOR_CACHE.clear()
        return run()

    def test_valid_link_passes(self) -> None:
        report = self._run("- [真篇目](kb/demo/techniques/01-real.md)\n")
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["links_checked"], 1)

    def test_missing_link_target_is_detected(self) -> None:
        report = self._run("- [没了](kb/demo/techniques/99-gone.md)\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "link_missing")

    def test_valid_anchor_passes(self) -> None:
        report = self._run("- [跳到小节](kb/demo/techniques/01-real.md#小节标题)\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_missing_anchor_is_detected(self) -> None:
        report = self._run("- [跳到空处](kb/demo/techniques/01-real.md#不存在的小节)\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "anchor_missing")

    def test_bare_anchor_resolves_within_the_same_document(self) -> None:
        report = self._run("# 顶层\n\n- [自指](#顶层)\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_backticked_existing_path_passes(self) -> None:
        report = self._run("见 `kb/demo/techniques/01-real.md`。\n")
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["paths_checked"], 1)

    def test_backticked_missing_path_is_detected(self) -> None:
        report = self._run("见 `kb/demo/techniques/42-ghost.md`。\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "path_missing")

    def test_skill_relative_path_resolves_against_doc_directory(self) -> None:
        skill = self.root / "skills" / "demo"
        (skill / "references").mkdir(parents=True)
        (skill / "references" / "note.md").write_text("# 笔记\n", encoding="utf-8")
        doc = skill / "SKILL.md"
        doc.write_text("见 `references/note.md`。\n", encoding="utf-8")
        self.assertTrue(run()["ok"])

    def test_external_link_is_exempt(self) -> None:
        report = self._run("- [外站](https://example.com/x.md)\n")
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["links_checked"], 1)

    def test_untracked_directory_is_exempt(self) -> None:
        report = self._run("- [报告](reports/2026-01-01.md)\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_template_path_is_exempt(self) -> None:
        report = self._run("技能路径为 `skills/<name>/SKILL.md`。\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_directory_reference_is_exempt(self) -> None:
        """目录引用常按读者自己的工作目录书写，本仓库不拥有其存在性。"""
        report = self._run("产物落到 `exports/automation/` 与 `data/device_profiles/`。\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_command_in_backticks_is_not_a_path(self) -> None:
        report = self._run("跑 `python scripts/misc/check_commands.py`。\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_code_fence_content_is_skipped(self) -> None:
        report = self._run("```bash\n# 见 kb/demo/techniques/99-ghost.md\n```\n")
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["paths_checked"], 0)


class ExemptionHygieneTests(unittest.TestCase):
    def test_every_exemption_states_a_reason(self) -> None:
        self.assertTrue(EXEMPTIONS)
        for reason, why in EXEMPTIONS:
            self.assertTrue(reason)
            self.assertGreater(len(why), 10, f"豁免 {reason} 的理由太短，等于没写")

    def test_report_prints_exemptions_with_hit_counts(self) -> None:
        report = run()
        reasons = {entry["reason"] for entry in report["exemptions"]}
        self.assertEqual(reasons, {reason for reason, _ in EXEMPTIONS})


class RealRepositoryTests(unittest.TestCase):
    def test_repository_references_all_resolve(self) -> None:
        report = run()
        self.assertTrue(
            report["ok"],
            "文档引用已断链：" + json.dumps(report["drifts"], ensure_ascii=False),
        )
        self.assertGreater(report["links_checked"], 20, "校验面太窄，守卫会形同虚设")
        self.assertGreater(report["paths_checked"], 40, "校验面太窄，守卫会形同虚设")

    def test_json_mode_keeps_output_parsable(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            check_doc_refs.main(["--json"])
        json.loads(stream.getvalue())


if __name__ == "__main__":
    unittest.main()
