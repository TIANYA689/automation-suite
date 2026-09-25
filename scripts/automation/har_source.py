#!/usr/bin/env python3
"""HAR 内嵌源码检索 —— 把抓包里**应用自己带的前端代码**当成证据来查。

定位：**只读、离线、不执行**，与 `har_probe.py` / `har_origin.py` 同一档。

它回答的问题是：

> 这个字段名 / 这个接口路径，抓包里有没有**源码级**的线索？

## 为什么需要它

`har_probe.py` 把 `.js` / `.css` / 图片一律归为"静态资源"并折叠掉。那对它的本职
（列接口清单）是对的——静态资源不是接口。但这个默认会让**证据最强的一类**整体消失：
前端应用把自己的代码发给了浏览器，而抓包把它原样存了下来。

实测代价：本项目的作业计划里写过

> deviceUuid 是 13 位标识符，抓包里只有一次样本、形态是 plain，**看不出生成规则**

而生成规则就躺在同一份抓包的 `js/8176.b4c9c7c2.js` 里：

    let l = localStorage.getItem("deviceUuid");
    l || (l = Math.random().toString(36), localStorage.setItem("deviceUuid", l))

这不是"看了没找到"，是**没有去这一类材料里看**。而它的产物是一句写进计划的、
看起来很像结论的错误陈述——正是这个项目最想避免的那种失效：**工具跑得动、
报告看起来完整、结论是空的。**

同一份文件里还能拿到：四个请求包装族各自的编码方式、鉴权拦截器怎么塞
`Authorization`、业务失败码 `5000` 的含义、以及**全部 73 个接口**。

## 默认检索范围是"源码类"，不是全部响应体

只搜源码类资源（`.js` / `.mjs` / `.css` / `.html` / `.map` 或对应 mimeType）。
理由有三条：

1. 这是本工具存在的理由——源码那一层。
2. 接口响应体里装的是**用户数据**。默认纳入会让输出被数据淹没，也会把凭证带进终端。
3. 想搜数据时显式 `--include-data`，那时你是在有意为之，不是在踩默认值。

## 掩码

默认把上下文里**又长又不透明**的串换成 `«len=N sha=xxxxxxxxxxxx»`。判据是机械的：
长度 >= `--mask-min`（默认 40）、字符集是 base64url 那一类、且**同时含大写、小写、
数字**。这样 JWT / base64 大块 / 会话号会被掩掉，而 URL、MIME 类型、代码标识符
（`application/x-www-form-urlencoded` 全小写无数字）会原样留着。

**掩码不是安全边界**，它是降噪 + 防误贴。真正的边界是：**别拿凭证当 needle 去搜**。
工具只保证"你搜什么，它就照着找"，不保证"你搜的东西适合出现在终端里"。

## 刻意不做的三件事

- 不执行 HAR 里的任何内容：不重放、不联网、不 eval。读源码不等于跑源码。
- 不猜语义：命中只说明"这个串在这份资源里出现过"，它意味着什么由人判断。
  本工具**不会**告诉你"这是签名算法"。
- 不把"没命中"说成"没有"：资源若是 base64 编码就读不出来。此时"0 命中"只等于
  "在这份残材料里没找到"，工具会把不可读的资源数显式报出来。

## 与真实抓包的边界

输入应当是真实抓包。`har_to_fixture.py` 降级出来的夹具把响应体压成了形态占位，
**源码不在里面**，跑出来必然是一份空报告——那不是"没有线索"，是"没有材料"。
所以本工具与真实抓包同属本地：不进仓库、不进 CI。

零第三方依赖。

用法：
    python scripts/automation/har_source.py capture.har
    python scripts/automation/har_source.py capture.har --grep deviceUuid
    python scripts/automation/har_source.py capture.har --grep deviceUuid --context 200
    python scripts/automation/har_source.py capture.har --grep keepSignIn --include-data
    python scripts/automation/har_source.py capture.har --grep deviceUuid --json --out src.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.har_probe import (  # noqa: E402
    classify_entry_order,
    load_har,
    sorted_indexed_entries,
)

# 源码类资源的判据：后缀与 mimeType 各一份，取并集。
# 只认"代码/标记"，不认 `application/json`——那一路是接口数据，走 --include-data。
SOURCE_SUFFIXES = (
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".css",
    ".html",
    ".htm",
    ".xhtml",
    ".map",
)

SOURCE_MIMES = frozenset(
    {
        "text/javascript",
        "application/javascript",
        "application/x-javascript",
        "application/ecmascript",
        "text/ecmascript",
        "module",
        "text/css",
        "text/html",
        "application/xhtml+xml",
    }
)

SHA_CHARS = 12
DEFAULT_CONTEXT = 300
DEFAULT_MASK_MIN = 40
DEFAULT_MAX_HITS = 5

# 掩码用的字符集：连续、不含空白。故意包含 `.` 与 `/`——JWT 有点号、
# 路径式的会话串有斜杠，不含它们就掩不住最该掩的东西。
OPAQUE_CHARS = r"0-9A-Za-z_+/=.~\-"
OPAQUE_RE = re.compile(rf"[{OPAQUE_CHARS}]{{{DEFAULT_MASK_MIN},}}")

# "这看起来是一个值而不是一个问题"。用来决定 needle 回显时要不要打码。
VALUE_RE = re.compile(rf"[{OPAQUE_CHARS}]{{16,}}")
MASKED_TEMPLATE = "«len={length} sha={sha}»"


def digest(value: str) -> str:
    """值的指纹。只出前 12 位——够区分，也不可能反推回原文。"""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:SHA_CHARS]


def masked(label: str) -> str:
    """把一个值换成长度 + 指纹。"""
    return MASKED_TEMPLATE.format(length=len(label), sha=digest(label))


def is_source_like(url: str, mime: str) -> bool:
    """这条响应是不是"源码类"资源。"""
    path = urlsplit(url or "").path.lower()
    if path.endswith(SOURCE_SUFFIXES):
        return True
    head = (mime or "").split(";")[0].strip().lower()
    return head in SOURCE_MIMES


def readable_text(entry: dict[str, Any]) -> tuple[str, str]:
    """取响应体里的可读文本。返回 (文本, 不可读原因)。

    不可读的原因有两种，且**必须分开报**：
    - `binary`：内容被 base64 编码。这是真正的"读不出来"，材料是残的。
    - `empty`：本来就没有正文（图片、304、预检响应）。这是正常的。

    两者混成一个"空"，会让"没有材料"看起来像"没有线索"。
    """
    content = (entry.get("response") or {}).get("content") or {}
    if content.get("encoding") == "base64":
        return "", "binary"
    text = content.get("text")
    if not isinstance(text, str) or not text:
        return "", "empty"
    return text, ""


def _is_opaque_run(run: str) -> bool:
    """这段长串是不是"不透明"到该掩掉。

    三个条件同时成立才算：够长、含数字、**同时**含大写与小写。
    这样 `application/x-www-form-urlencoded`（全小写）与
    `1900.cd97ba24.js`（无大写）都会原样留着——它们是可读的代码，不是凭证。
    """
    return (
        any(char.isdigit() for char in run)
        and any(char.isupper() for char in run)
        and any(char.islower() for char in run)
    )


def mask_runs(text: str, mask_min: int = DEFAULT_MASK_MIN) -> str:
    """把上下文里又长又不透明的串换成长度 + 指纹。"""
    pattern = OPAQUE_RE if mask_min == DEFAULT_MASK_MIN else re.compile(
        rf"[{OPAQUE_CHARS}]{{{mask_min},}}"
    )
    return pattern.sub(lambda m: masked(m.group(0)) if _is_opaque_run(m.group(0)) else m.group(0), text)


def display_needle(needle: str, mask: bool) -> str:
    """needle 回显时的样子。像值就打码，像名字/路径就原样。"""
    if mask and VALUE_RE.fullmatch(needle) and _is_opaque_run(needle):
        return masked(needle)
    return needle


def collect_sources(
    entries: Sequence[dict[str, Any]],
    *,
    include_data: bool,
    min_size: int,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """把抓包里**可读的文本响应**收成候选材料。

    返回值里的每一条都带 `_text`，它是给检索用的，不进报告——
    报告只带身份与长度，否则一份 JSON 报告会跟抓包一样大。
    """
    sources: list[dict[str, Any]] = []
    stats: Counter[str] = Counter({"responses": len(entries)})
    # 同一份资源被请求多次是常态（实测 reCAPTCHA 的脚本就抓了两次）。按
    # **URL + 内容指纹**去重：只有两者都相同才算同一份。不按 URL 单独去重——
    # 同一个接口地址返回不同内容是正常的，那会误合。
    seen: set[tuple[str, str]] = set()

    for index, entry in enumerate(entries):
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        url = request.get("url") or ""
        content = response.get("content") or {}
        mime = str(content.get("mimeType") or "")
        source_like = is_source_like(url, mime)

        if not source_like and not include_data:
            stats["skipped_not_source"] += 1
            continue

        text, reason = readable_text(entry)
        if not text:
            stats[f"unreadable_{reason}"] += 1
            continue
        if len(text) < min_size:
            stats["skipped_small"] += 1
            continue

        key = (url, digest(text))
        if key in seen:
            stats["duplicate_resources"] += 1
            continue
        seen.add(key)

        split = urlsplit(url)
        stats["source_like" if source_like else "data"] += 1
        sources.append(
            {
                "index": index,
                "url": url,
                "host": split.netloc,
                "path": split.path,
                "mime": mime,
                "chars": len(text),
                "lines": text.count("\n") + 1,
                "startedDateTime": str(entry.get("startedDateTime") or ""),
                "kind": "source" if source_like else "data",
                "_text": text,
            }
        )
    return sources, stats


def search_source(
    source: dict[str, Any],
    needles: Sequence[str],
    *,
    context: int,
    max_hits: int,
    mask: bool,
    regex: bool,
) -> dict[str, Any]:
    """在一份资源里找全部 needle，返回每处命中的偏移与上下文。"""
    text = source["_text"]
    found: dict[str, Any] = {}
    for needle in needles:
        if regex:
            try:
                matches = [m for m in re.finditer(needle, text)]
            except re.error:
                found[needle] = {"error": "正则无法编译"}
                continue
            spans = [(m.start(), m.end()) for m in matches]
        else:
            spans = []
            start = text.find(needle)
            while start != -1:
                spans.append((start, start + len(needle)))
                start = text.find(needle, start + 1)

        if not spans:
            continue
        rows = []
        for start, end in spans[:max_hits]:
            left = max(0, start - context)
            right = min(len(text), end + context)
            snippet = text[left:right]
            if mask:
                snippet = mask_runs(snippet)
            rows.append(
                {
                    "offset": start,
                    "line": text.count("\n", 0, start) + 1,
                    "context": snippet,
                }
            )
        found[needle] = {"count": len(spans), "matches": rows}
    return found


def analyze(
    har: dict[str, Any],
    *,
    needles: Sequence[str],
    include_data: bool,
    min_size: int,
    context: int,
    max_hits: int,
    mask: bool,
    regex: bool,
) -> dict[str, Any]:
    log = har.get("log") or {}
    raw = log.get("entries") or []
    entries = [entry for entry in raw if isinstance(entry, dict)]
    entry_order = classify_entry_order(
        [str(entry.get("startedDateTime") or "").strip() for entry in entries]
    )

    sources, stats = collect_sources(entries, include_data=include_data, min_size=min_size)

    results: list[dict[str, Any]] = []
    for needle in needles:
        rows: list[dict[str, Any]] = []
        total = 0
        for source in sources:
            hits = search_source(
                source,
                [needle],
                context=context,
                max_hits=max_hits,
                mask=mask,
                regex=regex,
            ).get(needle)
            if not hits or "error" in hits:
                continue
            total += hits["count"]
            rows.append(
                {
                    "index": source["index"],
                    "url": source["url"],
                    "host": source["host"],
                    "path": source["path"],
                    "chars": source["chars"],
                    "kind": source["kind"],
                    "count": hits["count"],
                    "matches": hits["matches"],
                }
            )
        rows.sort(key=lambda row: (-row["count"], row["index"]))
        results.append(
            {
                "needle": display_needle(needle, mask),
                "hits": total,
                "sources": len(rows),
                "results": rows,
            }
        )

    notes: list[str] = []
    if not sources:
        notes.append(
            "这份抓包里没有可读的文本资源：0 命中**不等于**「没有线索」，"
            "只等于「没有材料」。降级夹具就是这种情形——它把响应体压成了形态占位"
        )
    if stats.get("unreadable_binary"):
        notes.append(
            f"{stats['unreadable_binary']} 条响应的内容是 base64，读不出来："
            "材料是残的，这些资源里若有线索本工具看不见"
        )
    if not include_data:
        notes.append(
            f"接口数据响应体未纳入检索（已跳过 {stats.get('skipped_not_source', 0)} 条非源码资源）；"
            "要在响应数据里搜，加 --include-data"
        )
    if entry_order != "chronological":
        notes.append(
            "entries 数组不是时间序（实测 ProxyPin 导出基本是倒序）："
            "本工具按资源列结果，不按数组顺序下结论"
        )
    if needles and all(not row["hits"] for row in results):
        notes.append(
            "所有 needle 都 0 命中。这**是一条有用的负面结论**——说明线索不在这份抓包的"
            "源码里，别再在「看不出规则」上停留；但先确认上面的材料数不是 0"
        )

    # 报告里不带 _text。
    listing = [
        {key: value for key, value in source.items() if key != "_text"} for source in sources
    ]
    listing.sort(key=lambda row: -row["chars"])

    return {
        "har": {
            "entries": len(raw),
            "entries_parsed": len(entries),
            "entry_order": entry_order,
        },
        "scope": {
            "include_data": include_data,
            "min_size": min_size,
            "context": context,
            "max_hits": max_hits,
            "mask": mask,
            "regex": regex,
        },
        "counts": {
            "sources": len(sources),
            "source_like": stats.get("source_like", 0),
            "data": stats.get("data", 0),
            "unreadable_binary": stats.get("unreadable_binary", 0),
            "skipped_not_source": stats.get("skipped_not_source", 0),
            "skipped_small": stats.get("skipped_small", 0),
            "duplicate_resources": stats.get("duplicate_resources", 0),
            "chars_total": sum(source["chars"] for source in sources),
        },
        "sources": listing,
        "needles": results,
        "notes": notes,
    }


def render(report: dict[str, Any], top: int) -> str:
    lines: list[str] = []
    counts = report["counts"]
    scope = report["scope"]

    lines.append("=" * 70)
    lines.append("HAR 内嵌源码检索（只读、离线；长不透明串已掩码）")
    lines.append("=" * 70)
    lines.append(
        f"条目 {report['har']['entries']}（可解析 {report['har']['entries_parsed']}）  "
        f"可读文本资源 {counts['sources']}"
        f"（源码类 {counts['source_like']} / 数据 {counts['data']}）  "
        f"共 {counts['chars_total']} 字符"
    )
    if counts["unreadable_binary"]:
        lines.append(f"** 不可读（base64）{counts['unreadable_binary']} 条：材料是残的 **")
    if counts["duplicate_resources"]:
        lines.append(
            f"同一 URL 且内容相同的请求 {counts['duplicate_resources']} 条已合并为一份"
            "（抓包里同一资源被请求多次是常态）"
        )
    lines.append(
        f"范围 {'含接口数据' if scope['include_data'] else '仅源码类'}"
        f"    上下文 {scope['context']}    掩码 {'开' if scope['mask'] else '关'}"
    )

    if report["sources"]:
        lines.append("")
        lines.append("-- 可读资源（按大小） " + "-" * 30)
        for source in report["sources"][:top]:
            tag = "源码" if source["kind"] == "source" else "数据"
            lines.append(
                f"  [{tag}] {source['chars']:>8} 字符  {source['host']}{source['path']}"
            )
        if len(report["sources"]) > top:
            lines.append(f"  （另有 {len(report['sources']) - top} 份未列出，--top 可调）")

    for entry in report["needles"]:
        lines.append("")
        lines.append("-" * 70)
        lines.append(
            f"-- 「{entry['needle']}」 命中 {entry['hits']} 处 / {entry['sources']} 份资源"
        )
        if not entry["results"]:
            lines.append("   （0 命中：这份抓包的源码里没有它）")
            continue
        for row in entry["results"]:
            lines.append("")
            lines.append(
                f"  [{row['kind'] == 'source' and '源码' or '数据'}] {row['chars']} 字符  "
                f"{row['host']}{row['path']}   命中 {row['count']} 处"
            )
            for match in row["matches"]:
                lines.append(f"    @{match['offset']} ...{match['context']}...")
            if row["count"] > len(row["matches"]):
                lines.append(
                    f"    （另 {row['count'] - len(row['matches'])} 处未列出，--max-hits 可调）"
                )

    if report["notes"]:
        lines.append("")
        lines.append("-- 提示 " + "-" * 30)
        for note in report["notes"]:
            lines.append(f"· {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="HAR 内嵌源码检索：把应用自带的前端代码当证据来查。只读、离线、不执行。"
    )
    parser.add_argument("har", help="HAR 文件路径，'-' 表示从标准输入读取")
    parser.add_argument(
        "--grep",
        action="append",
        default=[],
        metavar="NEEDLE",
        help="要检索的串（字段名 / 接口路径 / 任意子串）。可重复",
    )
    parser.add_argument(
        "--regex", action="store_true", help="把 --grep 当正则（默认按字面量匹配）"
    )
    parser.add_argument(
        "--context",
        type=int,
        default=DEFAULT_CONTEXT,
        help=f"每处命中前后各显示多少字符（默认 {DEFAULT_CONTEXT}）",
    )
    parser.add_argument(
        "--max-hits",
        type=int,
        default=DEFAULT_MAX_HITS,
        help=f"每份资源每个 needle 最多列几处（默认 {DEFAULT_MAX_HITS}）",
    )
    parser.add_argument(
        "--include-data",
        action="store_true",
        help="把非源码类（接口数据）响应体也纳入检索；默认只搜源码类",
    )
    parser.add_argument(
        "--min-size", type=int, default=1, help="小于该长度的资源不纳入（默认 1）"
    )
    parser.add_argument(
        "--mask-min",
        type=int,
        default=DEFAULT_MASK_MIN,
        help=f"上下文里长于此的不透明串才掩码（默认 {DEFAULT_MASK_MIN}）",
    )
    parser.add_argument("--no-mask", action="store_true", help="不掩码，原样输出上下文")
    parser.add_argument("--top", type=int, default=30, help="资源清单最多列几份（默认 30）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", help="同时把 JSON 写入该路径")
    args = parser.parse_args(argv)

    if args.context < 0 or args.max_hits < 1 or args.min_size < 0 or args.mask_min < 1:
        print("--context/--min-size 不能为负，--max-hits/--mask-min 必须为正", file=sys.stderr)
        return 2

    try:
        har = load_har(args.har)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(f"无法解析 HAR: {error}", file=sys.stderr)
        return 2

    report = analyze(
        har,
        needles=args.grep,
        include_data=args.include_data,
        min_size=args.min_size,
        context=args.context,
        max_hits=args.max_hits,
        mask=not args.no_mask,
        regex=args.regex,
    )

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, args.top))
        if args.out:
            print(f"\nJSON 已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
