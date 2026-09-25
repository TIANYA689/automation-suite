"""HAR 静态盘点器的离线测试。

夹具是**内联合成 HAR**，不是真实抓包：真实抓包含凭证，不该进仓库，
而这里要验的是"解析与归类逻辑对不对"，不是"某站点长什么样"。

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

from automation.har_probe import (  # noqa: E402
    body_kind,
    classify_entry_order,
    entry_time_key,
    load_har,
    main,
    multipart_file_part_count,
    multipart_parts,
    normalize_path,
    probe,
    redact,
    sort_entries,
    sorted_indexed_entries,
    value_kind,
)

SIGN_A = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
SIGN_B = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


def _entry(
    url: str,
    *,
    method: str = "GET",
    started: str = "2026-09-25T01:00:00.000Z",
    status: int = 200,
    mime: str = "application/json",
    post_data: dict | None = None,
    headers: list[dict] | None = None,
    cookies: list[dict] | None = None,
) -> dict:
    request: dict = {"method": method, "url": url, "headers": headers or []}
    if post_data:
        request["postData"] = post_data
    if cookies:
        request["cookies"] = cookies
    return {
        "startedDateTime": started,
        "request": request,
        "response": {"status": status, "content": {"mimeType": mime}},
    }


def synthetic_har() -> dict:
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "synthetic-fixture"},
            "pages": [{"id": "page_1"}],
            "entries": [
                _entry(
                    "https://cdn.example.com/static/app.css",
                    started="2026-09-25T01:00:00.000Z",
                    mime="text/css",
                ),
                _entry(
                    "https://api.example.com/v1/user/12345/profile?uid=12345",
                    started="2026-09-25T01:00:01.000Z",
                    headers=[{"name": "Authorization", "value": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"}],
                    cookies=[{"name": "SESSIONID", "value": "9f8e7d6c5b4a39281706f5e4d3c2b1a0"}],
                ),
                _entry(
                    "https://api.example.com/v1/user/67890/profile?uid=67890",
                    started="2026-09-25T01:00:02.000Z",
                ),
                _entry(
                    "https://api.example.com/v1/auth/login",
                    method="POST",
                    started="2026-09-25T01:00:03.000Z",
                    post_data={
                        "mimeType": "application/json",
                        "text": json.dumps(
                            {
                                "phone": "13800000000",
                                "password": "example-password",
                                "deviceId": "web-01",
                            }
                        ),
                    },
                ),
                _entry(
                    "https://api.example.com/v1/sign/in",
                    method="POST",
                    started="2026-09-25T01:00:04.000Z",
                    post_data={
                        "mimeType": "application/json",
                        "text": json.dumps(
                            {"uid": "12345", "sign": SIGN_A, "ts": 1758700000, "nonce": "n-1"}
                        ),
                    },
                ),
                _entry(
                    "https://api.example.com/v1/sign/in",
                    method="POST",
                    started="2026-09-25T01:00:05.000Z",
                    post_data={
                        "mimeType": "application/json",
                        "text": json.dumps(
                            {"uid": "12345", "sign": SIGN_B, "ts": 1758700060, "nonce": "n-2"}
                        ),
                    },
                ),
                # 时间戳刻意逐个递增：这份夹具就是"数组顺序恰好是时间序"的样子，
                # 用来和真实抓包（基本是倒序）区分开。
                _entry(
                    "https://api.example.com/v1/asset/a.png",
                    started="2026-09-25T01:00:05.500Z",
                    mime="image/png",
                ),
                {"startedDateTime": "2026-09-25T01:00:06.000Z", "request": {}, "response": {}},
            ],
        }
    }


MULTIPART_BOUNDARY = "----WebKitFormBoundaryTESTBOUNDARY"


def multipart_body(parts: list[tuple[str, str, str | None]]) -> str:
    """拼一段 multipart 原文。(name, value, filename) 三元组，filename 为 None 即文本 part。"""
    chunks = []
    for name, value, filename in parts:
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        chunks.append(f"{disposition}\r\n\r\n{value}\r\n")
    return (
        f"--{MULTIPART_BOUNDARY}\r\n"
        + f"--{MULTIPART_BOUNDARY}\r\n".join(chunks)
        + f"--{MULTIPART_BOUNDARY}--\r\n"
    )


def multipart_post(parts: list[tuple[str, str, str | None]]) -> dict:
    """ProxyPin 的真实形态：`params` 是空的，字段只在 text 里。"""
    return {
        "mimeType": f"multipart/form-data; boundary={MULTIPART_BOUNDARY}",
        "params": [],
        "text": multipart_body(parts),
    }


def multipart_har() -> dict:
    """合成抓包 + 两个 multipart 端点：一个纯文本、一个带文件字段。

    真实抓包逼出来的场景：阿瓦隆的登录与取验证码都是**纯文本** multipart，
    而文件字段那一侧是真的还原不出来，必须继续拒绝——两条路要分开。
    """
    har = synthetic_har()
    har["log"]["entries"].extend(
        [
            _entry(
                "https://api.example.com/v1/auth/code",
                method="POST",
                started="2026-09-25T01:00:07.000Z",
                post_data=multipart_post(
                    [
                        ("loginName", "a@example.com", None),
                        ("token", "03AFcWeA" + "z" * 200, None),
                    ]
                ),
            ),
            _entry(
                "https://api.example.com/v1/upload/avatar",
                method="POST",
                started="2026-09-25T01:00:08.000Z",
                post_data=multipart_post([("photo", "\x00\x01binary", "a.png")]),
            ),
        ]
    )
    return har


class TestValueHelpers(unittest.TestCase):
    def test_normalize_path_collapses_ids(self) -> None:
        self.assertEqual(normalize_path("/v1/user/12345/profile"), "/v1/user/{id}/profile")
        self.assertEqual(
            normalize_path("/v1/order/550e8400-e29b-41d4-a716-446655440000/items"),
            "/v1/order/{uuid}/items",
        )
        self.assertEqual(normalize_path("/v1/blob/" + "a" * 32), "/v1/blob/{hash}")

    def test_normalize_path_keeps_words(self) -> None:
        self.assertEqual(normalize_path("/v1/sign/in"), "/v1/sign/in")
        self.assertEqual(normalize_path("/"), "/")

    def test_redact_masks_middle(self) -> None:
        masked = redact(SIGN_A)
        self.assertTrue(masked.startswith(SIGN_A[:4]))
        self.assertTrue(masked.endswith(SIGN_A[-4:]))
        self.assertNotIn(SIGN_A, masked)
        self.assertEqual(redact("abc"), "***")

    def test_value_kind_classifies(self) -> None:
        self.assertEqual(value_kind(SIGN_A), "hex32")
        self.assertEqual(value_kind("1758700000"), "timestamp_s")
        self.assertEqual(value_kind("1758700000000"), "timestamp_ms")
        self.assertEqual(value_kind("550e8400-e29b-41d4-a716-446655440000"), "uuid")
        self.assertEqual(value_kind("plain-text"), "plain")
        self.assertEqual(value_kind(""), "empty")

    def test_value_kind_does_not_call_short_hex_a_signature(self) -> None:
        self.assertEqual(value_kind("abc123"), "plain")

    def test_body_kind_detects_shape(self) -> None:
        self.assertEqual(body_kind(None), "empty")
        self.assertEqual(body_kind({"mimeType": "application/json; charset=utf-8"}), "json")
        self.assertEqual(body_kind({"mimeType": "application/x-www-form-urlencoded"}), "form")
        self.assertEqual(body_kind({"mimeType": "multipart/form-data"}), "multipart")

    def test_empty_post_data_is_not_unknown(self) -> None:
        # 实测 ProxyPin 会给每个请求挂一个空的 postData 对象。报成 unknown 会让
        # 下游把 GET 误判成"有请求体但看不懂"——这是被真实抓包暴露出来的判据。
        self.assertEqual(body_kind({"mimeType": "", "text": ""}), "empty")
        self.assertEqual(body_kind({"mimeType": "", "text": "raw-payload"}), "text")
        self.assertEqual(body_kind({"mimeType": "application/octet-stream"}), "application/octet-stream")


class TestEntryOrder(unittest.TestCase):
    """entries 数组顺序不携带时间信息——实测 ProxyPin 导出基本是倒序且非严格。"""

    def test_classify_recognises_the_three_shapes(self) -> None:
        self.assertEqual(classify_entry_order(["a", "b", "c"]), "chronological")
        self.assertEqual(classify_entry_order(["c", "b", "a"]), "reversed")
        self.assertEqual(classify_entry_order(["a", "c", "b"]), "unsorted")

    def test_classify_tolerates_empty_input(self) -> None:
        self.assertEqual(classify_entry_order([]), "chronological")
        self.assertEqual(classify_entry_order(["a"]), "chronological")

    def test_entry_time_key_puts_missing_timestamps_last(self) -> None:
        with_stamp = entry_time_key({"startedDateTime": "2026-01-01T00:00:00.000Z"}, 5)
        without = entry_time_key({}, 0)
        self.assertLess(with_stamp, without)

    def test_entry_time_key_is_stable_for_equal_stamps(self) -> None:
        first = entry_time_key({"startedDateTime": "same"}, 1)
        second = entry_time_key({"startedDateTime": "same"}, 2)
        self.assertLess(first, second)

    def test_sort_entries_reorders_and_keeps_everything(self) -> None:
        entries = [
            {"startedDateTime": "2026-01-01T00:00:02.000Z", "id": "c"},
            {"startedDateTime": "2026-01-01T00:00:00.000Z", "id": "a"},
            {"startedDateTime": "2026-01-01T00:00:01.000Z", "id": "b"},
        ]
        self.assertEqual([item["id"] for item in sort_entries(entries)], ["a", "b", "c"])
        self.assertEqual(len(sort_entries(entries)), 3)

    def test_sorted_indexed_entries_keeps_the_original_index(self) -> None:
        entries = [{"startedDateTime": "2026-01-01T00:00:01.000Z"}, {"startedDateTime": ""}]
        self.assertEqual([index for index, _ in sorted_indexed_entries(entries)], [0, 1])
        self.assertEqual(
            [index for index, _ in sorted_indexed_entries(list(reversed(entries)))], [1, 0]
        )


class TestProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = probe(synthetic_har(), include_static=False, redact_values=True)

    def test_summary_counts(self) -> None:
        summary = self.report["summary"]
        self.assertEqual(summary["entries_total"], 8)
        self.assertEqual(summary["entries_api"], 5)
        self.assertEqual(summary["entries_static"], 2)
        self.assertEqual(summary["entries_unparsed"], 1)
        self.assertEqual(summary["endpoints"], 3)

    def test_static_entries_do_not_reach_endpoint_list(self) -> None:
        paths = {row["path"] for row in self.report["endpoints"]}
        self.assertNotIn("/static/app.css", paths)
        self.assertNotIn("/v1/asset/a.png", paths)

    def test_same_endpoint_with_different_ids_merges(self) -> None:
        merged = [row for row in self.report["endpoints"] if row["path"] == "/v1/user/{id}/profile"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["count"], 2)

    def test_endpoints_sorted_by_count(self) -> None:
        counts = [row["count"] for row in self.report["endpoints"]]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_sequence_preserves_time_order(self) -> None:
        self.assertEqual(self.report["sequence"][0], "GET /v1/user/{id}/profile")
        self.assertEqual(self.report["sequence"][-1], "POST /v1/sign/in")

    def test_synthetic_fixture_is_already_chronological(self) -> None:
        self.assertEqual(self.report["summary"]["entry_order"], "chronological")

    def test_reversed_entries_are_reported_and_resequenced(self) -> None:
        # HAR 规范不要求 entries 按时间排；实测 ProxyPin 导出基本是倒序。
        # 数组顺序倒过来，接口清单不该变，但调用时序必须仍按时间。
        har = synthetic_har()
        har["log"]["entries"] = list(reversed(har["log"]["entries"]))
        report = probe(har, include_static=False, redact_values=True)
        self.assertEqual(report["summary"]["entry_order"], "reversed")
        self.assertEqual(report["sequence"], self.report["sequence"])
        self.assertEqual(
            {row["path"] for row in report["endpoints"]},
            {row["path"] for row in self.report["endpoints"]},
        )
        self.assertTrue(any("时间序" in note for note in report["notes"]))

    def test_missing_timestamps_are_reported_as_unsorted(self) -> None:
        har = synthetic_har()
        har["log"]["entries"][2]["startedDateTime"] = ""
        report = probe(har, include_static=False, redact_values=True)
        self.assertEqual(report["summary"]["entry_order"], "unsorted")

    def test_sensitive_fields_found(self) -> None:
        names = {row["name"] for row in self.report["fields"]["sensitive"]}
        self.assertIn("password", names)
        self.assertIn("SESSIONID", names)
        self.assertIn("Authorization", names)

    def test_signature_candidates_found(self) -> None:
        names = {row["name"] for row in self.report["fields"]["signature_candidates"]}
        self.assertIn("sign", names)

    def test_volatile_candidates_found(self) -> None:
        names = {row["name"] for row in self.report["fields"]["volatile_candidates"]}
        self.assertIn("ts", names)
        self.assertIn("nonce", names)

    def test_output_is_redacted_by_default(self) -> None:
        blob = json.dumps(self.report, ensure_ascii=False)
        self.assertNotIn(SIGN_A, blob)
        self.assertNotIn("example-password", blob)
        self.assertTrue(self.report["redacted"])

    def test_no_redact_keeps_values(self) -> None:
        raw = probe(synthetic_har(), include_static=False, redact_values=False)
        blob = json.dumps(raw, ensure_ascii=False)
        self.assertIn(SIGN_A, blob)
        self.assertFalse(raw["redacted"])

    def test_include_static_expands_endpoint_list(self) -> None:
        expanded = probe(synthetic_har(), include_static=True, redact_values=True)
        paths = {row["path"] for row in expanded["endpoints"]}
        self.assertIn("/static/app.css", paths)

    def test_notes_flag_signature_and_credential_risk(self) -> None:
        joined = " ".join(self.report["notes"])
        self.assertIn("签名", joined)
        self.assertIn("凭证", joined)


class TestLoadAndCli(unittest.TestCase):
    def test_rejects_non_har_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-a-har.json"
            path.write_text('{"foo": 1}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_har(str(path))

    def test_rejects_broken_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.har"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                load_har(str(path))

    def test_cli_writes_json_and_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har_path = Path(directory) / "capture.har"
            out_path = Path(directory) / "probe.json"
            har_path.write_text(json.dumps(synthetic_har()), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main([str(har_path), "--json", "--out", str(out_path)])
            self.assertEqual(code, 0)
            self.assertTrue(out_path.is_file())
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["entries_total"], 8)
            self.assertEqual(json.loads(stdout.getvalue())["summary"]["entries_api"], 5)

    def test_cli_returns_two_on_unreadable_input(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["does-not-exist.har"])
        self.assertEqual(code, 2)
        self.assertIn("无法解析", stderr.getvalue())

    def test_cli_timeline_renders_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har_path = Path(directory) / "capture.har"
            har_path.write_text(json.dumps(synthetic_har()), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main([str(har_path), "--timeline", "--top", "3"])
            self.assertEqual(code, 0)
            self.assertIn("调用时序", stdout.getvalue())

    def test_timeline_title_says_when_it_was_reordered(self) -> None:
        # 重排必须写在标题上，否则读者会以为这就是文件里数组的原样。
        har = synthetic_har()
        har["log"]["entries"] = list(reversed(har["log"]["entries"]))
        with tempfile.TemporaryDirectory() as directory:
            har_path = Path(directory) / "capture.har"
            har_path.write_text(json.dumps(har), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main([str(har_path), "--timeline"])
            self.assertIn("已按 startedDateTime 重排", stdout.getvalue())

    def test_timeline_title_stays_quiet_when_order_was_fine(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har_path = Path(directory) / "capture.har"
            har_path.write_text(json.dumps(synthetic_har()), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main([str(har_path), "--timeline"])
            self.assertIn("数组即时间序", stdout.getvalue())


class TestMultipartParsing(unittest.TestCase):
    """multipart 原文解析。

    为什么必须有这一组：ProxyPin 对 multipart 给的是**空** `params`
    （实测 `"params": []`），字段只在 `text` 里。只读 `params` 会让
    multipart 里的参数名完全不可见——`token` 这类易变字段因此进不了
    `volatile_candidates`，写计划的人看不到"这个值每次都在变"。
    """

    BOUNDARY = "----WebKitFormBoundaryTESTBOUNDARY"

    def _post(self, text: str) -> dict:
        return {"mimeType": f"multipart/form-data; boundary={self.BOUNDARY}", "params": [], "text": text}

    def test_parts_are_recovered_from_raw_text(self) -> None:
        text = (
            f"--{self.BOUNDARY}\r\n"
            'Content-Disposition: form-data; name="loginName"\r\n\r\n'
            "a@example.com\r\n"
            f"--{self.BOUNDARY}\r\n"
            'Content-Disposition: form-data; name="password"\r\n\r\n'
            "hunter2\r\n"
            f"--{self.BOUNDARY}--\r\n"
        )
        parts = multipart_parts(self._post(text))
        self.assertEqual([part["name"] for part in parts], ["loginName", "password"])
        self.assertEqual(parts[0]["value"], "a@example.com")
        self.assertEqual(parts[1]["value"], "hunter2")

    def test_file_part_is_counted_not_listed_as_field(self) -> None:
        text = (
            f"--{self.BOUNDARY}\r\n"
            'Content-Disposition: form-data; name="photo"; filename="a.png"\r\n\r\n'
            "\x00\x01binary\r\n"
            f"--{self.BOUNDARY}--\r\n"
        )
        post = self._post(text)
        self.assertEqual(1, multipart_file_part_count(post))
        self.assertEqual(1, len(multipart_parts(post)))

    def test_missing_boundary_yields_nothing(self) -> None:
        self.assertEqual([], multipart_parts({"mimeType": "multipart/form-data", "text": "x"}))

    def test_non_multipart_is_ignored(self) -> None:
        self.assertEqual([], multipart_parts({"mimeType": "application/json", "text": "{}"}))
        self.assertEqual([], multipart_parts(None))

    def test_endpoint_row_reports_file_part_count(self) -> None:
        har = synthetic_har()
        har["log"]["entries"].append(
            _entry(
                "https://api.example.com/v1/upload/avatar",
                method="POST",
                post_data=self._post(
                    f"--{self.BOUNDARY}\r\n"
                    'Content-Disposition: form-data; name="photo"; filename="a.png"\r\n\r\n'
                    "x\r\n"
                    f"--{self.BOUNDARY}--\r\n"
                ),
            )
        )
        report = probe(har, include_static=False, redact_values=True)
        row = next(r for r in report["endpoints"] if r["path"] == "/v1/upload/avatar")
        self.assertEqual(1, row["multipart_file_parts"])

    def test_text_only_multipart_has_zero_file_parts(self) -> None:
        har = synthetic_har()
        har["log"]["entries"].append(
            _entry(
                "https://api.example.com/v1/auth/code",
                method="POST",
                post_data=self._post(
                    f"--{self.BOUNDARY}\r\n"
                    'Content-Disposition: form-data; name="loginName"\r\n\r\n'
                    "a@example.com\r\n"
                    f"--{self.BOUNDARY}--\r\n"
                ),
            )
        )
        report = probe(har, include_static=False, redact_values=True)
        row = next(r for r in report["endpoints"] if r["path"] == "/v1/auth/code")
        self.assertEqual(0, row["multipart_file_parts"])

    def test_multipart_fields_reach_volatile_candidates(self) -> None:
        """multipart 里的长随机串必须被看见，否则写计划的人不知道它每次都在变。"""
        token = "03AFcWeA" + "z" * 200
        har = synthetic_har()
        har["log"]["entries"].append(
            _entry(
                "https://api.example.com/v1/auth/code",
                method="POST",
                post_data=self._post(
                    f"--{self.BOUNDARY}\r\n"
                    'Content-Disposition: form-data; name="token"\r\n\r\n'
                    f"{token}\r\n"
                    f"--{self.BOUNDARY}--\r\n"
                ),
            )
        )
        report = probe(har, include_static=False, redact_values=True)
        names = {row["name"] for row in report["fields"]["volatile_candidates"]}
        self.assertIn("token", names)
        where = next(r for r in report["fields"]["volatile_candidates"] if r["name"] == "token")
        self.assertIn("body.multipart", where["where"])


if __name__ == "__main__":
    unittest.main()
