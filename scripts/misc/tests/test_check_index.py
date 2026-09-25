"""索引完备性校验的测试。"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_index  # noqa: E402
from check_index import run  # noqa: E402


class CompletenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self._originals = (
            check_index.ROOT,
            check_index.KB_ROOT,
            check_index.SKILLS_ROOT,
            check_index.SCRIPTS_ROOT,
            check_index.ROUTING_SOURCE,
        )
        check_index.ROOT = self.root
        check_index.KB_ROOT = self.root / "kb"
        check_index.SKILLS_ROOT = self.root / "skills"
        check_index.SCRIPTS_ROOT = self.root / "scripts"
        check_index.ROUTING_SOURCE = self.root / "routing.source.json"
        (self.root / "kb" / "demo" / "techniques").mkdir(parents=True)
        (self.root / "skills").mkdir()
        (self.root / "scripts").mkdir()

    def tearDown(self) -> None:
        (
            check_index.ROOT,
            check_index.KB_ROOT,
            check_index.SKILLS_ROOT,
            check_index.SCRIPTS_ROOT,
            check_index.ROUTING_SOURCE,
        ) = self._originals
        self._temp.cleanup()

    def _write_index(self, files: list[str], signals: list[str] | None = None) -> None:
        """files 为空时写出空 entries，而不是写一条 files=[] 的残缺条目。"""
        entries = (
            [
                {
                    "id": "demo",
                    "signals": ["信号"] if signals is None else signals,
                    "files": files,
                    "priority": 10,
                }
            ]
            if files or signals is not None
            else []
        )
        payload = {"version": "1.0", "entries": entries}
        (self.root / "kb" / "demo" / "techniques" / "kb-index.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n"
        )

    def _write_skill(self, name: str, references: dict[str, str] | None = None) -> None:
        directory = self.root / "skills" / name
        directory.mkdir(parents=True, exist_ok=True)
        body = f"# {name}\n"
        if references:
            (directory / "references").mkdir(exist_ok=True)
            for filename, content in references.items():
                (directory / "references" / filename).write_text(content, encoding="utf-8", newline="\n")
                body += f"\n见 `{filename}`。\n"
        (directory / "SKILL.md").write_text(body, encoding="utf-8", newline="\n")

    def _write_routing(self, skills: list[str]) -> None:
        (self.root / "routing.source.json").write_text(
            json.dumps({"skills": {name: {"signals": []} for name in skills}}, ensure_ascii=False),
            encoding="utf-8", newline="\n",
        )

    def _kinds(self, report: dict) -> list[str]:
        return [drift["kind"] for drift in report["drifts"]]

    def test_clean_tree_passes(self) -> None:
        (self.root / "kb" / "demo" / "techniques" / "01-real.md").write_text("# x\n", encoding="utf-8", newline="\n")
        self._write_index(["01-real.md"])
        self._write_skill("alpha", {"note.md": "# 笔记\n"})
        self._write_routing(["alpha"])
        self.assertTrue(run()["ok"], run()["drifts"])

    def test_unindexed_kb_file_is_detected(self) -> None:
        """这是漂移检查看不见的那一类：从未入索引的篇目等于不存在。"""
        (self.root / "kb" / "demo" / "techniques" / "01-real.md").write_text("# x\n", encoding="utf-8", newline="\n")
        (self.root / "kb" / "demo" / "techniques" / "02-orphan.md").write_text("# y\n", encoding="utf-8", newline="\n")
        self._write_index(["01-real.md"])
        self._write_routing([])
        report = run()
        self.assertIn("kb_orphan_file", self._kinds(report))
        self.assertIn("02-orphan.md", json.dumps(report["drifts"], ensure_ascii=False))

    def test_domain_without_index_is_detected(self) -> None:
        """整个领域目录缺索引时，rglob 遍历不到它——这是本脚本最容易瞎掉的一处。"""
        self._write_index([])
        self._write_routing([])
        orphan = self.root / "kb" / "ghost" / "techniques"
        orphan.mkdir(parents=True)
        (orphan / "01-lost.md").write_text("# 没人找得到我\n", encoding="utf-8", newline="\n")
        report = run()
        self.assertIn("kb_index_missing", self._kinds(report))
        self.assertIn("01-lost.md", json.dumps(report["drifts"], ensure_ascii=False))

    def test_domain_with_index_is_not_flagged(self) -> None:
        (self.root / "kb" / "demo" / "techniques" / "01-real.md").write_text("# x\n", encoding="utf-8", newline="\n")
        self._write_index(["01-real.md"])
        self._write_routing([])
        self.assertNotIn("kb_index_missing", self._kinds(run()))

    def test_index_pointing_at_nothing_is_detected(self) -> None:
        self._write_index(["99-ghost.md"])
        self._write_routing([])
        self.assertIn("kb_missing_file", self._kinds(run()))

    def test_empty_entry_is_detected(self) -> None:
        (self.root / "kb" / "demo" / "techniques" / "01-real.md").write_text("# x\n", encoding="utf-8", newline="\n")
        self._write_index(["01-real.md"], signals=[])
        self._write_routing([])
        self.assertIn("kb_empty_entry", self._kinds(run()))

    def test_undeclared_skill_is_detected(self) -> None:
        self._write_index([])
        self._write_skill("alpha")
        self._write_routing([])
        self.assertIn("skill_undeclared", self._kinds(run()))

    def test_declared_skill_without_directory_is_detected(self) -> None:
        self._write_index([])
        self._write_routing(["ghost"])
        self.assertIn("skill_missing", self._kinds(run()))

    def test_orphan_reference_is_detected(self) -> None:
        self._write_index([])
        directory = self.root / "skills" / "alpha"
        (directory / "references").mkdir(parents=True)
        (directory / "SKILL.md").write_text("# alpha\n", encoding="utf-8", newline="\n")
        (directory / "references" / "unused.md").write_text("# 没人读我\n", encoding="utf-8", newline="\n")
        self._write_routing(["alpha"])
        self.assertIn("reference_orphan", self._kinds(run()))

    def test_orphan_script_is_detected(self) -> None:
        self._write_index([])
        self._write_routing([])
        (self.root / "scripts" / "lonely.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
        report = run()
        self.assertIn("script_orphan", self._kinds(report))

    def test_exempt_script_prefixes_are_skipped(self) -> None:
        self._write_index([])
        self._write_routing([])
        internal = self.root / "scripts" / "automation" / "routing"
        internal.mkdir(parents=True)
        (internal / "engine.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
        tests = self.root / "scripts" / "misc" / "tests"
        tests.mkdir(parents=True)
        (tests / "test_x.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
        self.assertTrue(run()["ok"], run()["drifts"])

    def test_backup_directory_is_not_a_skill(self) -> None:
        self._write_index([])
        self._write_routing([])
        (self.root / "skills" / "skills 原始备份").mkdir(parents=True)
        self.assertTrue(run()["ok"], run()["drifts"])


class RealRepositoryTests(unittest.TestCase):
    def test_repository_indexes_are_complete(self) -> None:
        report = run()
        self.assertTrue(
            report["ok"],
            "索引漏登或指向空气：" + json.dumps(report["drifts"], ensure_ascii=False),
        )
        self.assertGreaterEqual(report["declared_skills"], 10)
        self.assertGreaterEqual(report["kb_files"], 10)

    def test_json_mode_keeps_output_parsable(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            check_index.main(["--json"])
        json.loads(stream.getvalue())


if __name__ == "__main__":
    unittest.main()
