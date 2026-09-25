#!/usr/bin/env python3
"""文档交叉引用可达性校验。

`check_commands.py` 管"命令的参数是不是真的"，本脚本管"引用的目标是不是真的"。
两者是不同的问题：一个链接可以指向存在的文件而锚点不存在，一段散文可以点名
一个已经改名的 kb 篇目。

判据（任何一条命中即 drift）：

- `link_missing`   —— Markdown 链接指向的仓库内路径不存在
- `anchor_missing` —— 链接或裸锚点指向的小节标题不存在
- `path_missing`   —— 反引号点名的仓库内路径不存在

跳过与豁免都是显式常量并**全量打印**：可审计的排除不是漏洞。

零第三方依赖。

用法：
    python scripts/misc/check_doc_refs.py
    python scripts/misc/check_doc_refs.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCAN_ROOTS = (
    "README.md",
    "AI-USAGE.md",
    "AGENTS.md",
    "SKILLS.md",
    "CONTRIBUTING.md",
    "docs",
    "skills",
    "kb",
    "templates",
    "projects",
    "tools",
    ".github",
)
SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
}

# 不参与校验的路径前缀：这些目录是本地产物，新克隆里本来就不存在。
UNTRACKED_PREFIXES = ("cases/", "exports/", "reports/", "notes/", "tmp/")

PATH_SUFFIXES = (
    ".md",
    ".py",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".txt",
    ".toml",
    ".yml",
    ".yaml",
    ".html",
    ".js",
    ".java",
    ".ini",
    ".cfg",
)

EXEMPTIONS: tuple[tuple[str, str], ...] = (
    (
        "template",
        "含 `<...>`、`{...}`、`*`、`$` 的写法是模板或通配，不是具体路径",
    ),
    (
        "outside_repo",
        "以 `~`、盘符或 `http` 开头的是仓库外目标（用户级配置、外部站点），本仓库不拥有",
    ),
    (
        "untracked_dir",
        "`cases/`、`exports/`、`reports/`、`notes/`、`tmp/` 是本地产物目录，不在版本库里",
    ),
    (
        "not_a_path",
        "含空白（整条命令、含占位词的路径）或不含 `/` 的反引号内容（命令名、字段名、技能名），不是路径",
    ),
    (
        "directory_ref",
        "不以已知文件后缀结尾的是目录引用；目录常按读者自己的工作目录书写（`data/`、`outputs/`），本仓库不拥有其存在性",
    ),
)

LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)\)")
CODE_RE = re.compile(r"`(?P<body>[^`\n]+)`")
HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")


def slugify(title: str) -> str:
    """GitHub 风格锚点：去格式、转小写、空白转连字符、丢弃标点。

    标点判定必须按 Unicode 类别来，不能只留"字母数字 + CJK"：中文标题里的顿号
    `、` 是 Po 类标点，GitHub 会丢掉它，而"是 CJK 就保留"的写法会留下它，
    于是 `## P5.4 多邮箱适配、故障切换…` 的锚点永远匹配不上。
    """
    text = re.sub(r"`([^`]*)`", r"\1", title)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = unicodedata.normalize("NFKC", text).strip().lower()
    kept = []
    for character in text:
        category = unicodedata.category(character)
        if character in {"-", "_"}:
            kept.append(character)
            continue
        if category.startswith(("P", "S")):
            continue
        if character.isspace():
            kept.append(" ")
            continue
        kept.append(character)
    return "".join(kept).replace(" ", "-")


def _iter_docs() -> list[Path]:
    found: list[Path] = []
    for entry in SCAN_ROOTS:
        target = ROOT / entry
        if target.is_file():
            found.append(target)
            continue
        if not target.is_dir():
            continue
        for path in sorted(target.rglob("*.md")):
            if any(part in SKIP_DIR_NAMES for part in path.relative_to(ROOT).parts):
                continue
            found.append(path)
    return found


def collect_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return anchors
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            anchors.add(slugify(match.group("title")))
    return anchors


_ANCHOR_CACHE: dict[Path, set[str]] = {}


def anchors_of(path: Path) -> set[str]:
    if path not in _ANCHOR_CACHE:
        _ANCHOR_CACHE[path] = collect_anchors(path)
    return _ANCHOR_CACHE[path]


def _exempt(target: str) -> str | None:
    if any(token in target for token in ("<", ">", "{", "}", "*", "$")):
        return "template"
    if target.startswith(("http://", "https://", "mailto:", "~")) or re.match(
        r"^[A-Za-z]:", target
    ):
        return "outside_repo"
    normalised = target.replace("\\", "/").lstrip("./")
    if normalised.startswith(UNTRACKED_PREFIXES):
        return "untracked_dir"
    return None


def _resolve(doc: Path, target: str) -> Path | None:
    cleaned = target.replace("\\", "/")
    candidates = [ROOT / cleaned, doc.parent / cleaned]
    parts = doc.relative_to(ROOT).parts
    if parts and parts[0] == "docs":
        candidates.append(ROOT / "tools" / Path(*parts[1:]).parent / cleaned)
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


def _drift(file: Path, line: int, kind: str, detail: str) -> dict[str, object]:
    return {
        "file": file.relative_to(ROOT).as_posix(),
        "line": line,
        "kind": kind,
        "detail": detail,
    }


def _check_link(doc: Path, line: int, target: str) -> tuple[list[dict], str | None]:
    drifts: list[dict] = []
    reason = _exempt(target)
    if reason:
        return drifts, reason

    path_part, _, anchor = target.partition("#")
    resolved = _resolve(doc, path_part) if path_part else doc
    if resolved is None:
        drifts.append(_drift(doc, line, "link_missing", f"链接目标不存在：{target}"))
        return drifts, None
    if anchor:
        if resolved.suffix != ".md":
            drifts.append(
                _drift(doc, line, "anchor_missing", f"{target} 指向非 Markdown 文件，不可能有锚点")
            )
        elif slugify(anchor) not in anchors_of(resolved):
            drifts.append(_drift(doc, line, "anchor_missing", f"{path_part or doc.name} 没有小节 #{anchor}"))
    return drifts, None


def _check_backticked(doc: Path, line: int, body: str) -> tuple[list[dict], str | None]:
    drifts: list[dict] = []
    candidate = body.strip()
    if any(character.isspace() for character in candidate):
        return drifts, "not_a_path"
    if "/" not in candidate.rstrip("/"):
        return drifts, "not_a_path"
    if not candidate.endswith(PATH_SUFFIXES):
        return drifts, "directory_ref"
    reason = _exempt(candidate)
    if reason:
        return drifts, reason
    if _resolve(doc, candidate) is None:
        drifts.append(_drift(doc, line, "path_missing", f"点名的路径不存在：{candidate}"))
    return drifts, None


def run() -> dict[str, object]:
    drifts: list[dict[str, object]] = []
    exempt_hits: dict[str, int] = {reason: 0 for reason, _ in EXEMPTIONS}
    links_checked = 0
    paths_checked = 0

    for doc in _iter_docs():
        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        in_fence = False
        for number, raw in enumerate(text.splitlines(), 1):
            if raw.strip().startswith("```"):
                in_fence = not in_fence
            if in_fence:
                continue

            for match in LINK_RE.finditer(raw):
                links_checked += 1
                found, reason = _check_link(doc, number, match.group("target"))
                drifts.extend(found)
                if reason:
                    exempt_hits[reason] += 1

            for match in CODE_RE.finditer(raw):
                found, reason = _check_backticked(doc, number, match.group("body"))
                if reason:
                    exempt_hits[reason] += 1
                    continue
                paths_checked += 1
                drifts.extend(found)

    return {
        "ok": not drifts,
        "links_checked": links_checked,
        "paths_checked": paths_checked,
        "drift_count": len(drifts),
        "drifts": drifts,
        "exemptions": [
            {"reason": reason, "hits": exempt_hits.get(reason, 0), "why": why}
            for reason, why in EXEMPTIONS
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验文档交叉引用是否可达。")
    parser.add_argument("--json", action="store_true", help="只输出 JSON（不追加 RESULT 令牌）")
    args = parser.parse_args(argv)

    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.json:
        print(f"RESULT={'OK' if report['ok'] else 'DRIFT'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
