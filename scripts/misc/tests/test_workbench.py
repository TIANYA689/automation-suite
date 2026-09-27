#!/usr/bin/env python3
"""工作台协议的离线回归测试。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from automation.workbench import WorkbenchRun, build_plan  # noqa: E402


class WorkbenchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "skills").mkdir()
        shutil.copy2(ROOT / "AI-USAGE.md", self.root / "AI-USAGE.md")
        shutil.copy2(ROOT / "routing.source.json", self.root / "routing.source.json")
        shutil.copytree(ROOT / "skills" / "automation-architect", self.root / "skills" / "automation-architect")
        shutil.copytree(ROOT / "kb", self.root / "kb")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_plan_contains_route_and_knowledge_evidence(self) -> None:
        plan = build_plan(self.root, "设计一个自动化套件的路由方案")
        self.assertEqual(plan["selected_skill"], "automation-architect")
        self.assertTrue(plan["route"]["primary"])
        self.assertIn("knowledge", plan)
        self.assertTrue(plan["skill_excerpt"])
        self.assertTrue(all("evidence" in item for item in plan["route"]["primary"]))

    def test_agent_workbench_language_routes_to_architect(self) -> None:
        plan = build_plan(
            self.root,
            "全面检查当前项目，完成未完成的工作环境，组装 AI Agent 自主驱动工作台",
        )
        self.assertEqual(plan["selected_skill"], "automation-architect")

    def test_run_can_resume_and_finishes_read_only_workflow(self) -> None:
        run = WorkbenchRun.create(self.root, "设计自动化工作台路由")
        first = run.summary()
        self.assertEqual(first["status"], "READY")
        resumed = WorkbenchRun.open(self.root, first["run_id"])
        result = resumed.advance()
        self.assertEqual(result["status"], "DONE")
        self.assertTrue((resumed.directory / "events.jsonl").is_file())
        state = json.loads((resumed.directory / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["pending_actions"], [])

    def test_unrouted_query_never_becomes_executable(self) -> None:
        run = WorkbenchRun.create(self.root, "今天天气怎么样")
        result = run.advance()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIsNone(result["selected_skill"])
        state = json.loads((run.directory / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["blocked_actions"], ["skill"])

    def test_explicit_module_is_dry_run_and_audited(self) -> None:
        tools = self.root / "tools" / "automation-modules" / "checks" / "demo"
        tools.mkdir(parents=True)
        (tools / "demo.py").write_text("print('demo')\n", encoding="utf-8")
        source = json.loads((self.root / "routing.source.json").read_text(encoding="utf-8"))
        source["module_categories"] = {"demo": {"signals": ["demo"]}}
        source["execution"]["allowlist"] = ["demo"]
        (self.root / "routing.source.json").write_text(
            json.dumps(source, ensure_ascii=False), encoding="utf-8"
        )
        run = WorkbenchRun.create(self.root, "设计自动化工作台路由")
        result = run.advance(modules=["demo"])
        self.assertEqual(result["status"], "DONE")
        result_files = list((run.directory / "modules").glob("demo-*-run.json"))
        self.assertEqual(len(result_files), 1)
        output = json.loads(result_files[0].read_text(encoding="utf-8"))
        self.assertTrue(output["allowed"])
        self.assertFalse(output["executed"])
        self.assertTrue(output["dry_run"])

    def test_failed_module_execution_is_not_reported_as_done(self) -> None:
        tools = self.root / "tools" / "automation-modules" / "checks" / "failing"
        tools.mkdir(parents=True)
        (tools / "failing.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
        source = json.loads((self.root / "routing.source.json").read_text(encoding="utf-8"))
        source["module_categories"] = {"checks": {"signals": ["check"]}}
        source["execution"]["allowlist"] = ["failing"]
        (self.root / "routing.source.json").write_text(
            json.dumps(source, ensure_ascii=False), encoding="utf-8"
        )
        run = WorkbenchRun.create(self.root, "设计自动化工作台路由")
        result = run.advance(execute=True, modules=["failing"])
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failed_actions"], ["run:failing"])


if __name__ == "__main__":
    unittest.main()
