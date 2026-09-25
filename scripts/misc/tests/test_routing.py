"""路由索引与打分引擎的离线测试。

无需第三方依赖（不导入 mcp），可被 scripts/misc/run_offline_tests.py 直接发现。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from automation.routing import (  # noqa: E402
    build_index,
    describe_module,
    find_root,
    load_skill,
    route,
    run_module,
)
from automation.routing.index_builder import parse_frontmatter  # noqa: E402
from automation.routing.router import detect_languages, normalize, tokenize  # noqa: E402


class TestIndexBuilder(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = find_root()
        cls.index = build_index(cls.root)

    def test_root_found(self) -> None:
        self.assertTrue((self.root / "AI-USAGE.md").is_file())
        self.assertTrue((self.root / "skills").is_dir())

    def test_all_skills_indexed(self) -> None:
        names = {s["name"] for s in self.index["skills"]}
        # 以 routing.source.json 的声明为准，避免新增技能时测试变成硬编码计数器
        declared = set(json.loads((self.root / "routing.source.json").read_text(encoding="utf-8"))["skills"])
        self.assertEqual(names, declared)
        self.assertIn("automation-architect", names)
        self.assertIn("python-script-decryptor", names)
        self.assertIn("binary-symbol-recovery", names)
        self.assertIn("emulated-execution-debug", names)

    def test_no_index_diagnostics(self) -> None:
        diag = self.index["diagnostics"]
        for key in ("read_errors", "declared_missing_on_disk", "on_disk_missing_in_source"):
            self.assertEqual(diag[key], [], f"{key} 不应有内容")

    def test_module_categories_covered(self) -> None:
        categories = {m["category"] for m in self.index["modules"]}
        self.assertEqual(categories, {"接码", "过验证码", "邮箱"})
        self.assertEqual(self.index["diagnostics"]["module_categories_missing_in_source"], [])

    def test_fingerprint_stable_across_builds(self) -> None:
        again = build_index(self.root)
        self.assertEqual(self.index["fingerprint"], again["fingerprint"])

    def test_architect_is_router_role(self) -> None:
        by_name = {s["name"]: s for s in self.index["skills"]}
        self.assertEqual(by_name["automation-architect"]["role"], "router")
        self.assertEqual(by_name["knowledge-architect"]["invocation"], "manual-only")


class TestFrontmatter(unittest.TestCase):
    def test_flat_and_nested(self) -> None:
        text = '---\nname: demo\ndescription: "一段说明"\nmetadata:\n  version: "2.1.0"\n---\n# body\n'
        meta = parse_frontmatter(text)
        self.assertEqual(meta["name"], "demo")
        self.assertEqual(meta["description"], "一段说明")
        self.assertEqual(meta["metadata.version"], "2.1.0")

    def test_missing_frontmatter(self) -> None:
        self.assertEqual(parse_frontmatter("# no frontmatter"), {})


class TestNormalization(unittest.TestCase):
    def test_normalize_fullwidth_and_case(self) -> None:
        self.assertEqual(normalize("ＰＹＴＨＯＮ  脚本"), "python 脚本")

    def test_tokenize_drops_stopwords(self) -> None:
        tokens = tokenize("请帮我写一个 python 脚本")
        self.assertIn("python", tokens)
        self.assertNotIn("帮我", tokens)

    def test_detect_languages_requires_word_boundary(self) -> None:
        self.assertEqual(detect_languages("写个 node 脚本"), {"javascript"})
        self.assertEqual(detect_languages("python 脚本"), {"python"})
        self.assertEqual(detect_languages("json 解析"), set())


class TestRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index(find_root())

    CASES = [
        ("帮我写个 Python 青龙签到脚本，支持多账号", "automation-script-dev-py"),
        ("这个 js 脚本被混淆了，_0x 变量看不懂，帮我还原", "js-script-deobfuscator"),
        ("我要加密自己的 python 脚本再交付", "python-obfuscator-pro"),
        ("帮我解一下这个 python 壳，里面有 exec 和 base64", "python-script-decryptor"),
        ("加密这个 js 脚本防止别人看", "js-script-obfuscator"),
        ("抓包 HAR 分析一下接口再开发", "automation-architect"),
        ("把这次的经验沉淀进技能", "knowledge-architect"),
        ("写个 node 脚本适配 Surge 和 Loon", "automation-script-dev-js"),
        ("这个脚本要接码和收邮箱验证码", "automation-script-dev-py"),
    ]

    def test_primary_routing(self) -> None:
        for query, expected in self.CASES:
            with self.subTest(query=query):
                result = route(query, self.index)
                self.assertTrue(result["primary"], f"未产出主选：{query}")
                self.assertEqual(result["primary"][0]["skill"], expected)

    def test_language_disambiguates_obfuscators(self) -> None:
        py = route("加密这个 python 脚本", self.index)["primary"][0]["skill"]
        js = route("加密这个 js 脚本", self.index)["primary"][0]["skill"]
        self.assertEqual(py, "python-obfuscator-pro")
        self.assertEqual(js, "js-script-obfuscator")

    def test_evidence_present(self) -> None:
        result = route("青龙多账号签到", self.index)
        self.assertTrue(result["primary"][0]["evidence"])
        types = {hit["type"] for hit in result["primary"][0]["evidence"]}
        self.assertTrue(types & {"signal", "routing_rule", "language"})

    def test_module_suggestions(self) -> None:
        result = route("需要接码和邮箱收信", self.index)
        categories = {m["category"] for m in result["modules"]}
        self.assertEqual(categories, {"接码", "邮箱"})

    def test_empty_query_yields_no_primary(self) -> None:
        result = route("今天天气怎么样", self.index)
        self.assertEqual(result["primary"], [])

    def test_manual_only_flag_surfaces(self) -> None:
        result = route("把这次的经验沉淀进技能", self.index)
        self.assertEqual(result["primary"][0]["invocation"], "manual-only")
        self.assertIn("确认", result["next_step"])

    def test_load_skill_roundtrip(self) -> None:
        text = load_skill("automation-architect", self.index, find_root())
        self.assertIn("automation-architect", text)

    def test_load_skill_truncates_large_skill(self) -> None:
        text = load_skill("automation-script-dev-py", self.index, find_root(), max_chars=2000)
        self.assertIn("已截断", text)
        self.assertIn("automation-script-dev-py/SKILL.md", text)
        self.assertLess(len(text), 6000)

    def test_load_skill_small_skill_not_truncated(self) -> None:
        text = load_skill("python-obfuscator-pro", self.index, find_root())
        self.assertNotIn("已截断", text)

    def test_describe_module_is_read_only(self) -> None:
        detail = describe_module("24mail", self.index, find_root())
        self.assertIs(detail["executes_anything"], False)
        self.assertTrue(detail["entries"])
        self.assertIn("readme_excerpt", detail)
        self.assertEqual(detail["category"], "邮箱")

    def test_describe_unknown_module_raises(self) -> None:
        with self.assertRaises(KeyError):
            describe_module("no-such-module", self.index, find_root())

    def test_load_unknown_skill_raises(self) -> None:
        with self.assertRaises(KeyError):
            load_skill("not-a-skill", self.index, find_root())


def _make_root(tmp: Path, script_body: str, *, extra_entries: int = 0) -> tuple[Path, dict]:
    """在临时目录里造一个可执行模块，返回 (root, module)。"""
    module_dir = tmp / "tools" / "automation-modules" / "demo" / "hello"
    module_dir.mkdir(parents=True)
    main = module_dir / "hello.py"
    main.write_text(script_body, encoding="utf-8", newline="\n")
    entries = ["tools/automation-modules/demo/hello/hello.py"]
    for index in range(extra_entries):
        other = module_dir / f"other{index}.py"
        other.write_text("print('other')\n", encoding="utf-8", newline="\n")
        entries.append(f"tools/automation-modules/demo/hello/other{index}.py")
    module = {
        "category": "demo",
        "name": "hello",
        "path": "tools/automation-modules/demo/hello",
        "readme": "",
        "requirements": "",
        "entries": entries,
        "signals": [],
    }
    return tmp, module


def _exec_index(module: dict, **overrides) -> dict:
    execution = {
        "enabled": True,
        "default_dry_run": True,
        "allowlist": [],
        "timeout_seconds": 30,
        "max_output_chars": 1000,
        "audit_log": "exports/audit.jsonl",
    }
    execution.update(overrides)
    return {"skills": [], "modules": [module], "module_categories": {}, "routing_rules": [], "execution": execution}


class TestRunModuleGuardrails(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root, self.module = _make_root(
            Path(self._tmp.name),
            "import sys\nprint('hello', ' '.join(sys.argv[1:]))\n",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_refuses_when_not_allowlisted(self) -> None:
        result = run_module("hello", _exec_index(self.module), self.root)
        self.assertFalse(result["allowed"])
        self.assertFalse(result["executed"])
        self.assertIn("白名单", result["reason"])

    def test_refuses_when_execution_disabled(self) -> None:
        index = _exec_index(self.module, enabled=False, allowlist=["hello"])
        result = run_module("hello", index, self.root)
        self.assertFalse(result["allowed"])
        self.assertIn("关闭", result["reason"])

    def test_dry_run_is_default_and_does_not_execute(self) -> None:
        index = _exec_index(self.module, allowlist=["hello"])
        result = run_module("hello", index, self.root, args=["world"])
        self.assertTrue(result["allowed"])
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["executed"])
        self.assertIn("dry-run", result["reason"])
        self.assertEqual(result["exit_code"], None)
        self.assertEqual(result["stdout"], "")
        self.assertEqual(result["argv"][1], str(self.root / self.module["entries"][0]))
        self.assertEqual(result["argv"][2], "world")

    def test_executes_only_when_explicitly_requested(self) -> None:
        index = _exec_index(self.module, allowlist=["hello"])
        result = run_module("hello", index, self.root, args=["world"], dry_run=False)
        self.assertTrue(result["executed"])
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("hello world", result["stdout"])

    def test_unknown_module_refused(self) -> None:
        result = run_module("nope", _exec_index(self.module, allowlist=["nope"]), self.root)
        self.assertFalse(result["allowed"])
        self.assertIn("未知模块", result["reason"])

    def test_ambiguous_entry_requires_explicit_choice(self) -> None:
        root, module = _make_root(Path(self._tmp.name) / "second", "print('x')\n", extra_entries=1)
        index = _exec_index(module, allowlist=["hello"])
        result = run_module("hello", index, root)
        self.assertFalse(result["executed"])
        self.assertIn("多个入口", result["reason"])

    def test_explicit_entry_must_be_within_module(self) -> None:
        index = _exec_index(self.module, allowlist=["hello"])
        result = run_module("hello", index, self.root, entry="../../etc/passwd")
        self.assertFalse(result["executed"])
        self.assertIn("入口不在该模块", result["reason"])

    def test_non_string_args_rejected(self) -> None:
        index = _exec_index(self.module, allowlist=["hello"])
        result = run_module("hello", index, self.root, args=["ok", 42])
        self.assertFalse(result["executed"])
        self.assertIn("参数必须是字符串", result["reason"])

    def test_timeout_is_enforced(self) -> None:
        root, module = _make_root(Path(self._tmp.name) / "slow", "import time\ntime.sleep(10)\n")
        index = _exec_index(module, allowlist=["hello"])
        result = run_module("hello", index, root, dry_run=False, timeout=1)
        self.assertFalse(result["executed"])
        self.assertIn("超时", result["reason"])

    def test_audit_log_records_rejections_and_runs(self) -> None:
        index = _exec_index(self.module, allowlist=["hello"])
        run_module("hello", index, self.root)  # 通过白名单的 dry-run
        run_module("nope", index, self.root)  # 不在白名单，被拒
        log = self.root / "exports" / "audit.jsonl"
        self.assertTrue(log.is_file())
        lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("ts" in line and "module" in line for line in lines))
        self.assertEqual(lines[0]["module"], "hello")
        self.assertTrue(lines[0]["dry_run"])
        self.assertEqual(lines[1]["module"], "nope")
        self.assertFalse(lines[1]["allowed"])


if __name__ == "__main__":
    unittest.main()
