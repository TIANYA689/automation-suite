"""`run_ci_checks.py` 的判据。

要钉住的是最容易悄悄失效的那一环：**步骤列表是从 `ci.yml` 派生的**。
派生规则漏掉一步，本地跑绿了却比 CI 少一截，而**没有任何地方会报错**——
所以这里既测派生本身，也测「一个步骤都不许凭空消失」的完整记账。
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
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_ci_checks as rcc  # noqa: E402

# 模块共用一个沙箱：热路径里没有 rmtree（规则 36）。
_TMP_ROOT = Path(__file__).resolve().parents[3] / "tmp"
_TMP_ROOT.mkdir(exist_ok=True)
_SANDBOX = Path(tempfile.mkdtemp(dir=_TMP_ROOT, prefix="cicheck-test-"))
_COUNTER = itertools.count()

_REAL_ROOT = Path(rcc.__file__).resolve().parents[2]


def _cleanup(target: Path) -> None:
    """删不掉就留着，绝不把调用方带走（沙箱拦 rmtree 是预期）。"""
    try:
        shutil.rmtree(target, ignore_errors=True)
    except SystemExit:
        pass


atexit.register(_cleanup, _SANDBOX)


# 一份结构完整、覆盖四种步骤形态的夹具（缩进与判据无关，两者都是 `^\s*`）。
FIXTURE = (
    "name: CI\n"
    "on:\n"
    "  push:\n"
    "jobs:\n"
    "  checks:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - name: Checkout\n"
    "        uses: actions/checkout@v4\n"
    "\n"
    "      - name: Set up Python\n"
    "        uses: actions/setup-python@v5\n"
    "        with:\n"
    '          python-version: "3.11"\n'
    "\n"
    "      - name: Install uv\n"
    "        run: python -m pip install uv\n"
    "\n"
    "      - name: Real check\n"
    "        run: python scripts/misc/probe.py --strict\n"
    "\n"
    "      - name: Install deps\n"
    "        shell: bash\n"
    "        run: |\n"
    '          requirements="$(python scripts/misc/probe.py --print)"\n'
    "          python -m pip install $requirements\n"
)

EMPTY_WORKFLOW = "name: CI\non:\n  push:\njobs:\n  checks:\n    steps:\n      - name: X\n        uses: a/b@v1\n"


class DeriveTests(unittest.TestCase):
    def test_only_python_script_steps_are_taken(self) -> None:
        steps, _ = rcc.derive_steps(FIXTURE)
        self.assertEqual(
            [s["name"] for s in steps], ["Real check"]
        )
        self.assertEqual(steps[0]["command"], "python scripts/misc/probe.py --strict")

    def test_uses_step_is_skipped_with_a_reason(self) -> None:
        _, skipped = rcc.derive_steps(FIXTURE)
        reasons = {s["name"]: s["why"] for s in skipped}
        self.assertIn("uses 类环境准备步骤", reasons["Checkout"])
        self.assertIn("uses 类环境准备步骤", reasons["Set up Python"])

    def test_multiline_run_is_skipped(self) -> None:
        _, skipped = rcc.derive_steps(FIXTURE)
        reasons = {s["name"]: s["why"] for s in skipped}
        self.assertIn("多行 run", reasons["Install deps"])

    def test_pip_install_is_not_a_check(self) -> None:
        """`python -m pip install ...` 也以 `python ` 开头，必须被排除。"""
        steps, skipped = rcc.derive_steps(FIXTURE)
        self.assertNotIn("Install uv", [s["name"] for s in steps])
        self.assertIn("Install uv", [s["name"] for s in skipped])

    def test_accounting_is_complete(self) -> None:
        """**一个步骤都不许凭空消失**：取走的 + 跳过的 == 文件里的全部步骤。"""
        steps, skipped = rcc.derive_steps(FIXTURE)
        self.assertEqual(len(steps) + len(skipped), len(rcc._blocks(FIXTURE)))

    def test_skipped_steps_always_carry_a_reason(self) -> None:
        _, skipped = rcc.derive_steps(FIXTURE)
        self.assertTrue(skipped)
        for item in skipped:
            self.assertTrue(item["why"].strip(), item)


class GuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _SANDBOX / f"case-{next(_COUNTER)}"
        self.root.mkdir(parents=True, exist_ok=True)
        self._original = (rcc.ROOT, rcc.WORKFLOW)
        rcc.ROOT = self.root
        rcc.WORKFLOW = self.root / "ci.yml"

    def tearDown(self) -> None:
        rcc.ROOT, rcc.WORKFLOW = self._original

    def _write(self, text: str) -> None:
        rcc.WORKFLOW.write_text(text, encoding="utf-8", newline="\n")

    def _main(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = rcc.main(argv)
        return code, buffer.getvalue()

    def test_no_steps_must_not_pass(self) -> None:
        """派生不到步骤 = 判据空转，必须报错而不是「0 步全绿」。"""
        self._write(EMPTY_WORKFLOW)
        code, output = self._main([])
        self.assertEqual(code, 1)
        self.assertIn("判据空转", output)

    def test_missing_workflow_must_not_pass(self) -> None:
        code, output = self._main([])
        self.assertEqual(code, 1)
        self.assertIn("找不到", output)

    def test_only_typo_must_not_pass_as_an_empty_run(self) -> None:
        """`--only` 打错字筛空 → 空集不许充当通过（审计 F5 的同类）。"""
        self._write(FIXTURE)
        code, output = self._main(["--only", "绝不存在"])
        self.assertEqual(code, 1)
        self.assertIn("空集", output)


class ExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _SANDBOX / f"case-{next(_COUNTER)}"
        self.root.mkdir(parents=True, exist_ok=True)
        self._original = (rcc.ROOT, rcc.WORKFLOW)
        rcc.ROOT = self.root
        rcc.WORKFLOW = self.root / "ci.yml"
        rcc.WORKFLOW.write_text(
            "jobs:\n  checks:\n    steps:\n"
            "      - name: Probe\n"
            "        run: python probe.py\n",
            encoding="utf-8",
            newline="\n",
        )

    def tearDown(self) -> None:
        rcc.ROOT, rcc.WORKFLOW = self._original

    def _script(self, body: str) -> None:
        (self.root / "probe.py").write_text(body, encoding="utf-8", newline="\n")

    def _main(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = rcc.main(argv)
        return code, buffer.getvalue()

    def test_passing_step_reports_ok(self) -> None:
        self._script("import sys\nsys.exit(0)\n")
        code, output = self._main([])
        self.assertEqual(code, 0)
        self.assertIn("[PASS]", output)
        self.assertIn("RESULT=OK", output)

    def test_failing_step_makes_main_fail(self) -> None:
        self._script("import sys\nprint('boom')\nsys.exit(3)\n")
        code, output = self._main([])
        self.assertEqual(code, 1)
        self.assertIn("[FAIL]", output)
        self.assertIn("boom", output)

    def test_list_does_not_execute(self) -> None:
        """`--list` 只列不跑：脚本会写下哨兵文件，跑过就看得见。"""
        self._script(
            "import pathlib\npathlib.Path('sentinel.txt').write_text('x')\n"
        )
        code, output = self._main(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("Probe", output)
        self.assertFalse((self.root / "sentinel.txt").exists())

    def test_json_reports_failures(self) -> None:
        self._script("import sys\nsys.exit(2)\n")
        code, output = self._main(["--json"])
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed"], ["Probe"])
        self.assertEqual(payload["derived"], 1)


class OverrideTests(unittest.TestCase):
    """本地改写表必须与 ci.yml 的步骤名对齐。

    改名后改写**静默失效**是最坏的情况：本地会带 CI 的环境断言去跑，红得莫名其妙，
    而没人知道是这里没跟上。所以用一条判据把它钉住。
    """

    def test_every_override_key_is_a_real_ci_step(self) -> None:
        workflow = _REAL_ROOT / ".github" / "workflows" / "ci.yml"
        steps, _ = rcc.derive_steps(workflow.read_text(encoding="utf-8"))
        names = {step["name"] for step in steps}
        for name, _, _ in rcc.LOCAL_OVERRIDES:
            with self.subTest(step=name):
                self.assertIn(name, names)

    def test_override_rewrites_and_is_recorded(self) -> None:
        steps = [
            {
                "name": "Case state validation",
                "command": "python scripts/misc/validate_case_states.py --expect-cases 0",
            }
        ]
        rewritten, applied = rcc.apply_local_overrides(steps)
        self.assertEqual(
            rewritten[0]["command"], "python scripts/misc/validate_case_states.py"
        )
        self.assertEqual(len(applied), 1)
        self.assertIn("--expect-cases 0", applied[0]["from"])
        self.assertTrue(applied[0]["why"].strip())

    def test_unlisted_step_is_left_alone(self) -> None:
        steps = [
            {"name": "Cross-reference check", "command": "python scripts/misc/check_doc_refs.py"}
        ]
        rewritten, applied = rcc.apply_local_overrides(steps)
        self.assertEqual(rewritten, steps)
        self.assertEqual(applied, [])


class AsCiTests(unittest.TestCase):
    """`--as-ci` 是唯一能回答「CI 会不会绿」的模式。

    它必须**不**应用本地改写（否则预演的还是本地口径），且必须说清
    「你不在干净克隆里」——`--expect-cases 0` 是**对空克隆的断言**，
    在本地仓库照搬必然红，不说清楚就会把人引向错误方向。
    """

    FIXTURE = (
        "jobs:\n  checks:\n    steps:\n"
        "      - name: Case state validation\n"
        "        run: python scripts/misc/validate_case_states.py --expect-cases 0\n"
    )

    def setUp(self) -> None:
        self.root = _SANDBOX / f"case-{next(_COUNTER)}"
        self.root.mkdir(parents=True, exist_ok=True)
        self._original = (rcc.ROOT, rcc.WORKFLOW)
        rcc.ROOT = self.root
        rcc.WORKFLOW = self.root / "ci.yml"
        rcc.WORKFLOW.write_text(self.FIXTURE, encoding="utf-8", newline="\n")

    def tearDown(self) -> None:
        rcc.ROOT, rcc.WORKFLOW = self._original

    def _main(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = rcc.main(argv)
        return code, buffer.getvalue()

    @staticmethod
    def _derived_command(output: str, name: str) -> str:
        """取「派生出 N 个检查步骤」那一段里该步骤的命令行。

        **必须锚到这一行**，不能在全文里搜串：默认模式的改写说明里也会出现
        `--expect-cases 0`（在「CI：」那一行），全文搜串会把两种模式判成一样。
        """
        marker = f"- {name}："
        for line in output.splitlines():
            if line.strip().startswith(marker):
                return line.strip()
        raise AssertionError(f"没在输出里找到派生步骤 `{name}`：\n{output}")

    def test_as_ci_keeps_the_command_verbatim(self) -> None:
        code, output = self._main(["--as-ci", "--list"])
        self.assertEqual(code, 0)
        self.assertIn(
            "--expect-cases 0",
            self._derived_command(output, "Case state validation"),
        )
        self.assertNotIn("本地改写了", output)
        self.assertIn("按 CI 原样跑", output)

    def test_default_mode_applies_the_override(self) -> None:
        """对照组：不带 `--as-ci` 时派生的命令必须被改写，否则 `--as-ci` 就没有区分度。"""
        code, output = self._main(["--list"])
        self.assertEqual(code, 0)
        self.assertNotIn(
            "--expect-cases 0",
            self._derived_command(output, "Case state validation"),
        )
        self.assertIn("本地改写了", output)

    def test_as_ci_warns_when_cases_is_not_empty(self) -> None:
        (self.root / "cases").mkdir(exist_ok=True)
        (self.root / "cases" / "job.json").write_text("{}", encoding="utf-8")
        _, output = self._main(["--as-ci", "--list"])
        self.assertIn("提示", output)
        self.assertIn("cases/", output)

    def test_clean_clone_is_not_warned(self) -> None:
        _, output = self._main(["--as-ci", "--list"])
        self.assertNotIn("提示", output)

    def test_routing_index_also_marks_a_dirty_tree(self) -> None:
        """第二个廉价信号：`routing.index.json` 是派生且被 gitignore，克隆里不该有。"""
        (self.root / "routing.index.json").write_text("{}", encoding="utf-8")
        _, output = self._main(["--as-ci", "--list"])
        self.assertIn("routing.index.json", output)


class RealRepositoryTests(unittest.TestCase):
    def test_real_workflow_derives_the_expected_checks(self) -> None:
        text = (rcc.WORKFLOW if rcc.WORKFLOW.exists() else _REAL_ROOT / ".github" / "workflows" / "ci.yml")
        steps, skipped = rcc.derive_steps(text.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(steps), 10, [s["name"] for s in steps])
        names = {s["name"] for s in steps}
        for expected in ("Cross-reference check", "Offline unit tests"):
            self.assertIn(expected, names)
        self.assertTrue(skipped)

    def test_every_derived_command_points_at_an_existing_script(self) -> None:
        """派生出的命令必须指向真实存在的脚本——否则本地入口会跑出「找不到文件」。"""
        workflow = _REAL_ROOT / ".github" / "workflows" / "ci.yml"
        steps, _ = rcc.derive_steps(workflow.read_text(encoding="utf-8"))
        for step in steps:
            with self.subTest(step=step["name"]):
                script = step["command"].split()[1]
                self.assertTrue(
                    (_REAL_ROOT / script).exists(), f"{script} 不存在"
                )


if __name__ == "__main__":
    unittest.main()
