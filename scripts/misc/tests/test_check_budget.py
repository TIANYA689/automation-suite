"""预算度量的测试。

阈值是标定值，标定值必须被钉死：悄悄调阈值和悄悄让规则变松是一回事。
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

import check_budget  # noqa: E402
from check_budget import HARD_LIMITS, SOFT_LIMITS, estimate_tokens, run  # noqa: E402


class TokenEstimateTests(unittest.TestCase):
    def test_pure_ascii_is_four_chars_per_token(self) -> None:
        self.assertEqual(estimate_tokens("a" * 400), 100)

    def test_cjk_counts_one_per_character(self) -> None:
        self.assertEqual(estimate_tokens("中" * 100), 100)

    def test_mixed_text_adds_both_components(self) -> None:
        self.assertEqual(estimate_tokens("中" * 10 + "a" * 40), 20)

    def test_estimate_is_monotonic(self) -> None:
        short = estimate_tokens("abc")
        long = estimate_tokens("abc" * 100)
        self.assertLess(short, long)

    def test_fullwidth_punctuation_counts_as_cjk(self) -> None:
        self.assertEqual(estimate_tokens("，。" * 50), 100)


class ThresholdSanityTests(unittest.TestCase):
    def test_soft_is_below_hard_for_every_metric(self) -> None:
        self.assertEqual(set(SOFT_LIMITS), set(HARD_LIMITS))
        for metric, soft in SOFT_LIMITS.items():
            self.assertLess(soft, HARD_LIMITS[metric], f"{metric} 的软硬上限颠倒了")

    def test_thresholds_are_not_absurdly_loose(self) -> None:
        """阈值定得太松等于没有度量；这里给出下限，防止有人用调阈值来消警。"""
        self.assertLessEqual(HARD_LIMITS["skill_lines"], 2000)
        self.assertLessEqual(HARD_LIMITS["skill_tokens"], 30000)
        self.assertLessEqual(HARD_LIMITS["signal_chars"], 60)

    def test_file_size_soft_is_below_hard_for_every_metric(self) -> None:
        self.assertEqual(
            set(check_budget.FILE_SIZE_SOFT), set(check_budget.FILE_SIZE_HARD)
        )
        for metric, soft in check_budget.FILE_SIZE_SOFT.items():
            self.assertLess(
                soft,
                check_budget.FILE_SIZE_HARD[metric],
                f"file_size.{metric} 的软硬上限颠倒了",
            )

    def test_file_size_thresholds_are_not_absurdly_loose(self) -> None:
        self.assertLessEqual(check_budget.FILE_SIZE_HARD["lines"], 3000)
        self.assertLessEqual(check_budget.FILE_SIZE_HARD["bytes"], 200_000)

    def test_append_only_and_derived_suffixes_are_skipped(self) -> None:
        """这条钉的是口径：只增/派生的文件不参与体积度量。

        放宽它（比如允许 `.jsonl` 参与）会让经验库每加一条就多一条警，
        最后所有人学会忽略这个检查——**度量变成噪音就等于没有度量**。
        """
        self.assertLessEqual(
            {".json", ".jsonl", ".csv"}, set(check_budget.FILE_SIZE_SKIP_SUFFIXES)
        )

    def test_files_with_their_own_budget_are_skipped(self) -> None:
        self.assertLessEqual(
            {"SKILL.md", "AI-USAGE.md", "AGENTS.md"},
            set(check_budget.FILE_SIZE_SKIP_NAMES),
        )


class BudgetReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self._originals = (
            check_budget.ROOT,
            check_budget.SKILLS_ROOT,
            check_budget.ROUTING_SOURCE,
        )
        check_budget.ROOT = self.root
        check_budget.SKILLS_ROOT = self.root / "skills"
        check_budget.ROUTING_SOURCE = self.root / "routing.source.json"
        (self.root / "skills").mkdir()
        (self.root / "routing.source.json").write_text(
            json.dumps({"skills": {}}), encoding="utf-8", newline="\n"
        )

    def tearDown(self) -> None:
        (
            check_budget.ROOT,
            check_budget.SKILLS_ROOT,
            check_budget.ROUTING_SOURCE,
        ) = self._originals
        self._temp.cleanup()

    def _skill(self, name: str, lines: int) -> None:
        directory = self.root / "skills" / name
        directory.mkdir(parents=True, exist_ok=True)
        body = "\n".join(f"行 {index}" for index in range(lines))
        (directory / "SKILL.md").write_text(body, encoding="utf-8", newline="\n")

    def test_small_skill_is_within_budget(self) -> None:
        self._skill("alpha", 50)
        report = run()
        self.assertTrue(report["ok"], report["failures"])
        self.assertEqual(report["warnings"], [])

    def test_oversized_skill_warns_before_it_fails(self) -> None:
        self._skill("alpha", SOFT_LIMITS["skill_lines"] + 20)
        report = run()
        self.assertTrue(report["ok"], "软上限只出 warning，不应判失败")
        self.assertTrue(report["warnings"])
        self.assertEqual(report["warnings"][0]["metric"], "lines")

    def test_far_oversized_skill_fails(self) -> None:
        self._skill("alpha", HARD_LIMITS["skill_lines"] + 20)
        report = run()
        self.assertFalse(report["ok"])
        self.assertTrue(report["failures"])

    def test_strict_promotes_warnings_to_failure(self) -> None:
        self._skill("alpha", SOFT_LIMITS["skill_lines"] + 20)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            # 必须带 --json：不带时会在 JSON 后追加 RESULT 令牌，下游无法解析。
            code = check_budget.main(["--strict", "--json"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stream.getvalue())["ok"])

    def test_largest_skill_is_reported(self) -> None:
        self._skill("small", 10)
        self._skill("large", 200)
        report = run()
        self.assertEqual(report["measurements"]["largest_skill"]["skill"], "large")

    def test_missing_skills_directory_does_not_crash(self) -> None:
        check_budget.SKILLS_ROOT = self.root / "nope"
        report = run()
        self.assertIsNone(report["measurements"]["largest_skill"])

    def test_hedging_is_reported_as_a_trend_not_a_failure(self) -> None:
        self._skill("alpha", 5)
        (self.root / "skills" / "alpha" / "SKILL.md").write_text(
            "这里可能有问题，视情况处理。", encoding="utf-8", newline="\n"
        )
        report = run()
        self.assertTrue(report["ok"], "含糊词只作趋势报告，不判失败")
        self.assertTrue(report["notes"]["hedging"])
        self.assertEqual(report["notes"]["hedging"][0]["total"], 2)


class FileSizeBudgetTests(unittest.TestCase):
    """单文件体积预算。

    沙箱 ROOT 不是 git 仓库，`_git_listed_files()` 会返回 None，于是走
    文件系统回退遍历——这条路径本身也被这些用例覆盖着。
    """

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self._originals = (
            check_budget.ROOT,
            check_budget.SKILLS_ROOT,
            check_budget.ROUTING_SOURCE,
        )
        check_budget.ROOT = self.root
        check_budget.SKILLS_ROOT = self.root / "skills"
        check_budget.ROUTING_SOURCE = self.root / "routing.source.json"
        (self.root / "skills").mkdir()
        (self.root / "routing.source.json").write_text(
            json.dumps({"skills": {}}), encoding="utf-8", newline="\n"
        )

    def tearDown(self) -> None:
        (
            check_budget.ROOT,
            check_budget.SKILLS_ROOT,
            check_budget.ROUTING_SOURCE,
        ) = self._originals
        self._temp.cleanup()

    def _write(self, relative: str, lines: int, suffix: str = ".py") -> Path:
        path = self.root / f"{relative}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(f"行 {index}" for index in range(lines)),
            encoding="utf-8",
            newline="\n",
        )
        return path

    def _file_warnings(self, report: dict) -> list[dict]:
        return [w for w in report["warnings"] if str(w["metric"]).startswith("file_")]

    def test_small_source_file_is_within_budget(self) -> None:
        self._write("scripts/small", 50)
        report = run()
        self.assertTrue(report["ok"], report["failures"])
        self.assertEqual(self._file_warnings(report), [])

    def test_oversized_source_file_warns_before_it_fails(self) -> None:
        self._write("scripts/big", check_budget.FILE_SIZE_SOFT["lines"] + 20)
        report = run()
        self.assertTrue(report["ok"], "软上限只出 warning，不应判失败")
        self.assertTrue(self._file_warnings(report))
        self.assertEqual(self._file_warnings(report)[0]["metric"], "file_lines")

    def test_far_oversized_source_file_fails(self) -> None:
        self._write("scripts/huge", check_budget.FILE_SIZE_HARD["lines"] + 20)
        report = run()
        self.assertFalse(report["ok"])
        self.assertTrue(report["failures"])

    def test_append_only_and_derived_files_are_not_measured(self) -> None:
        """`.jsonl` / `.json` / `.csv` 只增或派生，不参与体积度量。"""
        oversized = check_budget.FILE_SIZE_HARD["lines"] + 500
        self._write("kb/findings", oversized, suffix=".jsonl")
        self._write("kb/kb-index", oversized, suffix=".json")
        self._write("kb/table", oversized, suffix=".csv")
        report = run()
        self.assertTrue(report["ok"], report["failures"])
        self.assertEqual(self._file_warnings(report), [])

    def test_files_with_their_own_budget_are_not_double_counted(self) -> None:
        """`SKILL.md` 走 skill_*，入口文档走 entry_*，不重复计入 file_*。"""
        oversized = check_budget.FILE_SIZE_SOFT["lines"] + 50
        self._write("skills/alpha/SKILL", oversized, suffix=".md")
        self._write("AI-USAGE", oversized, suffix=".md")
        report = run()
        subjects = [str(w["subject"]) for w in self._file_warnings(report)]
        self.assertEqual([s for s in subjects if "SKILL" in s or "AI-USAGE" in s], [])

    def test_largest_file_is_reported(self) -> None:
        self._write("scripts/small", 10)
        self._write("scripts/large", 300)
        report = run()
        self.assertEqual(report["measurements"]["largest_file"]["file"], "scripts/large.py")
        self.assertEqual(report["measurements"]["files_measured"], 2)

    def test_missing_files_do_not_crash_and_report_zero(self) -> None:
        report = run()
        self.assertIsNone(report["measurements"]["largest_file"])
        self.assertEqual(report["measurements"]["files_measured"], 0)

    def test_undecodable_file_is_skipped_not_counted(self) -> None:
        path = self.root / "scripts" / "blob.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00\x01\x02\xff" * 10)
        report = run()
        self.assertTrue(report["ok"], report["failures"])
        self.assertEqual(report["measurements"]["files_measured"], 0)

    def test_skipped_directories_are_not_walked(self) -> None:
        """回退遍历必须跳过本地产物目录，否则 tmp/ 里的克隆会让度量失真。"""
        oversized = check_budget.FILE_SIZE_HARD["lines"] + 500
        self._write("tmp/clone/scripts/huge", oversized)
        self._write("reports/snapshot", oversized, suffix=".md")
        report = run()
        self.assertTrue(report["ok"], report["failures"])


class RealRepositoryTests(unittest.TestCase):
    def test_repository_is_within_hard_budget(self) -> None:
        report = run()
        self.assertTrue(
            report["ok"],
            "已越过硬上限：" + json.dumps(report["failures"], ensure_ascii=False),
        )

    def test_worst_offender_has_headroom_under_the_hard_limit(self) -> None:
        """硬上限不能贴着当前最大值标定。

        若把 FILE_SIZE_HARD 定在紧邻最大文件的位置，下一个往那个文件里加三行的人
        会撞上 CI 红，而那时唯一的出路是拆分一个一千多行的文件——
        **一个没有可行修复路径的门禁，只会教人绕开它。**
        """
        largest = run()["measurements"]["largest_file"]
        self.assertIsNotNone(largest, "仓库里应当至少有一个被度量的文件")
        self.assertGreater(
            check_budget.FILE_SIZE_HARD["lines"],
            largest["lines"] * 1.15,
            f"硬上限离最大文件（{largest['file']}，{largest['lines']} 行）太近",
        )

    def test_file_measurement_actually_covers_the_repository(self) -> None:
        """防"零覆盖也报绿"：度量不到文件时，这个维度就是装饰品。"""
        report = run()
        self.assertGreater(
            report["measurements"]["files_measured"],
            50,
            "被度量的文件数太少，说明列表来源坏了（例如 git 列表为空）",
        )
        self.assertIsNotNone(report["measurements"]["largest_file"])

    def test_always_loaded_part_is_measured(self) -> None:
        report = run()
        self.assertGreater(report["measurements"]["always_loaded"]["lines"], 0)
        # 期望值取自路由单一事实源，而不是写死的数字：新增技能时不该需要改这个测试。
        declared = json.loads(
            (check_budget.ROOT / "routing.source.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            report["measurements"]["skills_measured"],
            len(declared["skills"]),
            "被测量的技能数必须与 routing.source.json 声明的技能数一致",
        )

    def test_json_mode_keeps_output_parsable(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            check_budget.main(["--json"])
        json.loads(stream.getvalue())


if __name__ == "__main__":
    unittest.main()
