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
其中 `in_fence` 一项（代码围栏内整行不参与校验）按**行**计数，其余按引用计数——
`check_commands.py` 反而**进**围栏，两者的取词范围**有意不同**，不是遗漏。

零第三方依赖。

用法：
    python scripts/misc/check_doc_refs.py
    python scripts/misc/check_doc_refs.py --json
"""

from __future__ import annotations

import argparse
import json
import os
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

# 不参与校验的路径前缀：这些目录是本地产物（或被 gitignore），新克隆里本来就不存在。
# `.workbuddy-ai/` 是代理本地记忆——`.gitignore` 与 `check_tool_inventory.py` 都已声明它
# 不进仓库。**它曾经不在这张表里**：文档里写 `.workbuddy-ai/...` 会被判 `path_missing`，
# 于是「本地绿、CI 红」（实测：2026-09-26，见 `test_dot_prefixed_local_dir_is_exempt`）。
UNTRACKED_PREFIXES = (
    "cases/",
    "exports/",
    "reports/",
    "notes/",
    "tmp/",
    ".workbuddy-ai/",
)

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

# 只有后缀、没有名字（`.js`、`.py`）——是"这类文件"，不是某个文件。
BARE_SUFFIX_ONLY_RE = re.compile(r"^\.[A-Za-z0-9]+$")

# 裸文件名（无 `/`）的**显式豁免表**：按名字精确列，每条带理由，并**全量打印**。
#
# 为什么必须是表而不是启发式：`中视频.py`（读者自己的示例输入）与
# `create-py-script.md`（**曾经真实存在的悬空引用**，见 F1）在**形状上完全一样**——
# 都是"无斜杠 + 已知后缀"。区别只在语义，正则看不见语义。
# 所以这里**不猜**：列出来；没列又解析不到的，就是 drift。
# 代价是新增示例名时要补一行——这正是"**强制问题被回答**"，不是噪声。
BARE_NAME_EXEMPTIONS: dict[str, str] = {
    "中视频.py": "教程里的示例输入文件名（读者自己会有），不是本仓库文件",
    "中视频.js": "教程里的示例输入文件名（读者自己会有），不是本仓库文件",
    "ua_generator.py": "示例脚本名（读者自己写），不是本仓库文件",
    "decrypt_tool.py": "示例工具名（读者自己写），不是本仓库文件",
    "cordova.js": "第三方项目（Cordova）内部的文件，本仓库不拥有",
    "decompile_failed.txt": "工具运行时的产出文件名，不是本仓库文件",
    "exports.txt": "工具运行时的产出文件名，不是本仓库文件",
    "imports.txt": "工具运行时的产出文件名，不是本仓库文件",
    "strings.txt": "工具运行时的产出文件名，不是本仓库文件",
}

# 整篇在讲**上游仓库**文件的文档：其中的裸文件名指上游的文件，本仓库不拥有。
#
# 为什么按**文档**豁免，而不是按文件名列：
#   - `ad-removal.md`（上游）与 `README.md`（本仓库）**形状完全一样**；
#   - 而且**同一份文档里两种都可能出现**（这份台账既列上游切片，也点本仓库落点）。
# 按文件名列会把本仓库的同名文件一起放过；按文档豁免保留的"文档级语境"
# 是这里**唯一可判别**的信息。
#
# **代价（明确记下，别忘）**：这份文档里的裸文件名**不参与校验**。
# 所以它只适用于"整篇在讲别的仓库"的台账，**不是通用逃生门**。
# `test_check_doc_refs.py::UpstreamDocExemptionTests` 钉住这些路径真实存在——
# 文档改名后豁免不会静默失效。
UPSTREAM_REFERENCE_DOCS = {"docs/upstream-absorption.md"}

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
        "`cases/`、`exports/`、`reports/`、`notes/`、`tmp/`、`.workbuddy-ai/` 是本地产物目录（或被 gitignore），不在版本库里",
    ),
    (
        "not_a_path",
        "含空白（整条命令、含占位词的路径），或不含 `/` 且不以已知后缀结尾的反引号内容（命令名、字段名、技能名），不是路径",
    ),
    (
        "bare_suffix_only",
        "只有后缀没有名字（`.js`、`.py`）——指的是**这类文件**，不是某个文件，无从校验存在性",
    ),
    (
        "bare_example_name",
        "裸文件名在 `BARE_NAME_EXEMPTIONS` 显式表里：读者自己的示例名 / 工具产出名 / 第三方项目文件，本仓库不拥有（**每条都有单独理由，全量打印**）",
    ),
    (
        "inside_local_job",
        "文档本身在 `projects/<作业>/` 里——作业目录是本地产物（真实抓包、真实域名），其中的文件名指向作业内文件，不进版本库",
    ),
    (
        "upstream_reference_doc",
        "文档整篇在讲**上游仓库**的文件（`UPSTREAM_REFERENCE_DOCS`）：其中的裸文件名指上游文件，本仓库不拥有。**代价：该文档的裸文件名不参与校验**",
    ),
    (
        "directory_ref",
        "不以已知文件后缀结尾的是目录引用；目录常按读者自己的工作目录书写（`data/`、`outputs/`），本仓库不拥有其存在性",
    ),
    (
        "in_fence",
        "``` 围栏内的**整行**不参与校验（**本项计数单位是行**，其余几项是引用数）："
        "围栏里放的是示例、命令与片段，其中的路径属于读者环境，不是本仓库的引用",
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
    # 只摘掉一个前导 `./`。**不能用 `lstrip("./")`**：它会连同点目录名的那个点一起剥掉，
    # `.workbuddy-ai/…` 变成 `workbuddy-ai/…`、`.github/…` 变成 `github/…`——
    # 于是任何以点开头的目录都匹配不上 UNTRACKED_PREFIXES，豁免静默失效。
    normalised = target.replace("\\", "/")
    if normalised.startswith("./"):
        normalised = normalised[2:]
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


_FILENAME_INDEX: dict[Path, dict[str, list[Path]]] = {}


def _build_filename_index() -> dict[str, list[Path]]:
    """文件名 → 路径们。用于解析**裸文件名**（无斜杠）。

    按 ROOT 缓存：测试会把 ROOT 指到沙箱，各沙箱各建各的索引，不会串味。
    遍历时剪掉 `SKIP_DIR_NAMES` 与 `tmp/`（`tmp/` 实测有几千个文件，
    且全是本地产物，不该参与"仓库里有没有这个名字"的判断）。
    """
    index: dict[str, list[Path]] = {}
    for current, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIR_NAMES and d != "tmp"]
        for name in files:
            index.setdefault(name, []).append(Path(current) / name)
    return index


def _filename_index() -> dict[str, list[Path]]:
    if ROOT not in _FILENAME_INDEX:
        _FILENAME_INDEX[ROOT] = _build_filename_index()
    return _FILENAME_INDEX[ROOT]


def _inside_local_job(doc: Path) -> bool:
    """文档是否在 `projects/<作业>/` 里（作业目录是本地产物）。"""
    try:
        parts = doc.relative_to(ROOT).parts
    except ValueError:
        return False
    if len(parts) < 2 or parts[0] != "projects":
        return False
    return parts[1] not in {"README.md", "_template"}


def _resolve_bare(doc: Path, name: str) -> Path | None:
    """解析裸文件名：同目录优先，其次全仓按文件名找。

    全仓有**多个同名**时返回第一个（保守放行）——"指的是哪一个"判不出来，
    而规则 79 说**宁可漏，不可误报**。
    """
    same_dir = doc.parent / name
    try:
        if same_dir.is_file():
            return same_dir
    except OSError:
        pass
    hits = _filename_index().get(name, [])
    return hits[0] if hits else None


def _drift(file: Path, line: int, kind: str, detail: str) -> dict[str, object]:
    return {
        "file": file.relative_to(ROOT).as_posix(),
        "line": line,
        "kind": kind,
        "detail": detail,
    }


def _check_bare_name(doc: Path, line: int, candidate: str) -> tuple[list[dict], str | None]:
    """裸文件名（无 `/`）的判据。

    F2：原先这里直接判 `not_a_path`，**整类豁免**——architect 里 5 处悬空的
    `create-py-script.md` / `create-js-script.md` 正是从这条缝漏的（F1）。
    现在的判据是：**能解析到就通过；解析不到就必须在显式表里**。
    """
    drifts: list[dict] = []
    reason = _exempt(candidate)
    if reason:
        return drifts, reason
    if BARE_SUFFIX_ONLY_RE.match(candidate):
        return drifts, "bare_suffix_only"
    if _inside_local_job(doc):
        return drifts, "inside_local_job"
    try:
        relative_doc = doc.relative_to(ROOT).as_posix()
    except ValueError:
        relative_doc = ""
    if relative_doc in UPSTREAM_REFERENCE_DOCS:
        return drifts, "upstream_reference_doc"
    if _resolve_bare(doc, candidate) is not None:
        return drifts, None
    if candidate in BARE_NAME_EXEMPTIONS:
        return drifts, "bare_example_name"
    drifts.append(
        _drift(doc, line, "path_missing", f"点名的文件名在本仓库里找不到：{candidate}")
    )
    return drifts, None


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
    has_slash = "/" in candidate.rstrip("/")
    if not candidate.endswith(PATH_SUFFIXES):
        # 无已知后缀：有斜杠的当目录引用，没斜杠的当命令名/字段名/技能名。
        return drifts, "directory_ref" if has_slash else "not_a_path"
    if not has_slash:
        # 裸文件名走单独判据（F2）：它可能是**真的引用**，也可能是示例名。
        return _check_bare_name(doc, line, candidate)
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
                # 分隔行本身既不校验、也不计入"围栏内"——计数只数**夹在中间**的行，
                # 这样 `in_fence` 的数字与读者理解的"围栏内有多少行"一致。
                in_fence = not in_fence
                continue
            if in_fence:
                # 围栏内整行跳过——但**要计数**。原先这里是静默 `continue`，
                # docstring 却写着"跳过与豁免都是显式常量并全量打印"，两句话对不上。
                # 不进入围栏是有意的（围栏里是示例与命令，路径属于读者环境），
                # 所以修法是把这次跳过**说出来**，而不是改成进围栏。
                exempt_hits["in_fence"] += 1
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
