"""路由 MCP 服务器冒烟检查的测试。

不需要真的安装 mcp：`--require-mcp` 的三条分支里，两条用桩替换依赖探测，
一条用「指向不存在的服务器脚本」制造真实崩溃，验证 stderr 会被带出来。

为什么值得测：F6 之前这条检查在 CI 上**永远跳过**（CI 不装 mcp），
退出码 0 让「跳过」和「通过」无法区分。修法是把跳过路径变成可关闭的，
而「可关闭」必须能被证伪。
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp_smoke_check as smoke  # noqa: E402


def _probe(returncode: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["python", "-c", "import mcp"], returncode=returncode,
                                       stdout="", stderr=stderr)


class MissingMcpTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with mock.patch.object(smoke.subprocess, "run", return_value=_probe(1, "No module named 'mcp'")):
            with contextlib.redirect_stdout(buffer):
                code = smoke.main(argv)
        return code, buffer.getvalue()

    def test_skips_by_default(self) -> None:
        code, out = self._run([])
        self.assertEqual(code, 0)
        self.assertIn("跳过", out)

    def test_require_mcp_turns_skip_into_failure(self) -> None:
        code, out = self._run(["--require-mcp"])
        self.assertEqual(code, 1)
        self.assertIn("失败", out)
        self.assertIn("requirements.txt", out)

    def test_failure_prints_probe_stderr(self) -> None:
        code, out = self._run(["--require-mcp"])
        self.assertEqual(code, 1)
        self.assertIn("No module named 'mcp'", out)


class ServerCrashTests(unittest.TestCase):
    def test_crash_reports_stderr_and_no_traceback(self) -> None:
        """服务器起不来时，失败信息必须能指认根因，而不是一句「提前关闭」。"""
        missing = Path("definitely-missing-mcp-server.py")
        buffer = io.StringIO()
        with mock.patch.object(smoke, "SERVER", missing), \
                mock.patch.object(smoke.subprocess, "run", return_value=_probe(0)):
            with contextlib.redirect_stdout(buffer):
                code = smoke.main([])
        out = buffer.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("协议交互中断", out)
        self.assertIn("服务器 stderr", out)
        # 原始异常类型不该以裸 traceback 的形式冒出去
        self.assertNotIn("Traceback (most recent call last)", out)


ROOT = Path(__file__).resolve().parents[3]


class CiWiringTests(unittest.TestCase):
    """CI 必须真的装上 mcp 并要求它存在。

    修复前 CI 不装 mcp，这条检查**永远跳过**，退出码 0 让「跳过」与「通过」
    在流水线上长得一模一样。装上依赖只是第一步，还得用 `--require-mcp` 把
    跳过路径关掉——否则依赖装失败时会悄悄退回原状。
    """

    def _workflow(self) -> str:
        return (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_ci_installs_routing_requirements(self) -> None:
        self.assertIn("scripts/automation/routing/requirements.txt", self._workflow())

    def test_ci_requires_mcp(self) -> None:
        lines = [line for line in self._workflow().splitlines() if "mcp_smoke_check.py" in line]
        self.assertTrue(lines, "CI 未调用 mcp_smoke_check.py")
        self.assertTrue(
            any("--require-mcp" in line for line in lines),
            "CI 未要求 mcp 必须存在——缺依赖时会静默跳过，门禁形同虚设",
        )

    def test_expected_tools_include_workbench_surface(self) -> None:
        self.assertTrue({
            "workbench_plan", "workbench_run", "workbench_resume",
            "workbench_status", "workbench_list",
        } <= smoke.EXPECTED_TOOLS)


if __name__ == "__main__":
    unittest.main()
