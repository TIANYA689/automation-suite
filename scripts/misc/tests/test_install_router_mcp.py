"""注册脚本的离线测试：重点覆盖 TOML 文本改写与 JSON 合并不破坏既有配置。

无需第三方依赖（不导入 mcp）。
"""

from __future__ import annotations

import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

MISC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MISC))

import install_router_mcp as inst  # noqa: E402


EXISTING_TOML = """[model_providers.custom]
name = "custom"

[projects.'d:\\work\\project']
trust_level = "trusted"

[mcp_servers]
[mcp_servers.node_repl]
args = []
command = 'C:\\tools\\someone\\node_repl.exe'
startup_timeout_sec = 120

[mcp_servers.node_repl.env]
FOO = "bar"

[mcp_servers.reverse_lab_tools]
command = "uv"
args = ["run", "--project", "D:/work/example/tools/skills/mcp/ExampleToolsMCP", "python", "x.py"]
startup_timeout_sec = 30
"""


class TestTomlString(unittest.TestCase):
    def test_windows_path_uses_literal_string(self) -> None:
        value = r"C:\tools\someone\python.exe"
        rendered = inst._toml_str(value)
        self.assertTrue(rendered.startswith("'"))
        self.assertEqual(tomllib.loads(f"k = {rendered}")["k"], value)

    def test_value_with_single_quote_falls_back_to_escaped(self) -> None:
        value = r"C:\it's\python.exe"
        rendered = inst._toml_str(value)
        self.assertTrue(rendered.startswith('"'))
        self.assertEqual(tomllib.loads(f"k = {rendered}")["k"], value)


class TestTomlBlock(unittest.TestCase):
    def test_block_parses_and_contains_server(self) -> None:
        block = inst.toml_block(r"C:\tools\someone\python.exe")
        parsed = tomllib.loads(block)
        server = parsed["mcp_servers"][inst.SERVER_NAME]
        self.assertEqual(server["command"], r"C:\tools\someone\python.exe")
        self.assertEqual(server["startup_timeout_sec"], inst.STARTUP_TIMEOUT_SEC)
        self.assertIn("AUTOMATION_SUITE_ROOT", server["env"])


class TestUpsertToml(unittest.TestCase):
    def test_insert_into_existing_preserves_others(self) -> None:
        updated = inst.upsert_toml(EXISTING_TOML, inst.toml_block("C:/py.exe"))
        parsed = tomllib.loads(updated)
        servers = parsed["mcp_servers"]
        self.assertIn(inst.SERVER_NAME, servers)
        self.assertIn("node_repl", servers)
        self.assertIn("reverse_lab_tools", servers)
        self.assertEqual(parsed["projects"]["d:\\work\\project"]["trust_level"], "trusted")
        self.assertEqual(parsed["model_providers"]["custom"]["name"], "custom")
        self.assertEqual(servers["node_repl"]["env"]["FOO"], "bar")

    def test_idempotent(self) -> None:
        once = inst.upsert_toml(EXISTING_TOML, inst.toml_block("C:/py.exe"))
        twice = inst.upsert_toml(once, inst.toml_block("C:/py.exe"))
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(f"[mcp_servers.{inst.SERVER_NAME}]"), 1)
        self.assertEqual(twice.count(f"[mcp_servers.{inst.SERVER_NAME}.env]"), 1)

    def test_replaces_legacy_block(self) -> None:
        legacy = (
            "[mcp_servers.automation-suite-router]\n"
            'command = "old"\n'
            "\n"
            "[mcp_servers.automation-suite-router.env]\n"
            'OLD = "1"\n'
        )
        updated = inst.upsert_toml(legacy + "\n" + EXISTING_TOML, inst.toml_block("C:/py.exe"))
        self.assertNotIn("automation-suite-router", updated)
        parsed = tomllib.loads(updated)
        self.assertIn(inst.SERVER_NAME, parsed["mcp_servers"])
        self.assertIn("node_repl", parsed["mcp_servers"])

    def test_upsert_into_empty_text(self) -> None:
        updated = inst.upsert_toml("", inst.toml_block("C:/py.exe"))
        parsed = tomllib.loads(updated)
        self.assertIn(inst.SERVER_NAME, parsed["mcp_servers"])


class TestWriteJson(unittest.TestCase):
    def test_merge_preserves_other_servers_and_drops_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp.json"
            path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "other": {"command": "x"},
                            "automation-suite-router": {"command": "stale"},
                        },
                        "keep": 1,
                    }
                ),
                encoding="utf-8",
            )
            inst.write_json(path, {"command": "py", "args": ["a.py"]})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("other", data["mcpServers"])
            self.assertIn(inst.SERVER_NAME, data["mcpServers"])
            self.assertNotIn("automation-suite-router", data["mcpServers"])
            self.assertEqual(data["keep"], 1)

    def test_invalid_json_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp.json"
            path.write_text("{ not json", encoding="utf-8")
            with self.assertRaises(SystemExit):
                inst.write_json(path, {"command": "py"})


if __name__ == "__main__":
    unittest.main()
