"""文档命令真实性校验的测试。

重点不是"能不能跑通"，而是**它真的会报错**：一个永远返回 ok 的守卫
比没有守卫更糟，因为它会让人以为文档是对的。
"""

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

import check_commands  # noqa: E402
from check_commands import EXEMPTIONS, extract_cli, run  # noqa: E402

SAMPLE_SCRIPT = '''
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("query", nargs="?")
parser.add_argument("--verify", action="store_true")
parser.add_argument("--top-k", type=int, default=5)

sub = parser.add_subparsers(dest="command", required=True)
p_add = sub.add_parser("add")
p_add.add_argument("--title", required=True)
p_add.add_argument("--reuse", default="medium")
sub.add_parser("validate")
'''


class CliExtractionTests(unittest.TestCase):
    def _spec(self):
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "sample.py"
            script.write_text(textwrap.dedent(SAMPLE_SCRIPT), encoding="utf-8", newline="\n")
            return extract_cli(script)

    def test_reads_top_level_options(self) -> None:
        spec = self._spec()
        self.assertIn("--verify", spec.options)
        self.assertIn("--top-k", spec.options)
        self.assertFalse(spec.options["--verify"], "store_true 不需要值")
        self.assertTrue(spec.options["--top-k"], "--top-k 需要一个值")

    def test_reads_assigned_subcommands(self) -> None:
        spec = self._spec()
        self.assertIn("add", spec.subcommands)
        self.assertIn("--title", spec.subcommands["add"])

    def test_reads_unassigned_subcommands(self) -> None:
        """`sub.add_parser("validate")` 不赋值也必须被登记。

        漏掉这一种会把真命令误报成未知子命令——本仓库的 ai_finding.py 就是这么写的。
        """
        spec = self._spec()
        self.assertIn("validate", spec.subcommands)

    def test_unparsable_script_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "broken.py"
            script.write_text("def (:\n", encoding="utf-8", newline="\n")
            self.assertIsNone(extract_cli(script))


class DriftDetectionTests(unittest.TestCase):
    """每条判据都要有能触发它的用例。"""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "tool.py").write_text(
            textwrap.dedent(SAMPLE_SCRIPT), encoding="utf-8", newline="\n"
        )
        self._original_root = check_commands.ROOT
        check_commands.ROOT = self.root

    def tearDown(self) -> None:
        check_commands.ROOT = self._original_root
        self._temp.cleanup()

    def _run(self, markdown: str) -> dict:
        doc = self.root / "README.md"
        doc.write_text(textwrap.dedent(markdown), encoding="utf-8", newline="\n")
        return run()

    def test_valid_command_passes(self) -> None:
        report = self._run(
            """
            ```bash
            python scripts/tool.py add --title hello
            python scripts/tool.py --verify add --title hello
            ```
            """
        )
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["checked_commands"], 2)

    def test_top_level_options_may_precede_the_subcommand(self) -> None:
        """argparse 允许 `tool.py --verbose add ...`；早先的写法会把它误报成未知子命令。"""
        report = self._run("```bash\npython scripts/tool.py --top-k 2 add --title x\n```\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_missing_required_subcommand_is_detected(self) -> None:
        report = self._run("```bash\npython scripts/tool.py --verify\n```\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "unknown_subcommand")
        self.assertIn("一个也没给", report["drifts"][0]["detail"])

    def test_optional_subparsers_do_not_require_a_subcommand(self) -> None:
        (self.root / "scripts" / "loose.py").write_text(
            "import argparse\n\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--verbose', action='store_true')\n"
            "sub = parser.add_subparsers(dest='command')\n"
            "sub.add_parser('run')\n",
            encoding="utf-8", newline="\n",
        )
        report = self._run("```bash\npython scripts/loose.py --verbose\n```\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_unknown_option_is_detected(self) -> None:
        report = self._run("```bash\npython scripts/tool.py add --nope\n```\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "unknown_option")

    def test_unknown_subcommand_is_detected(self) -> None:
        report = self._run("```bash\npython scripts/tool.py frobnicate\n```\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "unknown_subcommand")

    def test_option_for_wrong_subcommand_is_detected(self) -> None:
        report = self._run("```bash\npython scripts/tool.py validate --title x\n```\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "unknown_option")
        self.assertIn("tool.py validate", report["drifts"][0]["detail"])

    def test_missing_value_is_detected(self) -> None:
        report = self._run("```bash\npython scripts/tool.py add --title\n```\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "missing_value")

    def test_option_swallowing_next_option_is_detected(self) -> None:
        """上游那条判据：不能把"像选项的 token"当作上一个选项的值。"""
        report = self._run("```bash\npython scripts/tool.py --top-k --verify\n```\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "missing_value")

    def test_missing_script_is_detected(self) -> None:
        report = self._run("```bash\npython scripts/ghost.py --verify\n```\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "script_missing")

    def test_inline_value_is_accepted(self) -> None:
        report = self._run("```bash\npython scripts/tool.py --top-k=3 add --title x\n```\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_negative_number_is_a_value_not_an_option(self) -> None:
        report = self._run("```bash\npython scripts/tool.py --top-k -1 add --title x\n```\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_trailing_comment_is_ignored(self) -> None:
        report = self._run("```bash\npython scripts/tool.py add --title x   # 注释\n```\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_backslash_continuation_is_joined(self) -> None:
        report = self._run(
            """
            ```powershell
            python scripts/tool.py `
              --top-k 2 `
              add `
              --title x
            ```
            """
        )
        self.assertTrue(report["ok"], report["drifts"])

    def test_windows_backslash_path_resolves(self) -> None:
        report = self._run("```powershell\npython .\\scripts\\tool.py validate\n```\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_docs_snapshot_resolves_against_tools_mirror(self) -> None:
        mirror = self.root / "tools" / "modules" / "alpha"
        mirror.mkdir(parents=True)
        (mirror / "main.py").write_text("import argparse\n", encoding="utf-8", newline="\n")
        doc = self.root / "docs" / "modules" / "alpha" / "README.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("```bash\npython main.py\n```\n", encoding="utf-8", newline="\n")
        self.assertTrue(run()["ok"])

    def test_placeholder_is_exempt(self) -> None:
        report = self._run("```bash\npython scripts/tool.py add --title ...\n```\n")
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["checked_commands"], 0)

    def test_synopsis_is_exempt(self) -> None:
        report = self._run("```bash\npython scripts/tool.py add|validate\n```\n")
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["checked_commands"], 0)

    def test_interpreter_dash_m_is_exempt(self) -> None:
        report = self._run("```bash\npython -m unittest discover -s tests\n```\n")
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["checked_commands"], 0)

    def test_drift_carries_file_and_line(self) -> None:
        report = self._run("text\n\n```bash\npython scripts/tool.py --nope\n```\n")
        drift = report["drifts"][0]
        self.assertEqual(drift["file"], "README.md")
        self.assertEqual(drift["line"], 4)


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
        for entry in report["exemptions"]:
            self.assertIn("hits", entry)


class RealRepositoryTests(unittest.TestCase):
    def test_repository_documents_have_no_command_drift(self) -> None:
        report = run()
        self.assertTrue(
            report["ok"],
            "文档里的命令与脚本 argparse 表已分叉："
            + json.dumps(report["drifts"], ensure_ascii=False),
        )
        self.assertGreater(report["checked_commands"], 20, "校验面太窄，守卫会形同虚设")

    def test_json_mode_keeps_output_parsable(self) -> None:
        """`--json` 不能追加 RESULT 令牌，否则下游 json.loads 直接失败。"""
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = check_commands.main(["--json"])
        payload = json.loads(stream.getvalue())
        self.assertIn("ok", payload)
        self.assertEqual(code, 0 if payload["ok"] else 1)


if __name__ == "__main__":
    unittest.main()
