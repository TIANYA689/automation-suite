"""经验库质量门禁（check_kb_quality）的测试。

三条硬要求各有一组用例：

- **负例**：缺 evidence 的 active finding 必须被判失败（strict 下）；
- **空集守卫**：无条目 / 空文件 / 无 active 时不能静默通过，必须报错；
- **干净克隆前提**：判据只依赖注入的 `tracked` 集合与传入的 findings 文件，
  不依赖 `cases/`、`exports/`、`reports/`、`tmp/`、`.workbuddy-ai/` 是否存在。
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

import check_kb_quality as checker  # noqa: E402


def finding(**overrides: object) -> dict:
    record: dict = {
        "time": "2026-01-01T00:00:00+08:00",
        "kind": "path",
        "area": "automation",
        "title": "样例结论",
        "trigger": "何时读这条",
        "detail": "细节",
        "evidence": {"path": "kb/demo/techniques/01-x.md", "note": ""},
        "reuse": "high",
        "confidence": "high",
        "status": "active",
    }
    record.update(overrides)
    return record


class KbQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "findings.jsonl"
        self.tracked = {
            "kb/demo/techniques/01-x.md",
            "kb/demo/techniques/02-y.md",
            "scripts/misc/check_kb_quality.py",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, records: list[dict]) -> None:
        body = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
        self.path.write_text(body, encoding="utf-8", newline="\n")

    def run_check(self, strict: bool = False) -> dict:
        return checker.run(findings_path=self.path, tracked=set(self.tracked), strict=strict)

    def kinds(self, report: dict) -> list[str]:
        return [warning["kind"] for warning in report["warnings"]]

    # --- 正例 ---------------------------------------------------------------

    def test_active_finding_with_owned_evidence_passes(self) -> None:
        self.write([finding()])
        report = self.run_check()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["warnings"], [])

    def test_bare_filename_resolves_by_basename(self) -> None:
        """裸文件名按 basename 唯一匹配即可——与 check_doc_refs 的裸名判据同形。"""
        self.write([finding(evidence={"path": "01-x.md", "note": ""})])
        report = self.run_check()
        self.assertTrue(report["ok"], report)
        self.assertNotIn("missing_evidence", self.kinds(report))
        self.assertNotIn("evidence_not_owned", self.kinds(report))

    def test_superseded_pointing_to_real_technique_passes(self) -> None:
        self.write(
            [
                finding(),
                finding(
                    status="superseded",
                    detail="已提炼进 kb/demo/techniques/02-y.md",
                    evidence={"path": "", "note": ""},
                ),
            ]
        )
        report = self.run_check()
        self.assertTrue(report["ok"], report)
        self.assertNotIn("superseded_without_technique", self.kinds(report))

    # --- 负例：缺 evidence / 证据不拥有 --------------------------------------

    def test_active_finding_without_evidence_is_flagged(self) -> None:
        """负例：active 但 evidence 是自由文本（没有可解析路径）→ 必须被判失败。"""
        self.write([finding(evidence={"path": "release_checker 套件计数从 1 恢复", "note": ""})])
        lenient = self.run_check(strict=False)
        self.assertTrue(lenient["ok"], "默认模式只出 warning，不应失败")
        self.assertIn("missing_evidence", self.kinds(lenient))

        strict = self.run_check(strict=True)
        self.assertFalse(strict["ok"], "strict 下缺 evidence 的 active finding 必须失败")

    def test_local_artifact_evidence_is_accepted(self) -> None:
        """正例：证据落在**本地产物目录**里 —— 库自己的 README 就用
        `--evidence "exports/..."` 举例。这些目录被 gitignore 是设计，不是缺陷，
        判据不该要求证据搬进仓库（规则 98：判据的形态假设就是它的盲区）。

        第三例专门钉住「点目录」：token 正则若不允许前导点，`.workbuddy-ai/…`
        会被截成 `workbuddy-ai/…`，前缀匹配不上而误判断链。
        """
        for path in (
            "exports/demo/plan.json",
            "projects/20260925-avalon/capture/签到.har",
            ".workbuddy-ai/memory/2026-09-26/验证-CI克隆预演.md",
        ):
            with self.subTest(path=path):
                self.write([finding(evidence={"path": path, "note": ""})])
                report = self.run_check(strict=True)
                self.assertTrue(report["ok"], report)
                self.assertEqual(report["warnings"], [])

    def test_broken_in_repo_path_is_flagged(self) -> None:
        """负例：像仓库内路径却解析不到 → 断链，strict 下必须失败。"""
        self.write([finding(evidence={"path": "kb/demo/techniques/99-missing.md", "note": ""})])
        strict = self.run_check(strict=True)
        self.assertFalse(strict["ok"])
        self.assertIn("evidence_broken", self.kinds(strict))

    def test_low_confidence_without_evidence_is_allowed(self) -> None:
        """README 约定「没有证据的发现只能给 low 置信度」——给了 low 就不算缺陷。

        这条同时钉住「门禁要真的检查它引用的那条规则」：文案里写着这条约定，
        代码就必须按它判，否则又是一次「声明比实现强」。
        """
        self.write(
            [finding(confidence="low", evidence={"path": "没有可解析路径的描述", "note": ""})]
        )
        report = self.run_check(strict=True)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["warnings"], [])

    def test_superseded_without_technique_is_flagged(self) -> None:
        self.write(
            [
                finding(),
                finding(status="superseded", detail="已更新，详见新版说明", evidence={"path": "", "note": ""}),
            ]
        )
        strict = self.run_check(strict=True)
        self.assertFalse(strict["ok"])
        self.assertIn("superseded_without_technique", self.kinds(strict))

    # --- 空集守卫：不能静默通过 ---------------------------------------------

    def test_missing_file_is_an_error(self) -> None:
        report = self.run_check()
        self.assertFalse(report["ok"])
        self.assertTrue(any("不存在" in error for error in report["errors"]), report["errors"])

    def test_empty_file_is_an_error(self) -> None:
        self.path.write_text("", encoding="utf-8", newline="\n")
        report = self.run_check()
        self.assertFalse(report["ok"])
        self.assertTrue(any("0 条" in error for error in report["errors"]), report["errors"])

    def test_blank_lines_only_is_an_error(self) -> None:
        self.path.write_text("\n\n\n", encoding="utf-8", newline="\n")
        report = self.run_check()
        self.assertFalse(report["ok"])

    def test_no_active_findings_is_an_error(self) -> None:
        """整类 active 被筛成空集时，证据判据空转——必须报错，而不是当成通过。"""
        self.write(
            [
                finding(
                    status="superseded",
                    detail="已提炼进 kb/demo/techniques/02-y.md",
                    evidence={"path": "", "note": ""},
                )
            ]
        )
        report = self.run_check()
        self.assertFalse(report["ok"])
        self.assertTrue(any("active" in error for error in report["errors"]), report["errors"])

    def test_unparsable_line_is_an_error(self) -> None:
        self.path.write_text("{ not json\n", encoding="utf-8", newline="\n")
        report = self.run_check()
        self.assertFalse(report["ok"])
        self.assertTrue(report["errors"])

    # --- 干净克隆前提 -------------------------------------------------------

    def test_does_not_require_local_artifact_dirs(self) -> None:
        """干净克隆里 cases/exports/reports/tmp/.workbuddy-ai 都不存在，判据照样跑。"""
        for name in ("cases", "exports", "reports", "tmp", ".workbuddy-ai"):
            self.assertFalse((Path(self.temp.name) / name).exists())
        self.write([finding()])
        report = self.run_check()
        self.assertTrue(report["ok"], report)

    def test_real_repository_findings_have_no_errors(self) -> None:
        """真实仓库：git ls-files 判据跑得起来，且当前数据不产生硬错误。"""
        report = checker.run()
        self.assertEqual(report["errors"], [], report["errors"])
        self.assertGreater(report["total"], 0, "findings.jsonl 一条都没解析到，判据空转")
        self.assertTrue(report["ok"], "默认（warning）模式下不应失败")


class MainCliTests(unittest.TestCase):
    def test_json_mode_is_parsable(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            exit_code = checker.main(["--json"])
        report = json.loads(stream.getvalue())
        self.assertIn("warnings", report)
        self.assertEqual(exit_code, 0 if report["ok"] else 1)


if __name__ == "__main__":
    unittest.main()
