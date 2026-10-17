#!/usr/bin/env python3
"""经验库质量门禁：`kb/ai-findings/findings.jsonl`。

回答两个问题（都只读、离线、零第三方依赖）：

1. **active 的 finding 有没有证据，证据在不在本仓库里？**
   `evidence.path` 必须点名一个**本仓库拥有**的文件。判据用 `git ls-files`，
   不用工作区遍历——被 gitignore 的本地产物（`projects/`、`exports/`、
   `reports/`、`tmp/`、`.workbuddy-ai/`）在本地存在、在干净克隆里不存在，
   按工作区判会「本地绿、CI 红」（MEMORY 规则 113）。`git ls-files` 就是
   「本仓库拥有」的可执行定义：它和 `actions/checkout` 看到的是同一份文件集。
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
)
# 一个路径 token：以字母/数字/下划线开头，中间可含 `/ . - _` 与 CJK，
# 以「点 + 1~6 位后缀」结尾。`:行号` 与 `::符号` 因不含在字符集里而自然截断。
PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./\-\u4e00-\u9fff]*\.[A-Za-z0-9]{1,6}")
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
    """返回 token 的解析结果：`exact` / `basename` / `unowned`。

    裸文件名（无 `/`）允许按 basename 唯一匹配——与 `check_doc_refs` 的裸名判据
    同形，只是这里按 `git ls-files` 而不是工作区。
    """
    normalised = _normalise(token)
    if normalised in tracked:
        return "exact"
    if "/" not in normalised and normalised in basenames:
        return "basename"
    return "unowned"


def _resolve_evidence(text: str, tracked: set[str], basenames: set[str]) -> tuple[str, list[str]]:
    """返回 (结论, 未拥有的 token 列表)。结论 ∈ {resolved, unowned, none}。"""
    tokens = extract_path_tokens(text)
    if not tokens:
        return "none", []
    unowned = [t for t in tokens if resolve_token(t, tracked, basenames) == "unowned"]
    if len(unowned) == len(tokens):
        return "unowned", unowned
    return "resolved", unowned


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
            verdict, unowned = _resolve_evidence(str(path_text), tracked, basenames)
            if verdict == "none":
                warnings.append(
                    {
                        "line": record.get("_line"),
                        "title": record.get("title", ""),
                        "status": status,
                        "kind": "missing_evidence",
                        "detail": "active 的 finding 没有可解析的 evidence 路径（README 约定：没有证据只能给 low 置信度）",
                    }
                )
            elif verdict == "unowned":
                warnings.append(
                    {
                        "line": record.get("_line"),
                        "title": record.get("title", ""),
                        "status": status,
                        "kind": "evidence_not_owned",
                        "detail": "evidence 路径不在本仓库拥有（gitignore 或已删除）：" + "、".join(unowned),
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
                and resolve_token(token, tracked, basenames) != "unowned"
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
