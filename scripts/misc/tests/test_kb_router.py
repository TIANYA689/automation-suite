from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from automation.routing.kb_index import (  # noqa: E402
    kb_route,
    load_kb_indexes,
    route_kb,
    verify_kb_files,
)


class KbIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT
        self.entries, self.errors = load_kb_indexes(self.root)

    def test_index_loads_without_errors(self) -> None:
        self.assertEqual(self.errors, [])
        self.assertGreater(len(self.entries), 0)

    def test_all_declared_files_are_inside_repo(self) -> None:
        for entry in self.entries:
            for path in entry["files"]:
                self.assertTrue(path.startswith("kb/"), f"非 kb 路径: {path}")

    def test_all_declared_files_exist(self) -> None:
        result = verify_kb_files(route_kb("混淆", self.entries), self.root)
        self.assertTrue(result["matched"])
        for item in result["matched"]:
            for record in item["files_exist"]:
                self.assertTrue(record["exists"], f"索引声明的文件不存在: {record['path']}")

    def test_env_emulation_query_hits_expected_entry(self) -> None:
        result = route_kb("jsvmp 环境伪装 补环境", self.entries)
        self.assertIn("env-emulation-diff", [item["id"] for item in result["matched"]])

    def test_crypto_query_hits_expected_entry(self) -> None:
        result = route_kb("帮我还原这个 md5 签名 参数拼接", self.entries)
        self.assertIn("crypto-fingerprints", [item["id"] for item in result["matched"]])

    def test_symbol_query_hits_expected_entry(self) -> None:
        result = route_kb("stripped 二进制 符号恢复 交叉引用", self.entries)
        self.assertIn("symbol-recovery", [item["id"] for item in result["matched"]])

    def test_emulation_query_hits_expected_entry(self) -> None:
        result = route_kb("unicorn 模拟执行 arm64", self.entries)
        self.assertIn("emulated-execution", [item["id"] for item in result["matched"]])

    def test_unrelated_query_returns_no_match(self) -> None:
        result = route_kb("今天天气怎么样", self.entries)
        self.assertEqual(result["matched"], [])

    def test_scoring_is_deterministic(self) -> None:
        first = route_kb("jsvmp 双路径", self.entries)
        second = route_kb("jsvmp 双路径", self.entries)
        self.assertEqual([i["id"] for i in first["matched"]], [i["id"] for i in second["matched"]])
        self.assertEqual([i["score"] for i in first["matched"]], [i["score"] for i in second["matched"]])

    def test_kb_route_convenience_wrapper(self) -> None:
        result = kb_route("混淆 字符串数组", self.root, verify=True)
        self.assertTrue(result["matched"])
        self.assertIn("total_entries", result)


if __name__ == "__main__":
    unittest.main()
