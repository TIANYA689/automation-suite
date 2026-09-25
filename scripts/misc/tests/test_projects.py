from __future__ import annotations

import atexit
import itertools
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "scripts"))

import check_projects  # noqa: E402
import new_project  # noqa: E402

# 在打补丁之前抓住真实模板：沙箱里要用它的内容，才能测到真实的占位符形态。
REAL_TEMPLATE = check_projects.PROJECTS_ROOT / "_template"

INDEX_DOC_TEMPLATE = """# 作业区

<!-- BEGIN: projects-index -->
（暂无作业）
<!-- END: projects-index -->
"""

# 整个模块共用一个沙箱：用例之间只新建几个小文件，不复制整棵模板树。
# 实测本机在 tmp/ 下 rmtree 一个**空**目录要 ~800ms（D 盘 + 实时防护），
# 所以热路径里一次 rmtree 都不能有——沙箱在进程退出时一次性删掉。
_STALE_AFTER_SECONDS = 3600


def _cleanup(target: Path) -> None:
    """删一棵树，**删不掉就留着，绝不把调用方带走**。

    实测踩到：整棵一次 `rmtree` 会被按「一次删了多少条」拦下（本机的工作区沙箱
    有一条 50 条的阈值，而一个沙箱有 ~425 条）。拦下的方式是 `SystemExit`——
    `ignore_errors=True` **挡不住它**，它只吞 `OSError`。

    于是自愈变成「一碰就死」：整轮测试以一个跟被测代码毫无关系的理由结束，
    报错还指向 `tmp/`。清理路径的职责是**善后**，不是判定——它删不掉时正确
    的动作是留着让下一次再试，而不是把调用方一起带走。

    刻意**不**改成「逐个子项删」：本机 rmtree 一个空目录就要 ~800ms（见文件头），
    而沙箱里有 ~40 个子项，逐项删会把一次删除变成几十次。宁可留着，不可变慢。
    """
    try:
        shutil.rmtree(target, ignore_errors=True)
    except SystemExit:
        pass


def fresh_sandbox() -> Path:
    """建沙箱，并顺手清掉过期的旧沙箱。

    `atexit` 只在**正常退出**时执行。进程被 kill（CI 取消、网络掉线、
    在终端里 Ctrl-C 到子进程）时它不跑，残留会一直累积——实测攒到过 17 个。
    所以这里补一道自愈：同前缀目录只由本模块创建，清掉一小时前的不会有误伤，
    并发跑测试时也碰不到对方（对方的沙箱是新的）。
    """
    tmp_root = ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    now = time.time()
    for stale in tmp_root.glob("projects-test-*"):
        try:
            age = now - stale.stat().st_mtime
        except OSError:
            continue
        if age > _STALE_AFTER_SECONDS:
            _cleanup(stale)
    return Path(tempfile.mkdtemp(dir=tmp_root, prefix="projects-test-"))


_SANDBOX = fresh_sandbox()
_SANDBOX_COUNTER = itertools.count()
atexit.register(_cleanup, _SANDBOX)


def seed_template(target: Path) -> None:
    """把真实模板逐文件写进沙箱。逐文件写，不做递归复制。"""
    target.mkdir(parents=True, exist_ok=True)
    for source in sorted(REAL_TEMPLATE.iterdir()):
        (target / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")


def valid_job(project: str = "20260925-example") -> dict:
    return {
        "schema_version": 1,
        "project": project,
        "slug": "example",
        "created_at": "2026-09-25",
        "goal": "从抓包生成签到脚本",
        "status": "CONTINUE",
        "capture": {
            "name": "capture.har",
            "sha256": "0" * 64,
            "entries": 123,
            "endpoints": 21,
            "hosts": 5,
        },
        "artifacts": ["plan.json"],
        "knowledge_returned": ["kb/automation/techniques/02-har-to-script.md"],
        "evidence": ["fixture.har：端点 21 → 21"],
        "dead_ends": [{"path": "复现签名算法", "reason": "抓包里没有签名参数"}],
        "open_questions": [],
        "next_actions": ["确认授权范围"],
        "updated_at": "2026-09-25",
    }


class SandboxCleanupTests(unittest.TestCase):
    """善后路径的判据：**它自己失败时，不能把调用方带走。**

    实测踩到：一次 `rmtree` 会被按「一次删了多少条」拦下，拦下的方式是
    `SystemExit`——而 `ignore_errors=True` 只吞 `OSError`。于是自愈变成
    「一碰就死」：整轮测试以一个跟被测代码毫无关系的理由结束。
    """

    def test_refused_delete_does_not_propagate(self) -> None:
        target = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, target, ignore_errors=True)

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise SystemExit(1)

        original = shutil.rmtree
        shutil.rmtree = refuse
        try:
            _cleanup(target)  # 不许抛
        finally:
            shutil.rmtree = original
        self.assertTrue(target.exists(), "被拒绝时应该原样留着，而不是留下半个目录")

    def test_normal_delete_still_removes_the_tree(self) -> None:
        target = Path(tempfile.mkdtemp())
        (target / "run0").mkdir()
        (target / "run0" / "job.json").write_text("{}", encoding="utf-8", newline="\n")
        _cleanup(target)
        self.assertFalse(target.exists())

    def test_missing_target_is_not_an_error(self) -> None:
        target = Path(tempfile.mkdtemp())
        shutil.rmtree(target)
        _cleanup(target)  # 已经不在了，也不许抛


class TemplateIntegrityTests(unittest.TestCase):
    """模板进版本库，所以它必须始终可校验通过——模板烂了，所有新作业跟着烂。"""

    def test_real_template_job_validates(self) -> None:
        path = check_projects.PROJECTS_ROOT / "_template" / "job.json"
        self.assertTrue(path.is_file(), "模板 job.json 不见了")
        self.assertEqual(check_projects.validate_job(path), [])

    def test_real_template_has_the_expected_files(self) -> None:
        template = check_projects.PROJECTS_ROOT / "_template"
        names = {path.name for path in template.iterdir()}
        self.assertEqual(names, {"job.json", "README.md", "findings.md", "links.md"})

    def test_real_index_doc_has_the_derived_block(self) -> None:
        text = check_projects.INDEX_DOC.read_text(encoding="utf-8")
        block, errors = check_projects.read_index_block(text)
        self.assertEqual(errors, [])
        self.assertIsNotNone(block)

    def test_real_index_matches_the_jobs(self) -> None:
        """索引是派生产物；仓库里它必须与 job.json 一致。"""
        self.assertEqual(check_projects.run()["errors"], [])


class PatchableTestCase(unittest.TestCase):
    """把作业区根换到 tmp 下的假仓库，避免测试污染真实目录。

    沙箱整个模块共用（见 _SANDBOX），每个用例只重建 `projects/` 这一层——
    它在 tmp 下，不在版本库里，也不会被任何校验器扫到。
    """

    def setUp(self) -> None:
        self.fake_root = _SANDBOX / f"run{next(_SANDBOX_COUNTER)}" / "projects"
        self.fake_root.mkdir(parents=True)
        seed_template(self.fake_root / "_template")
        self.index_doc = self.fake_root / "README.md"
        self.index_doc.write_text(INDEX_DOC_TEMPLATE, encoding="utf-8", newline="\n")

        self.saved = (
            check_projects.PROJECTS_ROOT,
            check_projects.INDEX_DOC,
            new_project.PROJECTS_ROOT,
            new_project.TEMPLATE_DIR,
        )
        check_projects.PROJECTS_ROOT = self.fake_root
        check_projects.INDEX_DOC = self.index_doc
        new_project.PROJECTS_ROOT = self.fake_root
        new_project.TEMPLATE_DIR = self.fake_root / "_template"

    def tearDown(self) -> None:
        (
            check_projects.PROJECTS_ROOT,
            check_projects.INDEX_DOC,
            new_project.PROJECTS_ROOT,
            new_project.TEMPLATE_DIR,
        ) = self.saved

    def write_job(self, job: dict, directory: str) -> Path:
        target = self.fake_root / directory
        target.mkdir(parents=True, exist_ok=True)
        path = target / "job.json"
        path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8", newline="\n")
        return path

    def error_kinds(self, job: dict, directory: str = "20260925-example") -> list[str]:
        path = self.write_job(job, directory)
        return check_projects.validate_job(path)


class JobSchemaTests(PatchableTestCase):
    def test_valid_job_passes(self) -> None:
        self.assertEqual(self.error_kinds(valid_job()), [])

    def test_wrong_schema_version_is_reported(self) -> None:
        job = valid_job()
        job["schema_version"] = 2
        self.assertTrue(any("schema_version" in e for e in self.error_kinds(job)))

    def test_project_must_equal_the_directory_name(self) -> None:
        job = valid_job()
        job["project"] = "something-else"
        self.assertTrue(any("目录名" in e for e in self.error_kinds(job)))

    def test_slug_must_be_lowercase_and_hyphenated(self) -> None:
        for bad in ("Bad_Slug", "UPPER", "-leading", "trailing-", "with space"):
            job = valid_job()
            job["slug"] = bad
            with self.subTest(slug=bad):
                self.assertTrue(any("slug" in e for e in self.error_kinds(job)))

    def test_goal_must_be_non_empty(self) -> None:
        job = valid_job()
        job["goal"] = "   "
        self.assertTrue(any("goal" in e for e in self.error_kinds(job)))

    def test_status_must_be_one_of_the_three_states(self) -> None:
        job = valid_job()
        job["status"] = "in_progress"
        self.assertTrue(any("status" in e for e in self.error_kinds(job)))

    def test_dates_must_be_iso(self) -> None:
        job = valid_job()
        job["created_at"] = "2026/09/25"
        self.assertTrue(any("created_at" in e for e in self.error_kinds(job)))

    def test_string_list_fields_reject_blank_entries(self) -> None:
        for field in check_projects.STRING_LIST_FIELDS:
            job = valid_job()
            job[field] = ["ok", "  "]
            with self.subTest(field=field):
                self.assertTrue(any(field in e for e in self.error_kinds(job)))

    def test_dead_ends_need_a_reason(self) -> None:
        job = valid_job()
        job["dead_ends"] = [{"path": "某条路"}]
        self.assertTrue(any("排除原因" in e for e in self.error_kinds(job)))

    def test_capture_sha256_must_be_hex64_when_present(self) -> None:
        job = valid_job()
        job["capture"]["sha256"] = "abc"
        self.assertTrue(any("sha256" in e for e in self.error_kinds(job)))

    def test_capture_sha256_may_be_empty(self) -> None:
        job = valid_job()
        job["capture"]["sha256"] = ""
        self.assertEqual(self.error_kinds(job), [])

    def test_capture_counters_must_be_non_negative_integers(self) -> None:
        job = valid_job()
        job["capture"]["endpoints"] = -1
        self.assertTrue(any("endpoints" in e for e in self.error_kinds(job)))

    def test_capture_name_must_be_non_empty(self) -> None:
        job = valid_job()
        job["capture"]["name"] = ""
        self.assertTrue(any("capture.name" in e for e in self.error_kinds(job)))

    def test_capture_may_be_a_list_of_captures(self) -> None:
        """一次作业常要同时用几份抓包（注册一份、注册+登录+实名一份）。"""
        job = valid_job()
        job["capture"] = [job["capture"], {**job["capture"], "name": "second.har"}]
        self.assertEqual(self.error_kinds(job), [])

    def test_capture_list_rejects_a_bad_member(self) -> None:
        job = valid_job()
        job["capture"] = [job["capture"], {**job["capture"], "sha256": "abc"}]
        self.assertTrue(any("capture[1]" in e for e in self.error_kinds(job)))

    def test_capture_must_not_be_an_empty_list(self) -> None:
        job = valid_job()
        job["capture"] = []
        self.assertTrue(any("空列表" in e for e in self.error_kinds(job)))

    def test_capture_rejects_a_string(self) -> None:
        job = valid_job()
        job["capture"] = "capture.har"
        self.assertTrue(any("必须是对象" in e for e in self.error_kinds(job)))

    def test_continue_requires_next_actions(self) -> None:
        job = valid_job()
        job["status"] = "CONTINUE"
        job["next_actions"] = []
        self.assertTrue(any("next_actions" in e for e in self.error_kinds(job)))

    def test_done_requires_evidence(self) -> None:
        job = valid_job()
        job["status"] = "DONE"
        job["evidence"] = []
        self.assertTrue(any("evidence" in e for e in self.error_kinds(job)))

    def test_exhausted_requires_dead_ends(self) -> None:
        job = valid_job()
        job["status"] = "EXHAUSTED"
        job["dead_ends"] = []
        self.assertTrue(any("dead_ends" in e for e in self.error_kinds(job)))

    def test_broken_json_is_reported_not_raised(self) -> None:
        target = self.fake_root / "20260925-broken"
        target.mkdir()
        path = target / "job.json"
        path.write_text("{not json", encoding="utf-8", newline="\n")
        self.assertTrue(any("invalid JSON" in e for e in check_projects.validate_job(path)))


class IndexTests(PatchableTestCase):
    def test_empty_index_renders_a_placeholder(self) -> None:
        self.assertEqual(check_projects.render_index(), check_projects.EMPTY_TABLE)

    def test_render_is_deterministic(self) -> None:
        self.write_job(valid_job(), "20260925-example")
        first = check_projects.render_index()
        second = check_projects.render_index()
        self.assertEqual(first, second)
        self.assertIn("20260925-example", first)

    def test_jobs_are_listed_newest_first(self) -> None:
        self.write_job(valid_job("20260101-older"), "20260101-older")
        self.write_job(valid_job("20261231-newer"), "20261231-newer")
        table = check_projects.render_index()
        self.assertLess(table.index("20261231-newer"), table.index("20260101-older"))

    def test_template_directory_is_not_a_job(self) -> None:
        self.assertNotIn("_template", check_projects.render_index())

    def test_multi_capture_row_shows_the_count_and_sums(self) -> None:
        job = valid_job()
        job["capture"] = [
            {"name": "a.har", "sha256": "", "entries": 11, "endpoints": 8, "hosts": 4},
            {"name": "b.har", "sha256": "", "entries": 149, "endpoints": 29, "hosts": 6},
        ]
        self.write_job(job, "20260925-example")
        table = check_projects.render_index()
        self.assertIn("2 份 / 160 条 / 37 端点", table)

    def test_single_capture_row_keeps_the_old_shape(self) -> None:
        self.write_job(valid_job(), "20260925-example")
        self.assertIn("123 条 / 21 端点", check_projects.render_index())

    def test_missing_markers_are_reported(self) -> None:
        block, errors = check_projects.read_index_block("# 没有标记\n")
        self.assertIsNone(block)
        self.assertTrue(errors)

    def test_stale_index_is_detected(self) -> None:
        self.write_job(valid_job(), "20260925-example")
        self.assertNotEqual(check_projects.run()["errors"], [])
        self.assertTrue(any("索引表与各作业" in e for e in check_projects.run()["errors"]))

    def test_rebuild_makes_the_check_pass(self) -> None:
        self.write_job(valid_job(), "20260925-example")
        check_projects.rebuild_index()
        self.assertEqual(check_projects.run()["errors"], [])

    def test_rebuild_is_idempotent(self) -> None:
        self.write_job(valid_job(), "20260925-example")
        first = check_projects.rebuild_index()
        second = check_projects.rebuild_index()
        self.assertEqual(first, second)


class NewProjectTests(PatchableTestCase):
    def test_parse_date_accepts_both_forms(self) -> None:
        self.assertEqual(new_project.parse_date("20260925"), "2026-09-25")
        self.assertEqual(new_project.parse_date("2026-09-25"), "2026-09-25")

    def test_parse_date_rejects_garbage(self) -> None:
        for bad in ("2026", "20261332", "yesterday", "2026-9-5"):
            with self.subTest(value=bad):
                with self.assertRaises(new_project.NewProjectError):
                    new_project.parse_date(bad)

    def test_rejects_a_bad_slug(self) -> None:
        for bad in ("Bad", "a_b", "-x", "x-", ""):
            with self.subTest(slug=bad):
                with self.assertRaises(new_project.NewProjectError):
                    new_project.create(bad, "2026-09-25", None, dry_run=True)

    def test_dry_run_writes_nothing(self) -> None:
        result = new_project.create("example", "2026-09-25", "目标", dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse((self.fake_root / "20260925-example").exists())

    def test_creates_a_job_that_passes_validation(self) -> None:
        new_project.create("example", "2026-09-25", "从抓包生成签到脚本", dry_run=False)
        target = self.fake_root / "20260925-example"
        self.assertTrue(target.is_dir())
        self.assertEqual(check_projects.validate_job(target / "job.json"), [])

    def test_created_job_is_filled_not_copied(self) -> None:
        new_project.create("example", "2026-09-25", "目标原文", dry_run=False)
        job = json.loads((self.fake_root / "20260925-example" / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["project"], "20260925-example")
        self.assertEqual(job["slug"], "example")
        self.assertEqual(job["goal"], "目标原文")
        self.assertEqual(job["created_at"], "2026-09-25")
        self.assertEqual(job["status"], "CONTINUE")
        self.assertEqual(job["capture"]["sha256"], "")
        self.assertEqual(job["capture"]["entries"], 0)
        self.assertEqual(job["artifacts"], [])
        self.assertEqual(job["dead_ends"], [])
        self.assertTrue(job["next_actions"], "CONTINUE 必须有下一步，占位也算")

    def test_markdown_placeholders_are_filled(self) -> None:
        new_project.create("example", "2026-09-25", None, dry_run=False)
        readme = (self.fake_root / "20260925-example" / "README.md").read_text(encoding="utf-8")
        self.assertIn("20260925-example", readme)
        self.assertNotIn("<日期>-<项目名>", readme)

    def test_creates_the_index_row_too(self) -> None:
        new_project.create("example", "2026-09-25", "目标", dry_run=False)
        self.assertEqual(check_projects.run()["errors"], [])
        self.assertIn("20260925-example", check_projects.INDEX_DOC.read_text(encoding="utf-8"))

    def test_refuses_to_overwrite(self) -> None:
        new_project.create("example", "2026-09-25", None, dry_run=False)
        with self.assertRaises(new_project.NewProjectError):
            new_project.create("example", "2026-09-25", None, dry_run=False)

    def test_goal_falls_back_to_the_placeholder(self) -> None:
        new_project.create("example", "2026-09-25", "   ", dry_run=False)
        job = json.loads((self.fake_root / "20260925-example" / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["goal"], new_project.GOAL_PLACEHOLDER)

    def test_main_returns_non_zero_on_bad_input(self) -> None:
        self.assertEqual(new_project.main(["Bad_Slug"]), 1)
        self.assertEqual(new_project.main(["ok-slug", "--date", "20260925", "--dry-run"]), 0)


class ReleaseCheckScopeTests(unittest.TestCase):
    """projects/ 是部分提交目录：索引与模板要照常检查，作业目录是本地产物。"""

    def setUp(self) -> None:
        import public_release_check

        self.check = public_release_check

    def test_tracked_part_is_scanned(self) -> None:
        for relative in ("projects/README.md", "projects/_template/job.json"):
            with self.subTest(path=relative):
                self.assertFalse(self.check.is_ignored(check_projects.ROOT / relative))

    def test_job_directories_are_ignored(self) -> None:
        for relative in (
            "projects/20260925-avalon-signin/job.json",
            "projects/20260925-avalon-signin/capture/x.har",
            "projects/20260925-avalon-signin/scripts/a.py",
        ):
            with self.subTest(path=relative):
                self.assertTrue(self.check.is_ignored(check_projects.ROOT / relative))

    def test_other_directories_are_unaffected(self) -> None:
        self.assertTrue(self.check.is_ignored(check_projects.ROOT / "cases/foo/state.json"))
        self.assertFalse(self.check.is_ignored(check_projects.ROOT / "scripts/misc/check_projects.py"))


if __name__ == "__main__":
    unittest.main()
