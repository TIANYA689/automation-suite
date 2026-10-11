from __future__ import annotations

import sys
import contextlib
import io
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "misc"))

from automation.routing.kb_index import (  # noqa: E402
    kb_route,
    load_kb_indexes,
    route_kb,
    verify_kb_files,
)
import kb_router  # noqa: E402


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

    def test_external_source_audit_query_hits_new_entry(self) -> None:
        result = route_kb("GitHub 调研 上游来源 许可证复核 知识库优化", self.entries)
        self.assertIn("external-source-audit", [item["id"] for item in result["matched"]])

    def test_source_audit_signals_are_qualified_not_bare_github(self) -> None:
        """`GitHub` 是泛词：单独作 signal 会让来源审计条目抢走一切。

        现在用的是 `GitHub 调研`（带限定词）。这条判据钉住**信号粒度**——
        **行为对不等于不会退化**：有人把 signals 改成裸 `GitHub` 时，
        不会有任何东西报错，只有具体任务的推荐顺序悄悄变了。
        """
        matches = [e for e in self.entries if e["id"] == "external-source-audit"]
        self.assertTrue(matches, "条目 external-source-audit 不见了")
        self.assertNotIn("GitHub", matches[0]["signals"])

    def test_concrete_tasks_are_not_swallowed_by_source_audit(self) -> None:
        """近邻负例：**带 `github` 字样的具体需求**不该被来源审计条目抢走。

        这是审计报告 P1 的原始担心，**实测可复现**：把裸 `GitHub` 加进 signals 后，
        「github 上找到的混淆 js 脚本 怎么分析」的首选会从 `config-body-separation`
        变成 `external-source-audit`；「从 github 下载的 har 抓包文件 生成脚本」里
        它也会挤进第二位。

        **负例必须带 `github`**：不带 GitHub 的查询测不到这个问题——
        判据的形态假设就是它的盲区（规则 98）。

        正例（`test_external_source_audit_query_hits_new_entry`）证明条目能被找到，
        这条证明它**不盖住别人**，两条合起来才说明信号宽度是对的。
        """
        for query, expected in (
            ("github 上找到的混淆 js 脚本 怎么分析", "config-body-separation"),
            ("从 github 下载的 har 抓包文件 生成脚本", "har-to-script"),
            ("github 上有个 jsvmp 补环境的项目", "jsvmp-paths"),
        ):
            with self.subTest(query=query):
                ids = [item["id"] for item in route_kb(query, self.entries)["matched"]]
                self.assertTrue(ids, f"{query!r} 未命中任何条目，判据失去意义")
                self.assertNotIn(
                    "external-source-audit",
                    ids,
                    f"{query!r} 被来源审计条目抢走，命中：{ids}",
                )
                self.assertEqual(
                    ids[0],
                    expected,
                    f"{query!r} 的首选应是 {expected}，实际首选 {ids[0]}",
                )

    def test_cli_verify_uses_ascii_status_markers(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            original = sys.argv
            try:
                sys.argv = ["kb_router.py", "GitHub 调研", "--verify"]
                self.assertEqual(kb_router.main(), 0)
            finally:
                sys.argv = original
        self.assertIn("[OK]", stream.getvalue())
        self.assertNotIn("✓", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
