"""MCP 工具清单校验的测试。

覆盖的核心回归：文档写"5 个只读工具"却漏了一个（`kb_route` 那次），
以及"数量对了但名单短一个"这类只靠数量检查抓不到的形态。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_tool_inventory  # noqa: E402
from check_tool_inventory import run  # noqa: E402

# 3 个只读 + 1 个非只读，便于构造"数量对/名单短"等形态。
MCP_SOURCE = '''\
def _tool(annotations=None):
    def wrapper(func):
        return func
    return wrapper


READ_ONLY = object()
EXECUTES = object()


@_tool(READ_ONLY)
def route_task(query: str) -> dict:
    return {}


@_tool(READ_ONLY)
def load_skill(name: str) -> str:
    return ""


@_tool(READ_ONLY)
def list_skills() -> dict:
    return {}


@_tool(EXECUTES)
def run_module(name: str) -> dict:
    return {}
'''

CLEAN_DOC = (
    "| 路由 MCP | `scripts/automation/routing/mcp_server.py` | "
    "3 个只读工具 `route_task` / `load_skill` / `list_skills`，"
    "外加唯一的非只读工具 `run_module` |\n"
)


class InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self._originals = (check_tool_inventory.ROOT, check_tool_inventory.MCP_SERVER)
        check_tool_inventory.ROOT = self.root
        check_tool_inventory.MCP_SERVER = self.root / "mcp_server.py"
        check_tool_inventory.MCP_SERVER.write_text(MCP_SOURCE, encoding="utf-8")
        (self.root / "docs").mkdir()

    def tearDown(self) -> None:
        check_tool_inventory.ROOT, check_tool_inventory.MCP_SERVER = self._originals
        self._temp.cleanup()

    def _doc(self, body: str, name: str = "AI-USAGE.md") -> None:
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    def _kinds(self, report: dict) -> list[str]:
        return [drift["kind"] for drift in report["drifts"]]

    def test_clean_inventory_passes(self) -> None:
        self._doc(CLEAN_DOC)
        report = run()
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["tool_total"], 4)
        self.assertEqual(report["inventory_lines"], 1)

    def test_stale_readonly_count_is_detected(self) -> None:
        """真实回归：实现里 3 个只读工具，文档只写 2 个并只列 2 个。"""
        self._doc("3 个只读工具".replace("3", "2") + " `route_task` / `load_skill`，外加 `run_module`\n")
        report = run()
        self.assertIn("readonly_count", self._kinds(report))
        self.assertIn("undocumented_tool", self._kinds(report))

    def test_count_right_but_listing_short_is_detected(self) -> None:
        """数量写对了、名单却短一个——只靠数量检查抓不到。"""
        self._doc("3 个只读工具 `route_task` / `load_skill`，外加 `run_module`\n")
        report = run()
        self.assertIn("readonly_listing", self._kinds(report))
        self.assertIn("undocumented_tool", self._kinds(report))

    def test_unknown_tool_is_detected(self) -> None:
        self._doc("3 个只读工具 `route_task` / `load_skill` / `ghost_tool`，外加 `run_module`\n")
        self.assertIn("unknown_tool", self._kinds(run()))

    def test_undocumented_tool_is_detected(self) -> None:
        """工具存在但任何活文档都没提到——`kb_route` 当初就是这种状态。"""
        self._doc("1 个只读工具 `route_task`\n")
        report = run()
        detail = json.dumps(report["drifts"], ensure_ascii=False)
        self.assertIn("undocumented_tool", self._kinds(report))
        self.assertIn("load_skill", detail)
        self.assertIn("list_skills", detail)

    def test_total_count_is_detected(self) -> None:
        self._doc("MCP 工具共 9 个，其中 3 个只读 `route_task` / `load_skill` / `list_skills`。\n")
        self.assertIn("total_count", self._kinds(run()))

    def test_total_count_matching_passes(self) -> None:
        self._doc("MCP 工具共 4 个，其中 3 个只读 `route_task` / `load_skill` / `list_skills`，外加 `run_module`。\n")
        self.assertTrue(run()["ok"], run()["drifts"])

    def test_prose_mentioning_a_tool_is_not_an_inventory(self) -> None:
        """散文里提到工具名不算清单，不该被要求补齐名单。"""
        self._doc(
            "先调用 `route_task` 拿候选，再用 `load_skill` 加载正文，"
            "`list_skills` 看全貌，`run_module` 执行模块。\n"
        )
        report = run()
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["inventory_lines"], 0)

    def test_chinese_one_is_not_a_count(self) -> None:
        """'说一个工具' 不是数量声明。"""
        self._doc("说一个工具或文档已核验，意味着它有独立检查。\n")
        self.assertEqual(run()["inventory_lines"], 0)

    def test_reports_directory_is_out_of_scope(self) -> None:
        """日期快照里的过时数量不该报——它记录的是当时的状态。"""
        self._doc(CLEAN_DOC)
        self._doc("MCP 服务器，1 只读工具 + `run_module`\n", name="reports/old-validation.md")
        self.assertTrue(run()["ok"], run()["drifts"])

    def test_backup_directory_is_out_of_scope(self) -> None:
        self._doc(CLEAN_DOC)
        self._doc("9 个只读工具 `ghost`\n", name="skills/skills 原始备份/SKILL.md")
        self.assertTrue(run()["ok"], run()["drifts"])

    def test_unknown_annotation_is_detected(self) -> None:
        check_tool_inventory.MCP_SERVER.write_text(
            MCP_SOURCE + "\n\n@_tool()\ndef mystery() -> None:\n    return None\n",
            encoding="utf-8",
        )
        self._doc(CLEAN_DOC)
        self.assertIn("unknown_annotation", self._kinds(run()))

    def test_missing_server_reports_unreadable(self) -> None:
        check_tool_inventory.MCP_SERVER.unlink()
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = check_tool_inventory.main(["--json"])
        self.assertEqual(code, 2)
        json.loads(stream.getvalue())


class RealRepositoryTests(unittest.TestCase):
    def test_repository_inventory_is_consistent(self) -> None:
        report = run()
        self.assertTrue(
            report["ok"],
            "文档里的工具清单与实现不一致：" + json.dumps(report["drifts"], ensure_ascii=False),
        )
        self.assertGreaterEqual(report["tool_total"], 7)
        self.assertIn("run_module", report["executing_tools"])

    def test_json_mode_keeps_output_parsable(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            check_tool_inventory.main(["--json"])
        json.loads(stream.getvalue())


if __name__ == "__main__":
    unittest.main()
