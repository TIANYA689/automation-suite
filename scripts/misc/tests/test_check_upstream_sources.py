"""Tests for the offline external-source manifest validator."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

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
