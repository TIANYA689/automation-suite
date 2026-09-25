#!/usr/bin/env python3
"""HAR 字段溯源 —— 判定请求里的某个值是从哪条响应来的。

定位：**只读、离线、不执行**，与 `har_probe.py` 同一档。

它只回答一个问题：

> 请求里那个又长又看不懂的值，是从哪儿来的？

做法是把每条**响应**里的候选值做 sha256 索引，再拿目标**请求**的字段值去查这个
索引。命中就是**观测到的事实**：同一个字符串在两处都出现过。至于"这是不是令牌"
"这算不算签名"，本工具不猜——它只把"同串出现在哪、比目标请求早还是晚"摆出来。

为什么必须用哈希：这个值往往上千字符。打印明文既读不出结论，又把凭证写进了
终端与日志。**本工具只输出长度与哈希前缀，从不输出明文**——这不是可选项。

判定口径（这是本工具真正要区分的东西）：

| 判定 | 含义 |
|---|---|
| `origin` | 命中**更早**的响应，且域名符合 `--from` —— 值是从那里来的 |
| `other`  | 命中更早的响应，但域名不在 `--from` 里 —— 来源不是你以为的那个域名 |
| `echo`   | 只命中**同一条 entry 自己的响应** —— 发出去的值被原样回显 |
| `later`  | 只命中**更晚**的响应 —— 值先被发出去、之后才出现在响应里，**不是来源** |
| `shape`  | 没命中，但池里有**同长度、同形态**的串 —— 形态相似，来源未证实 |
| `miss`   | 都没有 |

`later` 和 `shape` 单独列出来，是因为它们最容易被误读成"找到了来源"。
它们不是证据，是待查线索。

`--from` **只用来区分 `origin` 与 `other`**。`echo` / `later` 是纯粹的时序事实，
与域名过滤无关——把过滤套到它们身上，只会让这两类被误标成 `other`，
也就是把两件正交的事混成一件。

池子有两个来源，缺一个就会漏：

- **响应体** —— 取其中 >= `--min-length` 的长串。字符集是连续 base64url（含点号，
  否则 JWT 会被按点号切断——实测这个 App 的 `Authorization` 正是 JWT）。
- **响应头** —— 把每条头值按 `;` 切段、按第一个 `=` 取值，并**也**把整条值本身
  当候选。`Set-Cookie: 名字=值; Path=/; HttpOnly` 这种复合结构，目标侧拿到的只是
  其中的**值**，整条头值不可能与它相等，而纯正则又会把 `;`、`=` 当分隔符切掉。

目标侧也一样会被"包一层"：`Authorization: Bearer <jwt>`、base64 尾部的 `=`。
所以查表前会把值按几种形态各试一次（原样 / 去前缀 / 去补位 / 等号后段），
命中的是哪一种会写进结果的 `matched_form`——**机械分解，且被说明**，不是猜语义。

请求侧默认把 **body / query / 请求头 / Cookie 全纳入**——这个项目的实测形态就是
令牌走 `Authorization` 头、动态参数走 query，默认关掉头等于看不见。命中少的请求会
被折叠，所以纳入头不会把输出淹掉。

刻意不做的三件事：

- 不执行 HAR 里的任何内容：不重放、不联网、不 eval。
- 不猜字段语义：命中只说明"同串出现过"，字段的业务含义由人判断。
- 不在池子残缺时下结论：响应体若被 base64 编码，内容读不出来，池子就是残的。
  此时"没命中"只等于"在这份残池里没找到"，工具会显式说出来并把 `pool.complete`
  置为 false。

**输入必须是真实抓包。** `har_to_fixture.py` 降级出来的夹具刻意**丢掉了响应体**
（它的职责是保住"参数形态"这一层判据），所以拿夹具跑本工具只会得到一份全空的
报告——那不是"没有来源"，是"没有材料"。这条边界写在 `projects/<作业>/` 的
授权边界里：本工具与真实抓包同属本地，不进仓库、不进 CI。

零第三方依赖。

用法：
    python scripts/automation/har_origin.py capture.har
    python scripts/automation/har_origin.py capture.har --from recaptcha.net
    python scripts/automation/har_origin.py capture.har --from recaptcha.net --to avalonavs.com
    python scripts/automation/har_origin.py capture.har --from recaptcha.net --json --out origin.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.har_probe import (  # noqa: E402
    ORDER_CHRONOLOGICAL,
    classify_entry_order,
    collect_fields,
    entry_time_key,
    load_har,
    normalize_path,
    sorted_indexed_entries,
)

DEFAULT_MIN_LENGTH = 200
DEFAULT_MIN_FIELD = 8
SHA_CHARS = 12
# 同一个值可能在很多条响应里出现。只留每个域名最早的一次，够用且不吃内存。
MAX_HOSTS_PER_VALUE = 8

# "连续 base64url 形态"的字符集。池子的正则与「同长」判定必须用**同一个**来源，
# 否则两边对"什么算一个串"的看法会分叉。
#
# **点号必须在里面。** 实测这个 App 的 Authorization 是 JWT，形如
# `头.载荷.签名`，段长 20 / 82 / 86。早先的字符集没有 `.`，正则会在每个点号处
# 断开，于是整个 JWT 从来进不了池子——而它的三个**段**反而都在池里。
# 结果是工具对它最该回答的那类值报 `miss`：不是没有来源，是看不见。
# 不能顺手把 `=` 也加进来：那会让 `sign=abcdef` 被当成一个整体串，
# 于是拿裸值 `abcdef` 去查又 miss 了——补位要在目标侧用 lookup_forms 剥。
POOL_CHARS = r"0-9A-Za-z_\-."
BLOB_RE = re.compile(rf"[{POOL_CHARS}]+")

# 目标侧字段值常被包了一层，拿整串去查必然 miss，而 miss 会被读成"没有来源"。
PREFIX_RE = re.compile(r"^(?:Bearer|Basic|Token)\s+", re.IGNORECASE)

VERDICTS = ("origin", "other", "echo", "later", "shape", "miss")
VERDICT_LABEL = {
    "origin": "来源",
    "other": "其它域名",
    "echo": "回显",
    "later": "回声",
    "shape": "同长",
    "miss": "未命中",
}
RELATION_LABEL = {"earlier": "早", "same": "同一条", "later": "晚"}
# 时序关系 → 判定。两者刻意分开：`relation` 是机械事实，`verdict` 是它的结论。
RELATION_VERDICT = {"earlier": "origin", "same": "echo", "later": "later"}


def digest(value: str) -> str:
    """值的指纹。只出前 12 位——够区分，也不可能反推回原文。"""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:SHA_CHARS]


def response_text(entry: dict[str, Any]) -> tuple[str, str]:
    """取响应体里的可读文本。返回 (文本, 不可读原因)。

    不可读的原因只有一种：内容被 base64 编码。这时**不能**当空串处理——
    池子会因此变残，而"没命中"就会被误读成"不是从这儿来的"。
    """
    content = (entry.get("response") or {}).get("content") or {}
    if content.get("encoding") == "base64":
        return "", "binary"
    text = content.get("text")
    if not isinstance(text, str) or not text:
        return "", "empty"
    return text, ""


def header_value_candidates(value: str, min_length: int) -> Iterator[str]:
    """把一条响应头的值拆成候选串。

    不能只做正则提取：`Set-Cookie` 的值是 `名字=值; Path=/; HttpOnly` 这种复合
    结构，目标侧的字段值只是其中的**值**那段，整条头值不可能与之相等，而正则又会
    把 `;`、`=` 当分隔符切掉。所以这里按 `;` 切段、取第一个 `=` 之后的部分，
    并且**也**把整条值本身当候选——两种形态都可能是答案，不该由工具替人挑。
    """
    if len(value) >= min_length:
        yield value
    for segment in value.split(";"):
        _, separator, tail = segment.partition("=")
        if separator and len(tail) >= min_length:
            yield tail


def lookup_forms(value: str) -> list[tuple[str, str]]:
    """目标侧字段值要试的几种形态：(形态名, 候选串)。

    为什么不能只拿整串去查：字段值常常不是"裸值"，而是被包了一层——
    `Authorization: Bearer <jwt>`、`Cookie: sid=<值>`、base64 尾部补 `=`。
    整串查必然 miss，而 miss 会被读成"没有来源"，正好是本工具要防的那类误读。

    这几条都是**机械分解**，不是猜语义，而且命中的是哪一种会写进结果
    （`matched_form`），不是悄悄替人决定。
    """
    forms: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(label: str, candidate: str) -> None:
        if candidate and candidate not in seen:
            seen.add(candidate)
            forms.append((label, candidate))

    add("原样", value)
    stripped = PREFIX_RE.sub("", value, count=1)
    if stripped != value:
        add("去前缀", stripped)
    # 补位剥在"去过前缀"的基础上：`Bearer <base64=>` 要两步都走完才等于裸值。
    base = stripped if stripped != value else value
    trimmed = base.rstrip("=")
    if trimmed != base:
        add("去补位", trimmed)
    _, separator, tail = value.partition("=")
    if separator and tail and tail != value:
        add("等号后段", tail)
    return forms


def _stamp_seconds(stamp: str) -> float | None:
    """把 startedDateTime 转成秒。解析不了就返回 None，绝不猜。"""
    text = (stamp or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except (ValueError, OSError, OverflowError):
        return None


def build_pool(
    entries: Sequence[dict[str, Any]], min_length: int
) -> tuple[dict[str, dict[str, Any]], Counter[int], dict[str, int]]:
    """把每条响应里的候选值收进哈希池。池是**全量**的，不按域名过滤。

    过滤只作用在"答案"上（见 `--from`）。如果连池子都按域名裁掉，"没命中"
    就同时意味着两件事——"这个值不存在"和"你把它过滤掉了"——而这两件事
    本该被分开。
    """
    pattern = re.compile(rf"[{POOL_CHARS}]{{{min_length},}}")
    pool: dict[str, dict[str, Any]] = {}
    lengths: Counter[int] = Counter()
    stats = Counter({"responses": len(entries)})

    def record(item: str, source: str, occurrence: dict[str, Any]) -> None:
        """把一个候选值记进池子。池里只留每个域名**最早**的一次出现。"""
        stats[f"strings_from_{source}"] += 1
        key = occurrence["key"]
        host = occurrence["host"]
        fingerprint = digest(item)
        slot = pool.get(fingerprint)
        if slot is None:
            pool[fingerprint] = {
                "length": len(item),
                "count": 1,
                "first": occurrence,
                "hosts": {host: occurrence},
            }
            lengths[len(item)] += 1
            return
        slot["count"] += 1
        if key < slot["first"]["key"]:
            slot["first"] = occurrence
        known = slot["hosts"].get(host)
        if known is None:
            if len(slot["hosts"]) < MAX_HOSTS_PER_VALUE:
                slot["hosts"][host] = occurrence
        elif key < known["key"]:
            slot["hosts"][host] = occurrence

    for index, entry in enumerate(entries):
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        split = urlsplit(request.get("url") or "")
        occurrence = {
            "key": entry_time_key(entry, index),
            "host": split.netloc,
            "method": (request.get("method") or "GET").upper(),
            "path": normalize_path(split.path),
            "startedDateTime": str(entry.get("startedDateTime") or ""),
        }

        text, reason = response_text(entry)
        if text:
            stats["bodies_readable"] += 1
            for item in pattern.findall(text):
                record(item, "body", occurrence)
        else:
            stats[f"bodies_{reason}"] += 1

        for header in response.get("headers") or []:
            if not isinstance(header, dict):
                continue
            for item in header_value_candidates(str(header.get("value") or ""), min_length):
                record(item, "header", occurrence)
    return pool, lengths, dict(stats)


def pick_match(slot: dict[str, Any], origin_needles: Sequence[str]) -> dict[str, Any] | None:
    """在候选出现点里挑一个作为"来源"。

    只在**时序上更早**的前提下才调用——`--from` 是用来区分"来源是不是你要的那个
    域名"的，跟"这条值是回声还是回显"无关。把域名过滤套到后两者上，会让
    `echo` / `later` 被误标成 `other`，那是把两件正交的事混成了一件。
    """
    if not origin_needles:
        return slot["first"]
    eligible = [
        item
        for host, item in slot["hosts"].items()
        if any(needle in host for needle in origin_needles)
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda item: item["key"])


def relation(match_key: tuple[int, str, int], target_key: tuple[int, str, int]) -> str:
    if match_key < target_key:
        return "earlier"
    if match_key == target_key:
        return "same"
    return "later"


def classify_field(
    name: str,
    where: str,
    value: str,
    target_key: tuple[int, str, int],
    pool: dict[str, dict[str, Any]],
    lengths: Counter[int],
    origin_needles: Sequence[str],
) -> dict[str, Any]:
    fingerprint = digest(value)
    row: dict[str, Any] = {
        "name": name,
        "where": where,
        "length": len(value),
        "sha": fingerprint,
        "verdict": "miss",
        "matched_form": None,
        "matches": 0,
        "match": None,
        # 目标请求时间 − 匹配响应时间：正数表示匹配更早。
        "delta_s": None,
    }

    # 先按几种形态找同串：字段值往往被 `Bearer ` 包了一层或补了 `=`。
    slot = None
    for form, candidate in lookup_forms(value):
        slot = pool.get(digest(candidate))
        if slot is not None:
            row["matched_form"] = form
            break

    if slot is None:
        # 池里没有同串。长度相同只说明"形态像"——这是线索，不是证据。
        # 还要求目标值也是连续 base64url 形态，见 POOL_CHARS 的说明。
        if len(value) in lengths and BLOB_RE.fullmatch(value):
            row["verdict"] = "shape"
        return row

    row["matches"] = slot["count"]
    overall = slot["first"]
    timing = relation(overall["key"], target_key)

    if timing != "earlier":
        # 回显 / 回声是纯粹的时序事实，与域名过滤无关。
        chosen = overall
        row["verdict"] = RELATION_VERDICT[timing]
    else:
        eligible = pick_match(slot, origin_needles)
        if eligible is None:
            # 更早的匹配都在被排除的域名上。报出来，否则用户会以为"根本不存在"。
            row["verdict"] = "other"
            chosen = overall
        else:
            row["verdict"] = "origin"
            chosen = eligible

    row["match"] = {
        "host": chosen["host"],
        "method": chosen["method"],
        "path": chosen["path"],
        "startedDateTime": chosen["startedDateTime"],
        "relation": relation(chosen["key"], target_key),
    }
    target_seconds = _stamp_seconds(target_key[1])
    match_seconds = _stamp_seconds(chosen["startedDateTime"])
    if target_seconds is not None and match_seconds is not None:
        row["delta_s"] = round(target_seconds - match_seconds, 3)
    return row


def analyze(
    har: dict[str, Any],
    *,
    origin_needles: Sequence[str],
    target_needles: Sequence[str],
    min_length: int,
    min_field: int,
    include_headers: bool,
    include_cookies: bool,
) -> dict[str, Any]:
    log = har.get("log") or {}
    raw = log.get("entries") or []
    entries = [entry for entry in raw if isinstance(entry, dict)]
    entry_order = classify_entry_order(
        [str(entry.get("startedDateTime") or "").strip() for entry in entries]
    )

    pool, lengths, pool_stats = build_pool(entries, min_length)

    host_pool: Counter[str] = Counter()
    for slot in pool.values():
        for host, occurrence in slot["hosts"].items():
            if occurrence["key"] == slot["first"]["key"]:
                host_pool[host] += 1

    targets: list[dict[str, Any]] = []
    verdicts: Counter[str] = Counter()
    fields_examined = 0
    considered = 0

    for index, entry in sorted_indexed_entries(entries):
        request = entry.get("request") or {}
        url = request.get("url") or ""
        if not url:
            continue
        host = urlsplit(url).netloc
        if target_needles and not any(needle in url for needle in target_needles):
            continue
        if origin_needles and any(needle in host for needle in origin_needles):
            # 来源域名自己的请求是"池"的那一侧，默认不当目标，否则自己命中自己。
            continue
        considered += 1

        target_key = entry_time_key(entry, index)
        fields: list[dict[str, Any]] = []
        for record in collect_fields(entry, redact_values=False):
            where = record["where"]
            if where == "cookie" and not include_cookies:
                continue
            if where == "header" and not include_headers:
                continue
            value = record["value"]
            if len(value) < min_field:
                continue
            row = classify_field(
                record["name"], where, value, target_key, pool, lengths, origin_needles
            )
            fields.append(row)
            verdicts[row["verdict"]] += 1

        if not fields:
            continue
        fields_examined += len(fields)
        targets.append(
            {
                "method": (request.get("method") or "GET").upper(),
                "host": host,
                "path": normalize_path(urlsplit(url).path),
                "startedDateTime": str(entry.get("startedDateTime") or ""),
                "fields": fields,
            }
        )

    notes: list[str] = []
    if pool_stats.get("bodies_binary"):
        notes.append(
            f"{pool_stats['bodies_binary']} 条响应的内容是 base64，读不出来：池子的响应体侧"
            "**是残的**，这些响应里若含有目标值，本工具看不见，不能据此判定「没有来源」"
        )
    if entry_order != ORDER_CHRONOLOGICAL:
        notes.append(
            "entries 数组不是时间序（实测 ProxyPin 导出基本是倒序）：已按 startedDateTime "
            "重排后再比先后，否则「来源/回声」会判反"
        )
    if verdicts["later"]:
        notes.append(
            f"{verdicts['later']} 个字段只命中**更晚**的响应：那是值被发出去之后才出现的，"
            "不是来源，别当证据用"
        )
    if verdicts["shape"]:
        notes.append(
            f"{verdicts['shape']} 个字段没命中但池里有同长度的串：只说明形态像，来源未证实"
        )
    if not include_headers:
        notes.append("请求头未纳入比对（默认纳入；本次被 --no-headers 关掉了）")
    if not include_cookies:
        notes.append("Cookie 未纳入比对（默认纳入；本次被 --no-cookies 关掉了）")

    return {
        "har": {
            "entries": len(raw),
            "entries_parsed": len(entries),
            "entry_order": entry_order,
        },
        "pool": {
            "min_length": min_length,
            "strings": len(pool),
            "responses": pool_stats.get("responses", 0),
            "bodies_readable": pool_stats.get("bodies_readable", 0),
            "bodies_binary": pool_stats.get("bodies_binary", 0),
            "bodies_empty": pool_stats.get("bodies_empty", 0),
            "strings_from_body": pool_stats.get("strings_from_body", 0),
            "strings_from_header": pool_stats.get("strings_from_header", 0),
            "complete": pool_stats.get("bodies_binary", 0) == 0,
            "hosts": [{"host": host, "strings": count} for host, count in host_pool.most_common()],
        },
        "filters": {
            "from": list(origin_needles),
            "to": list(target_needles),
            "min_field": min_field,
            "include_headers": include_headers,
            "include_cookies": include_cookies,
        },
        "targets": targets,
        "summary": {
            "entries_considered": considered,
            "targets": len(targets),
            "fields": fields_examined,
            "verdicts": {name: verdicts[name] for name in VERDICTS},
        },
        "notes": notes,
    }


def render(report: dict[str, Any], top: int, show_missed: bool = False) -> str:
    lines: list[str] = []
    pool = report["pool"]
    summary = report["summary"]
    filters = report["filters"]

    lines.append("=" * 70)
    lines.append("HAR 字段溯源（只比哈希，不打印明文）")
    lines.append("=" * 70)
    lines.append(
        f"条目 {report['har']['entries']}（可解析 {report['har']['entries_parsed']}）  "
        f"响应池 {pool['strings']} 个候选值（>={pool['min_length']} 字符）"
    )
    lines.append(
        f"池构成 响应体 {pool['strings_from_body']} 串 / 响应头 {pool['strings_from_header']} 串"
        f"    可读响应体 {pool['bodies_readable']}/{pool['responses']}"
    )
    lines.append(
        f"来源过滤 {'、'.join(filters['from']) if filters['from'] else '（不限）'}"
        f"    目标过滤 {'、'.join(filters['to']) if filters['to'] else '（不限）'}"
    )
    if not pool["complete"]:
        lines.append(f"** 池子残缺：{pool['bodies_binary']} 条响应体是 base64，读不出来 **")
    if pool["hosts"]:
        top_hosts = "  ".join(f"{row['host']}({row['strings']})" for row in pool["hosts"][:5])
        lines.append(f"池内域名 {top_hosts}")

    shown = 0
    folded = 0
    for target in report["targets"]:
        only_missed = all(row["verdict"] == "miss" for row in target["fields"])
        if (only_missed and not show_missed) or shown >= top:
            folded += 1
            continue
        shown += 1
        lines.append("")
        lines.append("-" * 70)
        lines.append(f"{target['method']} {target['host']}{target['path']}")
        lines.append(f"    @ {target['startedDateTime']}")
        missed = 0
        for row in target["fields"]:
            if row["verdict"] == "miss" and not show_missed:
                # 未命中是常态（一个请求有十几个头），全列出来会把唯一的命中淹掉。
                missed += 1
                continue
            mark = VERDICT_LABEL[row["verdict"]]
            detail = ""
            if row["match"]:
                match = row["match"]
                delta = ""
                if row["delta_s"] is not None:
                    delta = f"  {RELATION_LABEL[match['relation']]} {abs(row['delta_s'])}s"
                detail = f"  <== {match['host']} {match['method']} {match['path']}{delta}"
            extra = f"  x{row['matches']}" if row["matches"] > 1 else ""
            if row["matched_form"] and row["matched_form"] != "原样":
                # 说清楚是按哪种分解命中的：读者才能自己复核，而不是信一个黑箱结论。
                extra += f"  按[{row['matched_form']}]"
            lines.append(
                f"    {row['name']:<20s} len={row['length']:<6d} sha={row['sha']}  "
                f"[{mark}]{extra}{detail}"
            )
        if missed:
            lines.append(f"    （另 {missed} 个字段未命中，--show-missed 可展开）")
    if folded:
        lines.append("")
        lines.append(f"（另有 {folded} 条请求只有未命中的字段，已折叠）")

    lines.append("")
    lines.append("-" * 70)
    lines.append(
        f"汇总  目标请求 {summary['entries_considered']}（有可比字段的 {summary['targets']}）  "
        f"检查字段 {summary['fields']}"
    )
    lines.append(
        "      "
        + " / ".join(
            f"{VERDICT_LABEL[name]} {summary['verdicts'][name]}" for name in VERDICTS
        )
    )
    if report["notes"]:
        lines.append("")
        lines.append("-- 提示 " + "-" * 30)
        for note in report["notes"]:
            lines.append(f"· {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="HAR 字段溯源：判定请求里的值来自哪条响应。只读、离线、不执行。"
    )
    parser.add_argument("har", help="HAR 文件路径，'-' 表示从标准输入读取")
    parser.add_argument(
        "--from",
        dest="origin",
        action="append",
        default=[],
        metavar="DOMAIN",
        help="只认这些域名（子串匹配 host）上的响应为来源；不给则任何域名都算",
    )
    parser.add_argument(
        "--to",
        dest="target",
        action="append",
        default=[],
        metavar="NEEDLE",
        help="只分析 URL 含该子串的请求；不给则全部分析（来源域名自身除外）",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=DEFAULT_MIN_LENGTH,
        help=f"响应池只收这么长的值（默认 {DEFAULT_MIN_LENGTH}）",
    )
    parser.add_argument(
        "--min-field",
        type=int,
        default=DEFAULT_MIN_FIELD,
        help=f"字段值短于此长度不列（默认 {DEFAULT_MIN_FIELD}）",
    )
    parser.add_argument("--no-headers", action="store_true", help="不把请求头纳入比对")
    parser.add_argument("--no-cookies", action="store_true", help="不把 Cookie 纳入比对")
    parser.add_argument("--top", type=int, default=40, help="最多列多少条目标请求（默认 40）")
    parser.add_argument(
        "--show-missed", action="store_true", help="把未命中的字段也逐条列出（默认折叠）"
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", help="同时把 JSON 写入该路径")
    args = parser.parse_args(argv)

    if args.min_length < 1 or args.min_field < 1:
        print("--min-length / --min-field 必须为正整数", file=sys.stderr)
        return 2

    try:
        har = load_har(args.har)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(f"无法解析 HAR: {error}", file=sys.stderr)
        return 2

    report = analyze(
        har,
        origin_needles=args.origin,
        target_needles=args.target,
        min_length=args.min_length,
        min_field=args.min_field,
        include_headers=not args.no_headers,
        include_cookies=not args.no_cookies,
    )

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, args.top, args.show_missed))
        if args.out:
            print(f"\nJSON 已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
