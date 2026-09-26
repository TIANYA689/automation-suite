"""第三方脚本静态拆解**引擎**的离线测试。

覆盖：可读性分类、能力维度与风险规则、复用分档、扫描范围与"没材料"的表述、CLI。

夹具与沙箱基类在 `_teardown_support.py`；散文区间（`text_spans.py`）的用例在
`test_text_spans.py`，呈现层（`teardown_render.py`）的在 `test_teardown_render.py`。
**一个被测模块配一个测试文件**——拆分判据是变更轴，不是行数。

四条最要紧的断言：

1. **工具绝不执行目标文件**。诱饵脚本在模块级写文件并 `raise SystemExit`——
   一旦被导入或 exec，测试会立刻以两种方式之一失败（副作用文件出现 / SystemExit 逃逸）。
   这是本工具唯一的硬安全承诺，所以要用**能证伪**的方式钉住，而不是靠注释声明。
2. **凭据类命中不落片段**。报告会被贴进对话、写进笔记；片段里带真值，
   泄露就发生在"检查"这个动作里。
3. **"只在不可读文件里出现" ≠ "值得复用"**。压缩/混淆代码里的命中是信号不是范本。
4. **"没材料"与"没命中"分开报**。空目录不是"这个脚本没有能力"。

零第三方依赖，可被 scripts/misc/run_offline_tests.py 直接发现。
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

from _teardown_support import (  # noqa: E402  —— 必须最先导入：它负责把 scripts/misc 放进 sys.path
    DECOY_PY,
    MINIFIED_JS,
    OBFUSCATED_JS,
    OPAQUE,
    READABLE_PY,
    RISKY_PY,
    SECRET_PY,
    SYNTAX_ERROR_PY,
    _SANDBOX,
    SandboxCase,
    _write,
)
from script_teardown import (  # noqa: E402
    analyze,
    classify,
    main,
    mask_snippet,
    scan_delivery,
)
from teardown_render import render  # noqa: E402
from teardown_rules import DEFAULT_EXTENSIONS, FEATURE_BY_ID, TIERS  # noqa: E402

# ---------------------------------------------------------------- 分类


class TestClassification(SandboxCase):
    def test_readable_python(self):
        result = classify(READABLE_PY, "signin.py", ".py", True)
        self.assertEqual(result["kind"], "readable")
        self.assertEqual(result["language"], "python")
        self.assertTrue(result["why"])

    def test_minified_single_long_line(self):
        result = classify(MINIFIED_JS, "app.js", ".js", True)
        self.assertEqual(result["kind"], "minified")

    def test_bundle_naming_is_minified(self):
        result = classify("var a=1;\n", "vendor.bundle.js", ".js", True)
        self.assertEqual(result["kind"], "minified")

    def test_obfuscated_identifier_pool(self):
        result = classify(OBFUSCATED_JS, "guard.js", ".js", True)
        self.assertEqual(result["kind"], "obfuscated")

    def test_vendor_directory(self):
        result = classify("function f(){return 1;}\n", "vendor/lib/a.js", ".js", True)
        self.assertEqual(result["kind"], "vendor")

    def test_obfuscated_beats_vendor(self):
        # 分类优先级：一个放在 vendor 里的混淆文件，报的是"混淆"——
        # 因为"它是别人交付的库"这件事，不足以说明"它没有隐藏规则"。
        result = classify(OBFUSCATED_JS, "vendor/lib/a.js", ".js", True)
        self.assertEqual(result["kind"], "obfuscated")

    def test_unreadable_is_not_readable(self):
        result = classify("", "a.py", ".py", False)
        self.assertEqual(result["kind"], "unreadable")
        self.assertEqual(result["confidence"], "high")

    def test_classification_always_carries_why(self):
        for text, name in ((READABLE_PY, "a.py"), (MINIFIED_JS, "a.js"), (OBFUSCATED_JS, "a.js")):
            with self.subTest(name=name):
                self.assertTrue(classify(text, name, Path(name).suffix, True)["why"])


# ---------------------------------------------------------------- 能力与风险


class TestFeatureDetection(SandboxCase):
    def setUp(self):
        self.directory = self.case_dir("features")
        _write(self.directory, "signin.py", READABLE_PY)
        self.report = analyze([self.directory])

    def _bucket(self, feature_id: str) -> dict:
        for bucket in self.report["features"]:
            if bucket["id"] == feature_id:
                return bucket
        self.fail(f"未命中维度 {feature_id}")

    def test_core_dimensions_are_detected(self):
        for feature_id in ("config", "env", "accounts", "request", "timeout", "retry", "proxy", "mask"):
            with self.subTest(feature_id=feature_id):
                self._bucket(feature_id)

    def test_hit_carries_line_number(self):
        hit = self._bucket("config")["hits"][0]
        self.assertEqual(hit["file"], "signin.py")
        self.assertGreater(hit["line"], 1)

    def test_line_number_points_at_the_real_line(self):
        # 行号是本工具唯一能被逐条复核的证据，写错了整张能力矩阵就不可信。
        lines = READABLE_PY.splitlines()
        hit = self._bucket("retry")["hits"][0]
        self.assertIn("MAX_RETRIES", lines[hit["line"] - 1])

    def test_pattern_ref_is_present(self):
        self.assertIn("PY-P9", self._bucket("config")["pattern_ref"])

    def test_delivery_files_are_detected_by_listing_not_by_source(self):
        # `^#\s+\S` 那条源码正则曾把每个带注释的 Python 文件都判成"随附文档"。
        # 配套文件的证据在目录清单里，不在代码文本里。
        # 用独立子目录：共享 setUp 的目录会被这条用例写入 README，
        # 污染下一条"没有配套文件"的断言（测试顺序是字典序，会真的踩到）。
        isolated = self.case_dir("delivery")
        _write(isolated, "signin.py", READABLE_PY)
        _write(isolated, "README.md", "# 示例交付\n")
        _write(isolated, ".env.example", "APP_AUTH=\n")
        report = analyze([isolated])
        ids = {bucket["id"] for bucket in report["features"]}
        self.assertIn("readme", ids)
        self.assertIn("env_example", ids)
        self.assertNotIn("readme", {item["id"] for item in report["gaps"]})

    def test_no_delivery_files_means_no_delivery_bucket(self):
        self.assertNotIn("readme", {bucket["id"] for bucket in self.report["features"]})
        self.assertNotIn("env_example", {bucket["id"] for bucket in self.report["features"]})

    def test_scan_delivery_does_not_recurse_into_noise_dirs(self):
        isolated = self.case_dir("delivery_noise")
        _write(isolated, "node_modules/pkg/package.json", "{}\n")
        found = scan_delivery([isolated])
        self.assertNotIn("deps", {bucket["id"] for bucket in found})


class TestParseFailureDisclosure(SandboxCase):
    """「读得出」与「解析得了」是两件事——报告必须把它分开说。

    实测原形：雨云脚本第 8 行是一句裸 emoji 说明（`🔑 雨云邀请...`），
    `ast.parse` 当场失败。文件仍被判"可读"，但符号表为空、
    文档字符串也没参与去散文过滤。报告不写出来，读者会把"没有结构"
    当成"这个脚本就是没结构"。
    """

    BROKEN_PY = (
        '"""模块说明：这里提到 接码 与 recaptcha，但代码里没有。"""\n'
        "\n"
        "🔑 邀请链接：https://example.com/abc\n"
        "\n"
        "\n"
        "def main():\n"
        "    return 1\n"
    )

    def test_syntax_error_is_marked_on_the_record(self):
        directory = self.case_dir("broken")
        _write(directory, "broken.py", self.BROKEN_PY)
        report = analyze([directory])
        self.assertIs(report["files"][0]["parse_ok"], False)

    def test_syntax_error_is_disclosed_in_notes(self):
        directory = self.case_dir("broken_note")
        _write(directory, "broken.py", self.BROKEN_PY)
        report = analyze([directory])
        self.assertTrue(
            any("语法解析失败" in note for note in report["notes"]),
            "解析失败必须出现在提示里，否则「材料不全」会被读成「没有结构」",
        )

    def test_syntax_error_is_visible_in_the_rendered_report(self):
        directory = self.case_dir("broken_render")
        _write(directory, "broken.py", self.BROKEN_PY)
        self.assertIn("语法解析失败", render(analyze([directory])))

    def test_parse_failure_means_docstrings_were_not_filtered(self):
        # 这一条是"解析失败会带来什么后果"的说明书：文档字符串里的关键词
        # 会因为拿不到语法树而漏过滤，于是**误报变多**。
        # 钉住它是为了让这个后果可见——不是认可它。
        directory = self.case_dir("broken_leak")
        _write(directory, "broken.py", self.BROKEN_PY)
        report = analyze([directory])
        self.assertIn("captcha", {bucket["id"] for bucket in report["features"]})

    def test_healthy_file_is_not_flagged(self):
        directory = self.case_dir("healthy")
        _write(directory, "ok.py", "def main():\n    return 1\n")
        report = analyze([directory])
        self.assertIs(report["files"][0]["parse_ok"], True)
        self.assertFalse(any("语法解析失败" in note for note in report["notes"]))


class TestOpaqueMaterialDisclosure(SandboxCase):
    """「读了但看不进去」必须说出来——它和「没材料」「没命中」是三件事。

    实测原形（第二轮真用）：本地样本目录里那个 143 KB 的 JS 是个自解密脚本，
    外层几十行 `aes256GcmDecrypt` + 140 KB 密文。26 个维度对它命中 0 个，
    而报告**一个字都不说**——读者会把"关键词在密文里"读成"它没有这个能力"。
    这是记忆里「静默失效」的又一形态：工具没错，是没去那一类材料里看。
    """

    def _notes(self, name: str, text: str) -> list[str]:
        directory = self.case_dir(f"opaque_{name}")
        _write(directory, name, text)
        return analyze([directory])["notes"]

    def test_dominant_single_line_is_reported_as_packed(self):
        blob = "A" * 3000
        notes = self._notes("packed.js", "const k = 1;\n" + blob + "\n")
        self.assertTrue(any("加密 / 打包载荷" in note for note in notes), notes)

    def test_small_minified_file_is_not_called_packed(self):
        # 普通的压缩产物**美化一下就还原了**，不该被说成密文——
        # 那会把"去美化"说成"去解密"，把人引到错的路子上。
        notes = self._notes(
            "app.min.js", "var a=1," + ",".join(f"v{i}={i}" for i in range(200))
        )
        self.assertFalse(any("打包载荷" in note for note in notes), notes)


class TestRisks(SandboxCase):
    def setUp(self):
        self.directory = self.case_dir("risks")
        _write(self.directory, "leak.py", SECRET_PY)
        _write(self.directory, "risky.py", RISKY_PY)
        self.report = analyze([self.directory])

    def _risk(self, risk_id: str) -> dict:
        for risk in self.report["risks"]:
            if risk["id"] == risk_id:
                return risk
        self.fail(f"未命中风险 {risk_id}")

    def test_hardcoded_secret_is_refused(self):
        self.assertEqual(self._risk("hardcoded_secret")["tier"], "refuse")

    def test_hardcoded_secret_carries_no_snippet(self):
        # 报告会被贴进对话；片段里带真值，泄露就发生在"检查"这个动作里。
        self.assertEqual(self._risk("hardcoded_secret")["snippet"], "")

    def test_secret_value_absent_from_every_output(self):
        payload = json.dumps(self.report, ensure_ascii=False)
        self.assertNotIn("changeme-changeme", payload)
        self.assertNotIn("changeme-changeme", render(self.report))

    def test_bare_except_is_caution_not_refuse(self):
        self.assertEqual(self._risk("bare_except")["tier"], "caution")

    def test_unbounded_loop_is_caution(self):
        self.assertEqual(self._risk("unbounded_loop")["tier"], "caution")

    def test_refused_risks_land_in_the_refuse_tier(self):
        labels = {item["id"] for item in self.report["reuse"]["refuse"]}
        self.assertIn("hardcoded_secret", labels)

    def test_caution_risks_do_not_enter_the_reuse_lists(self):
        for tier in TIERS:
            self.assertNotIn("bare_except", {item["id"] for item in self.report["reuse"][tier]})


# ---------------------------------------------------------------- 复用分档


class TestReuseTiers(SandboxCase):
    def setUp(self):
        self.directory = self.case_dir("reuse")
        _write(self.directory, "signin.py", READABLE_PY)
        _write(self.directory, "obfuscated.js", OBFUSCATED_JS)
        self.report = analyze([self.directory])

    def test_tiers_are_the_four_declared_ones(self):
        self.assertEqual(set(self.report["reuse"]), set(TIERS))

    def test_direct_tier_holds_stable_dimensions(self):
        labels = {item["id"] for item in self.report["reuse"]["direct"]}
        self.assertIn("config", labels)
        self.assertIn("timeout", labels)

    def test_borrow_tier_holds_semantics_to_rewrite(self):
        labels = {item["id"] for item in self.report["reuse"]["borrow"]}
        self.assertIn("login", labels)

    def test_feature_seen_only_in_obfuscated_code_is_not_a_candidate(self):
        # `console.log` 只出现在混淆文件里 → 是信号，不是范本。
        only_obfuscated = self.case_dir("only_obfuscated")
        _write(only_obfuscated, "guard.js", OBFUSCATED_JS)
        report = analyze([only_obfuscated])
        self.assertIn("logging", {item["id"] for item in report["non_reference"]})
        for tier in TIERS:
            self.assertNotIn("logging", {item["id"] for item in report["reuse"][tier]})

    def test_preferred_hit_comes_from_a_readable_file(self):
        bucket = next(item for item in self.report["features"] if item["id"] == "logging")
        self.assertEqual(bucket["preferred"]["file"], "signin.py")

    def test_candidate_carries_its_readable_files(self):
        bucket = next(item for item in self.report["features"] if item["id"] == "retry")
        self.assertEqual(bucket["readable_files"], ["signin.py"])

    def test_gaps_are_dimensions_never_seen(self):
        gaps = {item["id"] for item in self.report["gaps"]}
        self.assertIn("notify", gaps)
        self.assertNotIn("config", gaps)

    def test_every_feature_is_classified_once(self):
        buckets = {item["id"] for item in self.report["features"]}
        for feature_id in FEATURE_BY_ID:
            if feature_id in buckets:
                continue
            self.assertIn(feature_id, {item["id"] for item in self.report["gaps"]})


# ---------------------------------------------------------------- 不执行目标


class TestNeverExecutesTargets(SandboxCase):
    """本工具唯一的硬安全承诺，用可证伪的方式钉住。"""

    def test_decoy_side_effect_never_happens(self):
        directory = self.case_dir("decoy")
        decoy = _write(directory, "decoy.py", DECOY_PY)
        report = analyze([directory])
        self.assertFalse(decoy.with_suffix(".executed").exists())
        self.assertEqual(report["counts"]["files"], 1)

    def test_decoy_is_still_analyzed(self):
        # 不执行 ≠ 不分析：跳过它会让"没执行"变成"没看见"，那是另一种失败。
        directory = self.case_dir("decoy_analyzed")
        _write(directory, "decoy.py", DECOY_PY)
        report = analyze([directory])
        self.assertEqual(report["files"][0]["parse_ok"], True)

    def test_syntax_error_does_not_crash_and_is_reported(self):
        directory = self.case_dir("broken")
        _write(directory, "broken.py", SYNTAX_ERROR_PY)
        report = analyze([directory])
        self.assertEqual(report["counts"]["files"], 1)
        self.assertEqual(report["files"][0]["parse_ok"], False)
        self.assertEqual(report["files"][0]["symbols"], [])

    def test_non_utf8_file_is_unreadable_not_a_crash(self):
        directory = self.case_dir("binary")
        (directory / "blob.py").write_bytes(b"\xff\xfe\x00\x01\x02")
        report = analyze([directory])
        self.assertEqual(report["counts"]["unreadable"], 1)
        self.assertTrue(any("无结论" in note for note in report["notes"]))

    def test_disclosure_states_no_execution(self):
        report = analyze([self.case_dir("decoy")])
        self.assertIn("未执行", report["disclosure"])


# ---------------------------------------------------------------- 掩码


class TestMasking(unittest.TestCase):
    def test_long_opaque_run_is_masked(self):
        out = mask_snippet(OPAQUE)
        self.assertNotIn(OPAQUE, out)
        self.assertIn("len=36", out)

    def test_identifier_chain_survives(self):
        code = 'session.request(method, url, timeout=15)'
        self.assertEqual(mask_snippet(code), code)

    def test_url_survives(self):
        url = "https://example.com/api/checkin"
        self.assertIn(url, mask_snippet(url))

    def test_email_is_masked(self):
        self.assertIn("<email>", mask_snippet("contact demo@example.com now"))

    def test_phone_is_masked(self):
        self.assertIn("<phone>", mask_snippet("mobile 13800000000 end"))

    def test_short_run_survives(self):
        self.assertEqual(mask_snippet("aB3"), "aB3")

    def test_newlines_collapse(self):
        self.assertNotIn("\n", mask_snippet("a\nb"))


# ---------------------------------------------------------------- 扫描范围


class TestScanScope(SandboxCase):
    def test_noise_dirs_are_skipped_and_counted(self):
        directory = self.case_dir("noise")
        _write(directory, "app.py", READABLE_PY)
        _write(directory, "node_modules/x.js", MINIFIED_JS)
        _write(directory, "venv/lib/y.py", READABLE_PY)
        report = analyze([directory])
        self.assertEqual(report["counts"]["files"], 1)
        self.assertEqual(report["skipped"]["skipped_noise"], 2)

    def test_suffix_out_of_scope_is_counted(self):
        directory = self.case_dir("suffix")
        _write(directory, "app.py", READABLE_PY)
        _write(directory, "data.csv", "a,b\n")
        report = analyze([directory])
        self.assertEqual(report["skipped"]["skipped_suffix"], 1)

    def test_ext_widens_the_scope(self):
        # 用 `.rb`：它**不在** DEFAULT_EXTENSIONS 里。早先这条用例用了 `.ps1`，
        # 而 `.ps1` 本来就在默认表内（本套件交付 Windows 启动器），
        # 于是"默认扫不到"这个前提是假的，用例测的是自己写错的前提。
        directory = self.case_dir("ext")
        _write(directory, "runner.rb", "puts 'hi'\n")
        self.assertEqual(analyze([directory])["counts"]["files"], 0)
        widened = analyze([directory], extensions=(".rb",))
        self.assertEqual(widened["counts"]["files"], 1)
        self.assertEqual(widened["files"][0]["language"], "other")

    def test_max_files_truncates_and_discloses(self):
        directory = self.case_dir("maxfiles")
        for index in range(4):
            _write(directory, f"app{index}.py", READABLE_PY)
        report = analyze([directory], max_files=2)
        self.assertEqual(report["counts"]["files"], 2)
        self.assertEqual(report["skipped"]["truncated"], 2)
        self.assertTrue(any("max-files" in note for note in report["notes"]))

    def test_empty_target_says_no_material(self):
        directory = self.case_dir("empty")
        report = analyze([directory])
        self.assertEqual(report["counts"]["files"], 0)
        self.assertTrue(any("没有材料" in note for note in report["notes"]))

    def test_only_unreadable_files_is_disclosed(self):
        directory = self.case_dir("all_binary")
        (directory / "a.py").write_bytes(b"\xff\xfe\x00\x01")
        report = analyze([directory])
        self.assertTrue(any("可读" in note for note in report["notes"]))

    def test_default_extensions_cover_python_and_javascript(self):
        self.assertIn(".py", DEFAULT_EXTENSIONS)
        self.assertIn(".js", DEFAULT_EXTENSIONS)


# ---------------------------------------------------------------- CLI


class TestCli(SandboxCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def setUp(self):
        self.directory = self.case_dir("cli")
        _write(self.directory, "signin.py", READABLE_PY)

    def test_text_mode(self):
        code, out, _ = self._run([str(self.directory)])
        self.assertEqual(code, 0)
        self.assertIn("第三方脚本静态拆解", out)

    def test_json_mode_is_parseable(self):
        code, out, _ = self._run([str(self.directory), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["counts"]["files"], 1)
        self.assertIn("reuse", payload)

    def test_ascii_flag(self):
        code, out, _ = self._run([str(self.directory), "--ascii"])
        self.assertEqual(code, 0)
        self.assertNotIn("═", out)

    def test_no_snippets_clears_every_snippet(self):
        code, out, _ = self._run([str(self.directory), "--no-snippets", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        for bucket in payload["features"]:
            for hit in bucket["hits"]:
                self.assertEqual(hit["snippet"], "")

    def test_out_writes_the_report(self):
        target = self.directory / "report.json"
        code, _, _ = self._run([str(self.directory), "--out", str(target)])
        self.assertEqual(code, 0)
        self.assertIn("features", json.loads(target.read_text(encoding="utf-8")))

    def test_single_file_target_is_accepted(self):
        code, out, _ = self._run([str(self.directory / "signin.py"), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["counts"]["files"], 1)

    def test_missing_target_exits_2(self):
        code, _, err = self._run([str(_SANDBOX / "definitely-not-here")])
        self.assertEqual(code, 2)
        self.assertIn("目标不存在", err)

    def test_no_target_exits_2(self):
        with self.assertRaises(SystemExit) as caught:
            self._run([])
        self.assertEqual(caught.exception.code, 2)

    def test_bad_numeric_option_exits_2(self):
        with self.assertRaises(SystemExit) as caught:
            self._run([str(self.directory), "--top", "0"])
        self.assertEqual(caught.exception.code, 2)

    def test_documented_commands_work(self):
        for argv in (
            [str(self.directory)],
            [str(self.directory), "--json"],
            [str(self.directory), "--no-snippets"],
            [str(self.directory), "--ascii", "--top", "5"],
            [str(self.directory), "--ext", ".py"],
        ):
            with self.subTest(argv=argv):
                code, out, _ = self._run(argv)
                self.assertEqual(code, 0)
                self.assertTrue(out.strip())


if __name__ == "__main__":
    unittest.main()
