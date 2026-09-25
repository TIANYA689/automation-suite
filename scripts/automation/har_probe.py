#!/usr/bin/env python3
"""HAR 静态盘点器 —— 把抓包文件变成一张"接口地图"。

定位：**只读、离线、不执行**。输入一个 HAR，输出域名分布、接口清单、
疑似敏感字段、动态参数候选（签名 / 时间戳 / 随机数）与按时间序的调用链。

它是"根据 HAR 写自动化脚本"这条流水线的**第一跳**：先看清楚有哪些接口、
哪些参数每次都在变，再决定哪些接口能直连、哪些必须走浏览器。

刻意不做的三件事：

- 不执行 HAR 里的任何内容：不重放、不联网、不 eval、不写盘（除 --out）。
- 不猜业务语义：不会告诉你"这个接口是签到"。语义由人和代理判断，
  本工具只负责把证据摆齐。
- 不还原被脱敏的内容：--no-redact 只影响**输出**，不改变输入文件。

关于时间：HAR 规范不要求 `entries` 按时间排。实测 ProxyPin 1.2.4 导出的四份真实
抓包基本是**倒序**（最新在前）且非严格倒序，所以本工具一律按 `startedDateTime`
重排，并在 `summary.entry_order` 里如实报告原始数组是什么顺序——修正要看得见，
不能静默。

零第三方依赖。

用法：
    python scripts/automation/har_probe.py capture.har
    python scripts/automation/har_probe.py capture.har --json --out probe.json
    python scripts/automation/har_probe.py - < capture.har
    python scripts/automation/har_probe.py capture.har --timeline --include-static
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import parse_qsl, urlsplit

STATIC_SUFFIXES = (
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".mp4",
    ".mp3",
    ".m4a",
    ".avif",
    ".webm",
)

# 字段名里出现这些词，按"值不可入日志"处理。
SENSITIVE_HINTS = (
    "cookie",
    "authorization",
    "token",
    "session",
    "sid",
    "jwt",
    "password",
    "passwd",
    "pwd",
    "secret",
    "apikey",
    "api_key",
    "access_key",
    "credential",
    "ticket",
    "refresh",
)

# 字段名里出现这些词，按"可能是请求签名"处理。
SIGNATURE_HINTS = ("sign", "signature", "sig", "hmac", "digest", "checksum", "md5", "sha")

# 字段名里出现这些词，按"每次请求都会变"处理。
VOLATILE_HINTS = ("nonce", "rand", "random", "salt", "iv", "uuid", "guid")

# 短名（<=3 字符）必须整名相等，避免 "t" 命中一切。
TIMESTAMP_NAMES = ("ts", "t", "time", "timestamp", "_t", "stamp", "date", "datetime", "curtime")

HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
B64_RE = re.compile(r"^[A-Za-z0-9+/_=-]+$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

HEX_STRONG_LENGTHS = (32, 40, 56, 64, 96, 128)

REDACT_KEEP = 4


def redact(value: str) -> str:
    """保留首尾各 4 个字符，中间打码。短值整体打码。"""
    text = str(value)
    if len(text) <= REDACT_KEEP * 2:
        return "*" * len(text)
    return f"{text[:REDACT_KEEP]}{'*' * 8}{text[-REDACT_KEEP:]}"


def value_kind(value: str) -> str:
    """判断一个参数值的形态：签名候选 / 时间戳候选 / 普通值。"""
    text = str(value).strip()
    if not text:
        return "empty"
    if UUID_RE.match(text):
        return "uuid"
    if text.isdigit():
        if len(text) == 10 and 1_000_000_000 <= int(text) <= 2_100_000_000:
            return "timestamp_s"
        if len(text) == 13 and 1_000_000_000_000 <= int(text) <= 2_100_000_000_000:
            return "timestamp_ms"
        return "number"
    if HEX_RE.match(text) and len(text) in HEX_STRONG_LENGTHS:
        return f"hex{len(text)}"
    if len(text) >= 20 and B64_RE.match(text) and any(c.isupper() for c in text) and any(
        c.islower() for c in text
    ):
        return "opaque_base64ish"
    return "plain"


def normalize_path(path: str) -> str:
    """把路径里的具体 id 归一成占位符，让同一接口的不同实例合并成一条。"""
    segments = []
    for segment in path.split("/"):
        if not segment:
            continue
        if segment.isdigit():
            segments.append("{id}")
        elif UUID_RE.match(segment):
            segments.append("{uuid}")
        elif len(segment) >= 16 and HEX_RE.match(segment):
            segments.append("{hash}")
        else:
            segments.append(segment)
    return "/" + "/".join(segments) if segments else "/"


def is_static(url: str, mime: str) -> bool:
    lowered = urlsplit(url).path.lower()
    if lowered.endswith(STATIC_SUFFIXES):
        return True
    head = (mime or "").split(";")[0].strip().lower()
    return head.startswith(("image/", "font/", "audio/", "video/")) or head in {
        "text/css",
        "text/javascript",
        "application/javascript",
        "application/x-javascript",
    }


def name_hits(name: str, hints: Sequence[str]) -> bool:
    lowered = name.strip().lower()
    return any(hint in lowered for hint in hints)


def flatten_keys(payload: Any, depth: int = 2, prefix: str = "") -> Iterator[tuple[str, str]]:
    """把 JSON 请求体的键值摊平，只下探 depth 层，避免把整个响应树读进内存。"""
    if depth < 0:
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            name = f"{prefix}{key}"
            if isinstance(value, (dict, list)):
                yield from flatten_keys(value, depth - 1, f"{name}.")
            else:
                yield name, "" if value is None else str(value)
    elif isinstance(payload, list):
        for item in payload[:3]:
            yield from flatten_keys(item, depth - 1, f"{prefix}[].")


def body_kind(post_data: dict[str, Any] | None) -> str:
    if not post_data:
        return "empty"
    mime = (post_data.get("mimeType") or "").split(";")[0].strip().lower()
    if "json" in mime:
        return "json"
    if "x-www-form-urlencoded" in mime:
        return "form"
    if "multipart" in mime:
        return "multipart"
    if post_data.get("text"):
        return "text"
    # 有些抓包工具（实测 ProxyPin）给每个请求都挂一个空的 postData 对象。
    # 那时 mimeType 与 text 都是空串，正确答案是"没有请求体"而不是"形态未知"——
    # 报成 unknown 会让下游把 GET 误判成"有 body 但看不懂"。
    return mime or "empty"


MULTIPART_HEADER_RE = re.compile(
    r'Content-Disposition:\s*form-data;\s*name="(?P<name>[^"]*)"'
    r'(?:;\s*filename="(?P<filename>[^"]*)")?',
    re.IGNORECASE,
)


def multipart_parts(post_data: dict[str, Any] | None) -> list[dict[str, str]]:
    """从 multipart 原文里取出各 part 的名字、值与文件名。

    为什么必须自己解析原文：实测 ProxyPin 对 multipart 请求给的是**空** `params`
    （`"params": []`），只有 `text` 里有真内容。若只读 `params`，
    multipart 里的参数名就完全不可见——连带 `token` 这类易变字段也进不了
    `volatile_candidates`，写计划的人因此看不到"这个值每次都在变"。
    """
    if not post_data:
        return []
    mime = post_data.get("mimeType") or ""
    text = post_data.get("text") or ""
    if "multipart" not in mime or not text:
        return []
    match = re.search(r"boundary=([^;\s]+)", mime)
    if not match:
        return []
    boundary = match.group(1).strip('"')

    parts: list[dict[str, str]] = []
    for chunk in text.split("--" + boundary):
        header = MULTIPART_HEADER_RE.search(chunk)
        if not header:
            continue
        _, _, body = chunk.partition("\r\n\r\n")
        if not body:
            continue
        body = body.rstrip("\r\n")
        if body.endswith("--"):
            body = body[:-2].rstrip("\r\n")
        parts.append(
            {
                "name": header.group("name"),
                "value": body,
                "filename": header.group("filename") or "",
            }
        )
    return parts


def multipart_file_part_count(post_data: dict[str, Any] | None) -> int:
    """multipart 里带 filename 的 part 数。文件字段无法从 HAR 可靠还原，要单独计。"""
    return sum(1 for part in multipart_parts(post_data) if part["filename"])


def collect_fields(entry: dict[str, Any], redact_values: bool) -> list[dict[str, str]]:
    """收集一次请求里出现的所有参数名与值，标明来源位置。"""
    request = entry.get("request") or {}
    found: list[dict[str, str]] = []

    for key, value in parse_qsl(urlsplit(request.get("url") or "").query, keep_blank_values=True):
        found.append({"name": key, "value": value, "where": "query"})

    for item in request.get("queryString") or []:
        if isinstance(item, dict) and item.get("name"):
            found.append(
                {"name": str(item["name"]), "value": str(item.get("value", "")), "where": "query"}
            )

    post_data = request.get("postData") or {}
    kind = body_kind(post_data)
    if kind == "form":
        for key, value in parse_qsl(post_data.get("text") or "", keep_blank_values=True):
            found.append({"name": key, "value": value, "where": "body.form"})
    elif kind == "json":
        try:
            parsed = json.loads(post_data.get("text") or "{}")
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            for name, value in flatten_keys(parsed):
                found.append({"name": name, "value": value, "where": "body.json"})
    elif kind == "multipart":
        # 文件 part 不是"参数"，不列入字段表；只统计数量（见 multipart_file_part_count）。
        records = [
            {"name": part["name"], "value": part["value"], "where": "body.multipart"}
            for part in multipart_parts(post_data)
            if not part["filename"]
        ]
        if not records:
            # 少数抓包工具（非 ProxyPin）会给结构化 params，作为回退。
            records = [
                {
                    "name": str(param["name"]),
                    "value": str(param.get("value", "")),
                    "where": "body.multipart",
                }
                for param in post_data.get("params") or []
                if isinstance(param, dict) and param.get("name")
            ]
        found.extend(records)

    for item in request.get("cookies") or []:
        if isinstance(item, dict) and item.get("name"):
            found.append(
                {"name": str(item["name"]), "value": str(item.get("value", "")), "where": "cookie"}
            )

    for item in request.get("headers") or []:
        if isinstance(item, dict) and item.get("name"):
            found.append(
                {
                    "name": str(item["name"]),
                    "value": str(item.get("value", "")),
                    "where": "header",
                }
            )

    if redact_values:
        for record in found:
            record["value"] = redact(record["value"])
    return found


def load_har(source: str) -> dict[str, Any]:
    if source == "-":
        payload = json.load(sys.stdin)
    else:
        payload = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "log" not in payload:
        raise ValueError("不是合法的 HAR：缺少顶层 log 字段")
    return payload


ORDER_CHRONOLOGICAL = "chronological"
ORDER_REVERSED = "reversed"
ORDER_UNSORTED = "unsorted"


def entry_time_key(entry: dict[str, Any], index: int) -> tuple[int, str, int]:
    """给条目一个可比较的时间键：缺时间戳的排最后，同刻的按原下标稳定。"""
    stamp = str(entry.get("startedDateTime") or "").strip()
    return (1 if not stamp else 0, stamp, index)


def classify_entry_order(stamps: Sequence[str]) -> str:
    """判断 entries 数组本身是不是时间序。"""
    if all(stamps[index] <= stamps[index + 1] for index in range(len(stamps) - 1)):
        return ORDER_CHRONOLOGICAL
    if all(stamps[index] >= stamps[index + 1] for index in range(len(stamps) - 1)):
        return ORDER_REVERSED
    return ORDER_UNSORTED


def sorted_indexed_entries(entries: Sequence[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """按时间序返回 (原始下标, entry)。下标要留着——同刻条目的先后由它决定。"""
    indexed = list(enumerate(entries))
    indexed.sort(key=lambda item: entry_time_key(item[1], item[0]))
    return indexed


def sort_entries(entries: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 startedDateTime 重排条目。

    为什么必须排：HAR 规范**不要求** entries 按时间排，实测 ProxyPin 1.2.4 导出的
    四份真实抓包基本是**倒序**（最新在前），而且不是严格倒序——相邻递增的比例分别是
    5/148、0/10、3/122、1/36。也就是说数组下标**不携带时间信息**。

    不排的代价不是报错，而是得到一份看起来很像、方向恰好相反的时序图：
    签到会显示成在登录之前发生。所以任何"谁先谁后"的推理都必须走这里。
    """
    return [entry for _, entry in sorted_indexed_entries(entries)]


def probe(har: dict[str, Any], *, include_static: bool, redact_values: bool) -> dict[str, Any]:
    log = har.get("log") or {}
    raw_entries = log.get("entries") or []

    dict_entries = [entry for entry in raw_entries if isinstance(entry, dict)]
    entry_order = classify_entry_order(
        [str(entry.get("startedDateTime") or "").strip() for entry in dict_entries]
    )

    host_counter: Counter[str] = Counter()
    host_api: Counter[str] = Counter()
    endpoint_map: dict[str, dict[str, Any]] = {}
    sequence: list[str] = []
    field_stats: dict[str, dict[str, Any]] = {}
    header_counter: Counter[str] = Counter()
    mime_counter: Counter[str] = Counter()
    static_count = 0
    parse_errors = len(raw_entries) - len(dict_entries)
    timestamps: list[str] = []

    # 遍历顺序 = 时间顺序，不是数组顺序（见 sort_entries 的说明）。
    for entry in sort_entries(dict_entries):
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        url = request.get("url") or ""
        if not url:
            parse_errors += 1
            continue

        started = (entry.get("startedDateTime") or "").strip()
        if started:
            timestamps.append(started)

        split = urlsplit(url)
        host = split.netloc
        mime = ((response.get("content") or {}).get("mimeType") or "").strip()
        static = is_static(url, mime)

        host_counter[host] += 1
        mime_counter[mime.split(";")[0].strip() or "(none)"] += 1

        for item in request.get("headers") or []:
            if isinstance(item, dict) and item.get("name"):
                header_counter[str(item["name"]).lower()] += 1

        if static and not include_static:
            static_count += 1
            continue

        method = (request.get("method") or "GET").upper()
        template = normalize_path(split.path)
        key = f"{method} {template}"
        host_api[host] += 1
        sequence.append(key)

        slot = endpoint_map.setdefault(
            key,
            {
                "method": method,
                "path": template,
                "host": host,
                "count": 0,
                "query_keys": set(),
                "body_kinds": Counter(),
                "multipart_file_parts": 0,
                "statuses": Counter(),
                "response_mimes": Counter(),
            },
        )
        slot["count"] += 1
        slot["body_kinds"][body_kind(request.get("postData"))] += 1
        slot["multipart_file_parts"] = max(
            slot["multipart_file_parts"], multipart_file_part_count(request.get("postData"))
        )
        slot["statuses"][str(response.get("status", "?"))] += 1
        slot["response_mimes"][mime.split(";")[0].strip() or "(none)"] += 1
        for key_name, _ in parse_qsl(split.query, keep_blank_values=True):
            slot["query_keys"].add(key_name)

        for record in collect_fields(entry, redact_values=False):
            name = record["name"]
            stat = field_stats.setdefault(
                name,
                {"name": name, "count": 0, "where": Counter(), "kinds": Counter(), "sample": ""},
            )
            stat["count"] += 1
            stat["where"][record["where"]] += 1
            kind = value_kind(record["value"])
            stat["kinds"][kind] += 1
            if not stat["sample"] and kind not in ("empty", "plain"):
                stat["sample"] = record["value"] if not redact_values else redact(record["value"])

    endpoints = []
    for slot in endpoint_map.values():
        endpoints.append(
            {
                "method": slot["method"],
                "path": slot["path"],
                "host": slot["host"],
                "count": slot["count"],
                "query_keys": sorted(slot["query_keys"]),
                "body_kinds": dict(slot["body_kinds"]),
                "multipart_file_parts": slot["multipart_file_parts"],
                "statuses": dict(slot["statuses"]),
                "response_mimes": list(slot["response_mimes"]),
            }
        )
    endpoints.sort(key=lambda item: (-item["count"], item["path"]))

    def field_report(predicate) -> list[dict[str, Any]]:
        rows = []
        for stat in field_stats.values():
            if not predicate(stat):
                continue
            sample = stat["sample"]
            if redact_values and sample:
                sample = redact(sample)
            rows.append(
                {
                    "name": stat["name"],
                    "count": stat["count"],
                    "where": sorted(stat["where"]),
                    "value_kinds": dict(stat["kinds"]),
                    "sample": sample,
                }
            )
        rows.sort(key=lambda item: (-item["count"], item["name"]))
        return rows

    volatile_kinds = {
        "hex32",
        "hex40",
        "hex56",
        "hex64",
        "hex96",
        "hex128",
        "opaque_base64ish",
        "timestamp_s",
        "timestamp_ms",
        "uuid",
    }

    sensitive = field_report(
        lambda stat: name_hits(stat["name"], SENSITIVE_HINTS)
        or stat["where"].get("cookie", 0) > 0
    )
    signatures = field_report(
        lambda stat: name_hits(stat["name"], SIGNATURE_HINTS)
        or any(kind in stat["kinds"] for kind in ("hex32", "hex40", "hex56", "hex64", "hex96", "hex128"))
    )
    volatile = field_report(
        lambda stat: name_hits(stat["name"], VOLATILE_HINTS)
        or any(kind in stat["kinds"] for kind in volatile_kinds)
        or stat["name"].strip().lower() in TIMESTAMP_NAMES
    )

    notes: list[str] = []
    if parse_errors:
        notes.append(f"{parse_errors} 条 entry 缺 url 或结构异常，已跳过")
    if entry_order != ORDER_CHRONOLOGICAL:
        label = "倒序（最新在前）" if entry_order == ORDER_REVERSED else "乱序"
        notes.append(
            f"entries 数组是{label}，不是时间序：调用时序已按 startedDateTime 重排，"
            "别把数组下标当先后"
        )
    if static_count:
        notes.append(f"{static_count} 条静态资源已折叠（--include-static 可展开）")
    if any(name_hits(row["name"], SENSITIVE_HINTS) for row in sensitive):
        notes.append("检测到凭证类字段：这些值不得写入脚本、日志或状态文件")
    if signatures:
        notes.append("检测到签名/摘要类参数：直连前需先复现其生成算法，否则脚本必然失败")

    return {
        "har": {
            "version": log.get("version"),
            "creator": (log.get("creator") or {}).get("name"),
            "pages": len(log.get("pages") or []),
        },
        "summary": {
            "entries_total": len(raw_entries),
            "entries_api": sum(1 for _ in sequence),
            "entries_static": static_count,
            "entries_unparsed": parse_errors,
            "hosts": len(host_counter),
            "endpoints": len(endpoints),
            "entry_order": entry_order,
            "first_seen": min(timestamps) if timestamps else None,
            "last_seen": max(timestamps) if timestamps else None,
        },
        "hosts": [
            {"host": host, "total": total, "api": host_api.get(host, 0)}
            for host, total in host_counter.most_common()
        ],
        "endpoints": endpoints,
        "request_headers": [
            {"name": name, "count": count} for name, count in header_counter.most_common()
        ],
        "response_mimes": [
            {"mime": mime, "count": count} for mime, count in mime_counter.most_common()
        ],
        "fields": {
            "sensitive": sensitive,
            "signature_candidates": signatures,
            "volatile_candidates": volatile,
        },
        "sequence": sequence,
        "redacted": redact_values,
        "notes": notes,
    }


def render(report: dict[str, Any], top: int, timeline: bool) -> str:
    lines: list[str] = []
    summary = report["summary"]
    lines.append("=" * 68)
    lines.append("HAR 静态盘点")
    lines.append("=" * 68)
    lines.append(
        f"条目 {summary['entries_total']}（接口 {summary['entries_api']} / "
        f"静态 {summary['entries_static']} / 异常 {summary['entries_unparsed']}）  "
        f"域名 {summary['hosts']}  接口 {summary['endpoints']}"
    )
    if summary["first_seen"]:
        lines.append(f"时间范围 {summary['first_seen']} → {summary['last_seen']}")
    if report["redacted"]:
        lines.append("输出已脱敏（--no-redact 可关闭）")

    lines.append("")
    lines.append(f"-- 域名分布 (top {top}) " + "-" * 30)
    for row in report["hosts"][:top]:
        lines.append(f"{row['api']:>5} 接口 / {row['total']:>5} 全部   {row['host']}")

    lines.append("")
    lines.append(f"-- 接口清单 (top {top}) " + "-" * 30)
    for row in report["endpoints"][:top]:
        extra = []
        if row["query_keys"]:
            extra.append("query:" + ",".join(row["query_keys"][:6]))
        kinds = [k for k in row["body_kinds"] if k != "empty"]
        if kinds:
            extra.append("body:" + ",".join(kinds))
        if row.get("multipart_file_parts"):
            # 有文件字段的 multipart 无法从 HAR 还原内容，必须让人看见。
            extra.append(f"文件字段x{row['multipart_file_parts']}")
        statuses = ",".join(f"{k}x{v}" for k, v in sorted(row["statuses"].items()))
        suffix = f"   [{' | '.join(extra)}]" if extra else ""
        lines.append(f"{row['count']:>5}x  {row['method']:<6} {row['path']}{suffix}   [{statuses}]")

    fields = report["fields"]
    for title, key in (
        ("凭证类字段（不得入库）", "sensitive"),
        ("签名/摘要候选（直连前必须先复现）", "signature_candidates"),
        ("易变参数候选（时间戳 / 随机数 / 哈希）", "volatile_candidates"),
    ):
        rows = fields[key]
        lines.append("")
        lines.append(f"-- {title} " + "-" * max(0, 40 - len(title)))
        if not rows:
            lines.append("（无）")
            continue
        for row in rows[:top]:
            kinds = ",".join(sorted(row["value_kinds"]))
            sample = f"  例:{row['sample']}" if row["sample"] else ""
            lines.append(f"{row['count']:>5}x  {row['name']:<24} [{kinds}] {','.join(row['where'])}{sample}")

    if timeline:
        lines.append("")
        if report["summary"].get("entry_order", ORDER_CHRONOLOGICAL) == ORDER_CHRONOLOGICAL:
            lines.append("-- 调用时序（数组即时间序） " + "-" * 30)
        else:
            # 说清楚重排过：否则读者会以为这就是文件里数组的原样。
            lines.append("-- 调用时序（已按 startedDateTime 重排） " + "-" * 30)
        for index, item in enumerate(report["sequence"], 1):
            lines.append(f"{index:>4}. {item}")

    if report["notes"]:
        lines.append("")
        lines.append("-- 提示 " + "-" * 30)
        for note in report["notes"]:
            lines.append(f"· {note}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HAR 静态盘点：只读、离线、不执行。")
    parser.add_argument("har", help="HAR 文件路径，'-' 表示从标准输入读取")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", help="同时把 JSON 写入该路径")
    parser.add_argument("--top", type=int, default=40, help="各分区最多列多少条（默认 40）")
    parser.add_argument(
        "--timeline", action="store_true", help="附上调用链（按 startedDateTime 重排后）"
    )
    parser.add_argument("--include-static", action="store_true", help="把静态资源也计入接口清单")
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="不脱敏（仅影响输出；导出到仓库外的临时文件时才使用）",
    )
    args = parser.parse_args(argv)

    try:
        har = load_har(args.har)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(f"无法解析 HAR: {error}", file=sys.stderr)
        return 2

    report = probe(har, include_static=args.include_static, redact_values=not args.no_redact)

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, args.top, args.timeline))
        if args.out:
            print(f"\nJSON 已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
