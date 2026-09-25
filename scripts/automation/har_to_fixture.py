#!/usr/bin/env python3
"""HAR 降级器：把真实抓包变成可以进仓库的合成夹具。

夹具的用途是**回归测试解析逻辑**，不是"给人看这个站点长什么样"。这个定位决定了两条设计：

**一、替换必须保形。** 如果把 `sign` 的值换成 `REDACTED`，`har_probe` 就再也判不出
它是 hex32，`har_to_script` 也就推不出策略——夹具变成废纸。所以替换按值的形态走：
hex32 换 hex32、UUID 换 UUID、纯数字换等长数字串、邮箱换邮箱。

**二、替换必须确定。** 同一个原值永远映射到同一个假值（由哈希派生，不用随机数）。
这条不是洁癖：整条工具链的核心判据是"哪些参数每次都在变"，如果替换动作自己引入了
随机性，常量会看起来像变量、变量之间的相等关系也会断掉——**夹具会把要测的东西测坏**。

顺带一个好处：确定性意味着同一份抓包每次降级得到逐字节相同的结果，夹具可以 diff。

**保留什么**：方法、路径、字段名、header 名、body 形态、状态码、MIME、时间戳、
相对时序。**替换什么**：所有值（时间戳除外）。**删什么**：响应体、响应头、请求耗时与体积。

用法：

    python scripts/automation/har_to_fixture.py capture.har --out fixture.har
    python scripts/automation/har_to_fixture.py capture.har --out fixture.har --anonymize-paths
    python scripts/automation/har_to_fixture.py capture.har --out fixture.har --redact-terms acme,internal

零第三方依赖。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.har_probe import (  # noqa: E402
    MULTIPART_HEADER_RE,
    SENSITIVE_HINTS,
    collect_fields,
    load_har,
    name_hits,
    normalize_path,
    probe,
    value_kind,
)

BASE_TIME = datetime(2020, 1, 1, tzinfo=timezone.utc)

# 值一律替换，唯独时间戳保留：它不是凭证，而且是"参数在变"最直接的证据。
PRESERVED_KINDS = {"timestamp_s", "timestamp_ms"}

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

# 这些 header 的值按 host 映射走，避免 URL 与 Host 头自相矛盾。
HOST_HEADERS = {"host", ":authority"}


# ------------------------------------------------------------ 确定性假值


def _digest(seed: str, round_index: int = 0) -> str:
    return hashlib.blake2s(f"{seed}:{round_index}".encode("utf-8"), digest_size=32).hexdigest()


def _hex_from(seed: str, length: int) -> str:
    chunks: list[str] = []
    round_index = 0
    while sum(len(chunk) for chunk in chunks) < length:
        chunks.append(_digest(seed, round_index))
        round_index += 1
    return "".join(chunks)[:length]


def _opaque_from(seed: str, length: int) -> str:
    out: list[str] = []
    round_index = 0
    while len(out) < length:
        digest = _digest(seed, round_index)
        for index in range(0, len(digest), 2):
            out.append(ALPHABET[int(digest[index : index + 2], 16) % len(ALPHABET)])
            if len(out) >= length:
                break
        round_index += 1
    return "".join(out)


def fake_value(original: str, *, sensitive: bool = False) -> str:
    """按形态派生假值。同一原值恒定得到同一假值。"""
    text = str(original)
    if not text:
        return text

    kind = value_kind(text)
    if kind in PRESERVED_KINDS:
        return text
    if kind == "uuid":
        digits = _hex_from(text, 32)
        return f"{digits[:8]}-{digits[8:12]}-4{digits[13:16]}-a{digits[17:20]}-{digits[20:32]}"
    if kind.startswith("hex"):
        return _hex_from(text, len(text))
    if kind == "number":
        digits = "".join(str(int(char, 16) % 10) for char in _hex_from(text, len(text)))
        # 保留首位数字：否则一个"10 位但不在时间戳区间"的数字可能被替换成
        # 落在区间内的数字，形态判据就从 number 变成 timestamp_s——替换动作
        # 自己制造了假证据。
        return text[0] + digits[1:] if digits else digits
    if kind == "opaque_base64ish":
        return _opaque_from(text, len(text))
    if "@" in text and "." in text.split("@")[-1]:
        return f"u{_hex_from(text, 8)}@example.com"

    prefix = "REDACTED" if sensitive else "v"
    return f"{prefix}-{_hex_from(text, 8)}"


# ---------------------------------------------------------------- 降级流程


def _parse_time(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _format_time(moment: datetime) -> str:
    """把平移后的时刻写成 HAR 的 startedDateTime。

    **毫秒必须留着。** 早先这里硬编码 `.000Z`，等于把所有条目压到整秒——
    实测 reCAPTCHA 令牌与用它的请求之间只差 0.24~0.39 秒，全都会被压成同一刻。
    后果不是报错，而是任何按时间判先后的东西静默失效：`har_probe --timeline`
    的调用链会退化成乱序，`har_origin` 的「来源」会退化成「回显」。
    降级只该改**值**，不该改**精度**——本模块的契约是"只做归一，不做重排"。
    """
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _original_slots(har: dict[str, Any]) -> set[str]:
    """原 HAR 里所有"值槽位"的内容：header / cookie / query / body 叶子值。

    刻意不收 HTTP 方法名与 MIME 类型——它们是结构字段，不是值；
    收进来会让自检在 `method`、`mimeType` 这类字段上产生永久假阳性。
    """
    slots: set[str] = set()
    for entry in (har.get("log") or {}).get("entries") or []:
        if not isinstance(entry, dict):
            continue
        for record in collect_fields(entry, redact_values=False):
            slots.add(str(record["value"]))
    return {value for value in slots if len(value) >= 4 and value_kind(value) not in PRESERVED_KINDS}


def _fixture_slots(fixture: dict[str, Any]) -> set[str]:
    """夹具里所有"值本不该在这里出现"的位置。

    分两类：

    - **值槽位**：header / cookie / query / body 叶子值。这些位置一律替换过，
      出现原值就是泄漏。
    - **标识符形态的路径段**：数字、UUID、哈希、长 base64 串。它们在
      `Anonymizer.path` 里同样被替换过，所以出现原值也是泄漏。

    刻意**不含语义路径段**（`signIn`、`profile` 这类）：它们是设计上要保留的
    接口语义载体。把它们算进来，一个恰好与路径段同名的请求头值就会变成
    永久假阳性，而那是"保留路径"这个决策的必然结果，不是泄漏。
    """
    slots: set[str] = set()
    for entry in (fixture.get("log") or {}).get("entries") or []:
        if not isinstance(entry, dict):
            continue
        for record in collect_fields(entry, redact_values=False):
            slots.add(str(record["value"]))
        path = urlsplit(((entry.get("request") or {}).get("url")) or "").path
        for segment in path.split("/"):
            if not segment:
                continue
            kind = value_kind(segment)
            if kind in ("number", "uuid", "opaque_base64ish") or kind.startswith("hex"):
                slots.add(segment)
    return {value for value in slots if value}


def _select_entries(
    entries: list[dict[str, Any]], samples_per_endpoint: int, max_entries: int
) -> list[dict[str, Any]]:
    """每个端点留几个样本——因为要看"参数在变"，一个样本看不出变化。"""
    kept: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        request = entry.get("request") or {}
        url = request.get("url") or ""
        if not url:
            continue
        key = f"{(request.get('method') or 'GET').upper()} {normalize_path(urlsplit(url).path)}"
        count = kept.get(key, 0)
        if count >= samples_per_endpoint:
            continue
        kept[key] = count + 1
        selected.append(entry)
    if max_entries and len(selected) > max_entries:
        selected = selected[:max_entries]
    return selected


class Anonymizer:
    """持有各张映射表，保证同一原值全篇一致。"""

    def __init__(self, *, anonymize_paths: bool, redact_terms: Sequence[str]) -> None:
        self.hosts: dict[str, str] = {}
        self.segments: dict[str, str] = {}
        self.values: dict[str, str] = {}
        self.anonymize_paths = anonymize_paths
        self.redact_terms = [term.strip().casefold() for term in redact_terms if term.strip()]
        self.timestamps_preserved = 0
        self.values_replaced = 0

    def host(self, host: str) -> str:
        if host not in self.hosts:
            self.hosts[host] = f"host-{len(self.hosts) + 1}.example.com"
        return self.hosts[host]

    def _segment_hit(self, segment: str) -> bool:
        if self.anonymize_paths:
            return True
        lowered = segment.casefold()
        return any(term in lowered for term in self.redact_terms)

    def segment(self, segment: str) -> str:
        if segment not in self.segments:
            self.segments[segment] = f"seg-{len(self.segments) + 1}"
        return self.segments[segment]

    def path(self, path: str) -> str:
        parts = []
        for segment in path.split("/"):
            if not segment:
                continue
            kind = value_kind(segment)
            # 数字 / UUID / 哈希 / 长 base64 串都是**标识符**，不是语义词——
            # 一律按形态替换。最后这一类是被真实抓包逼出来的：reCAPTCHA 的
            # 版本号 `/releases/P8cy…/` 既出现在路径里、又出现在查询串里，
            # 只替换查询串就会留下路径这条泄漏通道。
            if kind in ("number", "uuid", "opaque_base64ish") or kind.startswith("hex"):
                parts.append(fake_value(segment))
            elif self._segment_hit(segment):
                parts.append(self.segment(segment))
            else:
                parts.append(segment)
        return "/" + "/".join(parts) if parts else "/"

    def url(self, url: str) -> str:
        split = urlsplit(url)
        query = split.query
        if query:
            pairs = []
            for chunk in query.split("&"):
                if not chunk:
                    continue
                name, _, value = chunk.partition("=")
                pairs.append(f"{name}={self.value(name, value)}")
            query = "&".join(pairs)
        rebuilt = f"{split.scheme}://{self.host(split.netloc)}{self.path(split.path)}"
        return f"{rebuilt}?{query}" if query else rebuilt

    def value(self, name: str, raw: str) -> str:
        text = str(raw)
        if not text:
            return text
        if value_kind(text) in PRESERVED_KINDS:
            self.timestamps_preserved += 1
            return text
        if text not in self.values:
            self.values[text] = fake_value(text, sensitive=name_hits(name, SENSITIVE_HINTS))
            self.values_replaced += 1
        return self.values[text]


def _scrub_request(request: dict[str, Any], anonymizer: Anonymizer) -> dict[str, Any]:
    scrubbed: dict[str, Any] = {
        "method": (request.get("method") or "GET").upper(),
        "url": anonymizer.url(request.get("url") or ""),
    }

    headers = []
    for item in request.get("headers") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        name = str(item["name"])
        value = str(item.get("value", ""))
        if name.casefold() in HOST_HEADERS:
            value = anonymizer.host(urlsplit(request.get("url") or "").netloc)
        else:
            value = anonymizer.value(name, value)
        headers.append({"name": name, "value": value})
    if headers:
        scrubbed["headers"] = headers

    cookies = []
    for item in request.get("cookies") or []:
        if isinstance(item, dict) and item.get("name"):
            cookies.append(
                {"name": str(item["name"]), "value": anonymizer.value(str(item["name"]), item.get("value", ""))}
            )
    if cookies:
        scrubbed["cookies"] = cookies

    query = []
    for item in request.get("queryString") or []:
        if isinstance(item, dict) and item.get("name"):
            query.append(
                {"name": str(item["name"]), "value": anonymizer.value(str(item["name"]), item.get("value", ""))}
            )
    if query:
        scrubbed["queryString"] = query

    post_data = request.get("postData") or {}
    if post_data:
        mime = post_data.get("mimeType") or ""
        scrubbed_post: dict[str, Any] = {"mimeType": mime}
        text = post_data.get("text")
        if text:
            scrubbed_post["text"] = _scrub_body(str(text), mime, anonymizer)
        params = post_data.get("params")
        if params:
            scrubbed_post["params"] = [
                {
                    "name": str(item.get("name", "")),
                    "value": anonymizer.value(str(item.get("name", "")), item.get("value", "")),
                }
                for item in params
                if isinstance(item, dict)
            ]
        scrubbed["postData"] = scrubbed_post

    return scrubbed


def _scrub_body(text: str, mime: str, anonymizer: Anonymizer) -> str:
    """请求体：JSON 按键替换值，表单按 name=value 替换，其余整体当字符串处理。"""
    lowered = (mime or "").casefold()
    if "json" in lowered:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return anonymizer.value("", text)
        return json.dumps(_scrub_json(payload, anonymizer), ensure_ascii=False)
    if "x-www-form-urlencoded" in lowered:
        pairs = []
        for chunk in text.split("&"):
            if not chunk:
                continue
            name, _, value = chunk.partition("=")
            pairs.append(f"{name}={anonymizer.value(name, value)}")
        return "&".join(pairs)
    if "multipart" in lowered:
        return _scrub_multipart(text, mime, anonymizer)
    return anonymizer.value("", text)


def _scrub_multipart(text: str, mime: str, anonymizer: Anonymizer) -> str:
    """multipart 请求体：按 part 名替换值，边界与 Content-Disposition 原样保留。

    不能像以前那样整体当一个字符串替换——那会把 multipart 的**结构**抹掉：
    part 数变成 1、字段名全部消失，夹具与原件不再同形，而"同形"正是夹具
    能当证据的前提（`body_kinds` 还写着 multipart，里面却已经不是 multipart 了）。

    带 filename 的 part 属于文件上传：内容无法从 HAR 可靠还原，也不该进仓库，
    因此内容置空（与"响应体一律删除"同一条政策），文件名照常替换。
    """
    match = re.search(r"boundary=([^;\s]+)", mime)
    if not match:
        # 没有边界就切不开，退回整体替换——至少不会漏值。
        return anonymizer.value("", text)
    delimiter = "--" + match.group(1).strip('"')

    rebuilt: list[str] = []
    for chunk in text.split(delimiter):
        header = MULTIPART_HEADER_RE.search(chunk)
        if not header:
            # 前导空串与收尾的 "--" 段，原样保留。
            rebuilt.append(chunk)
            continue
        head, separator, body = chunk.partition("\r\n\r\n")
        if not separator:
            rebuilt.append(chunk)
            continue

        trailing = ""
        if body.endswith("\r\n"):
            trailing = "\r\n"
            body = body[:-2]

        name = header.group("name")
        if header.group("filename"):
            # 文件内容置空；文件名本身也是泄漏通道（真实姓名 / 订单号），照常替换。
            value = ""
            start, end = header.start("filename"), header.end("filename")
            head = head[:start] + anonymizer.value("filename", header.group("filename")) + head[end:]
        else:
            value = anonymizer.value(name, body)
        rebuilt.append(head + separator + value + trailing)

    return delimiter.join(rebuilt)


def _scrub_json(payload: Any, anonymizer: Anonymizer, prefix: str = "") -> Any:
    if isinstance(payload, dict):
        return {key: _scrub_json(value, anonymizer, f"{prefix}{key}") for key, value in payload.items()}
    if isinstance(payload, list):
        return [_scrub_json(item, anonymizer, prefix) for item in payload[:3]]
    if payload is None or isinstance(payload, bool):
        return payload

    name = prefix.rsplit(".", 1)[-1]
    fake = anonymizer.value(name, str(payload))

    # JSON 里原本是数字的，替换后也要是数字。否则夹具会把"数值字段"变成"字符串字段"，
    # 任何依赖类型的断言都会失真——这是替换动作自己制造出来的差异。
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        body = fake.lstrip("-")
        if body.isdigit():
            return int(fake)
    return fake


def anonymize(
    har: dict[str, Any],
    *,
    samples_per_endpoint: int = 2,
    max_entries: int = 0,
    anonymize_paths: bool = False,
    redact_terms: Sequence[str] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """返回 (夹具, 统计)。"""
    log = har.get("log") or {}
    entries = _select_entries(list(log.get("entries") or []), samples_per_endpoint, max_entries)

    anonymizer = Anonymizer(anonymize_paths=anonymize_paths, redact_terms=redact_terms)

    times = [_parse_time(entry.get("startedDateTime") or "") for entry in entries]
    known = [moment for moment in times if moment is not None]
    origin = min(known) if known else BASE_TIME

    scrubbed_entries = []
    for entry, moment in zip(entries, times):
        response = entry.get("response") or {}
        offset = (moment - origin).total_seconds() if moment is not None else 0.0
        scrubbed_entries.append(
            {
                "startedDateTime": _format_time(BASE_TIME + timedelta(seconds=offset)),
                "request": _scrub_request(entry.get("request") or {}, anonymizer),
                "response": {
                    "status": response.get("status", 0),
                    "content": {"mimeType": ((response.get("content") or {}).get("mimeType") or "")},
                },
            }
        )

    fixture = {
        "log": {
            "version": log.get("version") or "1.2",
            "creator": {"name": "har_to_fixture"},
            "entries": scrubbed_entries,
        }
    }

    stats = {
        "entries_in": len(log.get("entries") or []),
        "entries_out": len(scrubbed_entries),
        "hosts_anonymized": len(anonymizer.hosts),
        "segments_anonymized": len(anonymizer.segments),
        "values_replaced": anonymizer.values_replaced,
        "timestamps_preserved": anonymizer.timestamps_preserved,
        "host_map": dict(anonymizer.hosts),
        "segment_map": dict(anonymizer.segments),
    }
    return fixture, stats


# ------------------------------------------------------------ 自检与保真度


def self_check(fixture: dict[str, Any], original: dict[str, Any]) -> list[str]:
    """降级后必须过三关，任一不过就不该把文件写出去。"""
    problems: list[str] = []

    try:
        report = probe(fixture, include_static=True, redact_values=True)
    except Exception as error:  # noqa: BLE001 —— 夹具不能解析就没有存在意义
        problems.append(f"夹具无法被 har_probe 解析：{error}")
        return problems

    # probe 对畸形输入是宽容的（读不到就当空的），所以"没抛异常"不等于"解析成功"。
    if not report["summary"]["entries_total"]:
        problems.append("夹具里没有可解析的条目")
        return problems

    leaked = sorted(_original_slots(original) & _fixture_slots(fixture))
    if leaked:
        problems.append(
            f"{len(leaked)} 个原始值仍留在夹具的值槽位里，例如 {leaked[0][:40]!r}"
        )

    return problems


def fidelity(original: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    """证据保真度：降级后判据还成立吗。这是夹具唯一的验收标准。"""
    before = probe(original, include_static=False, redact_values=True)
    after = probe(fixture, include_static=False, redact_values=True)

    def endpoints(report: dict[str, Any]) -> set[str]:
        return {f"{row['method']} {row['path']}" for row in report.get("endpoints") or []}

    def names(report: dict[str, Any], bucket: str) -> set[str]:
        return {row["name"] for row in (report.get("fields") or {}).get(bucket) or []}

    def shapes(report: dict[str, Any], bucket: str) -> dict[str, list[str]]:
        return {
            row["name"]: sorted((row.get("value_kinds") or {}).keys())
            for row in (report.get("fields") or {}).get(bucket) or []
        }

    missing_endpoints = sorted(endpoints(before) - endpoints(after))
    shape_changes = []
    for bucket in ("signature_candidates", "volatile_candidates"):
        before_shapes = shapes(before, bucket)
        after_shapes = shapes(after, bucket)
        for name, kinds in before_shapes.items():
            if name in after_shapes and after_shapes[name] != kinds:
                shape_changes.append(f"{bucket}.{name}: {kinds} → {after_shapes[name]}")

    return {
        "endpoints_before": len(endpoints(before)),
        "endpoints_after": len(endpoints(after)),
        "endpoints_missing": missing_endpoints,
        "sensitive_before": len(names(before, "sensitive")),
        "sensitive_after": len(names(after, "sensitive")),
        "shape_changes": shape_changes,
        "ok": not missing_endpoints and not shape_changes,
    }


# ---------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把真实 HAR 降级成可进仓库的合成夹具。")
    parser.add_argument("har", help="HAR 文件路径，'-' 表示标准输入")
    parser.add_argument("--out", help="夹具输出路径；缺省打印到标准输出")
    parser.add_argument(
        "--samples-per-endpoint",
        type=int,
        default=2,
        help="每个端点保留几个样本（默认 2；一个样本看不出参数在变）",
    )
    parser.add_argument("--max-entries", type=int, default=0, help="总条目上限（0 表示不限）")
    parser.add_argument("--anonymize-paths", action="store_true", help="把路径段也映射成 seg-N")
    parser.add_argument(
        "--redact-terms",
        default="",
        help="逗号分隔的敏感词，命中这些词的路径段会被映射掉",
    )
    parser.add_argument("--map-out", help="把 host / 路径段映射表写到该路径（默认不写）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出统计与保真度")
    args = parser.parse_args(argv)

    try:
        original = load_har(args.har)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(f"无法解析 HAR: {error}", file=sys.stderr)
        return 2

    fixture, stats = anonymize(
        original,
        samples_per_endpoint=args.samples_per_endpoint,
        max_entries=args.max_entries,
        anonymize_paths=args.anonymize_paths,
        redact_terms=args.redact_terms.split(","),
    )

    problems = self_check(fixture, original)
    fidelity_report = fidelity(original, fixture)

    if args.map_out:
        Path(args.map_out).write_text(
            json.dumps(
                {"host_map": stats["host_map"], "segment_map": stats["segment_map"]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
            newline="\n",
        )

    result = {
        "ok": not problems and fidelity_report["ok"],
        "stats": {key: value for key, value in stats.items() if not key.endswith("_map")},
        "self_check": problems,
        "fidelity": fidelity_report,
    }

    if problems:
        print("降级失败，未写出夹具：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    if args.out:
        Path(args.out).write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
    elif not args.json:
        print(json.dumps(fixture, ensure_ascii=False, indent=2))

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"条目 {stats['entries_in']} → {stats['entries_out']}，"
            f"域名匿名 {stats['hosts_anonymized']}，值替换 {stats['values_replaced']}，"
            f"时间戳保留 {stats['timestamps_preserved']}"
        )
        print(
            f"证据保真度：端点 {fidelity_report['endpoints_before']} → "
            f"{fidelity_report['endpoints_after']}，形态变化 {len(fidelity_report['shape_changes'])} 处"
        )
        if not args.anonymize_paths:
            print("提示：路径段默认保留（它是接口语义的载体）。若含可识别信息，用 --redact-terms 指定。")
        if args.out:
            print(f"夹具已写入 {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
