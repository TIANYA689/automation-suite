"""交叉引用校验的测试。"""

from __future__ import annotations

import atexit
import contextlib
import io
import itertools
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_doc_refs  # noqa: E402
from check_doc_refs import EXEMPTIONS, run, slugify  # noqa: E402


class SlugTests(unittest.TestCase):
    def test_ascii_heading(self) -> None:
        self.assertEqual(slugify("Gates — clear these first"), "gates--clear-these-first")

    def test_chinese_punctuation_is_dropped(self) -> None:
        """顿号是 Po 类标点，GitHub 会丢掉它；按"CJK 就保留"写会永远匹配不上。"""
        self.assertEqual(
            slugify("P5.4 多邮箱适配、故障切换与验证码来源过滤"),
            "p54-多邮箱适配故障切换与验证码来源过滤",
        )

    def test_inline_code_and_links_are_unwrapped(self) -> None:
        """链接取渲染后的文本，URL 不参与锚点。"""
        self.assertEqual(slugify("`code` 与 [文本](x.md)"), "code-与-文本")

    def test_uppercase_is_lowered(self) -> None:
        self.assertEqual(slugify("P1.3 Health-Aware Pool"), "p13-health-aware-pool")


# 整个模块共用一个沙箱：**热路径里没有 rmtree**。
# 实测本机 rmtree 一个空目录要 ~400ms，25 个用例各建各的 TemporaryDirectory
# 要跑 28.6 秒；改成共用一个沙箱后不到 1 秒（同 test_projects.py / test_validate_case_states.py）。
_TMP_ROOT = Path(__file__).resolve().parents[3] / "tmp"
_TMP_ROOT.mkdir(exist_ok=True)
_SANDBOX = Path(tempfile.mkdtemp(dir=_TMP_ROOT, prefix="docrefs-test-"))
_COUNTER = itertools.count()


def _cleanup(target: Path) -> None:
    """删不掉就留着，绝不把调用方带走（沙箱会拦 rmtree，那是预期）。"""
    try:
        shutil.rmtree(target, ignore_errors=True)
    except SystemExit:
        pass


atexit.register(_cleanup, _SANDBOX)

# 真实仓库根：从模块文件反推，**不受 `check_doc_refs.ROOT` 被测试猴补影响**。
# 用于钉"豁免指向的文档真实存在"这类必须打在真仓库上的判据。
_REAL_ROOT = Path(check_doc_refs.__file__).resolve().parents[2]


def _tracked_basenames() -> set[str] | None:
    """`git ls-files` 的 basename 集合；git 不可用时返回 None。

    用 git 而不是 `Path.exists()`：后者在**本地工作区**会被 gitignore 的文件喂饱，
    于是"本仓库拥不拥有这个名字"在本地与干净克隆里是两个答案——
    **本地绿、CI 红**（2026-09-26 实测）。
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files"],
            cwd=_REAL_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return {
        Path(line).name for line in completed.stdout.splitlines() if line.strip()
    }


class _SandboxCase(unittest.TestCase):
    """一个用例一个沙箱子目录的基类。

    把 `ROOT` 指向沙箱、清掉两个按 ROOT 缓存的索引（锚点表 + 文件名索引），
    退出时恢复——`_FILENAME_INDEX` 按 ROOT 键控，不清会跨用例长大。
    """

    def setUp(self) -> None:
        self.root = _SANDBOX / f"case-{next(_COUNTER)}"
        self.root.mkdir(parents=True, exist_ok=True)
        self._original = check_doc_refs.ROOT
        check_doc_refs.ROOT = self.root
        self._clear_caches()

    def tearDown(self) -> None:
        check_doc_refs.ROOT = self._original
        self._clear_caches()

    @staticmethod
    def _clear_caches() -> None:
        check_doc_refs._ANCHOR_CACHE.clear()
        check_doc_refs._FILENAME_INDEX.clear()

    def _write(self, relative: str, markdown: str) -> Path:
        doc = self.root / relative
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(textwrap.dedent(markdown), encoding="utf-8", newline="\n")
        self._clear_caches()
        return doc


class ReferenceDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _SANDBOX / f"case-{next(_COUNTER)}"
        (self.root / "kb" / "demo" / "techniques").mkdir(parents=True)
        (self.root / "kb" / "demo" / "techniques" / "01-real.md").write_text(
            "# 真篇目\n\n## 小节标题\n", encoding="utf-8", newline="\n"
        )
        self._original = check_doc_refs.ROOT
        check_doc_refs.ROOT = self.root
        check_doc_refs._ANCHOR_CACHE.clear()

    def tearDown(self) -> None:
        check_doc_refs.ROOT = self._original
        check_doc_refs._ANCHOR_CACHE.clear()

    def _run(self, markdown: str) -> dict:
        doc = self.root / "README.md"
        doc.write_text(textwrap.dedent(markdown), encoding="utf-8", newline="\n")
        check_doc_refs._ANCHOR_CACHE.clear()
        return run()

    def test_valid_link_passes(self) -> None:
        report = self._run("- [真篇目](kb/demo/techniques/01-real.md)\n")
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["links_checked"], 1)

    def test_missing_link_target_is_detected(self) -> None:
        report = self._run("- [没了](kb/demo/techniques/99-gone.md)\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "link_missing")

    def test_valid_anchor_passes(self) -> None:
        report = self._run("- [跳到小节](kb/demo/techniques/01-real.md#小节标题)\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_missing_anchor_is_detected(self) -> None:
        report = self._run("- [跳到空处](kb/demo/techniques/01-real.md#不存在的小节)\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "anchor_missing")

    def test_bare_anchor_resolves_within_the_same_document(self) -> None:
        report = self._run("# 顶层\n\n- [自指](#顶层)\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_backticked_existing_path_passes(self) -> None:
        report = self._run("见 `kb/demo/techniques/01-real.md`。\n")
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["paths_checked"], 1)

    def test_backticked_missing_path_is_detected(self) -> None:
        report = self._run("见 `kb/demo/techniques/42-ghost.md`。\n")
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "path_missing")

    def test_skill_relative_path_resolves_against_doc_directory(self) -> None:
        skill = self.root / "skills" / "demo"
        (skill / "references").mkdir(parents=True)
        (skill / "references" / "note.md").write_text("# 笔记\n", encoding="utf-8", newline="\n")
        doc = skill / "SKILL.md"
        doc.write_text("见 `references/note.md`。\n", encoding="utf-8", newline="\n")
        self.assertTrue(run()["ok"])

    def test_external_link_is_exempt(self) -> None:
        report = self._run("- [外站](https://example.com/x.md)\n")
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["links_checked"], 1)

    def test_untracked_directory_is_exempt(self) -> None:
        report = self._run("- [报告](reports/2026-01-01.md)\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_dot_prefixed_local_dir_is_exempt(self) -> None:
        """`.workbuddy-ai/` 是本地产物（被 gitignore），不能判 `path_missing`。

        它**曾经**被判：`_exempt` 用 `lstrip("./")` 归一化，把点目录名的那个点一起剥掉，
        `.workbuddy-ai/…` 变成 `workbuddy-ai/…`，匹配不上任何前缀。
        后果是**本地绿、CI 红**——本机有这个目录，新克隆里没有。
        """
        report = self._run("见 `.workbuddy-ai/memory/MEMORY.md`。\n")
        self.assertTrue(report["ok"], report["drifts"])
        hits = {entry["reason"]: entry["hits"] for entry in report["exemptions"]}
        self.assertEqual(hits["untracked_dir"], 1)

    def test_dot_prefixed_name_without_the_dot_is_not_exempt(self) -> None:
        """豁免表里是 `.workbuddy-ai/`，不是 `workbuddy-ai/`——点目录名的点不许被剥。"""
        report = self._run("见 `workbuddy-ai/memory/MEMORY.md`。\n")
        self.assertFalse(report["ok"])
        self.assertEqual([d["kind"] for d in report["drifts"]], ["path_missing"])

    def test_single_dot_slash_prefix_is_stripped(self) -> None:
        report = self._run("见 `./reports/2026-01-01.md`。\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_template_path_is_exempt(self) -> None:
        report = self._run("技能路径为 `skills/<name>/SKILL.md`。\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_directory_reference_is_exempt(self) -> None:
        """目录引用常按读者自己的工作目录书写，本仓库不拥有其存在性。"""
        report = self._run("产物落到 `exports/automation/` 与 `data/device_profiles/`。\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_command_in_backticks_is_not_a_path(self) -> None:
        report = self._run("跑 `python scripts/misc/check_commands.py`。\n")
        self.assertTrue(report["ok"], report["drifts"])

    def test_code_fence_content_is_skipped(self) -> None:
        report = self._run("```bash\n# 见 kb/demo/techniques/99-ghost.md\n```\n")
        self.assertTrue(report["ok"], report["drifts"])
        self.assertEqual(report["paths_checked"], 0)

    def test_fence_skip_is_counted_as_an_exemption(self) -> None:
        """F3：围栏跳过原先**静默**，而 docstring 写着"豁免全量打印"——两句话对不上。

        判据不是"它跳过了"（上面那条已证），而是"**这次跳过被报出来了**"。
        """
        report = self._run("```bash\n# 见 kb/demo/techniques/99-ghost.md\n```\n")
        fence = [e for e in report["exemptions"] if e["reason"] == "in_fence"]
        self.assertEqual(len(fence), 1, "in_fence 必须是显式豁免项之一")
        self.assertEqual(fence[0]["hits"], 1, "围栏内跳过 1 行，计数应为 1")

    def test_fence_skip_count_is_measured_not_constant(self) -> None:
        """计数必须是真数出来的——写死成 1 的话上面那条就成了装饰。"""
        report = self._run("```bash\nline1\nline2\nline3\n```\n")
        fence = [e for e in report["exemptions"] if e["reason"] == "in_fence"][0]
        self.assertEqual(fence["hits"], 3)

    def test_entering_fences_would_report_them(self) -> None:
        """证伪那条豁免**不是装饰**：关掉跳过，围栏里的坏引用就该报出来。

        不进入围栏是有意的（围栏里是示例与命令，路径属于读者环境），
        所以这里钉的是"这条豁免确实在挡东西"，而不是"它挡了什么具体内容"。
        """
        source = Path(check_doc_refs.__file__).read_text(encoding="utf-8")
        patched, count = re.subn(
            r"(\n\s*)if in_fence:", r"\1if in_fence and False:", source, count=1
        )
        self.assertEqual(count, 1, "找不到围栏跳过的那一行，判据会空转")
        document = "```text\n见 `kb/demo/techniques/99-ghost.md` 一节。\n```\n"
        doc = self.root / "README.md"
        doc.write_text(document, encoding="utf-8", newline="\n")
        check_doc_refs._ANCHOR_CACHE.clear()

        # 沙箱内执行"进围栏"版本：ROOT 指向同一个沙箱
        namespace = {"__name__": "patched", "__file__": str(Path(check_doc_refs.__file__))}
        patched = patched.replace(
            "ROOT = Path(__file__).resolve().parents[2]", f'ROOT = Path(r"{self.root}")'
        )
        exec(compile(patched, "patched", "exec"), namespace)
        report = namespace["run"]()
        kinds = {drift["kind"] for drift in report["drifts"]}
        self.assertIn("path_missing", kinds, "关掉围栏豁免后，围栏内的坏引用应当被报出来")


class BareFilenameTests(_SandboxCase):
    """F2：裸文件名（无 `/`）原先被**整类**判成 `not_a_path` 放行。

    漏的正是 F1——`create-py-script.md` / `create-js-script.md` 这类**悬空的真引用**，
    它们"无斜杠 + 已知后缀"，形状与读者的示例名一模一样。
    现在的判据：**能解析到就通过；解析不到就必须在显式表里**。
    """

    def test_resolvable_bare_name_passes(self) -> None:
        self._write("kb/demo/note.md", "# 笔记\n")
        self._write("README.md", "见 `note.md`。\n")
        report = run()
        self.assertTrue(report["ok"], report["drifts"])

    def test_bare_filename_is_counted_as_checked(self) -> None:
        """回归判据：裸名现在**真的进了校验**（此前整类豁免，不计数）。

        带斜杠的与裸的都要计数——若裸名又退回 `not_a_path`，这里会掉成 1。
        """
        self._write("kb/demo/note.md", "# 笔记\n")
        self._write("README.md", "见 `kb/demo/note.md` 与 `note.md`。\n")
        report = run()
        self.assertEqual(report["paths_checked"], 2)

    def test_dangling_bare_name_is_reported(self) -> None:
        """F1 类：悬空的裸文件名必须报 `path_missing`，不能靠形状放过。"""
        self._write("README.md", "见 `create-py-script.md`。\n")
        report = run()
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "path_missing")
        self.assertIn("create-py-script.md", report["drifts"][0]["detail"])

    def test_untracked_dirs_are_not_searched_for_bare_names(self) -> None:
        """本地产物目录**不参与**「仓库里有没有这个名字」的判断。

        这里曾经只剪 `tmp/`，而 `UNTRACKED_PREFIXES` 有六项——**同一份名单存在
        两处且不一致**。于是 `exports/` 下的 `plan.json` 让**本地**解析成功，
        而干净克隆里没有这个文件：**本地绿、CI 红**。
        现在名单从 `UNTRACKED_PREFIXES` 派生，任意一个本地产物目录都不该被搜到。
        """
        for prefix in check_doc_refs.UNTRACKED_PREFIXES:
            self._write(f"{prefix}probe_name.py", "x\n")
        self._write("README.md", "见 `probe_name.py`。\n")
        report = run()
        self.assertFalse(
            report["ok"], "本地产物目录里的同名文件不该让裸文件名解析成功"
        )

    def test_tracked_dir_is_still_searched_for_bare_names(self) -> None:
        """对照组：正常目录（`kb/`）里的同名文件**必须**能被解析到。

        没有这一条，把索引整个清空也能让上面那条通过。
        """
        self._write("kb/probe_name.py", "x\n")
        self._write("README.md", "见 `probe_name.py`。\n")
        report = run()
        self.assertTrue(report["ok"], report["drifts"])

    def test_suffix_only_token_is_exempt(self) -> None:
        """`.js` 指的是"这类文件"，不是某个文件——无从校验存在性。"""
        self._write("README.md", "产物是 `.js` 或 `.py`。\n")
        report = run()
        self.assertTrue(report["ok"], report["drifts"])
        reasons = {entry["reason"]: entry["hits"] for entry in report["exemptions"]}
        self.assertEqual(reasons["bare_suffix_only"], 2)

    def test_explicit_example_name_is_exempt(self) -> None:
        """显式表里的示例名放行，且**理由被打印**（可审计的排除不是漏洞）。"""
        self._write("README.md", "把你的输入命名为 `中视频.py`。\n")
        report = run()
        self.assertTrue(report["ok"], report["drifts"])
        reasons = {entry["reason"]: entry["hits"] for entry in report["exemptions"]}
        self.assertEqual(reasons["bare_example_name"], 1)

    def test_exemption_table_is_consulted_not_a_blanket(self) -> None:
        """证伪"裸名一律放行"：表外的悬空裸名照报，表内的才放行。

        两条判据必须同时成立，否则表就成了摆设。
        """
        self._write("README.md", "`中视频.py` 放行，`ghost-nowhere.py` 不放行。\n")
        report = run()
        self.assertFalse(report["ok"])
        self.assertEqual(len(report["drifts"]), 1)
        self.assertIn("ghost-nowhere.py", report["drifts"][0]["detail"])

    def test_doc_inside_local_job_is_exempt(self) -> None:
        """`projects/<作业>/` 里的文档讲的是作业内文件，作业目录不进版本库。"""
        self._write("projects/20260101-demo/job-notes.md", "产物是 `whatever-step.py`。\n")
        report = run()
        self.assertTrue(report["ok"], report["drifts"])
        reasons = {entry["reason"]: entry["hits"] for entry in report["exemptions"]}
        self.assertEqual(reasons["inside_local_job"], 1)

    def test_job_readme_is_not_treated_as_a_local_job(self) -> None:
        """`projects/README.md` 是**仓库文档**，不是作业内文档——豁免不能误伤它。"""
        self._write("projects/README.md", "见 `ghost-index.py`。\n")
        report = run()
        self.assertFalse(report["ok"], "作业区 README 里的悬空裸名应当照报")
        self.assertEqual(report["drifts"][0]["kind"], "path_missing")


class UpstreamDocDeclarationTests(unittest.TestCase):
    """`UPSTREAM_REFERENCE_DOCS` 是**文档级**豁免，代价最大，所以它自己必须被钉住。

    这组判据打在**真仓库**上（用 `_REAL_ROOT` 而非模块 `ROOT`，避免被别的用例猴补影响）。
    """

    def test_declared_upstream_docs_exist(self) -> None:
        self.assertTrue(check_doc_refs.UPSTREAM_REFERENCE_DOCS, "豁免表为空则判据空转")
        for relative in sorted(check_doc_refs.UPSTREAM_REFERENCE_DOCS):
            path = _REAL_ROOT / relative
            self.assertTrue(
                path.is_file(),
                f"豁免指向的文档不存在了：{relative}——文档改名后豁免已静默失效",
            )

    def test_declared_upstream_doc_is_actually_scanned(self) -> None:
        """豁免文档必须真的在扫描面里，否则这条豁免永远用不上（等于没有）。"""
        original = check_doc_refs.ROOT
        check_doc_refs.ROOT = _REAL_ROOT
        try:
            scanned = {
                path.relative_to(_REAL_ROOT).as_posix() for path in check_doc_refs._iter_docs()
            }
        finally:
            check_doc_refs.ROOT = original
        for relative in sorted(check_doc_refs.UPSTREAM_REFERENCE_DOCS):
            self.assertIn(relative, scanned, f"{relative} 不在扫描面里，豁免是空转的")


class UpstreamDocExemptionTests(_SandboxCase):
    """豁免是**文档级语境**：只对那几份文档生效，不是按文件名放开。"""

    def test_bare_name_inside_upstream_doc_is_exempt(self) -> None:
        self._write("docs/upstream-absorption.md", "上游切片 `ad-removal.md` 未吸收。\n")
        report = run()
        self.assertTrue(report["ok"], report["drifts"])
        reasons = {entry["reason"]: entry["hits"] for entry in report["exemptions"]}
        self.assertEqual(reasons["upstream_reference_doc"], 1)

    def test_same_name_outside_upstream_doc_is_reported(self) -> None:
        """对照：同一句放在别处文档里照报——否则豁免就是"按文件名"而不是"按语境"。"""
        self._write("docs/other.md", "上游切片 `ad-removal.md` 未吸收。\n")
        report = run()
        self.assertFalse(report["ok"])
        self.assertEqual(report["drifts"][0]["kind"], "path_missing")


class ExemptionHygieneTests(unittest.TestCase):
    def test_every_exemption_states_a_reason(self) -> None:
        self.assertTrue(EXEMPTIONS)
        for reason, why in EXEMPTIONS:
            self.assertTrue(reason)
            self.assertGreater(len(why), 10, f"豁免 {reason} 的理由太短，等于没写")

    def test_every_bare_name_exemption_states_a_reason(self) -> None:
        table = check_doc_refs.BARE_NAME_EXEMPTIONS
        self.assertTrue(table, "豁免表空了，裸文件名判据会立刻开始误报")
        for name, why in table.items():
            with self.subTest(name=name):
                self.assertGreater(len(why), 10, f"豁免 {name} 的理由太短，等于没写")

    def test_bare_name_exemptions_are_not_tracked_files(self) -> None:
        """豁免的语义是「**本仓库不拥有**」，所以这些名字不该被 git 跟踪。

        防的是「豁免变成逃生门」：把本仓库**真有**的文件塞进豁免表，
        引用写错就被永久掩盖。判据用 `git ls-files` 而不是 `Path.exists()`——
        后者会被 gitignore 的文件喂饱，在本地与干净克隆里给出两个答案。
        """
        tracked = _tracked_basenames()
        self.assertIsNotNone(
            tracked, "git 不可用——这条判据需要 git，不能静默跳过（跳过与通过要区分）"
        )
        for name in check_doc_refs.BARE_NAME_EXEMPTIONS:
            with self.subTest(name=name):
                self.assertNotIn(
                    name,
                    tracked,
                    f"{name} 被 git 跟踪，说明本仓库拥有它，不该进豁免表",
                )

    def test_report_prints_exemptions_with_hit_counts(self) -> None:
        report = run()
        reasons = {entry["reason"] for entry in report["exemptions"]}
        self.assertEqual(reasons, {reason for reason, _ in EXEMPTIONS})


class RealRepositoryTests(unittest.TestCase):
    def test_repository_references_all_resolve(self) -> None:
        report = run()
        self.assertTrue(
            report["ok"],
            "文档引用已断链：" + json.dumps(report["drifts"], ensure_ascii=False),
        )
        self.assertGreater(report["links_checked"], 20, "校验面太窄，守卫会形同虚设")
        self.assertGreater(report["paths_checked"], 40, "校验面太窄，守卫会形同虚设")

    def test_json_mode_keeps_output_parsable(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            check_doc_refs.main(["--json"])
        json.loads(stream.getvalue())


if __name__ == "__main__":
    unittest.main()
