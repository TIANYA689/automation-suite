#!/usr/bin/env python3
"""可复用发现库（kb/ai-findings/findings.jsonl）的读写工具。

只做两件事：追加一条结构化发现、按关键词检索。追加为纯 append，不修改历史记录；
结论变化通过 status 字段标记（active / superseded / invalid），原始记录保留。
追加前取进程间写锁（`findings.jsonl.lock`），避免并发写入把 JSONL 截成半行。

零第三方依赖。默认写入 kb/ai-findings/findings.jsonl（该文件随仓库提交）。

用法：
    python scripts/misc/ai_finding.py add --kind path --area js-reverse \
        --title "..." --trigger "..." --detail "..." --reuse high
    python scripts/misc/ai_finding.py search "混淆 字符串数组"
    python scripts/misc/ai_finding.py list --limit 20
    python scripts/misc/ai_finding.py validate
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINDINGS = ROOT / "kb" / "ai-findings" / "findings.jsonl"
LOCK = FINDINGS.with_name(FINDINGS.name + ".lock")

LOCK_RETRY_SECONDS = 0.05
LOCK_TIMEOUT_SECONDS = 15.0
LOCK_STALE_SECONDS = 120.0

KINDS = {"path", "tool", "signal", "dead-end"}
LEVELS = {"high", "medium", "low"}
STATUSES = {"active", "superseded", "invalid"}
REQUIRED = ("time", "kind", "area", "title", "trigger", "detail", "reuse", "confidence", "status")

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|secret|token)\b\s*[:=]\s*[\"'][^\"']{8,}[\"']"),
    re.compile(r"C:\\Users\\[^\\\s]+", re.I),
    re.compile(r"D:[\\/]Git[\\/]", re.I),
]

SCANNED_FIELDS = ("title", "trigger", "detail", "area", "kind")


def _iter_strings(value: object) -> list[str]:
    """递归收集嵌套结构里的所有字符串，用于敏感内容扫描。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _iter_strings(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _iter_strings(item)]
    return []


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "").lower()).strip()


def load(path: Path | None = None) -> list[dict]:
    path = path or FINDINGS
    if not path.is_file():
        return []
    records = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            record = {"_error": f"第 {lineno} 行 JSON 解析失败: {exc}"}
        record["_line"] = lineno
        records.append(record)
    return records


def validate_records(records: list[dict]) -> list[str]:
    errors: list[str] = []
    for record in records:
        line = record.get("_line", "?")
        if record.get("_error"):
            errors.append(record["_error"])
            continue
        for key in REQUIRED:
            if key not in record or not str(record[key]).strip():
                errors.append(f"第 {line} 行缺少字段: {key}")
        if record.get("kind") and record["kind"] not in KINDS:
            errors.append(f"第 {line} 行 kind 非法: {record['kind']}（可选 {sorted(KINDS)}）")
        for key in ("reuse", "confidence"):
            if record.get(key) and record[key] not in LEVELS:
                errors.append(f"第 {line} 行 {key} 非法: {record[key]}")
        if record.get("status") and record["status"] not in STATUSES:
            errors.append(f"第 {line} 行 status 非法: {record['status']}")
        for pattern in SECRET_PATTERNS:
            haystack = " ".join(text for key in SCANNED_FIELDS for text in _iter_strings(record.get(key)))
            haystack += " " + " ".join(_iter_strings(record.get("evidence", {})))
            if pattern.search(haystack):
                errors.append(f"第 {line} 行疑似含凭据或本机路径，已拒绝写入")
                break
    return errors


class FindingsLock:
    """发现库的跨进程写锁。

    `add` 是"读全量 → 判重 → 追加"，不是原子操作。两个进程并发 add 时会各自
    基于旧内容判断，然后交错写入同一文件，产出半行 JSON，整个库随之失效。
    这里用 O_CREAT|O_EXCL 建锁文件互斥；锁文件超过 LOCK_STALE_SECONDS 视为
    残留（进程被杀），自动清理后重试。
    """

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT_SECONDS) -> None:
        self.path = path
        self.timeout = timeout

    def __enter__(self) -> "FindingsLock":
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._is_stale():
                    self._release()
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"等待发现库写锁超时（{self.timeout:g}s）：{self.path}；"
                        "若确认无其他写入进程，可手动删除该锁文件"
                    )
                time.sleep(LOCK_RETRY_SECONDS)
                continue
            os.close(descriptor)
            return self

    def __exit__(self, *_exc: object) -> None:
        self._release()

    def _is_stale(self) -> bool:
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return False
        return age > LOCK_STALE_SECONDS

    def _release(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def findings_lock() -> FindingsLock:
    return FindingsLock(LOCK)


def display_path(path: Path) -> str:
    """仓库内用相对路径，仓库外退回绝对路径（测试与自定义布局会用到）。"""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def add(args: argparse.Namespace) -> int:
    record = {
        "time": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "kind": args.kind,
        "area": args.area,
        "title": args.title,
        "trigger": args.trigger,
        "detail": args.detail,
        "evidence": {"path": args.evidence or "", "note": args.note or ""},
        "reuse": args.reuse,
        "confidence": args.confidence,
        "status": args.status,
    }
    errors = validate_records([record])
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    FINDINGS.parent.mkdir(parents=True, exist_ok=True)
    # 判重与追加必须整体互斥：两个进程同时 add 会各自读到旧内容并交错写入，
    # 结果是 JSONL 被截断成半行（实测踩过）。
    with findings_lock():
        existing = load()
        duplicate = next(
            (
                r
                for r in existing
                if not r.get("_error") and normalize(r.get("title", "")) == normalize(record["title"])
            ),
            None,
        )
        if duplicate:
            print(
                json.dumps(
                    {"ok": False, "reason": f"已存在同标题记录（第 {duplicate['_line']} 行），请改用 status 更新而非重复追加"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1

        # newline="\n"：Windows 默认会把 \n 翻成 \r\n，混进原本 LF 的 JSONL。
        with FINDINGS.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(json.dumps({"ok": True, "appended_to": display_path(FINDINGS), "record": record}, ensure_ascii=False, indent=2))
    return 0


def search(query: str, records: list[dict], limit: int) -> list[dict]:
    normalized = normalize(query)
    tokens = {tok for tok in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", normalized)}
    scored = []
    for record in records:
        if record.get("_error"):
            continue
        haystack = normalize(
            " ".join(
                str(record.get(key, ""))
                for key in ("title", "trigger", "detail", "area", "kind")
            )
            + " "
            + json.dumps(record.get("evidence", {}), ensure_ascii=False)
        )
        score = 0.0
        if normalized and normalized in haystack:
            score += 10.0
        score += sum(3.0 for token in tokens if token in haystack)
        if score > 0:
            # 质量加成只在已有内容命中时生效，否则任意记录都会得分
            if record.get("status") == "active":
                score += 1.0
            if record.get("reuse") == "high":
                score += 1.0
            scored.append((score, record))
    scored.sort(key=lambda item: (-item[0], item[1].get("time", "")))
    return [{"score": round(score, 2), **record} for score, record in scored[:limit]]


def main() -> int:
    parser = argparse.ArgumentParser(description="可复用发现库读写工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="追加一条发现")
    p_add.add_argument("--kind", required=True, choices=sorted(KINDS))
    p_add.add_argument("--area", required=True)
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--trigger", required=True, help="什么信号出现时该读这条")
    p_add.add_argument("--detail", required=True)
    p_add.add_argument("--evidence", default="")
    p_add.add_argument("--note", default="")
    p_add.add_argument("--reuse", default="medium", choices=sorted(LEVELS))
    p_add.add_argument("--confidence", default="medium", choices=sorted(LEVELS))
    p_add.add_argument("--status", default="active", choices=sorted(STATUSES))

    p_search = sub.add_parser("search", help="按关键词检索")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="列出最近记录")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--json", action="store_true")

    sub.add_parser("validate", help="校验全部记录")

    args = parser.parse_args()
    records = load()

    if args.command == "add":
        return add(args)

    if args.command == "validate":
        errors = validate_records(records)
        print(
            json.dumps(
                {"ok": not errors, "count": len(records), "path": FINDINGS.relative_to(ROOT).as_posix(), "errors": errors},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if not errors else 1

    if args.command == "search":
        hits = search(args.query, records, args.limit)
        if args.json:
            print(json.dumps({"query": args.query, "hits": hits}, ensure_ascii=False, indent=2))
            return 0
        if not hits:
            print("未命中。可尝试更宽的关键词，或先用 ai_finding.py list 浏览。")
            return 0
        for hit in hits:
            print(f"[{hit['score']}] {hit.get('kind')} / {hit.get('area')} — {hit.get('title')}")
            print(f"      触发: {hit.get('trigger')}")
            print(f"      详情: {hit.get('detail')}")
            print()
        return 0

    selected = [r for r in records if not r.get("_error")][-args.limit :]
    if args.json:
        print(json.dumps(selected, ensure_ascii=False, indent=2))
        return 0
    if not selected:
        print("暂无记录。")
        return 0
    for record in reversed(selected):
        print(f"{record.get('time', '')}  [{record.get('kind')}/{record.get('area')}]  {record.get('title')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
