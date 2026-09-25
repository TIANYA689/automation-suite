"""HAR 降级器的离线测试。

夹具的验收标准只有一条：**降级之后，判据还成立吗**。所以这里最重的两个用例是
`test_fidelity_*`——如果替换动作把"哪些参数在变"的证据改掉了，夹具就是废纸，
哪怕它看起来完全脱敏了。

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
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))

from automation.har_probe import probe, value_kind  # noqa: E402
from automation.har_to_fixture import (  # noqa: E402
    anonymize,
    fake_value,
    fidelity,
    main,
    self_check,
)
from test_har_probe import (  # noqa: E402
    MULTIPART_BOUNDARY,
    SIGN_A,
    SIGN_B,
    multipart_har,
    synthetic_har,
)

COOKIE_VALUE = "9f8e7d6c5b4a39281706f5e4d3c2b1a0"
PHONE = "13800000000"


def fixture_and_stats(**kwargs) -> tuple[dict, dict]:
    return anonymize(synthetic_har(), **kwargs)


class TestFakeValue(unittest.TestCase):
    def test_deterministic(self) -> None:
        self.assertEqual(fake_value(SIGN_A), fake_value(SIGN_A))
        self.assertNotEqual(fake_value(SIGN_A), fake_value(SIGN_B))

    def test_shape_is_preserved(self) -> None:
        cases = [
            SIGN_A,  # hex32
            "9f8e7d6c5b4a39281706f5e4d3c2b1a0",  # hex32
            "550e8400-e29b-41d4-a716-446655440000",  # uuid
            PHONE,  # number
            "user@example.com",  # email
            "QWERTYUIOPasdfghjkl1234567890",  # opaque_base64ish
        ]
        for original in cases:
            with self.subTest(original=original):
                self.assertEqual(value_kind(fake_value(original)), value_kind(original))

    def test_timestamps_are_preserved(self) -> None:
        self.assertEqual(fake_value("1758700000"), "1758700000")
        self.assertEqual(fake_value("1758700000000"), "1758700000000")

    def test_numbers_keep_length_and_leading_digit(self) -> None:
        fake = fake_value("0500000001")
        self.assertEqual(len(fake), len("0500000001"))
        self.assertEqual(fake[0], "0")
        self.assertEqual(value_kind(fake), "number")

    def test_sensitive_values_get_a_visible_marker(self) -> None:
        # 明文敏感值要能一眼看出被替换过。
        self.assertTrue(fake_value("some-token-value", sensitive=True).startswith("REDACTED-"))

    def test_shape_preservation_wins_over_the_marker(self) -> None:
        # 形态保真优先于"看起来像被脱敏了"：sign 必须还是 hex32，
        # 否则 har_probe 的动态性判据失效，夹具就成了废纸。
        fake = fake_value(SIGN_A, sensitive=True)
        self.assertEqual(value_kind(fake), "hex32")
        self.assertFalse(fake.startswith("REDACTED-"))

    def test_empty_stays_empty(self) -> None:
        self.assertEqual(fake_value(""), "")


class TestAnonymize(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture, cls.stats = fixture_and_stats()
        cls.original = synthetic_har()

    def test_har_shape_is_kept(self) -> None:
        self.assertEqual(self.fixture["log"]["creator"]["name"], "har_to_fixture")
        self.assertEqual(self.fixture["log"]["version"], "1.2")
        self.assertTrue(self.fixture["log"]["entries"])

    def test_hosts_are_anonymized(self) -> None:
        text = json.dumps(self.fixture, ensure_ascii=False)
        self.assertNotIn("api.example.com", text.replace("host-", ""))
        self.assertNotIn("cdn.example.com", text)
        self.assertIn("host-1.example.com", text)

    def test_same_host_maps_to_same_label(self) -> None:
        urls = [entry["request"]["url"] for entry in self.fixture["log"]["entries"]]
        api_urls = [url for url in urls if "/v1/" in url]
        self.assertTrue(api_urls)
        for url in api_urls:
            self.assertTrue(url.startswith("https://host-"), url)

    def test_host_header_follows_the_url(self) -> None:
        # Host 头若走通用值替换，就会与 URL 里的域名自相矛盾，夹具立刻失真。
        for entry in self.fixture["log"]["entries"]:
            for header in entry["request"].get("headers") or []:
                if header["name"].casefold() == "host":
                    self.assertIn("example.com", header["value"])

    def test_no_original_value_survives(self) -> None:
        text = json.dumps(self.fixture, ensure_ascii=False)
        for leaked in (SIGN_A, SIGN_B, COOKIE_VALUE, PHONE, "web-01", "example-password"):
            self.assertNotIn(leaked, text)

    def test_url_query_values_are_replaced(self) -> None:
        text = json.dumps(self.fixture, ensure_ascii=False)
        self.assertIn("uid=", text)
        self.assertNotIn("uid=12345", text)

    def test_cross_references_stay_consistent(self) -> None:
        # 同一个原值出现在两处时必须换成同一个假值，否则"常量"会看起来像"变量"。
        bodies = [
            json.loads(entry["request"]["postData"]["text"])
            for entry in self.fixture["log"]["entries"]
            if entry["request"].get("postData", {}).get("mimeType", "").find("json") >= 0
        ]
        uids = [body["uid"] for body in bodies if "uid" in body]
        self.assertEqual(len(set(uids)), 1)

    def test_response_body_and_headers_are_dropped(self) -> None:
        for entry in self.fixture["log"]["entries"]:
            response = entry["response"]
            self.assertNotIn("headers", response)
            self.assertNotIn("text", response["content"])
            self.assertIn("mimeType", response["content"])
            self.assertIn("status", response)

    def test_started_time_is_normalized_with_offsets_preserved(self) -> None:
        # 降级只做"归一"，不做"重排"：条目顺序与输入一致，时间戳按偏移量平移。
        stamps = [entry["startedDateTime"] for entry in self.fixture["log"]["entries"]]
        self.assertTrue(all(stamp.startswith("2020-01-01T") for stamp in stamps))
        self.assertEqual(
            stamps,
            [
                "2020-01-01T00:00:00.000Z",
                "2020-01-01T00:00:01.000Z",
                "2020-01-01T00:00:02.000Z",
                "2020-01-01T00:00:03.000Z",
                "2020-01-01T00:00:04.000Z",
                "2020-01-01T00:00:05.000Z",
                # 输入夹具里这条是 05.500s（刻意为让数组严格递增）。
                # 亚秒必须原样留下：reCAPTCHA 令牌与用它的请求只差 0.24~0.39 秒，
                # 压到整秒会让 har_origin 的「来源」静默退化成「回显」。
                "2020-01-01T00:00:05.500Z",
            ],
        )

    def test_sub_second_offsets_survive_anonymization(self) -> None:
        # 亚秒精度不能丢。实测 reCAPTCHA 令牌与用它的请求只差 0.24~0.39 秒，
        # 压到整秒会让按时间判先后的东西静默失效（har_probe 的调用链、har_origin
        # 的来源判定），而夹具的契约是"只做归一，不做重排"。
        har = synthetic_har()
        har["log"]["entries"][1]["startedDateTime"] = "2026-09-25T01:00:01.000Z"
        har["log"]["entries"][2]["startedDateTime"] = "2026-09-25T01:00:01.390Z"
        fixture, _ = anonymize(har)
        stamps = [entry["startedDateTime"] for entry in fixture["log"]["entries"]]
        self.assertEqual(stamps[1], "2020-01-01T00:00:01.000Z")
        self.assertEqual(stamps[2], "2020-01-01T00:00:01.390Z")
        # 归一之后相对间隔也必须原样保留。
        self.assertEqual(
            probe(fixture, include_static=False, redact_values=True)["summary"]["first_seen"],
            "2020-01-01T00:00:00.000Z",
        )

    def test_timestamps_inside_parameters_are_kept(self) -> None:
        bodies = [
            json.loads(entry["request"]["postData"]["text"])
            for entry in self.fixture["log"]["entries"]
            if "sign" in (entry["request"].get("postData") or {}).get("text", "")
        ]
        self.assertTrue(bodies)
        self.assertEqual({body["ts"] for body in bodies}, {1758700000, 1758700060})

    def test_sampling_keeps_one_per_endpoint_when_asked(self) -> None:
        _, stats = fixture_and_stats(samples_per_endpoint=1)
        self.assertEqual(stats["entries_out"], 5)

    def test_max_entries_caps_the_fixture(self) -> None:
        _, stats = fixture_and_stats(samples_per_endpoint=2, max_entries=3)
        self.assertEqual(stats["entries_out"], 3)

    def test_deterministic_across_runs(self) -> None:
        first, _ = fixture_and_stats()
        second, _ = fixture_and_stats()
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True),
            json.dumps(second, ensure_ascii=False, sort_keys=True),
        )


class TestPathHandling(unittest.TestCase):
    def test_paths_kept_by_default(self) -> None:
        fixture, stats = fixture_and_stats()
        self.assertEqual(stats["segments_anonymized"], 0)
        text = json.dumps(fixture, ensure_ascii=False)
        self.assertIn("/v1/sign/in", text)

    def test_anonymize_paths_maps_segments(self) -> None:
        fixture, stats = fixture_and_stats(anonymize_paths=True)
        self.assertGreater(stats["segments_anonymized"], 0)
        text = json.dumps(fixture, ensure_ascii=False)
        self.assertNotIn("/v1/sign/in", text)
        self.assertIn("/seg-1/", text)

    def test_distinct_endpoints_stay_distinct_after_anonymizing_paths(self) -> None:
        # 段映射必须是保序且单射的，否则不同接口会被合并成一条，夹具就测不出归并逻辑了。
        fixture, _ = fixture_and_stats(anonymize_paths=True)
        paths = {row["path"] for row in probe(fixture, include_static=False, redact_values=True)["endpoints"]}
        self.assertEqual(len(paths), 3)

    def test_id_like_segments_keep_their_shape(self) -> None:
        fixture, _ = fixture_and_stats()
        paths = {row["path"] for row in probe(fixture, include_static=False, redact_values=True)["endpoints"]}
        self.assertIn("/v1/user/{id}/profile", paths)

    def test_redact_terms_only_touch_matching_segments(self) -> None:
        fixture, stats = fixture_and_stats(redact_terms=["sign"])
        self.assertEqual(stats["segments_anonymized"], 1)
        text = json.dumps(fixture, ensure_ascii=False)
        self.assertNotIn("/v1/sign/in", text)
        self.assertIn("/v1/auth/login", text)


class TestSelfCheck(unittest.TestCase):
    def test_clean_fixture_passes(self) -> None:
        fixture, _ = fixture_and_stats()
        self.assertEqual(self_check(fixture, synthetic_har()), [])

    def test_leak_is_detected(self) -> None:
        fixture, _ = fixture_and_stats()
        fixture["log"]["entries"][1]["request"]["headers"].append(
            {"name": "X-Session", "value": COOKIE_VALUE}
        )
        problems = self_check(fixture, synthetic_har())
        self.assertEqual(len(problems), 1)
        self.assertIn("仍留在夹具的值槽位里", problems[0])

    def test_structural_fields_are_not_treated_as_values(self) -> None:
        # 方法名与 MIME 类型是结构字段。把它们当"值"比对，会在每个夹具上
        # 产生永久假阳性——这是被真实抓包（ProxyPin）暴露出来的。
        fixture, _ = fixture_and_stats()
        self.assertEqual(self_check(fixture, synthetic_har()), [])
        text = json.dumps(fixture, ensure_ascii=False)
        self.assertIn('"method": "POST"', text)
        self.assertIn("application/json", text)

    def test_substring_matches_do_not_count_as_leaks(self) -> None:
        # 值比对必须是槽位相等，不是子串包含：否则一个短值会命中长路径段。
        original = synthetic_har()
        original["log"]["entries"][1]["request"]["headers"].append(
            {"name": "X-Dest", "value": "profile"}
        )
        fixture, _ = anonymize(original, samples_per_endpoint=2)
        # 夹具里仍有 .../profile 这个路径段，但它不等于那个值，所以不算泄漏。
        self.assertIn("/profile", json.dumps(fixture, ensure_ascii=False))
        self.assertEqual(self_check(fixture, original), [])

    def test_semantic_path_segments_are_not_slots(self) -> None:
        # 语义路径段是设计上要保留的，把它当槽位会让同名请求头值变成永久假阳性。
        fixture, _ = fixture_and_stats()
        original = synthetic_har()
        original["log"]["entries"][1]["request"]["headers"].append(
            {"name": "X-Dest", "value": "login"}
        )
        self.assertIn("/v1/auth/login", json.dumps(fixture, ensure_ascii=False))
        self.assertEqual(self_check(fixture, original), [])

    def test_unreplaced_identifier_path_segment_is_caught(self) -> None:
        # 标识符形态的路径段必须已被替换；若它原样留在夹具里，就是一条泄漏通道。
        original = synthetic_har()
        original["log"]["entries"][1]["request"]["url"] = (
            "https://api.example.com/v1/user/9f8e7d6c5b4a39281706f5e4d3c2b1a0/profile?uid=12345"
        )
        fixture, _ = anonymize(original, samples_per_endpoint=2)
        # 正常路径：标识符段被替换，自检通过。
        self.assertEqual(self_check(fixture, original), [])

        # 人为把替换后的段改回原值，模拟"替换漏了这一段"。
        for entry in fixture["log"]["entries"]:
            entry["request"]["url"] = entry["request"]["url"].replace(
                entry["request"]["url"].split("/v1/user/")[1].split("/")[0], COOKIE_VALUE
            ) if "/v1/user/" in entry["request"]["url"] else entry["request"]["url"]
        problems = self_check(fixture, original)
        self.assertTrue(problems)
        self.assertIn("仍留在夹具的值槽位里", problems[0])

    def test_unparseable_fixture_is_detected(self) -> None:
        # probe 对畸形输入是宽容的，"没抛异常"不等于"解析成功"。
        problems = self_check({"nope": True}, synthetic_har())
        self.assertTrue(problems)
        self.assertIn("没有可解析的条目", problems[0])


class TestFidelity(unittest.TestCase):
    def test_endpoints_and_shapes_survive(self) -> None:
        fixture, _ = fixture_and_stats()
        report = fidelity(synthetic_har(), fixture)
        self.assertTrue(report["ok"])
        self.assertEqual(report["endpoints_before"], report["endpoints_after"])
        self.assertEqual(report["shape_changes"], [])
        self.assertEqual(report["sensitive_before"], report["sensitive_after"])

    def test_signature_shape_specifically_survives(self) -> None:
        # 这是整条工具链的命门：sign 必须还是 hex32，否则 har_to_script 推不出策略。
        fixture, _ = fixture_and_stats()
        before = probe(synthetic_har(), include_static=False, redact_values=True)
        after = probe(fixture, include_static=False, redact_values=True)

        def kinds(report: dict, name: str) -> set[str]:
            for bucket in ("signature_candidates", "volatile_candidates"):
                for row in report["fields"][bucket]:
                    if row["name"] == name:
                        return set(row["value_kinds"])
            return set()

        self.assertEqual(kinds(after, "sign"), kinds(before, "sign"))
        self.assertEqual(kinds(after, "sign"), {"hex32"})

    def test_fidelity_reports_a_broken_shape(self) -> None:
        fixture, _ = fixture_and_stats()
        for entry in fixture["log"]["entries"]:
            text = (entry["request"].get("postData") or {}).get("text", "")
            if "sign" in text:
                body = json.loads(text)
                body["sign"] = "not-a-hash-anymore"
                entry["request"]["postData"]["text"] = json.dumps(body)
        report = fidelity(synthetic_har(), fixture)
        self.assertFalse(report["ok"])
        self.assertTrue(report["shape_changes"])


class TestMultipartScrubbing(unittest.TestCase):
    """multipart 请求体的脱敏必须**保结构**。

    原先 `_scrub_body` 没有 multipart 分支，整个 body 被当一个字符串替换——
    part 数变成 1、字段名全消失，而 `body_kinds` 还写着 multipart。
    夹具与原件不同形，就不能再当证据用。
    """

    def _body(self, fixture: dict, path: str) -> str:
        for entry in fixture["log"]["entries"]:
            if entry["request"].get("url", "").endswith(path):
                return entry["request"]["postData"]["text"]
        raise AssertionError(f"夹具里没有 {path}")

    def test_structure_survives(self) -> None:
        fixture, _ = anonymize(multipart_har())
        text = self._body(fixture, "/v1/auth/code")
        self.assertIn(MULTIPART_BOUNDARY, text)
        self.assertIn('name="loginName"', text)
        self.assertIn('name="token"', text)
        # 两个 part：分隔符出现 1（开头）+ 1（中间）+ 1（收尾）= 3 次
        self.assertEqual(3, text.count(f"--{MULTIPART_BOUNDARY}"))

    def test_values_are_replaced(self) -> None:
        fixture, _ = anonymize(multipart_har())
        text = self._body(fixture, "/v1/auth/code")
        self.assertNotIn("a@example.com", text)
        self.assertNotIn("03AFcWeA", text)

    def test_opaque_shape_survives(self) -> None:
        """token 必须还是等长的 opaque 串，否则 har_probe 判不出它在变。"""
        original = "03AFcWeA" + "z" * 200
        fixture, _ = anonymize(multipart_har())
        text = self._body(fixture, "/v1/auth/code")
        value = text.split('name="token"')[1].split("\r\n\r\n", 1)[1].split("\r\n")[0]
        self.assertEqual(len(original), len(value))
        self.assertEqual("opaque_base64ish", value_kind(value))

    def test_file_part_content_is_emptied_and_filename_replaced(self) -> None:
        fixture, _ = anonymize(multipart_har())
        text = self._body(fixture, "/v1/upload/avatar")
        self.assertIn('name="photo"', text)
        self.assertIn("filename=", text)
        self.assertNotIn("binary", text)
        self.assertNotIn('filename="a.png"', text)

    def test_probe_sees_the_same_endpoints_and_body_kinds(self) -> None:
        fixture, _ = anonymize(multipart_har())
        before = probe(multipart_har(), include_static=False, redact_values=True)
        after = probe(fixture, include_static=False, redact_values=True)
        self.assertEqual(
            [(row["method"], row["path"]) for row in before["endpoints"]],
            [(row["method"], row["path"]) for row in after["endpoints"]],
        )
        kinds = {
            row["path"]: {k for k in row["body_kinds"] if k != "empty"} for row in after["endpoints"]
        }
        self.assertEqual({"multipart"}, kinds["/v1/auth/code"])

    def test_fidelity_still_passes_on_a_multipart_capture(self) -> None:
        fixture, _ = anonymize(multipart_har())
        report = fidelity(multipart_har(), fixture)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["shape_changes"], [])


class TestCli(unittest.TestCase):
    def _har_file(self, directory: str) -> Path:
        path = Path(directory) / "capture.har"
        path.write_text(json.dumps(synthetic_har()), encoding="utf-8", newline="\n")
        return path

    def test_writes_fixture_and_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = self._har_file(directory)
            target = Path(directory) / "fixture.har"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main([str(har), "--out", str(target)])
            self.assertEqual(code, 0)
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["log"]["creator"]["name"], "har_to_fixture")
            self.assertIn("证据保真度", stdout.getvalue())

    def test_map_out_writes_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = self._har_file(directory)
            mapping = Path(directory) / "map.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main([str(har), "--out", str(Path(directory) / "f.har"), "--map-out", str(mapping)])
            self.assertEqual(code, 0)
            payload = json.loads(mapping.read_text(encoding="utf-8"))
            self.assertIn("host_map", payload)
            self.assertIn("api.example.com", payload["host_map"])

    def test_json_mode_reports_stats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = self._har_file(directory)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main([str(har), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["stats"]["entries_in"], 8)
            self.assertTrue(payload["fidelity"]["ok"])

    def test_refuses_to_write_when_self_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = self._har_file(directory)
            target = Path(directory) / "fixture.har"
            stderr = io.StringIO()
            with mock.patch(
                "automation.har_to_fixture.self_check", return_value=["泄漏了"]
            ), contextlib.redirect_stderr(stderr):
                code = main([str(har), "--out", str(target)])
            self.assertEqual(code, 1)
            self.assertFalse(target.exists())
            self.assertIn("未写出夹具", stderr.getvalue())

    def test_unreadable_har_returns_two(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["does-not-exist.har"])
        self.assertEqual(code, 2)
        self.assertIn("无法解析", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
