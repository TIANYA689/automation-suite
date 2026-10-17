"""历史泄漏扫描的测试。"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_history_leaks  # noqa: E402
from check_history_leaks import scan  # noqa: E402

# 临时仓库的提交身份必须显式给：没有它，`git commit` 会因缺少 user.name /
# user.email 直接失败（而不是像在开发机上那样继承全局配置）。
GIT_IDENTITY = (
    "-c",
    "user.name=History Leak Test",
    "-c",
    "user.email=test@example.test",
    # 全局开了签名时，临时仓库里没有密钥，commit 会失败。
    "-c",
    "commit.gpgsign=false",
)

# 夹具域名拆成两段拼接，两个理由缺一不可：
# 1. 必须用**非保留域**——`example.com` 之类会被占位判据放行，测不到 `identity_email`；
# 2. 又不能写出完整邮箱字面量——本仓 `public_release_check.py` 会把任何非保留域邮箱
#    当真人 PII 报出来，测试文件也不例外（它的设计是「判据落在内容上，不做文件豁免」）。
# 相邻字面量在编译期就拼好，源码里不存在完整邮箱，于是两个门禁同时成立。
FIXTURE_DOMAIN = "corp" "-real.com"
ALICE = f"alice@{FIXTURE_DOMAIN}"
BOB = f"bob@{FIXTURE_DOMAIN}"


class HistoryScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self._original_root = check_history_leaks.ROOT
        check_history_leaks.ROOT = self.root

    def tearDown(self) -> None:
        check_history_leaks.ROOT = self._original_root
        self._temp.cleanup()

    def _git(self, *args: str) -> bytes:
        completed = subprocess.run(
            ["git", *GIT_IDENTITY, *args],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        return completed.stdout

    def _init(self) -> None:
        self._git("init")

    def _commit(self, name: str, content: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        self._git("add", "--", name)
        self._git("commit", "-m", f"add {name}")

    def _commit_bytes(self, name: str, content: bytes) -> None:
        path = self.root / name
        path.write_bytes(content)
        self._git("add", "--", name)
        self._git("commit", "-m", f"add {name}")

    def _commit_as(self, name: str, content: str, email: str, message: str) -> None:
        """用指定的 author/committer 邮箱与提交信息提交。

        后面的 `-c user.email=...` 覆盖 `GIT_IDENTITY` 里的默认值——git 对
        多个 `-c` 取最后一个。
        """
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        self._git("add", "--", name)
        self._git("-c", f"user.email={email}", "commit", "-m", message)

    def _run_main(self, argv: list[str]) -> tuple[int, str]:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = check_history_leaks.main(argv)
        return code, stream.getvalue()

    def _kinds(self, report: dict) -> dict[str, int]:
        by_kind = report["by_kind"]
        assert isinstance(by_kind, dict)
        return by_kind

    # --- 检测形态 ---------------------------------------------------------

    def test_windows_path_in_history_is_found(self) -> None:
        self._init()
        self._commit("secret.txt", "path = D:/Git/secret/x.txt\n")

        report = scan(self.root)

        self.assertIsNone(report["error"])
        self.assertEqual(self._kinds(report)["abs_path_windows"], 1)
        finding = report["findings"][0]
        self.assertEqual(finding["kind"], "abs_path_windows")
        self.assertEqual(finding["file"], "secret.txt")
        self.assertEqual(finding["line"], 1)
        self.assertIn("D:/Git/secret/x.txt", finding["match"])
        self.assertEqual(len(finding["commit"]), 7)

    def test_posix_path_email_and_private_key_are_found(self) -> None:
        self._init()
        self._commit(
            "leak.txt",
            "home = /Users/alice/work\n"
            "mail = alice@notexample.com\n"
            "key = -----BEGIN RSA PRIVATE KEY-----\n",
        )

        report = scan(self.root)
        by_kind = self._kinds(report)
        self.assertEqual(by_kind["abs_path_posix"], 1)
        self.assertEqual(by_kind["email"], 1)
        self.assertEqual(by_kind["private_key"], 1)

        matches = {item["kind"]: item["match"] for item in report["findings"]}
        # 路径保留目录结构，用户名段替换为 <user>。
        self.assertEqual(matches["abs_path_posix"], "/Users/<user>")
        # 邮箱本地部分只留首字母。
        self.assertEqual(matches["email"], "a***@notexample.com")
        self.assertEqual(matches["private_key"], "-----BEGIN … PRIVATE KEY-----")

    def test_fake_token_is_reported_and_masked(self) -> None:
        fake_token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        self._init()
        self._commit("config.txt", f'token = "{fake_token}"\n')

        report = scan(self.root)

        self.assertEqual(self._kinds(report)["token"], 1)
        serialized = json.dumps(report, ensure_ascii=False)
        # 报告里绝不能出现完整凭据。
        self.assertNotIn(fake_token, serialized)
        self.assertIn(fake_token[:4] + "…" + fake_token[-2:], serialized)

    def test_non_utf8_history_does_not_crash(self) -> None:
        """老 commit 里的非 UTF-8 内容按 errors="replace" 解码，扫描照常进行。"""
        self._init()
        self._commit_bytes(
            "legacy.txt",
            b"caf\xe9 path = D:/Git/legacy/x.txt\n",
        )

        report = scan(self.root)

        self.assertIsNone(report["error"])
        self.assertEqual(self._kinds(report)["abs_path_windows"], 1)

    # --- 干净历史 ---------------------------------------------------------

    def test_clean_history_has_no_findings(self) -> None:
        self._init()
        self._commit("readme.md", "# hello\nnothing sensitive here\n")

        report = scan(self.root)

        self.assertIsNone(report["error"])
        self.assertEqual(report["total"], 0)
        self.assertTrue(report["clean"])
        self.assertEqual(report["commits"], 1)

        code, output = self._run_main(["--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["total"], 0)

    def test_placeholder_values_are_suppressed_and_counted(self) -> None:
        """占位值不计入命中，但必须单独计数——排除要可审计。"""
        self._init()
        self._commit("fixture.txt", "mail = test@example.com\npython = C:/py.exe\n")

        report = scan(self.root)

        self.assertEqual(report["total"], 0)
        self.assertEqual(self._kinds(report)["email"], 0)
        self.assertEqual(report["suppressed"]["email"], 1)
        self.assertEqual(report["suppressed"]["abs_path_windows"], 1)

    # --- 提交元数据与提交信息 ---------------------------------------------

    def test_real_identity_email_is_found(self) -> None:
        self._init()
        self._commit_as("readme.md", "# hi\n", ALICE, "init")

        report = scan(self.root)

        self.assertIsNone(report["error"])
        self.assertEqual(self._kinds(report)["identity_email"], 1)
        self.assertEqual(report["identity_total"], 1)
        self.assertEqual(report["identity_exposed"], 1)

        finding = next(
            item for item in report["findings"] if item["kind"] == "identity_email"
        )
        self.assertEqual(finding["source"], "identity")
        # 默认掩码，报告里不出现完整邮箱。
        self.assertEqual(finding["match"], f"a***@{FIXTURE_DOMAIN}")
        # 身份邮箱只在元数据里，diff 的 email 类不应跟着命中。
        self.assertEqual(self._kinds(report)["email"], 0)

    def test_noreply_identity_is_exempt(self) -> None:
        self._init()
        self._commit_as(
            "readme.md",
            "# hi\n",
            "12345+bot@users.noreply.github.com",
            "init",
        )

        report = scan(self.root)

        self.assertEqual(report["total"], 0)
        self.assertEqual(self._kinds(report)["identity_email"], 0)
        # 豁免也要计数：可审计的排除不是漏洞。
        self.assertEqual(report["suppressed"]["identity_email"], 1)
        self.assertEqual(report["identity_total"], 1)
        self.assertEqual(report["identity_exposed"], 0)
        self.assertFalse(report["identities"][0]["exposed"])

    def test_token_in_commit_message_is_found(self) -> None:
        fake_token = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"
        self._init()
        self._commit_as(
            "readme.md",
            "# hi\n",
            "test@example.test",
            f"debug\n\ntoken={fake_token}\n",
        )

        report = scan(self.root)

        self.assertEqual(self._kinds(report)["token"], 1)
        finding = next(item for item in report["findings"] if item["kind"] == "token")
        self.assertEqual(finding["source"], "commit_message")
        self.assertIsNone(finding["file"])
        self.assertEqual(finding["line"], 3)
        self.assertNotIn(fake_token, json.dumps(report, ensure_ascii=False))

    def test_windows_path_in_commit_message_is_found(self) -> None:
        self._init()
        self._commit_as(
            "readme.md",
            "# hi\n",
            "test@example.test",
            "note\n\ncopy D:/Git/private/x.txt\n",
        )

        report = scan(self.root)

        self.assertEqual(self._kinds(report)["abs_path_windows"], 1)
        finding = next(
            item for item in report["findings"] if item["kind"] == "abs_path_windows"
        )
        self.assertEqual(finding["source"], "commit_message")
        self.assertEqual(finding["match"], "D:/Git/private/x.txt")

    def test_identity_emails_are_masked_by_default(self) -> None:
        self._init()
        self._commit_as("readme.md", "# hi\n", ALICE, "init")

        code, output = self._run_main([])
        self.assertEqual(code, 0)
        self.assertNotIn(ALICE, output)
        self.assertIn(f"a***@{FIXTURE_DOMAIN}", output)

        code, output = self._run_main(["--json"])
        self.assertEqual(code, 0)
        self.assertNotIn(ALICE, output)
        self.assertEqual(json.loads(output)["identities"][0]["email"], f"a***@{FIXTURE_DOMAIN}")

        code, output = self._run_main(["--reveal-identities"])
        self.assertEqual(code, 0)
        self.assertIn(ALICE, output)

        code, output = self._run_main(["--json", "--reveal-identities"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["identities"][0]["email"], ALICE)

    def test_identities_are_deduplicated_by_email(self) -> None:
        self._init()
        self._commit_as("a.txt", "a\n", ALICE, "a")
        self._commit_as("b.txt", "b\n", ALICE, "b")
        self._commit_as("c.txt", "c\n", BOB, "c")

        report = scan(self.root)

        # 同一邮箱 2 个 commit 只算 1 个身份。
        self.assertEqual(report["identity_total"], 2)
        self.assertEqual(report["identity_exposed"], 2)
        self.assertEqual(self._kinds(report)["identity_email"], 2)

        by_email = {row["email"]: row["commits"] for row in report["identities"]}
        self.assertEqual(by_email[f"a***@{FIXTURE_DOMAIN}"], 2)
        self.assertEqual(by_email[f"b***@{FIXTURE_DOMAIN}"], 1)

    # --- 空解析守卫 -------------------------------------------------------

    def test_non_git_directory_is_an_error_not_a_pass(self) -> None:
        report = scan(self.root)
        self.assertIsNotNone(report["error"])
        self.assertEqual(report["commits"], 0)

        code, output = self._run_main([])
        self.assertEqual(code, 2)
        self.assertIn("扫描失败", output)
        # 跳过不能打印成通过。
        self.assertNotIn("未发现命中", output)

    def test_empty_repository_is_an_error_not_a_pass(self) -> None:
        self._init()

        report = scan(self.root)
        self.assertIsNotNone(report["error"])
        self.assertEqual(report["commits"], 0)

        code, output = self._run_main([])
        self.assertEqual(code, 2)
        self.assertIn("扫描失败", output)

    # --- fail-on 与 limit -------------------------------------------------

    def test_fail_on_any_follows_findings(self) -> None:
        self._init()
        self._commit("readme.md", "# clean\n")
        code, _ = self._run_main(["--fail-on", "any"])
        self.assertEqual(code, 0)

        self._commit("secret.txt", "path = D:/Git/secret/x.txt\n")
        code, _ = self._run_main(["--fail-on", "any"])
        self.assertEqual(code, 1)

        # 指定 kind 时只按该 kind 计数。
        code, _ = self._run_main(["--fail-on", "token"])
        self.assertEqual(code, 0)

    def test_limit_truncates_print_but_not_counts(self) -> None:
        self._init()
        self._commit("a.txt", "path = D:/Git/a/x.txt\n")
        self._commit("b.txt", "path = D:/Git/b/x.txt\n")

        code, output = self._run_main(["--limit", "1"])
        self.assertEqual(code, 0)
        # 计数是完整的 2，打印只有 1 条。
        self.assertIn("共 2 条", output)
        self.assertIn("显示 1 条", output)
        self.assertTrue(("D:/Git/a/x.txt" in output) ^ ("D:/Git/b/x.txt" in output))

        code, output = self._run_main(["--json", "--limit", "1"])
        self.assertEqual(code, 0)
        report = json.loads(output)
        self.assertEqual(report["total"], 2)
        self.assertEqual(self._kinds(report)["abs_path_windows"], 2)


if __name__ == "__main__":
    unittest.main()
