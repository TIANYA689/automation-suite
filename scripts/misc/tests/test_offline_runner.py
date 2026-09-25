"""离线测试运行器自身的测试。

重点覆盖三处容易静默出错的逻辑：解释器解析、依赖探测、跳过语义。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import run_offline_tests
from run_offline_tests import missing_modules, resolve_interpreter, run_suite


class ResolveInterpreterTests(unittest.TestCase):
    def test_falls_back_to_current_interpreter(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            interpreter, source = resolve_interpreter(Path(raw))
        self.assertEqual(interpreter, sys.executable)
        self.assertEqual(source, "current")

    def test_prefers_module_venv(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            working_directory = Path(raw)
            launcher = working_directory / "venv" / "Scripts" / "python.exe"
            launcher.parent.mkdir(parents=True)
            launcher.write_text("", encoding="utf-8", newline="\n")
            interpreter, source = resolve_interpreter(working_directory)
        self.assertEqual(source, "module-venv")
        self.assertTrue(interpreter.endswith("python.exe"))

    def test_supports_posix_layout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            working_directory = Path(raw)
            launcher = working_directory / ".venv" / "bin" / "python"
            launcher.parent.mkdir(parents=True)
            launcher.write_text("", encoding="utf-8", newline="\n")
            interpreter, source = resolve_interpreter(working_directory)
        self.assertEqual(source, "module-venv")
        self.assertTrue(interpreter.endswith("python"))


class MissingModulesTests(unittest.TestCase):
    def test_empty_requirement_needs_no_probe(self) -> None:
        self.assertEqual(missing_modules(sys.executable, ()), [])

    def test_detects_absent_module(self) -> None:
        absent = missing_modules(sys.executable, ("definitely_not_installed_pkg_xyz",))
        self.assertEqual(absent, ["definitely_not_installed_pkg_xyz"])

    def test_recognises_present_module(self) -> None:
        self.assertEqual(missing_modules(sys.executable, ("json", "pathlib")), [])


class RunSuiteTests(unittest.TestCase):
    def test_skips_when_dependency_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            working_directory = Path(raw)
            (working_directory / "tests").mkdir()
            result = run_suite(
                "probe",
                working_directory,
                ("definitely_not_installed_pkg_xyz",),
                {},
            )
        self.assertEqual(result["status"], "skipped")
        self.assertIn("missing_dependency", str(result["reason"]))

    def test_skips_when_suite_directory_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = run_suite("probe", Path(raw) / "nope", (), {})
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "suite_directory_missing")

    def test_reports_passing_suite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            working_directory = Path(raw)
            tests = working_directory / "tests"
            tests.mkdir()
            (tests / "test_sample.py").write_text(
                "import unittest\n\n\n"
                "class Sample(unittest.TestCase):\n"
                "    def test_ok(self) -> None:\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8", newline="\n",
            )
            result = run_suite("sample", working_directory, (), {})
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["tests"], 1)

    def test_ignores_nested_test_counts(self) -> None:
        """套件自身打印的 "Ran N tests" 不得盖过真实计数。"""
        with tempfile.TemporaryDirectory() as raw:
            working_directory = Path(raw)
            tests = working_directory / "tests"
            tests.mkdir()
            (tests / "test_sample.py").write_text(
                "import unittest\n\n\n"
                "class Sample(unittest.TestCase):\n"
                "    def test_a(self) -> None:\n"
                "        print('Ran 99 tests in 0.001s')\n"
                "    def test_b(self) -> None:\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8", newline="\n",
            )
            result = run_suite("sample", working_directory, (), {})
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["tests"], 2)

    def test_reports_failing_suite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            working_directory = Path(raw)
            tests = working_directory / "tests"
            tests.mkdir()
            (tests / "test_sample.py").write_text(
                "import unittest\n\n\n"
                "class Sample(unittest.TestCase):\n"
                "    def test_nope(self) -> None:\n"
                "        self.fail('boom')\n",
                encoding="utf-8", newline="\n",
            )
            # 失败的套件会把子进程输出转发到 stderr；这里必须吞掉，
            # 否则 "Ran 1 test" 会混进外层运行器的输出，污染计数解析。
            with contextlib.redirect_stderr(io.StringIO()):
                result = run_suite("sample", working_directory, (), {})
        self.assertEqual(result["status"], "failed")


class SummaryTests(unittest.TestCase):
    def test_declared_suites_are_wellformed(self) -> None:
        from run_offline_tests import SUITES

        names = [entry[0] for entry in SUITES]
        self.assertEqual(len(names), len(set(names)), "套件名不得重复")
        for name, working_directory, required in SUITES:
            self.assertTrue(name)
            self.assertIsInstance(working_directory, Path)
            self.assertIsInstance(required, tuple)
        self.assertIn("release_checker", names)

    def test_suite_filter_matches_nothing_when_name_unknown(self) -> None:
        from run_offline_tests import main

        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(["--suite", "no_such_suite"])
        summary = json.loads(stream.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(summary["suites"], [])
        self.assertTrue(summary["ok"])

    def test_strict_turns_skipped_into_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            working_directory = Path(raw)
            (working_directory / "tests").mkdir()
            original = run_offline_tests.SUITES
            run_offline_tests.SUITES = [
                ("needs_absent_dep", working_directory, ("definitely_not_installed_pkg_xyz",))
            ]
            try:
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream):
                    lenient = run_offline_tests.main([])
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream):
                    strict = run_offline_tests.main(["--strict"])
            finally:
                run_offline_tests.SUITES = original

        self.assertEqual(lenient, 0, "缺依赖默认跳过，不算失败")
        self.assertEqual(strict, 1, "--strict 下跳过视为失败")

    def test_print_requirements_lists_declared_dependencies(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = run_offline_tests.main(["--print-requirements"])
        self.assertEqual(code, 0)
        self.assertEqual(stream.getvalue().strip(), "requests")

    def test_ci_installs_every_declared_dependency(self) -> None:
        """CI 若漏装依赖，套件会被静默跳过——这条守卫防止它悄悄发生。

        CI 不硬编码依赖名，而是用 `--print-requirements` 从 `SUITES` 派生；
        同时必须带 `--strict`，否则缺依赖时"跳过即绿"会掩盖问题。
        """
        workflow = (
            Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("--print-requirements", workflow, "CI 应派生依赖清单而非硬编码")
        self.assertIn("--strict", workflow, "CI 应使用 --strict，避免跳过被当作通过")
        self.assertEqual(
            run_offline_tests.declared_requirements(),
            ["requests"],
            "真实 SUITES 声明的依赖应与 CI 派生结果一致",
        )


if __name__ == "__main__":
    unittest.main()
