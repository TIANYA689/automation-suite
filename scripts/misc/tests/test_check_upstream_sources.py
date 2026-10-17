"""Tests for the external-source manifest validator (offline plus mocked network)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_upstream_sources as checker  # noqa: E402


class SourceManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "sources.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, records: list[dict[str, str]]) -> None:
        self.path.write_text(json.dumps({"version": "1.0", "sources": records}), encoding="utf-8")

    def record(self, **overrides: str) -> dict[str, str]:
        item = {
            "id": "sample",
            "url": "https://github.com/org/repo",
            "revision": "a" * 40,
            "spdx_license": "MIT",
            "checked_at": "2026-10-01",
            "scope": "methodology only",
        }
        item.update(overrides)
        return item

    def test_valid_record_passes(self) -> None:
        self.write([self.record()])
        self.assertTrue(checker.validate(self.path)["ok"])

    def test_revision_placeholder_fails(self) -> None:
        self.write([self.record(revision="REVISION_REQUIRED")])
        report = checker.validate(self.path)
        self.assertFalse(report["ok"])
        self.assertTrue(any("revision" in error for error in report["errors"]))

    def test_unknown_license_fails(self) -> None:
        self.write([self.record(spdx_license="Unknown")])
        self.assertFalse(checker.validate(self.path)["ok"])

    def test_duplicate_ids_fail(self) -> None:
        self.write([self.record(), self.record()])
        report = checker.validate(self.path)
        self.assertTrue(any("duplicate id" in error for error in report["errors"]))

    def test_non_github_url_fails(self) -> None:
        self.write([self.record(url="http://example.org/repo")])
        self.assertFalse(checker.validate(self.path)["ok"])

    def test_unreadable_json_fails_cleanly(self) -> None:
        self.path.write_text("{", encoding="utf-8")
        report = checker.validate(self.path)
        self.assertFalse(report["ok"])
        self.assertEqual(report["sources"], 0)


class NetworkCheckTests(unittest.TestCase):
    """联网核验的行为，全部通过替换 ``_fetch_json`` 模拟，绝不访问真实网络。

    每个用例都断言 ``calls``，确保测试本身没有偷偷发起请求；默认模式则要求
    ``calls`` 严格为 0。
    """

    BASE = "https://api.github.com/repos/org/repo"
    REVISION = "a" * 40
    HEAD = "b" * 40

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "sources.json"
        self.calls: list[str] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, records: list[dict[str, str]]) -> None:
        self.path.write_text(
            json.dumps({"version": "1.0", "sources": records}), encoding="utf-8"
        )

    def record(self, **overrides: str) -> dict[str, str]:
        item = {
            "id": "sample",
            "url": "https://github.com/org/repo",
            "revision": self.REVISION,
            "spdx_license": "MIT",
            "checked_at": date.today().isoformat(),
            "scope": "methodology only",
        }
        item.update(overrides)
        return item

    def routes(self, **overrides: object) -> dict[str, object]:
        """默认：仓库存在、MIT、revision 存在、HEAD 未漂移。"""
        values: dict[str, object] = {
            self.BASE: {"archived": False, "license": {"spdx_id": "MIT"}},
            f"{self.BASE}/commits/{self.REVISION}": {"sha": self.REVISION},
            f"{self.BASE}/commits?per_page=1": [{"sha": self.REVISION}],
        }
        values.update(overrides)
        return values

    def fetcher(self, values: dict[str, object]):
        def fake(url: str, timeout: float) -> object:
            self.calls.append(url)
            value = values.get(url)
            if isinstance(value, Exception):
                raise value
            if value is None:
                raise checker.FetchError(
                    "GitHub API 返回 HTTP 404：Not Found", url=url, status=404
                )
            return value

        return fake

    def run_network(
        self, values: dict[str, object], *extra: str
    ) -> tuple[int, dict[str, object]]:
        buffer = io.StringIO()
        with patch.object(checker, "_fetch_json", self.fetcher(values)):
            with contextlib.redirect_stdout(buffer):
                code = checker.main(
                    [
                        "--network",
                        "--json",
                        "--manifest",
                        str(self.path),
                        "--skip-ledger",
                        *extra,
                    ]
                )
        return code, json.loads(buffer.getvalue())

    @staticmethod
    def findings(report: dict[str, object], code: str) -> list[dict[str, str]]:
        return [
            item
            for item in report["findings"]  # type: ignore[index]
            if item["code"] == code
        ]

    def test_offline_mode_never_calls_fetch(self) -> None:
        """默认路径必须保持纯离线：一次 fetch 都不允许发生。"""
        self.write([self.record()])
        buffer = io.StringIO()
        with patch.object(checker, "_fetch_json", self.fetcher(self.routes())):
            with contextlib.redirect_stdout(buffer):
                code = checker.main(
                    ["--manifest", str(self.path), "--skip-ledger"]
                )
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [])
        self.assertTrue(json.loads(buffer.getvalue())["ok"])

    def test_missing_repository_is_an_error(self) -> None:
        self.write([self.record()])
        code, report = self.run_network(
            self.routes(
                **{
                    self.BASE: checker.FetchError(
                        "GitHub API 返回 HTTP 404：Not Found", status=404
                    )
                }
            )
        )
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        found = self.findings(report, "repo-missing")
        self.assertEqual(len(found), 1)
        self.assertIn("不存在", found[0]["message"])
        # 仓库都不存在时，不应继续请求 commits。
        self.assertEqual(len(self.calls), 1)

    def test_archived_repository_is_a_warning(self) -> None:
        self.write([self.record()])
        code, report = self.run_network(
            self.routes(
                **{
                    self.BASE: {
                        "archived": True,
                        "license": {"spdx_id": "MIT"},
                    }
                }
            )
        )
        self.assertEqual(code, 0)
        self.assertEqual(report["counts"]["warning"], 1)  # type: ignore[index]
        found = self.findings(report, "archived")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "warning")

    def test_license_mismatch_is_an_error(self) -> None:
        self.write([self.record(spdx_license="Apache-2.0")])
        code, report = self.run_network(self.routes())
        self.assertEqual(code, 1)
        found = self.findings(report, "license-mismatch")
        self.assertEqual(len(found), 1)
        self.assertIn("许可证", found[0]["message"])

    def test_noassertion_matches_manifest_noassertion(self) -> None:
        """上游本来就没声明许可证，不能误报成许可证变化。"""
        self.write([self.record(spdx_license="LicenseRef-NOASSERTION")])
        code, report = self.run_network(
            self.routes(
                **{
                    self.BASE: {
                        "archived": False,
                        "license": {"spdx_id": "NOASSERTION"},
                    }
                }
            )
        )
        self.assertEqual(code, 0, report["findings"])
        self.assertEqual(self.findings(report, "license-mismatch"), [])

    def test_null_license_matches_manifest_noassertion(self) -> None:
        self.write([self.record(spdx_license="LicenseRef-NOASSERTION")])
        code, report = self.run_network(
            self.routes(**{self.BASE: {"archived": False, "license": None}})
        )
        self.assertEqual(code, 0, report["findings"])

    def test_github_gpl_alias_matches_pinned_license(self) -> None:
        """GitHub 常把 GPL-3.0-only 报成 GPL-3.0，不应误报。"""
        self.write([self.record(spdx_license="GPL-3.0-only")])
        code, report = self.run_network(
            self.routes(
                **{
                    self.BASE: {
                        "archived": False,
                        "license": {"spdx_id": "GPL-3.0"},
                    }
                }
            )
        )
        self.assertEqual(code, 0, report["findings"])

    def test_missing_revision_is_an_error(self) -> None:
        self.write([self.record()])
        code, report = self.run_network(
            self.routes(
                **{
                    f"{self.BASE}/commits/{self.REVISION}": checker.FetchError(
                        "GitHub API 返回 HTTP 404：Not Found", status=404
                    )
                }
            )
        )
        self.assertEqual(code, 1)
        found = self.findings(report, "revision-missing")
        self.assertEqual(len(found), 1)
        self.assertIn("revision", found[0]["message"])

    def test_head_drift_is_info_and_does_not_fail(self) -> None:
        self.write([self.record()])
        code, report = self.run_network(
            self.routes(**{f"{self.BASE}/commits?per_page=1": [{"sha": self.HEAD}]})
        )
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"])
        found = self.findings(report, "head-drift")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "info")
        self.assertEqual(report["counts"]["error"], 0)  # type: ignore[index]

    def test_rate_limit_is_a_clear_error(self) -> None:
        self.write([self.record()])
        code, report = self.run_network(
            self.routes(
                **{
                    self.BASE: checker.FetchError(
                        "GitHub API 限流（rate limit），配额重置时间：2026-10-17 12:00:00 UTC",
                        status=403,
                        rate_limited=True,
                    )
                }
            )
        )
        self.assertEqual(code, 1)
        messages = [item["message"] for item in report["findings"]]  # type: ignore[index]
        self.assertTrue(
            any("限流" in message or "rate limit" in message for message in messages),
            messages,
        )

    def test_network_failure_is_an_error(self) -> None:
        self.write([self.record()])
        code, report = self.run_network(
            self.routes(
                **{
                    self.BASE: checker.FetchError(
                        "网络不可达或请求超时：timed out"
                    )
                }
            )
        )
        self.assertEqual(code, 1)
        self.assertEqual(len(self.findings(report, "repo-unreadable")), 1)

    def test_stale_checked_at_is_a_warning(self) -> None:
        self.write([self.record(checked_at="2020-01-01")])
        code, report = self.run_network(self.routes())
        self.assertEqual(code, 0)
        found = self.findings(report, "stale")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "warning")

    def test_empty_manifest_fails_loudly(self) -> None:
        """空清单不能输出「全部通过」，必须报错并非零退出。"""
        self.write([])
        code, report = self.run_network(self.routes())
        self.assertEqual(code, 1)
        self.assertEqual(report["checked"], 0)  # type: ignore[index]
        self.assertEqual(len(self.findings(report, "empty-manifest")), 1)
        self.assertEqual(self.calls, [])

    def test_empty_commit_list_fails_loudly(self) -> None:
        """API 返回 0 条结果同样不能当作通过。"""
        self.write([self.record()])
        code, report = self.run_network(
            self.routes(**{f"{self.BASE}/commits?per_page=1": []})
        )
        self.assertEqual(code, 1)
        self.assertEqual(len(self.findings(report, "empty-commits")), 1)


class LedgerCoverageTests(unittest.TestCase):
    """The ledger and the manifest are two faces of one source list.

    A repository added to the ledger and forgotten in the manifest makes the
    manifest **quietly shorter** — nothing errors, and the missing revision
    only surfaces months later. These checks close that gap.
    """

    LEDGER = (
        "# 台账\n\n"
        "## 本轮吸收的来源\n\n"
        "| 仓库 | 吸收的部分 | 剔除的部分 |\n"
        "|---|---|---|\n"
        "| `acme/one` | 方法论 | 无 |\n"
        "| `acme/two` | 工程骨架 | 攻击性内容 |\n"
    )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.ledger = base / "ledger.md"
        self.manifest = base / "sources.json"
        self.ledger.write_text(self.LEDGER, encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_manifest(self, repos: list[str]) -> None:
        records = [
            {
                "id": repo.split("/")[1],
                "url": f"https://github.com/{repo}",
                "revision": "a" * 40,
                "spdx_license": "MIT",
                "checked_at": "2026-10-11",
                "scope": "methodology only",
            }
            for repo in repos
        ]
        self.manifest.write_text(
            json.dumps({"version": "1.0", "sources": records}), encoding="utf-8"
        )

    def test_full_coverage_passes(self) -> None:
        self._write_manifest(["acme/one", "acme/two"])
        report = checker.check_ledger_coverage(self.ledger, self.manifest)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["named"], 2)
        self.assertEqual(report["listed"], 2)

    def test_ledger_repo_missing_from_manifest_fails(self) -> None:
        self._write_manifest(["acme/one"])
        report = checker.check_ledger_coverage(self.ledger, self.manifest)
        self.assertFalse(report["ok"])
        self.assertTrue(any("acme/two" in error for error in report["errors"]))

    def test_repository_names_are_compared_case_insensitively(self) -> None:
        """GitHub treats repository names case-insensitively; so must this."""
        self._write_manifest(["Acme/One", "ACME/TWO"])
        report = checker.check_ledger_coverage(self.ledger, self.manifest)
        self.assertTrue(report["ok"], report["errors"])

    def test_ledger_without_owner_repo_rows_fails_loudly(self) -> None:
        """An empty parse means the table shape changed — fail, do not pass vacuously."""
        self.ledger.write_text("# 台账\n\n没有表格。\n", encoding="utf-8")
        self._write_manifest(["acme/one"])
        report = checker.check_ledger_coverage(self.ledger, self.manifest)
        self.assertFalse(report["ok"])
        self.assertTrue(any("not running" in error for error in report["errors"]))

    def test_unreadable_manifest_is_reported_not_raised(self) -> None:
        self.manifest.write_text("{", encoding="utf-8")
        report = checker.check_ledger_coverage(self.ledger, self.manifest)
        self.assertFalse(report["ok"])


class RealLedgerTests(unittest.TestCase):
    def test_shipped_ledger_and_manifest_agree(self) -> None:
        """The repository's own ledger and manifest must be in sync."""
        report = checker.check_ledger_coverage()
        self.assertTrue(report["ok"], report["errors"])
        self.assertGreater(report["named"], 0, "台账里一个来源都没解析到，判据空转")


if __name__ == "__main__":
    unittest.main()
