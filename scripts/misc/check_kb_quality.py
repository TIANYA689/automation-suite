#!/usr/bin/env python3
"""经验库质量门禁：`kb/ai-findings/findings.jsonl`。

回答两个问题（都只读、离线、零第三方依赖）：

1. **active 的 finding 有没有证据，证据是不是一条断链？**
   `evidence.path` 必须至少含一个**像路径**的 token（描述文字不算——schema 里
   这个字段的语义是「证据文件相对路径」）。token 分三类：
   - **本仓库拥有**（`git ls-files` 命中）→ 通过；
   - **本地产物**（首段是 `projects/` `exports/` `reports/` `notes/` `tmp/`
     `.workbuddy-ai/`）→ **通过**。库自己的 README 就用 `--evidence "exports/..."`
     举例，这些目录是作业产物的既定位置，被 gitignore 是设计而非缺陷；
   - **像仓库内路径却不在仓库里**（文件被删或路径写错）→ 断链，报
     `evidence_broken`。
   **不要求证据必须在仓库里**：本门禁的第一版用 `git ls-files` 一刀切，把上面
   第二类判成缺陷，等于要求证据搬家——那是把判据的形态假设当成了事实（规则 98），
   而且与库自己的 README 示例相矛盾。
2. **superseded 的 finding 有没有指向真实存在的技术条目？**
   结论被更新时按 `kb/ai-findings/README.md` 的约定把 `status` 改成
   `superseded`，并在 `detail` 里指向新的 `kb/*/techniques/*.md`；那个引用
   必须能解析到本仓库里的文件，否则「已提炼」这句话无从复核。

**空集必须报错**（MEMORY 规则 101：「跳过」与「通过」退出码相同本身就是缺陷）：
`findings.jsonl` 不存在、解析出 0 条、或 active 一条都没有时，脚本以非零退出。
这三种「被筛成空集」的情形必须失败，不能静默通过。

**默认只出 warning**（对应审计 P2 的「先 warning 后 strict」）：证据类问题默认
只报告不影响退出码，`--strict` 才把 warning 升级为失败。真正的硬失败只有
「空集」这一类——它回答的是「这条门禁到底跑没跑」。

用法：
    python scripts/misc/check_kb_quality.py
    python scripts/misc/check_kb_quality.py --strict
    python scripts/misc/check_kb_quality.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_finding  # noqa: E402  （复用发现库的加载与状态枚举，避免两处判据漂移）

ROOT = Path(__file__).resolve().parents[2]
FINDINGS = ROOT / "kb" / "ai-findings" / "findings.jsonl"

# 只认这些后缀的 token 才是「像路径的东西」。没有它，`0.24`、`pool.comple`
# 这类散文里的数字与标识符也会被当成路径，报告会被噪声淹没。
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
    ".har",
)

# 「本地产物目录」——库自己的 README 用 `--evidence "exports/..."` 举例，这些
# 目录是作业产物的既定位置（被 .gitignore 挡住是设计，不是缺陷）。证据落在这里
# 一律通过：本门禁回答的是「有没有证据 / 是不是断链」，不是「证据搬没搬进仓库」。
LOCAL_ARTIFACT_PREFIXES = (
    "projects/",
    "exports/",
    "reports/",
    "notes/",
    "tmp/",
    ".workbuddy-ai/",
)
# 一个路径 token：以字母/数字/下划线开头（**允许一个前导点**，否则
# `.workbuddy-ai/…` 会被截成 `workbuddy-ai/…` 而前缀匹配不上——与 finding
# 「check_doc_refs 的点目录归一化剥点」是同一个坑），中间可含 `/ . - _` 与 CJK，
# 以「点 + 1~6 位后缀」结尾。`:行号` 与 `::符号` 因不含在字符集里而自然截断。
PATH_TOKEN_RE = re.compile(r"\.?[A-Za-z0-9_][A-Za-z0-9_./\-\u4e00-\u9fff]*\.[A-Za-z0-9]{1,6}")
SEGMENT_SPLIT_RE = re.compile(r"[;；]")


def load_tracked(root: Path = ROOT) -> set[str]:
    """本仓库拥有的文件集（相对仓库根、POSIX 分隔）。

    `git ls-files` 就是 `actions/checkout` 之后仓库里的文件集——用它判「拥有」，
    而不是 `Path.exists()`，才不会把 gitignore 掉的本地产物算进来。
    git 不可用时抛错，**不退回工作区遍历**：退回等于把这条判据偷偷换掉。
    """
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git ls-files 失败（exit={completed.returncode}）："
            f"{(completed.stderr or '').strip()}；无法判定文件是否被本仓库拥有"
        )
    return {
        name.replace("\\", "/")
        for name in completed.stdout.split("\0")
        if name.strip()
    }


def extract_path_tokens(text: str) -> list[str]:
    """从一段自由文本里抽出「像仓库内路径」的 token（去重、保序）。"""
    tokens: list[str] = []
    for segment in SEGMENT_SPLIT_RE.split(text or ""):
        for match in PATH_TOKEN_RE.finditer(segment):
            token = match.group(0)
            if token.endswith(PATH_SUFFIXES) and token not in tokens:
                tokens.append(token)
    return tokens


def _normalise(token: str) -> str:
    normalised = token.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def resolve_token(token: str, tracked: set[str], basenames: set[str]) -> str:
    """返回 token 的解析结果：`exact` / `local` / `basename` / `bare` / `broken`。

    - `exact`    ：本仓库拥有（`git ls-files` 命中）；
    - `local`    ：落在本地产物目录下——**合法**的证据位置，只是不在仓库里；
    - `basename` ：裸文件名，按 basename 命中仓库内文件；
    - `bare`     ：裸文件名但仓库里没有——可能是本地产物的名字，不判断链；
    - `broken`   ：像仓库内相对路径却解析不到——**断链**，这才要报。
    """
    normalised = _normalise(token)
    if normalised in tracked:
        return "exact"
    if normalised.startswith(LOCAL_ARTIFACT_PREFIXES):
        return "local"
    if "/" not in normalised:
        return "basename" if normalised in basenames else "bare"
    return "broken"


def _resolve_evidence(text: str, tracked: set[str], basenames: set[str]) -> tuple[str, list[str]]:
    """返回 (结论, 断链 token 列表)。结论 ∈ {resolved, broken, none}。

    `none` 指整段里没有一个「像路径」的 token——schema 里 `path` 的语义是
    证据文件相对路径，写成描述文字属字段误用，报 `missing_evidence`。
    """
    tokens = extract_path_tokens(text)
    if not tokens:
        return "none", []
    broken = [t for t in tokens if resolve_token(t, tracked, basenames) == "broken"]
    if broken:
        return "broken", broken
    return "resolved", []


def check(
    records: list[dict],
    tracked: set[str],
    errors: list[str],
    warnings: list[dict],
) -> dict[str, int]:
    """对已解析的记录跑两条质量判据。空集守卫的结论写进 `errors`。"""
    basenames = {Path(name).name for name in tracked}
    by_status: dict[str, int] = {}
    active = 0
    superseded = 0
    for record in records:
        if record.get("_error"):
            errors.append(
                f"第 {record.get('_line', '?')} 行 JSON 解析失败：{record['_error']}"
            )
            continue
        status = str(record.get("status", "")).strip() or "<空>"
        by_status[status] = by_status.get(status, 0) + 1

        if status == "active":
            active += 1
            evidence = record.get("evidence")
            path_text = evidence.get("path", "") if isinstance(evidence, dict) else ""
            verdict, broken = _resolve_evidence(str(path_text), tracked, basenames)
            confidence = str(record.get("confidence", "")).strip() or "<空>"
            if verdict == "none" and confidence != "low":
                warnings.append(
                    {
                        "line": record.get("_line"),
                        "title": record.get("title", ""),
                        "status": status,
                        "kind": "missing_evidence",
                        "detail": (
                            f"evidence.path 里没有一个像路径的 token（confidence={confidence}）——"
                            "schema 里这个字段的语义是「证据文件相对路径」；"
                            "README 约定：没有证据的发现只能给 low 置信度"
                        ),
                    }
                )
            elif verdict == "broken":
                warnings.append(
                    {
                        "line": record.get("_line"),
                        "title": record.get("title", ""),
                        "status": status,
                        "kind": "evidence_broken",
                        "detail": "evidence 里像仓库内路径的 token 解析不到（文件已删或路径写错）："
                        + "、".join(broken),
                    }
                )
        elif status == "superseded":
            superseded += 1
            evidence = record.get("evidence")
            path_text = evidence.get("path", "") if isinstance(evidence, dict) else ""
            haystack = f"{record.get('detail', '')} {path_text}"
            technique = [
                token
                for token in extract_path_tokens(haystack)
                if "/techniques/" in _normalise(token)
                and _normalise(token).endswith(".md")
                and resolve_token(token, tracked, basenames) in ("exact", "basename")
            ]
            if not technique:
                warnings.append(
                    {
                        "line": record.get("_line"),
                        "title": record.get("title", ""),
                        "status": status,
                        "kind": "superseded_without_technique",
                        "detail": "superseded 的 finding 没有指向真实存在的 kb/*/techniques/*.md 技术条目",
                    }
                )
    return {"active": active, "superseded": superseded, "by_status": by_status}


def run(
    findings_path: Path | None = None,
    tracked: set[str] | None = None,
    strict: bool = False,
) -> dict[str, object]:
    findings_path = findings_path or FINDINGS
    errors: list[str] = []
    warnings: list[dict] = []

    if tracked is None:
        try:
            tracked = load_tracked(ROOT)
        except RuntimeError as exc:
            errors.append(str(exc))
            tracked = set()

    records: list[dict] = []
    if not findings_path.is_file():
        errors.append(f"{_display(findings_path)} 不存在，经验库门禁无从运行")
    else:
        records = ai_finding.load(findings_path)
        if not records:
            errors.append(
                f"{_display(findings_path)} 解析出 0 条记录，门禁空转（空集与通过同为 exit=0 是缺陷）"
            )

    counts = {"active": 0, "superseded": 0, "by_status": {}}
    if records:
        counts = check(records, tracked, errors, warnings)
        if counts["active"] == 0:
            errors.append(
                "没有任何 active 的 finding——证据判据被筛成空集，拒绝以「空集」充当通过"
            )

    ok = not errors and (not strict or not warnings)
    return {
        "ok": ok,
        "strict": strict,
        "path": _display(findings_path),
        "tracked_files": len(tracked),
        "total": len([r for r in records if not r.get("_error")]),
        "active": counts["active"],
        "superseded": counts["superseded"],
        "by_status": counts["by_status"],
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _print_human(report: dict[str, object]) -> None:
    print(f"经验库质量门禁：{report['path']}")
    print(
        f"  记录 {report['total']} 条（active {report['active']}、superseded {report['superseded']}）；"
        f"本仓库拥有 {report['tracked_files']} 个文件；模式 {'strict' if report['strict'] else 'warning'}"
    )
    if report["by_status"]:
        statuses = "、".join(f"{k} {v}" for k, v in sorted(report["by_status"].items()))
        print(f"  状态分布：{statuses}")
    if report["errors"]:
        print(f"\n错误 {report['error_count']} 条（硬失败）：")
        for error in report["errors"]:
            print(f"  - {error}")
    if report["warnings"]:
        print(f"\n警告 {report['warning_count']} 条（--strict 时升级为失败）：")
        for warning in report["warnings"]:
            print(f"  - 第 {warning['line']} 行 [{warning['kind']}] {warning['title']}")
            print(f"      {warning['detail']}")
    if not report["errors"] and not report["warnings"]:
        print("\n无问题。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="经验库质量门禁：active 证据可达 + superseded 指向技术条目。"
    )
    parser.add_argument("--json", action="store_true", help="只输出 JSON（不追加 RESULT 令牌）")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="把 warning 升级为失败（默认只出 warning）；空集错误始终失败",
    )
    parser.add_argument("--findings", type=Path, default=None, help="findings.jsonl 路径（默认仓库内那份）")
    args = parser.parse_args(argv)

    report = run(findings_path=args.findings, strict=args.strict)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    _print_human(report)
    print(f"RESULT={'OK' if report['ok'] else 'FAIL'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
