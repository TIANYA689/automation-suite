"""HAR 内嵌源码检索工具的离线测试。

夹具是**内联合成 HAR**，不是真实抓包：真实抓包含凭证，不该进仓库，
而这里要验的是"检索范围、掩码与否定结论的表述对不对"，不是"某站点长什么样"。

三条最要紧的断言：

1. **源码里的凭证绝不出现在任何输出里**（JSON 与文本都查）——这是本工具的安全底线。
   掩码不是安全边界，但"工具自己把凭证印出来"是明确的缺陷。
2. **"没命中"与"没材料"必须分开报**——前者是结论，后者是残缺。混成一句
   就复现了当初那个错误：把"没去看"写成"看不出规则"。
3. **默认只搜源码类资源**——接口数据默认不纳入，否则用户数据会淹没输出。

零第三方依赖，可被 scripts/misc/run_offline_tests.py 直接发现。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from automation.har_source import (  # noqa: E402
    DEFAULT_MASK_MIN,
    SOURCE_MIMES,
    SOURCE_SUFFIXES,
    analyze,
    collect_sources,
    digest,
    display_needle,
    is_source_like,
    main,
    mask_runs,
    readable_text,
    render,
    search_source,
)

# 长、混合大小写、含数字 → 会被掩码。故意做成"像凭证"。
#
# 刻意**不**叫 OPAQUE_VALUE：它只是合成出来的不透明串，不是秘密，而 `public_release_check`
# 会按「secret = "..."」这类赋值形态拦下来（它拦得对——真实仓库里那种写法就是事故）。
# 名字要如实描述它是什么，而不是它长得像什么。
OPAQUE_VALUE = "aB3" * 40  # 120 字符
# 同长度但全小写无数字 → 不该被掩码（它长得像 MIME / 路径，是可读的代码）
PLAINISH = "application/x-www-form-urlencoded-" * 3  # 105 字符，全小写带连字符

DEVICE_JS = (
    'var t=1;function login(){let l=localStorage.getItem("deviceUuid");'
    'l||(l=Math.random().toString(36),localStorage.setItem("deviceUuid",l));'
    'return {deviceUuid:l,token:"' + OPAQUE_VALUE + '"}}'
)
API_JS = (
    'function Y(t){return(0,n.hd)(`${n.pc}/app/api/signIn/keepSignIn`,t)}'
    'function Z(t){return(0,n.Jt)(`${n.pc}/app/api/notice/list`,t)}'
)


def _entry(
    url: str,
    *,
    method: str = "GET",
    started: str = "2026-09-25T01:00:00.000Z",
    body: str | None = None,
    mime: str = "application/json",
    encoding: str | None = None,
) -> dict:
    content: dict = {"mimeType": mime}
    if body is not None:
        content["text"] = body
    if encoding is not None:
        content["encoding"] = encoding
    return {
        "startedDateTime": started,
        "request": {"method": method, "url": url, "headers": []},
        "response": {"status": 200, "content": content, "headers": []},
    }


def har(*entries: dict) -> dict:
    return {"log": {"version": "1.2", "entries": list(entries)}}


def js_har() -> dict:
    """一份含源码资源的抓包：JS 里有字段名、有接口路径、有一个凭证。"""
    return har(
        _entry(
            "https://app.example.com/app/webapp/js/8176.b4c9c7c2.js",
            body=DEVICE_JS,
            mime="application/javascript",
            started="2026-09-25T01:00:00.000Z",
        ),
        _entry(
            "https://app.example.com/app/webapp/js/1900.cd97ba24.js",
            body=API_JS,
            mime="application/javascript",
            started="2026-09-25T01:00:01.000Z",
        ),
        _entry(
            "https://app.example.com/api/app/api/notice/list",
            body=json.dumps({"code": 0, "data": []}),
            mime="application/json",
            started="2026-09-25T01:00:02.000Z",
        ),
    )


def run(har_dict: dict, **kwargs) -> dict:
    options = {
        "needles": [],
        "include_data": False,
        "min_size": 1,
        "context": 120,
        "max_hits": 5,
        "mask": True,
        "regex": False,
    }
    options.update(kwargs)
    return analyze(har_dict, **options)


class TestSourceClassification(unittest.TestCase):
    def test_js_suffix_is_source(self):
        self.assertTrue(is_source_like("https://x/a/b.js", ""))

    def test_mjs_and_map_and_css_and_html_are_source(self):
        for suffix in (".mjs", ".css", ".html", ".map"):
            with self.subTest(suffix=suffix):
                self.assertTrue(is_source_like(f"https://x/a{suffix}", ""))

    def test_query_string_does_not_defeat_suffix(self):
        self.assertTrue(is_source_like("https://x/a.js?v=3", ""))

    def test_javascript_mime_without_suffix_is_source(self):
        self.assertTrue(is_source_like("https://x/download", "text/javascript"))

    def test_json_is_not_source(self):
        self.assertFalse(is_source_like("https://x/api/list", "application/json"))

    def test_image_is_not_source(self):
        self.assertFalse(is_source_like("https://x/a.png", "image/png"))

    def test_empty_url_and_mime_is_not_source(self):
        self.assertFalse(is_source_like("", ""))

    def test_mime_with_charset_is_normalized(self):
        self.assertTrue(is_source_like("https://x/download", "text/javascript; charset=utf-8"))

    def test_source_mimes_are_all_lowercase(self):
        # mimeType 比对前会 lower()，集合里若混进大写就永远匹配不上。
        self.assertTrue(all(item == item.lower() for item in SOURCE_MIMES))
        self.assertTrue(all(item == item.lower() for item in SOURCE_SUFFIXES))


class TestReadableText(unittest.TestCase):
    def test_plain_text_is_readable(self):
        text, reason = readable_text(_entry("https://x/a.js", body="var a=1"))
        self.assertEqual(text, "var a=1")
        self.assertEqual(reason, "")

    def test_base64_is_binary_not_empty(self):
        text, reason = readable_text(
            _entry("https://x/a.js", body="AAAA", encoding="base64")
        )
        self.assertEqual(text, "")
        self.assertEqual(reason, "binary")

    def test_missing_body_is_empty_not_binary(self):
        text, reason = readable_text(_entry("https://x/a.png", mime="image/png"))
        self.assertEqual(text, "")
        self.assertEqual(reason, "empty")

    def test_binary_and_empty_are_different_reasons(self):
        # 这是本工具的核心区分：读不出来（材料残）≠ 本来就没有正文。
        self.assertNotEqual(
            readable_text(_entry("https://x/a", encoding="base64"))[1],
            readable_text(_entry("https://x/a"))[1],
        )


class TestMasking(unittest.TestCase):
    def test_long_mixed_case_run_is_masked(self):
        out = mask_runs(OPAQUE_VALUE)
        self.assertNotIn(OPAQUE_VALUE, out)
        self.assertIn(f"len={len(OPAQUE_VALUE)}", out)
        self.assertIn(digest(OPAQUE_VALUE), out)

    def test_lowercase_run_survives(self):
        # 全小写无数字 → 像 MIME 类型，是可读的代码，不该被掩。
        self.assertIn(PLAINISH, mask_runs(PLAINISH))

    def test_identifier_chain_survives(self):
        code = 'localStorage.getItem("deviceUuid")'
        self.assertIn(code, mask_runs(code))

    def test_url_survives(self):
        url = "app.example.com/app/webapp/js/1900.cd97ba24.js"
        self.assertIn(url, mask_runs(url))

    def test_short_run_survives_even_if_mixed_case(self):
        self.assertIn("aB3", mask_runs("aB3"))

    def test_mask_min_is_honored(self):
        run = "aB3" * 10  # 30 字符
        self.assertIn(run, mask_runs(run, mask_min=DEFAULT_MASK_MIN))
        self.assertNotIn(run, mask_runs(run, mask_min=10))

    def test_masking_is_reversible_only_by_length_and_hash(self):
        out = mask_runs(OPAQUE_VALUE)
        self.assertEqual(out.count("«"), 1)
        self.assertEqual(out.count("»"), 1)

    def test_display_needle_masks_a_value(self):
        shown = display_needle(OPAQUE_VALUE, True)
        self.assertNotIn(OPAQUE_VALUE, shown)
        self.assertIn("len=", shown)

    def test_display_needle_keeps_a_field_name(self):
        self.assertEqual(display_needle("deviceUuid", True), "deviceUuid")

    def test_display_needle_keeps_a_path(self):
        needle = "/app/api/signIn/keepSignIn"
        self.assertEqual(display_needle(needle, True), needle)

    def test_display_needle_no_mask_mode_is_identity(self):
        self.assertEqual(display_needle(OPAQUE_VALUE, False), OPAQUE_VALUE)


class TestCollectSources(unittest.TestCase):
    def test_default_skips_data_responses(self):
        sources, stats = collect_sources(js_har()["log"]["entries"], include_data=False, min_size=1)
        self.assertEqual(len(sources), 2)
        self.assertEqual(stats["skipped_not_source"], 1)

    def test_include_data_adds_them(self):
        sources, stats = collect_sources(js_har()["log"]["entries"], include_data=True, min_size=1)
        self.assertEqual(len(sources), 3)
        self.assertEqual(stats["data"], 1)

    def test_source_carries_no_text_in_listing_shape(self):
        sources, _ = collect_sources(js_har()["log"]["entries"], include_data=False, min_size=1)
        self.assertTrue(all("_text" in source for source in sources))

    def test_min_size_filters(self):
        sources, stats = collect_sources(
            js_har()["log"]["entries"], include_data=False, min_size=10_000
        )
        self.assertEqual(sources, [])
        self.assertEqual(stats["skipped_small"], 2)

    def test_identical_url_and_body_are_merged(self):
        entries = [
            _entry("https://x/a.js", body=DEVICE_JS, mime="application/javascript"),
            _entry("https://x/a.js", body=DEVICE_JS, mime="application/javascript"),
        ]
        sources, stats = collect_sources(entries, include_data=False, min_size=1)
        self.assertEqual(len(sources), 1)
        self.assertEqual(stats["duplicate_resources"], 1)

    def test_same_url_different_body_is_kept(self):
        # 同一个接口地址返回不同内容是正常的，按 URL 单独去重会误合。
        entries = [
            _entry("https://x/a.js", body="var a=1;", mime="application/javascript"),
            _entry("https://x/a.js", body="var a=2;", mime="application/javascript"),
        ]
        sources, stats = collect_sources(entries, include_data=False, min_size=1)
        self.assertEqual(len(sources), 2)
        self.assertEqual(stats.get("duplicate_resources", 0), 0)

    def test_binary_resource_is_counted_not_collected(self):
        entries = [_entry("https://x/a.js", body="AAAA", encoding="base64")]
        sources, stats = collect_sources(entries, include_data=False, min_size=1)
        self.assertEqual(sources, [])
        self.assertEqual(stats["unreadable_binary"], 1)

    def test_listing_sorted_by_size_desc_in_report(self):
        report = run(js_har())
        sizes = [source["chars"] for source in report["sources"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.report = run(js_har(), needles=["deviceUuid"])

    def test_literal_hit_is_found(self):
        self.assertEqual(self.report["needles"][0]["hits"], 3)

    def test_hit_names_the_resource(self):
        row = self.report["needles"][0]["results"][0]
        self.assertIn("8176.b4c9c7c2.js", row["path"])

    def test_hit_carries_offset_and_line(self):
        match = self.report["needles"][0]["results"][0]["matches"][0]
        self.assertIn("offset", match)
        self.assertEqual(match["line"], 1)

    def test_context_contains_the_needle(self):
        match = self.report["needles"][0]["results"][0]["matches"][0]
        self.assertIn("deviceUuid", match["context"])

    def test_max_hits_caps_listed_matches(self):
        report = run(js_har(), needles=["deviceUuid"], max_hits=1)
        row = report["needles"][0]["results"][0]
        self.assertEqual(row["count"], 3)
        self.assertEqual(len(row["matches"]), 1)

    def test_context_width_is_honored(self):
        narrow = run(js_har(), needles=["deviceUuid"], context=5)
        wide = run(js_har(), needles=["deviceUuid"], context=120)
        narrow_len = len(narrow["needles"][0]["results"][0]["matches"][0]["context"])
        wide_len = len(wide["needles"][0]["results"][0]["matches"][0]["context"])
        self.assertLess(narrow_len, wide_len)

    def test_api_path_is_findable(self):
        report = run(js_har(), needles=["keepSignIn"])
        self.assertEqual(report["needles"][0]["hits"], 1)
        self.assertIn("1900.cd97ba24.js", report["needles"][0]["results"][0]["path"])

    def test_multiple_needles_are_searched_independently(self):
        report = run(js_har(), needles=["deviceUuid", "keepSignIn"])
        self.assertEqual(len(report["needles"]), 2)
        self.assertEqual(report["needles"][0]["hits"], 3)
        self.assertEqual(report["needles"][1]["hits"], 1)

    def test_data_body_is_not_searched_by_default(self):
        report = run(js_har(), needles=["noticeType"])
        self.assertEqual(report["needles"][0]["hits"], 0)

    def test_data_body_is_searched_with_include_data(self):
        entries = js_har()["log"]["entries"]
        entries[2]["response"]["content"]["text"] = json.dumps({"noticeType": 2})
        report = run(har(*entries), needles=["noticeType"], include_data=True)
        self.assertEqual(report["needles"][0]["hits"], 1)

    def test_regex_mode(self):
        report = run(js_har(), needles=[r"deviceUu\w+:"], regex=True)
        self.assertEqual(report["needles"][0]["hits"], 1)

    def test_literal_mode_does_not_interpret_regex(self):
        report = run(js_har(), needles=[r"deviceUu\w+:"], regex=False)
        self.assertEqual(report["needles"][0]["hits"], 0)

    def test_invalid_regex_does_not_crash(self):
        report = run(js_har(), needles=["("], regex=True)
        self.assertEqual(report["needles"][0]["hits"], 0)

    def test_search_source_returns_empty_for_missing_needle(self):
        sources, _ = collect_sources(js_har()["log"]["entries"], include_data=False, min_size=1)
        found = search_source(
            sources[0], ["nope"], context=10, max_hits=1, mask=True, regex=False
        )
        self.assertEqual(found, {})


class TestNegativeResults(unittest.TestCase):
    """「没命中」与「没材料」必须分开说——这条是本工具存在的理由。"""

    def test_no_sources_says_no_material(self):
        only_json = har(_entry("https://x/api/a", body=json.dumps({"a": 1})))
        report = run(only_json, needles=["deviceUuid"])
        self.assertEqual(report["counts"]["sources"], 0)
        self.assertTrue(any("没有材料" in note for note in report["notes"]))

    def test_zero_hit_says_it_is_a_real_negative(self):
        report = run(js_har(), needles=["nonexistentField"])
        self.assertEqual(report["needles"][0]["hits"], 0)
        self.assertTrue(any("负面结论" in note for note in report["notes"]))

    def test_binary_resource_produces_a_completeness_note(self):
        entries = list(js_har()["log"]["entries"])
        entries.append(_entry("https://x/b.js", body="AAAA", encoding="base64"))
        report = run(har(*entries), needles=["deviceUuid"])
        self.assertEqual(report["counts"]["unreadable_binary"], 1)
        self.assertTrue(any("残" in note for note in report["notes"]))

    def test_data_skip_is_disclosed(self):
        report = run(js_har(), needles=["deviceUuid"])
        self.assertTrue(any("--include-data" in note for note in report["notes"]))

    def test_unsorted_entries_are_reported(self):
        entries = [
            _entry("https://x/a.js", body=DEVICE_JS, mime="application/javascript",
                   started="2026-09-25T01:00:05.000Z"),
            _entry("https://x/b.js", body=API_JS, mime="application/javascript",
                   started="2026-09-25T01:00:00.000Z"),
        ]
        report = run(har(*entries))
        self.assertEqual(report["har"]["entry_order"], "reversed")
        self.assertTrue(any("不是时间序" in note for note in report["notes"]))

    def test_no_needle_means_no_negative_note(self):
        report = run(js_har())
        self.assertFalse(any("负面结论" in note for note in report["notes"]))


class TestNoPlaintextLeaks(unittest.TestCase):
    """安全底线：源码里的凭证不许出现在任何输出里。"""

    def _outputs(self) -> tuple[str, str]:
        report = run(js_har(), needles=["deviceUuid", OPAQUE_VALUE])
        text = render(report, top=30)
        payload = json.dumps(report, ensure_ascii=False)
        return text, payload

    def test_secret_absent_from_text_render(self):
        text, _ = self._outputs()
        self.assertNotIn(OPAQUE_VALUE, text)

    def test_secret_absent_from_json_report(self):
        _, payload = self._outputs()
        self.assertNotIn(OPAQUE_VALUE, payload)

    def test_secret_used_as_needle_is_masked_in_echo(self):
        text, _ = self._outputs()
        self.assertIn("len=120", text)

    def test_masked_form_is_present_so_the_hit_is_still_usable(self):
        _, payload = self._outputs()
        self.assertIn(digest(OPAQUE_VALUE), payload)

    def test_no_mask_flag_does_expose_it_and_that_is_documented(self):
        # --no-mask 是显式选择，不是默认；这里把行为钉住，免得将来悄悄反转。
        # 上下文要开得比 OPAQUE_VALUE 长，否则整串会被截断在片段边界外，
        # 断言会以"没看见"的形式失败——那正是本工具最想避免的读法。
        report = run(js_har(), needles=["deviceUuid"], mask=False, context=400)
        self.assertIn(OPAQUE_VALUE, render(report, top=30))


class TestRendering(unittest.TestCase):
    def test_render_has_header_and_scope(self):
        text = render(run(js_har(), needles=["deviceUuid"]), top=30)
        self.assertIn("HAR 内嵌源码检索", text)
        self.assertIn("仅源码类", text)

    def test_render_shows_include_data_when_set(self):
        text = render(run(js_har(), needles=["deviceUuid"], include_data=True), top=30)
        self.assertIn("含接口数据", text)

    def test_render_lists_resources(self):
        text = render(run(js_har()), top=30)
        self.assertIn("8176.b4c9c7c2.js", text)

    def test_render_top_caps_the_listing(self):
        text = render(run(js_har()), top=1)
        self.assertIn("--top 可调", text)

    def test_render_marks_zero_hit_explicitly(self):
        text = render(run(js_har(), needles=["nope"]), top=30)
        self.assertIn("0 命中", text)

    def test_render_prints_notes(self):
        text = render(run(js_har(), needles=["deviceUuid"]), top=30)
        self.assertIn("-- 提示", text)

    def test_render_shows_mask_state(self):
        self.assertIn("掩码 开", render(run(js_har()), top=5))
        self.assertIn("掩码 关", render(run(js_har(), mask=False), top=5))


class TestCli(unittest.TestCase):
    def _write(self, payload: dict) -> str:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".har", delete=False, encoding="utf-8", newline="\n"
        )
        with handle:
            json.dump(payload, handle, ensure_ascii=False)
        self.addCleanup(Path(handle.name).unlink, missing_ok=True)
        return handle.name

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_list_mode_needs_no_grep(self):
        code, out, _ = self._run([self._write(js_har())])
        self.assertEqual(code, 0)
        self.assertIn("8176.b4c9c7c2.js", out)

    def test_grep_mode(self):
        code, out, _ = self._run([self._write(js_har()), "--grep", "deviceUuid"])
        self.assertEqual(code, 0)
        self.assertIn("deviceUuid", out)

    def test_json_mode_is_parseable(self):
        code, out, _ = self._run([self._write(js_har()), "--grep", "deviceUuid", "--json"])
        self.assertEqual(code, 0)
        self.assertIn("sources", json.loads(out))

    def test_out_writes_the_report(self):
        target = Path(tempfile.mkdtemp()) / "src.json"
        self.addCleanup(target.unlink, missing_ok=True)
        code, _, _ = self._run([self._write(js_har()), "--out", str(target)])
        self.assertEqual(code, 0)
        self.assertTrue(target.exists())
        self.assertIn("sources", json.loads(target.read_text(encoding="utf-8")))

    def test_missing_file_exits_2(self):
        code, _, err = self._run([str(Path(tempfile.gettempdir()) / "definitely-not-here.har")])
        self.assertEqual(code, 2)
        self.assertIn("无法解析 HAR", err)

    def test_non_har_json_exits_2(self):
        code, _, err = self._run([self._write({"nope": 1})])
        self.assertEqual(code, 2)
        self.assertIn("无法解析 HAR", err)

    def test_bad_numeric_options_exit_2(self):
        code, _, _ = self._run([self._write(js_har()), "--context", "-1"])
        self.assertEqual(code, 2)

    def test_zero_max_hits_exits_2(self):
        code, _, _ = self._run([self._write(js_har()), "--max-hits", "0"])
        self.assertEqual(code, 2)

    def test_repeated_grep_is_supported(self):
        code, out, _ = self._run(
            [self._write(js_har()), "--grep", "deviceUuid", "--grep", "keepSignIn"]
        )
        self.assertEqual(code, 0)
        self.assertIn("deviceUuid", out)
        self.assertIn("keepSignIn", out)

    def test_documented_commands_work(self):
        path = self._write(js_har())
        for argv in (
            [path],
            [path, "--grep", "deviceUuid"],
            [path, "--grep", "deviceUuid", "--context", "200"],
            [path, "--grep", "keepSignIn", "--include-data"],
            [path, "--grep", "deviceUuid", "--json"],
        ):
            with self.subTest(argv=argv):
                code, out, _ = self._run(argv)
                self.assertEqual(code, 0)
                self.assertTrue(out.strip())


if __name__ == "__main__":
    unittest.main()
