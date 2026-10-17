"""长任务案例状态校验的测试。

重点覆盖 F5 那条修复：`cases/` 与 `templates/` 的覆盖度必须**分开报**，
且「空集」要能被写成断言（`--expect-cases`）。

为什么值得单独测：`cases/` 被 `.gitignore` 挡住，CI 上新克隆里它是空的。
修复前「空集通过」与「有内容且通过」退出码都是 0——两种含义完全不同的事
在退出码上长得一模一样，是一处看不见的失效。

沙箱约定与 `test_projects.py` 一致：整个模块共用一个沙箱，**热路径里没有 rmtree**。
本机 rmtree 一个空目录要 ~400ms，11 个用例各建各的临时目录要跑 21 秒。
"""

from __future__ import annotations

import atexit
import contextlib
import io
import itertools
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import validate_case_states as v  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
_STALE_AFTER_SECONDS = 3600


def _cleanup(target: Path) -> None:
    """删不掉就留着，绝不把调用方带走（与 test_projects.py 同款善后）。"""
    try:
        shutil.rmtree(target, ignore_errors=True)
    except SystemExit:
        pass


def fresh_sandbox() -> Path:
    tmp_root = ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    now = time.time()
    for stale in tmp_root.glob("case-states-test-*"):
        try:
            age = now - stale.stat().st_mtime
        except OSError:
            continue
        if age > _STALE_AFTER_SECONDS:
            _cleanup(stale)
    return Path(tempfile.mkdtemp(dir=tmp_root, prefix="case-states-test-"))


_SANDBOX = fresh_sandbox()
_COUNTER = itertools.count()
atexit.register(_cleanup, _SANDBOX)


def _valid_state(case: str) -> str:
    return json.dumps(
        {
            "case": case,
            "goal": "一句话目标",
            "status": "in_progress",
            "next_steps": ["下一步"],
            "updated_at": "2026-09-26",
        },
        ensure_ascii=False,
    )


def _valid_manifest(case: str) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "case": case,
            "goal": "目标",
            "status": "CONTINUE",
            "inputs": [],
            "steps_done": [],
            "evidence": [],
            "dead_ends": [],
            "next_actions": ["下一步"],
            "open_questions": [],
            "updated_at": "2026-09-26",
        },
        ensure_ascii=False,
    )


class CaseStateTestCase(unittest.TestCase):
    """每个用例拿一个全新沙箱根，并把三个路径常量一起指过去。

    `_load` 会对文件做 `relative_to(ROOT)`，所以 ROOT 也必须一起改，
    否则沙箱在 ROOT 之外会直接抛 ValueError。
    """

    def setUp(self) -> None:
        self.root = _SANDBOX / f"case-{next(_COUNTER)}"
        (self.root / "cases").mkdir(parents=True)
        (self.root / "templates" / "case").mkdir(parents=True)
        self._original = (v.ROOT, v.CASES_ROOT, v.TEMPLATE_ROOT)
        v.ROOT = self.root
        v.CASES_ROOT = self.root / "cases"
        v.TEMPLATE_ROOT = self.root / "templates" / "case"
        self._write_template()

    def tearDown(self) -> None:
        v.ROOT, v.CASES_ROOT, v.TEMPLATE_ROOT = self._original

    def _write_template(self) -> None:
        (self.root / "templates" / "case" / "state.json").write_text(
            _valid_state("case"), encoding="utf-8", newline="\n"
        )
        (self.root / "templates" / "case" / "ai_manifest.json").write_text(
            _valid_manifest("case"), encoding="utf-8", newline="\n"
        )

    def _add_case(self, name: str) -> None:
        case_dir = self.root / "cases" / name
        case_dir.mkdir()
        (case_dir / "state.json").write_text(_valid_state(name), encoding="utf-8", newline="\n")

    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = v.main(argv)
        return code, buffer.getvalue()


class CoverageSplitTests(CaseStateTestCase):
    def test_template_only_is_reported_as_zero_case_items(self) -> None:
        states, manifests, coverage = v.collect()
        self.assertEqual(coverage["case_items"], 0)
        self.assertEqual(coverage["template_items"], 2)
        self.assertEqual(len(states), 1)
        self.assertEqual(len(manifests), 1)

    def test_case_and_template_are_counted_separately(self) -> None:
        self._add_case("ad-hoc")
        self._add_case("other-job")
        _, _, coverage = v.collect()
        self.assertEqual(coverage["case_items"], 2)
        self.assertEqual(coverage["template_items"], 2)

    def test_empty_cases_prints_note(self) -> None:
        code, out = self._run([])
        self.assertEqual(code, 0)
        self.assertIn("NOTE:", out)
        self.assertIn("没有可校验项", out)

    def test_non_empty_cases_has_no_note(self) -> None:
        self._add_case("ad-hoc")
        code, out = self._run([])
        self.assertEqual(code, 0)
        self.assertNotIn("NOTE:", out)


class ExpectCasesTests(CaseStateTestCase):
    def test_zero_matches_empty_cases(self) -> None:
        code, _ = self._run(["--expect-cases", "0"])
        self.assertEqual(code, 0)

    def test_zero_fails_when_cases_present(self) -> None:
        """将来若有人把 cases/ 纳入版本库，CI 必须变红而不是默默改含义。"""
        self._add_case("ad-hoc")
        code, out = self._run(["--expect-cases", "0"])
        self.assertEqual(code, 1)
        self.assertIn("应为 0 个", out)
        self.assertIn("实际 1 个", out)

    def test_count_mismatch_names_the_counting_unit(self) -> None:
        """计数口径必须写清楚：这里是 `state.json` + `ai_manifest.json` 的**文件数**。

        与 `run_ci_checks.py` 的「作业目录数」单位不同，量词不能都叫「个条目」。
        """
        self._add_case("ad-hoc")
        code, out = self._run(["--expect-cases", "0"])
        self.assertEqual(code, 1)
        self.assertIn("校验项（state.json + ai_manifest.json）应为 0 个", out)
        self.assertIn("实际 1 个", out)

    def test_positive_count_fails_when_empty(self) -> None:
        """反向也要钉住：断言不为 0 时空集必须失败，否则它只是装饰。"""
        code, out = self._run(["--expect-cases", "3"])
        self.assertEqual(code, 1)
        self.assertIn("应为 3 个", out)

    def test_count_matches_actual(self) -> None:
        self._add_case("ad-hoc")
        self._add_case("other-job")
        code, _ = self._run(["--expect-cases", "2"])
        self.assertEqual(code, 0)

    def test_default_does_not_check_count(self) -> None:
        self._add_case("ad-hoc")
        code, out = self._run([])
        self.assertEqual(code, 0)
        self.assertNotIn("应为", out)


class ExistingValidationTests(CaseStateTestCase):
    """回归：加了开关不能把原有判据挤掉。"""

    def test_bad_state_still_fails(self) -> None:
        case_dir = self.root / "cases" / "broken"
        case_dir.mkdir()
        (case_dir / "state.json").write_text(
            json.dumps(
                {"case": "broken", "goal": "", "status": "nope", "next_steps": [], "updated_at": "x"},
                ensure_ascii=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
        code, out = self._run([])
        self.assertEqual(code, 1)
        self.assertIn("goal must be a non-empty string", out)
        self.assertIn("status must be one of", out)

    def test_manifest_status_lower_bound_still_enforced(self) -> None:
        case_dir = self.root / "cases" / "job"
        case_dir.mkdir()
        (case_dir / "ai_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "case": "job",
                    "goal": "目标",
                    "status": "DONE",
                    "inputs": [],
                    "steps_done": [],
                    "evidence": [],
                    "dead_ends": [],
                    "next_actions": [],
                    "open_questions": [],
                    "updated_at": "2026-09-26",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
        code, out = self._run([])
        self.assertEqual(code, 1)
        self.assertIn("DONE 状态必须有至少一条 evidence", out)


class CiWiringTests(unittest.TestCase):
    """CI 必须真的带上 `--expect-cases`。

    本地跑得再绿也说明不了 CI 有效——门禁有两半：判据写对了，**且**判据真的在
    CI 里执行。少一半，这个开关就只是本地的一个可选参数。
    与 `test_offline_runner.test_ci_installs_every_declared_dependency` 同款守卫。
    """

    def _workflow(self) -> str:
        return (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_ci_invokes_validate_case_states(self) -> None:
        lines = [line for line in self._workflow().splitlines() if "validate_case_states.py" in line]
        self.assertTrue(lines, "CI 未调用 validate_case_states.py")

    def test_ci_passes_expect_cases(self) -> None:
        lines = [line for line in self._workflow().splitlines() if "validate_case_states.py" in line]
        self.assertTrue(
            any("--expect-cases" in line for line in lines),
            "CI 未把 cases/ 的空集写成断言——这条门禁的含义会随仓库内容漂移",
        )


if __name__ == "__main__":
    unittest.main()
