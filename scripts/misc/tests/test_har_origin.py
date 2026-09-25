"""HAR 字段溯源工具的离线测试。

夹具是**内联合成 HAR**，不是真实抓包：真实抓包含凭证，不该进仓库，
而这里要验的是"归属判定与安全约束对不对"，不是"某站点长什么样"。

两条最要紧的断言：

1. **明文绝不出现在任何输出里**（JSON 与文本都查）——这是本工具的安全底线。
2. **数组顺序倒过来，判定不能变**——HAR 不保证 entries 按时间排，
   实测 ProxyPin 导出基本是倒序，不重排会把"来源"判成"回声"。

零第三方依赖，可被 scripts/misc/run_offline_tests.py 直接发现。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from automation.har_origin import (  # noqa: E402
    BLOB_RE,
    POOL_CHARS,
    analyze,
    build_pool,
    classify_field,
    digest,
    entry_time_key,
    header_value_candidates,
    lookup_forms,
    main,
    pick_match,
    relation,
    render,
    response_text,
)

# 全是 200 字符的 base64url 形态串，彼此不同。用重复片段是为了肉眼能看出长度。
TOKEN = "deadbeef" * 25  # 200
TOKEN_ECHO = "cafebabe" * 25  # 200
TOKEN_LATE = "0badf00d" * 25  # 200
TOKEN_OTHER = "feedface" * 25  # 200
TOKEN_COOKIE = "abad1dea" * 25  # 200
TOKEN_SHAPE = "a1b2c3d4" * 25  # 200，池里没有同串、只有同长度
LONGEST = "e" * 202  # 202，只为了造一个"长度 202"的池内项
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) " + "z" * 165)[:202]  # 202 字符，非 base64url
# JWT 形态：点号分隔的三段。**点号必须被池子的字符集认下**，否则整串进不了池子，
# 只有三个段能进去——实测这个 App 的 Authorization 就是这种形态。
JWT_LIKE = "a" * 60 + "." + "b" * 80 + "." + "c" * 84  # 226 字符

MIN_LENGTH = 200
SHORT_SECRET = "zq7x9"  # 5 字符，短于 min_field，不许进报告


def _lengths(pool: dict) -> Counter:
    out: Counter = Counter()
    for slot in pool.values():
        out[slot["length"]] += 1
    return out


def _entry(
    url: str,
    *,
    method: str = "GET",
    started: str = "2026-09-25T01:00:00.000Z",
    status: int = 200,
    body: str | None = None,
    mime: str = "application/json",
    encoding: str | None = None,
    post: str | None = None,
    post_mime: str = "application/x-www-form-urlencoded",
    headers: list[dict] | None = None,
    resp_headers: list[dict] | None = None,
) -> dict:
    request: dict = {"method": method, "url": url, "headers": headers or []}
    if post is not None:
        request["postData"] = {"mimeType": post_mime, "text": post}
    content: dict = {"mimeType": mime}
    if body is not None:
        content["text"] = body
    if encoding is not None:
        content["encoding"] = encoding
    return {
        "startedDateTime": started,
        "request": request,
        "response": {"status": status, "content": content, "headers": resp_headers or []},
    }


def form(**fields: str) -> str:
    return "&".join(f"{key}={value}" for key, value in fields.items())


def synthetic_har() -> dict:
    """一份把五种判定各造一次的抓包。时间递增，但**数组顺序被刻意打乱**。"""
    entries = [
        # t0 来源：reCAPTCHA 的响应体里有 TOKEN
        _entry(
            "https://recaptcha.net/recaptcha/api2/reload",
            method="POST",
            started="2026-09-25T01:00:00.000Z",
            body=json.dumps({"token": TOKEN}),
        ),
        # t1 目标：TOKEN 出现在更晚的请求里 → origin
        _entry(
            "https://api.example.com/v1/sign",
            method="POST",
            started="2026-09-25T01:00:01.000Z",
            post=form(token=TOKEN, uid=SHORT_SECRET, deviceId="web-desktop-01"),
        ),
        # t2 回显：值出现在**自己这条**的响应里 → echo
        _entry(
            "https://api.example.com/v1/echo?value=" + TOKEN_ECHO,
            started="2026-09-25T01:00:02.000Z",
            body=json.dumps({"echo": TOKEN_ECHO}),
        ),
        # t3 回声：值先被发出去，之后才出现在别人的响应里 → later
        _entry(
            "https://api.example.com/v1/late",
            method="POST",
            started="2026-09-25T01:00:03.000Z",
            post=form(value=TOKEN_LATE),
        ),
        _entry(
            "https://api.example.com/v1/late-echo",
            started="2026-09-25T01:00:04.000Z",
            body=json.dumps({"seen": TOKEN_LATE}),
        ),
        # t5 同长：池里有 200 字符的串，但没有这个串 → shape
        _entry(
            "https://api.example.com/v1/shape",
            started="2026-09-25T01:00:05.000Z",
            post=form(value=TOKEN_SHAPE),
            post_mime="application/x-www-form-urlencoded",
        ),
        # t6 其它域名：TOKEN_OTHER 来自被 --from 排除的域名 → other
        _entry(
            "https://third.example.org/seed",
            started="2026-09-25T01:00:06.000Z",
            body=json.dumps({"seed": TOKEN_OTHER}),
        ),
        _entry(
            "https://api.example.com/v1/other",
            method="POST",
            started="2026-09-25T01:00:07.000Z",
            post=form(value=TOKEN_OTHER),
        ),
        # t8 池子残缺：响应体是 base64，读不出来
        _entry(
            "https://api.example.com/v1/binary",
            started="2026-09-25T01:00:08.000Z",
            body="QUJD",
            encoding="base64",
        ),
        # t9 响应头来源：Set-Cookie 的值只在头里，不在任何响应体里
        _entry(
            "https://recaptcha.net/recaptcha/api2/anchor",
            started="2026-09-25T01:00:09.000Z",
            body="{}",
            resp_headers=[{"name": "Set-Cookie", "value": f"sid={TOKEN_COOKIE}; Path=/; HttpOnly"}],
        ),
        _entry(
            "https://api.example.com/v1/from-cookie",
            method="POST",
            started="2026-09-25T01:00:10.000Z",
            post=form(value=TOKEN_COOKIE),
        ),
        # t11 长度撞车但形态不同：User-Agent 202 字符，池里也有 202 字符的串
        _entry(
            "https://api.example.com/v1/ua",
            started="2026-09-25T01:00:11.000Z",
            body=json.dumps({"pad": LONGEST}),
            headers=[{"name": "User-Agent", "value": UA}],
        ),
        # t12 登录：响应体的 data 就是完整的 Authorization 头值（含 Bearer 前缀）
        _entry(
            "https://api.example.com/v1/login",
            method="POST",
            started="2026-09-25T01:00:12.000Z",
            body=json.dumps({"code": 0, "msg": "ok", "data": f"Bearer {JWT_LIKE}"}),
        ),
        # t13 后续请求：头里带的是同一个 JWT，但整串带前缀查不到 → 必须靠"去前缀"
        _entry(
            "https://api.example.com/v1/me",
            started="2026-09-25T01:00:13.000Z",
            headers=[{"name": "Authorization", "value": f"Bearer {JWT_LIKE}"}],
        ),
    ]
    # 真实抓包的数组顺序不携带时间信息，这里刻意打乱：偶数位与奇数位互换。
    shuffled = entries[1::2] + entries[0::2]
    return {"log": {"version": "1.2", "creator": {"name": "synthetic"}, "entries": shuffled}}


def run(har: dict, **overrides):
    kwargs = {
        "origin_needles": [],
        "target_needles": [],
        "min_length": MIN_LENGTH,
        "min_field": 8,
        "include_headers": True,
        "include_cookies": True,
    }
    kwargs.update(overrides)
    return analyze(har, **kwargs)


def verdicts(report: dict) -> dict[tuple[str, str], str]:
    """{(方法+路径, 字段名): 判定}，用来比对两次运行是否一致。"""
    out: dict[tuple[str, str], str] = {}
    for target in report["targets"]:
        for row in target["fields"]:
            out[(f"{target['method']} {target['path']}", row["name"])] = row["verdict"]
    return out


def find(report: dict, path_needle: str, name: str) -> dict:
    for target in report["targets"]:
        if path_needle not in target["path"]:
            continue
        for row in target["fields"]:
            if row["name"] == name:
                return row
    raise AssertionError(f"没找到 {path_needle} / {name}：{sorted(verdicts(report))}")


class TestVerdicts(unittest.TestCase):
    """五种判定各造一次，逐个钉住。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.report = run(synthetic_har(), origin_needles=["recaptcha.net"])

    def test_earlier_response_is_the_origin(self) -> None:
        row = find(self.report, "/v1/sign", "token")
        self.assertEqual(row["verdict"], "origin")
        self.assertEqual(row["match"]["host"], "recaptcha.net")
        self.assertEqual(row["match"]["relation"], "earlier")
        # delta_s = 目标请求时间 − 匹配响应时间，正数即匹配更早。
        self.assertGreater(row["delta_s"], 0, "来源应当比目标请求更早")

    def test_value_echoed_in_its_own_response(self) -> None:
        row = find(self.report, "/v1/echo", "value")
        self.assertEqual(row["verdict"], "echo")
        self.assertEqual(row["match"]["relation"], "same")
        self.assertEqual(row["delta_s"], 0.0)

    def test_later_response_is_not_an_origin(self) -> None:
        row = find(self.report, "/v1/late", "value")
        self.assertEqual(row["verdict"], "later")
        self.assertEqual(row["match"]["relation"], "later")
        self.assertLess(row["delta_s"], 0, "回声出现在目标请求之后")

    def test_same_length_but_different_string(self) -> None:
        row = find(self.report, "/v1/shape", "value")
        self.assertEqual(row["verdict"], "shape")
        self.assertIsNone(row["match"], "同长不是命中，不该给出匹配点")

    def test_match_on_an_excluded_domain_is_reported_as_such(self) -> None:
        row = find(self.report, "/v1/other", "value")
        self.assertEqual(row["verdict"], "other")
        self.assertEqual(row["match"]["host"], "third.example.org")

    def test_same_value_without_the_filter_is_a_plain_origin(self) -> None:
        # 不给 --from 时，任何域名上的更早响应都算来源。
        report = run(synthetic_har())
        self.assertEqual(find(report, "/v1/other", "value")["verdict"], "origin")

    def test_origin_found_via_a_response_header(self) -> None:
        # Set-Cookie 的值不在任何响应体里，只有头里有。
        row = find(self.report, "/v1/from-cookie", "value")
        self.assertEqual(row["verdict"], "origin")
        self.assertEqual(row["match"]["host"], "recaptcha.net")

    def test_non_blob_value_with_a_colliding_length_is_not_shape(self) -> None:
        # User-Agent 与池里那个填充串**长度确实相同**，但形态不同，不许报"同长"。
        self.assertEqual(len(UA), len(LONGEST))
        self.assertIsNone(BLOB_RE.fullmatch(UA))
        row = find(self.report, "/v1/ua", "User-Agent")
        self.assertEqual(row["verdict"], "miss")

    def test_jwt_like_value_is_found_through_the_prefix_stripping_form(self) -> None:
        # 实测形态：Authorization 的值是 `Bearer <jwt>`，而响应体里的 data 也是
        # 同一个完整头值。整串直接查会 miss（池子里只有不带 Bearer 的那段）。
        # 这条不加 --from：来源就是同一个域名，加过滤会变成 other。
        report = run(synthetic_har())
        row = find(report, "/v1/me", "Authorization")
        self.assertEqual(row["verdict"], "origin")
        self.assertEqual(row["matched_form"], "去前缀")
        self.assertEqual(row["match"]["host"], "api.example.com")
        self.assertIn("/v1/login", row["match"]["path"])

    def test_prefix_stripped_hit_is_still_labeled_other_under_a_domain_filter(self) -> None:
        # 形态分解与域名过滤是两件正交的事：换了形态不等于换了来源域名。
        row = find(self.report, "/v1/me", "Authorization")
        self.assertEqual(row["matched_form"], "去前缀")
        self.assertEqual(row["verdict"], "other")

    def test_direct_hit_is_reported_as_the_as_is_form(self) -> None:
        row = find(self.report, "/v1/sign", "token")
        self.assertEqual(row["matched_form"], "原样")

    def test_every_verdict_value_is_known(self) -> None:
        known = {"origin", "other", "echo", "later", "shape", "miss"}
        for verdict in verdicts(self.report).values():
            self.assertIn(verdict, known)

    def test_summary_counts_match_the_rows(self) -> None:
        counted: dict[str, int] = {}
        for verdict in verdicts(self.report).values():
            counted[verdict] = counted.get(verdict, 0) + 1
        for name, value in self.report["summary"]["verdicts"].items():
            self.assertEqual(value, counted.get(name, 0), name)
        self.assertEqual(self.report["summary"]["fields"], sum(counted.values()))


class TestTimeOrdering(unittest.TestCase):
    """数组顺序不携带时间信息，判定必须只依赖 startedDateTime。"""

    def test_shuffled_array_is_reported_as_not_chronological(self) -> None:
        self.assertNotEqual(run(synthetic_har())["har"]["entry_order"], "chronological")

    def test_reversing_the_array_does_not_change_any_verdict(self) -> None:
        forward = verdicts(run(synthetic_har(), origin_needles=["recaptcha.net"]))
        reversed_har = synthetic_har()
        reversed_har["log"]["entries"] = list(reversed(reversed_har["log"]["entries"]))
        backward = verdicts(run(reversed_har, origin_needles=["recaptcha.net"]))
        self.assertEqual(forward, backward)

    def test_naive_array_order_would_flip_the_verdict(self) -> None:
        # 反证：数组顺序里，来源响应排在目标请求**后面**。
        # 若把数组下标当时间先后，"来源"就会被判成"回声"——方向恰好相反。
        har = synthetic_har()
        entries = har["log"]["entries"]

        def index_of(suffix: str) -> int:
            return next(
                i for i, e in enumerate(entries) if e["request"]["url"].endswith(suffix)
            )

        source = index_of("/recaptcha/api2/reload")
        target = index_of("/v1/sign")
        self.assertGreater(source, target, "夹具必须先满足：来源响应在数组里排在后面")

        pool, _, _ = build_pool(entries, MIN_LENGTH)
        lengths = _lengths(pool)
        row = classify_field(
            "token",
            "body.form",
            TOKEN,
            entry_time_key(entries[target], target),
            pool,
            lengths,
            ["recaptcha.net"],
        )
        # 按真实 startedDateTime 排完，结论是"来源"。
        self.assertEqual(row["verdict"], "origin")


class TestPool(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = synthetic_har()["log"]["entries"]
        self.pool, self.lengths, self.stats = build_pool(self.entries, MIN_LENGTH)

    def test_pool_collects_both_body_and_header_values(self) -> None:
        self.assertGreater(self.stats["strings_from_body"], 0)
        self.assertGreater(self.stats["strings_from_header"], 0)

    def test_base64_response_is_counted_as_unreadable_not_as_empty(self) -> None:
        self.assertEqual(self.stats["bodies_binary"], 1)
        report = run(synthetic_har())
        self.assertFalse(report["pool"]["complete"])
        self.assertTrue(any("残" in note for note in report["notes"]))

    def test_short_strings_stay_out_of_the_pool(self) -> None:
        self.assertNotIn(digest("12345"), self.pool)

    def test_every_pooled_value_meets_the_minimum_length(self) -> None:
        for slot in self.pool.values():
            self.assertGreaterEqual(slot["length"], MIN_LENGTH)

    def test_min_length_changes_the_pool(self) -> None:
        entries = [_entry("https://a/b", body="shortvalue " + "x" * 40)]
        coarse, _, _ = build_pool(entries, MIN_LENGTH)
        fine, _, _ = build_pool(entries, 8)
        self.assertEqual(len(coarse), 0)
        self.assertGreaterEqual(len(fine), 1)

    def test_pool_keeps_only_the_earliest_occurrence_per_host(self) -> None:
        slot = self.pool[digest(TOKEN_LATE)]
        self.assertEqual(slot["count"], 1)
        self.assertEqual(slot["first"]["host"], "api.example.com")

    def test_pool_captures_a_dotted_blob_as_one_run(self) -> None:
        # 点号必须在池子的字符集里。否则 JWT 会被按点号切成三段，整串永远进不了池，
        # 而三个段反而都在——工具会对它最该回答的那类值报 miss。
        self.assertIn(".", POOL_CHARS)
        self.assertIn(digest(JWT_LIKE), self.pool)
        self.assertEqual(self.pool[digest(JWT_LIKE)]["length"], len(JWT_LIKE))

    def test_dotted_blob_segments_are_not_the_whole_story(self) -> None:
        # 反证：把点号拿掉，池里就只剩三段，整串查不到。
        entries = [
            _entry("https://a/b", body=json.dumps({"data": JWT_LIKE})),
        ]
        pool, _, _ = build_pool(entries, MIN_LENGTH)
        self.assertIn(digest(JWT_LIKE), pool)
        for segment in JWT_LIKE.split("."):
            if len(segment) >= MIN_LENGTH:
                self.assertIn(digest(segment), pool)

    def test_earliest_is_kept_regardless_of_array_order(self) -> None:
        # 数组被 shuffle 过，池里留的仍必须是时间最早的那次出现。
        slot = self.pool[digest(TOKEN)]
        self.assertEqual(slot["first"]["startedDateTime"], "2026-09-25T01:00:00.000Z")


class TestPickMatch(unittest.TestCase):
    def setUp(self) -> None:
        self.pool, _, _ = build_pool(synthetic_har()["log"]["entries"], MIN_LENGTH)

    def test_no_filter_returns_the_earliest_occurrence(self) -> None:
        self.assertEqual(pick_match(self.pool[digest(TOKEN_OTHER)], [])["host"], "third.example.org")

    def test_filter_that_matches_nothing_returns_none(self) -> None:
        self.assertIsNone(pick_match(self.pool[digest(TOKEN_OTHER)], ["recaptcha.net"]))

    def test_filter_uses_host_substring(self) -> None:
        self.assertIsNotNone(pick_match(self.pool[digest(TOKEN_OTHER)], ["example.org"]))


class TestHelpers(unittest.TestCase):
    def test_digest_is_short_stable_and_not_the_value(self) -> None:
        first = digest(TOKEN)
        self.assertEqual(first, digest(TOKEN))
        self.assertEqual(len(first), 12)
        self.assertNotIn(TOKEN[:12], first)

    def test_response_text_flags_base64(self) -> None:
        entry = _entry("https://x/y", body="QUJD", encoding="base64")
        text, reason = response_text(entry)
        self.assertEqual((text, reason), ("", "binary"))

    def test_response_text_flags_missing_body(self) -> None:
        text, reason = response_text(_entry("https://x/y"))
        self.assertEqual((text, reason), ("", "empty"))

    def test_response_text_passes_through_plain_text(self) -> None:
        text, reason = response_text(_entry("https://x/y", body="hello"))
        self.assertEqual((text, reason), ("hello", ""))

    def test_header_candidates_include_the_whole_value(self) -> None:
        value = "x" * MIN_LENGTH
        self.assertIn(value, list(header_value_candidates(value, MIN_LENGTH)))

    def test_header_candidates_split_cookie_style_values(self) -> None:
        value = f"sid={TOKEN}; Path=/; HttpOnly"
        candidates = list(header_value_candidates(value, MIN_LENGTH))
        self.assertIn(TOKEN, candidates)

    def test_header_candidates_ignore_short_segments(self) -> None:
        self.assertEqual(list(header_value_candidates("a=b; c=d", MIN_LENGTH)), [])

    def test_relation(self) -> None:
        self.assertEqual(relation((0, "a", 1), (0, "b", 2)), "earlier")
        self.assertEqual(relation((0, "b", 2), (0, "b", 2)), "same")
        self.assertEqual(relation((0, "c", 3), (0, "b", 2)), "later")


class TestLookupForms(unittest.TestCase):
    """字段值常常被包了一层；整串查必然 miss，而 miss 会被读成"没有来源"。"""

    def test_plain_value_is_tried_as_is(self) -> None:
        self.assertEqual(lookup_forms("abc123"), [("原样", "abc123")])

    def test_bearer_prefix_is_stripped(self) -> None:
        self.assertIn(("去前缀", "abc123"), lookup_forms("Bearer abc123"))

    def test_prefix_match_is_case_insensitive(self) -> None:
        self.assertIn(("去前缀", "abc123"), lookup_forms("bearer abc123"))
        self.assertIn(("去前缀", "abc123"), lookup_forms("BASIC abc123"))

    def test_base64_padding_is_trimmed(self) -> None:
        self.assertIn(("去补位", "abc123"), lookup_forms("abc123=="))

    def test_prefix_and_padding_are_both_stripped(self) -> None:
        self.assertIn(("去补位", "abc123"), lookup_forms("Bearer abc123=="))

    def test_pair_tail_is_tried(self) -> None:
        self.assertIn(("等号后段", "abc123"), lookup_forms("sid=abc123"))

    def test_forms_are_deduplicated(self) -> None:
        forms = lookup_forms("abc123")
        self.assertEqual(len(forms), len({candidate for _, candidate in forms}))

    def test_empty_candidates_are_dropped(self) -> None:
        self.assertNotIn(("去前缀", ""), lookup_forms("Bearer "))

    def test_jwt_is_not_split_by_the_forms(self) -> None:
        self.assertEqual(lookup_forms(JWT_LIKE), [("原样", JWT_LIKE)])


class TestNoPlaintextLeaks(unittest.TestCase):
    """本工具的安全底线：输出里不许出现任何明文值。"""

    def setUp(self) -> None:
        self.report = run(synthetic_har(), origin_needles=["recaptcha.net"])
        self.secrets = [
            TOKEN,
            TOKEN_ECHO,
            TOKEN_LATE,
            TOKEN_OTHER,
            TOKEN_COOKIE,
            TOKEN_SHAPE,
            LONGEST,
            UA,
            "web-desktop-01",
            JWT_LIKE,
            f"Bearer {JWT_LIKE}",
        ]

    def test_json_report_contains_no_plaintext(self) -> None:
        blob = json.dumps(self.report, ensure_ascii=False)
        for secret in self.secrets:
            self.assertNotIn(secret, blob)

    def test_rendered_text_contains_no_plaintext(self) -> None:
        text = render(self.report, 40, show_missed=True)
        for secret in self.secrets:
            self.assertNotIn(secret, text)

    def test_rendered_text_still_shows_the_hashes(self) -> None:
        text = render(self.report, 40)
        self.assertIn(digest(TOKEN), text)
        self.assertIn("[来源]", text)

    def test_short_field_values_never_enter_the_report(self) -> None:
        blob = json.dumps(self.report, ensure_ascii=False)
        self.assertNotIn(SHORT_SECRET, blob)


class TestRendering(unittest.TestCase):
    def setUp(self) -> None:
        self.report = run(synthetic_har(), origin_needles=["recaptcha.net"])

    def test_missed_fields_are_folded_by_default(self) -> None:
        text = render(self.report, 40)
        # 一是有命中的请求里，未命中字段被折叠；二是全未命中的请求整条被折叠。
        self.assertIn("未命中，--show-missed 可展开", text)
        self.assertIn("只有未命中的字段，已折叠", text)

    def test_show_missed_lists_them(self) -> None:
        text = render(self.report, 40, show_missed=True)
        self.assertNotIn("--show-missed 可展开", text)
        self.assertIn("User-Agent", text)
        self.assertIn("deviceId", text)

    def test_top_limits_the_listed_requests(self) -> None:
        text = render(self.report, 1)
        self.assertIn("已折叠", text)

    def test_incomplete_pool_is_shouted_about(self) -> None:
        self.assertIn("池子残缺", render(self.report, 40))

    def test_matched_form_is_shown_when_it_is_not_the_raw_value(self) -> None:
        # 命中的是哪种分解要写出来，读者才能自己复核，而不是信一个黑箱结论。
        text = render(run(synthetic_har()), 40)
        self.assertIn("按[去前缀]", text)
        self.assertNotIn("按[原样]", text)

    def test_notes_mention_the_ordering_fix(self) -> None:
        self.assertTrue(any("时间序" in note for note in self.report["notes"]))

    def test_later_hits_are_called_out_as_non_evidence(self) -> None:
        self.assertTrue(any("不是来源" in note for note in self.report["notes"]))


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="origin-test-"))
        self.har_path = self.tmp / "capture.har"
        self.har_path.write_text(json.dumps(synthetic_har()), encoding="utf-8")

    def tearDown(self) -> None:
        for path in sorted(self.tmp.rglob("*"), reverse=True):
            path.unlink()
        self.tmp.rmdir()

    def capture(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_text_run_succeeds_and_stays_clean(self) -> None:
        code, out = self.capture([str(self.har_path)])
        self.assertEqual(code, 0)
        self.assertIn("HAR 字段溯源", out)
        self.assertNotIn(TOKEN, out)

    def test_json_run_is_parseable(self) -> None:
        code, out = self.capture([str(self.har_path), "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertIn("summary", report)

    def test_out_writes_the_json_file(self) -> None:
        target = self.tmp / "origin.json"
        code, _ = self.capture([str(self.har_path), "--json", "--out", str(target)])
        self.assertEqual(code, 0)
        self.assertTrue(target.is_file())
        self.assertIn("pool", json.loads(target.read_text(encoding="utf-8")))

    def test_from_and_to_narrow_the_report(self) -> None:
        code, out = self.capture([str(self.har_path), "--from", "recaptcha.net", "--to", "/v1/sign"])
        self.assertEqual(code, 0)
        self.assertIn("/v1/sign", out)
        self.assertNotIn("/v1/from-cookie", out)

    def test_no_headers_drops_header_fields(self) -> None:
        code, out = self.capture([str(self.har_path), "--no-headers", "--show-missed"])
        self.assertEqual(code, 0)
        self.assertNotIn("User-Agent", out)

    def test_zero_min_length_is_rejected(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = main([str(self.har_path), "--min-length", "0"])
        self.assertEqual(code, 2)
        self.assertIn("正整数", buffer.getvalue())

    def test_missing_file_is_reported(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = main([str(self.tmp / "nope.har")])
        self.assertEqual(code, 2)
        self.assertIn("无法解析", buffer.getvalue())

    def test_non_har_json_is_reported(self) -> None:
        bad = self.tmp / "bad.har"
        bad.write_text('{"not": "a har"}', encoding="utf-8")
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = main([str(bad)])
        self.assertEqual(code, 2)
        self.assertIn("log", buffer.getvalue())

    def test_documented_commands_work(self) -> None:
        # 文档里的每条用法都得真能跑——check_commands.py 只看选项名，跑不了这一层。
        for extra in (
            [],
            ["--from", "recaptcha.net"],
            ["--from", "recaptcha.net", "--to", "example.com"],
            ["--from", "recaptcha.net", "--json"],
        ):
            code, _ = self.capture([str(self.har_path), *extra])
            self.assertEqual(code, 0, extra)


if __name__ == "__main__":
    unittest.main()
