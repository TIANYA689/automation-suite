#!/usr/bin/env python3
"""索引完备性校验：每个文件都必须被某个索引点名，且索引不许指向空气。

与 `check_routing_drift.py` 的分工：那个校验"Markdown 路由表与索引是否一致"，
本脚本校验"**索引本身是否漏登**"。漂移检查看不见漏登——一个从未被写进索引的
知识篇目，对漂移检查来说是"不存在的文件"，永远不会被报出来；而它恰恰是知识路由
永远找不到的那一篇。

判据（任何一条命中即 drift）：

- `kb_orphan_file`    —— kb 知识篇目未被同目录 kb-index.json 点名
- `kb_index_missing`  —— 整个 kb 领域目录没有 kb-index.json（该领域的篇目全部不可路由）
- `kb_missing_file`   —— kb-index.json 条目指向不存在的文件
- `kb_empty_entry`    —— 索引条目缺 signals 或 files
- `skill_undeclared`  —— 技能目录存在但未在 routing.source.json 声明
- `skill_missing`     —— routing.source.json 声明了但 SKILL.md 不存在
- `reference_orphan`  —— 技能的 references/*.md 未被该技能 SKILL.md 点名
- `script_orphan`     —— scripts/ 下的脚本未被任何文档点名

零第三方依赖。

用法：
    python scripts/misc/check_index.py
    python scripts/misc/check_index.py --json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

KB_ROOT = ROOT / "kb"
SKILLS_ROOT = ROOT / "skills"
SCRIPTS_ROOT = ROOT / "scripts"
ROUTING_SOURCE = ROOT / "routing.source.json"

# 内部模块与被测试运行器自动发现的用例：不靠"被文档点名"获得存在意义。
SCRIPT_ORPHAN_EXEMPT: tuple[tuple[str, str], ...] = (
    (
        "scripts/automation/routing/",
        "internal_module：路由引擎内部模块，由包导入使用，不是给人敲的命令行入口",
    ),
    (
        "scripts/misc/tests/",
        "test_module：由 run_offline_tests.py 按目录发现，不靠文档点名",
    ),
)

DOC_SUFFIXES = (".md",)


def _docs() -> list[Path]:
    found: list[Path] = []
    for entry in (
        "README.md",
        "AI-USAGE.md",
        "AGENTS.md",
        "SKILLS.md",
        "CONTRIBUTING.md",
        "docs",
        "skills",
        "kb",
        "templates",
        ".github",
    ):
        target = ROOT / entry
        if target.is_file():
            found.append(target)
        elif target.is_dir():
            found.extend(sorted(target.rglob("*.md")))
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _check_kb(drifts: list[dict[str, object]]) -> tuple[int, int]:
    entries_seen = 0
    files_seen = 0
    index_files = sorted(KB_ROOT.rglob("kb-index.json"))
    indexed_dirs = {index_file.parent for index_file in index_files}

    # 整个领域目录缺索引时，下面的 rglob 根本不会遍历到它——于是那些篇目
    # 既不会被报"漏登"，也不会被知识路由找到。这是本脚本最容易瞎掉的一处。
    for directory in sorted(path for path in KB_ROOT.glob("*/techniques") if path.is_dir()):
        if directory in indexed_dirs:
            continue
        for path in sorted(directory.glob("*.md")):
            drifts.append(
                {
                    "file": path.relative_to(ROOT).as_posix(),
                    "kind": "kb_index_missing",
                    "detail": "该领域目录没有 kb-index.json，知识路由永远找不到这一篇",
                }
            )

    for index_file in index_files:
        try:
            payload = json.loads(index_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            drifts.append(
                {
                    "file": index_file.relative_to(ROOT).as_posix(),
                    "kind": "kb_index_unreadable",
                    "detail": str(error),
                }
            )
            continue

        directory = index_file.parent
        listed: set[str] = set()
        for entry in payload.get("entries", []):
            entries_seen += 1
            identifier = entry.get("id", "?")
            files = entry.get("files") or []
            signals = entry.get("signals") or []
            if not files or not signals:
                drifts.append(
                    {
                        "file": index_file.relative_to(ROOT).as_posix(),
                        "kind": "kb_empty_entry",
                        "detail": f"条目 {identifier} 缺 {'files' if not files else 'signals'}",
                    }
                )
            for name in files:
                listed.add(name)
                files_seen += 1
                if not (directory / name).is_file():
                    drifts.append(
                        {
                            "file": index_file.relative_to(ROOT).as_posix(),
                            "kind": "kb_missing_file",
                            "detail": f"条目 {identifier} 指向不存在的 {name}",
                        }
                    )

        for path in sorted(directory.glob("*.md")):
            if path.name not in listed:
                drifts.append(
                    {
                        "file": path.relative_to(ROOT).as_posix(),
                        "kind": "kb_orphan_file",
                        "detail": f"{index_file.relative_to(ROOT).as_posix()} 没有点名它，知识路由永远找不到这一篇",
                    }
                )
    return entries_seen, files_seen


def _check_skills(drifts: list[dict[str, object]]) -> int:
    declared: set[str] = set()
    try:
        payload = json.loads(ROUTING_SOURCE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        drifts.append({"file": "routing.source.json", "kind": "routing_unreadable", "detail": str(error)})
        payload = {}
    declared = set(payload.get("skills", {}))

    on_disk = {
        path.name
        for path in SKILLS_ROOT.iterdir()
        if path.is_dir()
    }

    for name in sorted(on_disk - declared):
        drifts.append(
            {
                "file": f"skills/{name}",
                "kind": "skill_undeclared",
                "detail": "技能目录存在但 routing.source.json 未声明，route_task 永远路由不到它",
            }
        )
    for name in sorted(declared - on_disk):
        drifts.append(
            {
                "file": f"skills/{name}",
                "kind": "skill_missing",
                "detail": "routing.source.json 声明了该技能，但 skills/<name>/ 不存在",
            }
        )

    for name in sorted(on_disk & declared):
        skill_file = SKILLS_ROOT / name / "SKILL.md"
        if not skill_file.is_file():
            drifts.append(
                {
                    "file": f"skills/{name}",
                    "kind": "skill_missing",
                    "detail": "缺少 SKILL.md",
                }
            )
            continue
        body = _read(skill_file)
        references = SKILLS_ROOT / name / "references"
        if not references.is_dir():
            continue
        for path in sorted(references.rglob("*.md")):
            if path.name not in body:
                drifts.append(
                    {
                        "file": path.relative_to(ROOT).as_posix(),
                        "kind": "reference_orphan",
                        "detail": f"未被 skills/{name}/SKILL.md 点名，加载技能时永远不会被读到",
                    }
                )
    return len(declared)


def _check_scripts(drifts: list[dict[str, object]]) -> int:
    corpus = "\n".join(_read(path) for path in _docs())
    checked = 0
    for path in sorted(SCRIPTS_ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if any(relative.startswith(prefix) for prefix, _ in SCRIPT_ORPHAN_EXEMPT):
            continue
        checked += 1
        if path.name not in corpus:
            drifts.append(
                {
                    "file": relative,
                    "kind": "script_orphan",
                    "detail": "没有任何文档点名它，使用者不会知道它存在",
                }
            )
    return checked


def run() -> dict[str, object]:
    drifts: list[dict[str, object]] = []
    entries, kb_files = _check_kb(drifts)
    declared = _check_skills(drifts)
    scripts = _check_scripts(drifts)

    return {
        "ok": not drifts,
        "kb_entries": entries,
        "kb_files": kb_files,
        "declared_skills": declared,
        "scripts_checked": scripts,
        "drift_count": len(drifts),
        "drifts": drifts,
        "exemptions": [
            {
                "reason": prefix,
                "scope": prefix,
                "why": why,
            }
            for prefix, why in SCRIPT_ORPHAN_EXEMPT
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验索引完备性：没有文件被漏登。")
    parser.add_argument("--json", action="store_true", help="只输出 JSON（不追加 RESULT 令牌）")
    args = parser.parse_args(argv)

    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.json:
        print(f"RESULT={'OK' if report['ok'] else 'DRIFT'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
