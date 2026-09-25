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


class RealRepositoryTests(unittest.TestCase):
    def test_repository_is_within_hard_budget(self) -> None:
        report = run()
        self.assertTrue(
            report["ok"],
            "已越过硬上限：" + json.dumps(report["failures"], ensure_ascii=False),
        )

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
