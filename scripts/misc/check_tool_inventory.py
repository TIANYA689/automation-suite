#!/usr/bin/env python3
"""MCP 工具清单校验：文档复述的工具名与数量必须与实现一致。

背景（实测踩过）：`mcp_server.py` 增删工具后，文档里的复述不会自动跟着变。
2026-09-25 发现 `AI-USAGE.md` 写着"5 个只读工具"，逐个点名却漏了 `kb_route`。
当时已有的四类文档校验都不覆盖"工具清单"这一维度：漂移检查只比对技能名，
命令检查只看命令行，交叉引用只看链接可达，索引检查只看文件有没有被点名。
**"数量"和"名单"当时没有任何校验器在看。**

判据（任何一条命中即 drift）：

- `unknown_tool`      —— 文档点名的工具在 mcp_server.py 中不存在（改名或笔误）
- `readonly_count`    —— 文档声明的只读工具数与实现不符
- `total_count`       —— 文档声明的工具总数与实现不符
- `readonly_listing`  —— 声明的只读数与该行实际列出的只读工具名个数不符
                         （典型形态：写"6 个只读工具"，却只列出 5 个名字）
- `undocumented_tool` —— 实现里存在的工具在任何活文档中都没被提到
- `unknown_annotation`—— 工具的装饰器既非 READ_ONLY 也非 EXECUTES，类别无法判定

范围只覆盖"活文档"。`reports/` 是日期快照，记录的是**当时**的工具面，
随代码演进而过时属正常，纳入比对只会制造永久噪音。被排除的范围会全量打印并附理由。

AST 静态解析，不导入 mcp_server，因此**不需要 `mcp` 包**，零第三方依赖。

用法：
    python scripts/misc/check_tool_inventory.py
    python scripts/misc/check_tool_inventory.py --json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER = ROOT / "scripts" / "automation" / "routing" / "mcp_server.py"

# 活文档入口：与 check_index.py 的 _docs() 保持一致的口径。
DOC_ENTRIES = (
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
)

# 不覆盖的范围与理由——全量打印，便于定期复核（豁免项最容易变成漂移藏身处）。
EXCLUDED_PATHS: tuple[tuple[str, str], ...] = (
    ("reports/", "日期快照：记录的是当时的工具面，随代码过时属正常，不参与比对"),
    ("tmp/", "临时工作区，不提交"),
    ("exports/", "运行产物与审计日志，不是交付文档"),
    ("cases/", "案例现场，含 backups/ 下的历史副本"),
    ("skills/skills 原始备份/", "备份目录，不属于套件内正式技能"),
    (".workbuddy-ai/", "代理本地记忆，不进仓库，CI 中不存在"),
)

# 反引号里的标识符才当作工具名候选；`route_task(<需求>)`、`x.py` 这类不会命中。
TOOL_TOKEN = re.compile(r"`([a-z][a-z0-9_]{3,})`")
RE_READONLY = re.compile(r"(\d+)\s*个?\s*只读")
RE_TOTAL_PATTERNS = (
    re.compile(r"(?:工具共|工具总数)\s*(\d+)\s*个"),
    re.compile(r"共\s*(\d+)\s*个工具"),
)
# 只有带这些标记的行才被当作"清单行"，避免把散文里的普通标识符误判为工具名。
# 用正则而非子串：中文散文里的"一个工具"不该被当成数量声明。
RE_INVENTORY = re.compile(r"只读工具|非只读|工具共|工具总数|\d+\s*个工具")


def _load_tools() -> tuple[set[str], set[str], list[str]]:
    """AST 解析 mcp_server.py，返回 (只读工具集, 非只读工具集, 诊断)。"""
    source = MCP_SERVER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MCP_SERVER))

    readonly: set[str] = set()
    executing: set[str] = set()
    diagnostics: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            callee = decorator.func
            callee_name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
            if callee_name != "_tool":
                continue
            kind = ""
            if decorator.args:
                first = decorator.args[0]
                kind = getattr(first, "id", "") or getattr(first, "attr", "")
            if kind == "READ_ONLY":
                readonly.add(node.name)
            elif kind == "EXECUTES":
                executing.add(node.name)
            else:
                diagnostics.append(f"{node.name}: 装饰器类别无法判定（{kind or '未传参'}）")
    return readonly, executing, diagnostics


def _excluded(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    return any(relative.startswith(prefix) for prefix, _ in EXCLUDED_PATHS)


def _docs() -> list[Path]:
    found: list[Path] = []
    for entry in DOC_ENTRIES:
        target = ROOT / entry
        if target.is_file():
            found.append(target)
        elif target.is_dir():
            found.extend(sorted(target.rglob("*.md")))
    return [path for path in found if not _excluded(path)]


def run() -> dict[str, object]:
    readonly, executing, diagnostics = _load_tools()
    all_tools = readonly | executing

    drifts: list[dict[str, object]] = [
        {
            "file": "scripts/automation/routing/mcp_server.py",
            "kind": "unknown_annotation",
            "detail": message,
        }
        for message in diagnostics
    ]

    mentioned: set[str] = set()
    inventory_lines = 0
    docs = _docs()

    for path in docs:
        relative = path.relative_to(ROOT).as_posix()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            tokens = set(TOOL_TOKEN.findall(line))
            mentioned |= tokens & all_tools
            if not RE_INVENTORY.search(line):
                continue
            inventory_lines += 1
            location = f"{relative}:{number}"

            for token in sorted(tokens - all_tools):
                drifts.append(
                    {
                        "file": location,
                        "kind": "unknown_tool",
                        "detail": f"点名的工具 `{token}` 在 mcp_server.py 中不存在",
                    }
                )

            match = RE_READONLY.search(line)
            if match:
                declared = int(match.group(1))
                if declared != len(readonly):
                    drifts.append(
                        {
                            "file": location,
                            "kind": "readonly_count",
                            "detail": f"声明 {declared} 个只读工具，实现里有 {len(readonly)} 个："
                            + " / ".join(sorted(readonly)),
                        }
                    )
                listed = tokens & readonly
                if len(listed) >= 2 and len(listed) != declared:
                    drifts.append(
                        {
                            "file": location,
                            "kind": "readonly_listing",
                            "detail": f"声明 {declared} 个只读工具，该行只列出 {len(listed)} 个："
                            + " / ".join(sorted(listed)),
                        }
                    )

            for pattern in RE_TOTAL_PATTERNS:
                total = pattern.search(line)
                if total is None:
                    continue
                declared_total = int(total.group(1))
                if declared_total != len(all_tools):
                    drifts.append(
                        {
                            "file": location,
                            "kind": "total_count",
                            "detail": f"声明工具总数 {declared_total}，实现里有 {len(all_tools)} 个",
                        }
                    )
                break

    for name in sorted(all_tools - mentioned):
        drifts.append(
            {
                "file": "scripts/automation/routing/mcp_server.py",
                "kind": "undocumented_tool",
                "detail": f"工具 `{name}` 未在任何活文档中被提到，使用者不会知道它存在",
            }
        )

    return {
        "ok": not drifts,
        "readonly_tools": sorted(readonly),
        "executing_tools": sorted(executing),
        "tool_total": len(all_tools),
        "docs_scanned": len(docs),
        "inventory_lines": inventory_lines,
        "drift_count": len(drifts),
        "drifts": drifts,
        "excluded": [
            {"scope": prefix, "why": why}
            for prefix, why in EXCLUDED_PATHS
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验文档里的 MCP 工具清单与实际实现一致。")
    parser.add_argument("--json", action="store_true", help="只输出 JSON（不追加 RESULT 令牌）")
    args = parser.parse_args(argv)

    if not MCP_SERVER.is_file():
        print(json.dumps({"ok": False, "error": f"找不到 {MCP_SERVER}"}, ensure_ascii=False, indent=2))
        if not args.json:
            print("RESULT=UNREADABLE")
        return 2

    try:
        report = run()
    except (SyntaxError, UnicodeDecodeError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2))
        if not args.json:
            print("RESULT=UNREADABLE")
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.json:
        print(f"RESULT={'OK' if report['ok'] else 'DRIFT'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
