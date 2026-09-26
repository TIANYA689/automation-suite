"""技能路由 MCP 服务器（stdio）。

暴露 7 个工具，其中前 6 个为只读：
- route_task       按查询返回 primary/complementary/additional 候选与证据
- load_skill       按需返回 SKILL.md 正文（渐进式披露，避免一次性占满上下文）
- list_skills      列出技能清单、版本与调用模式
- kb_route         技能路由的第二跳：把需求映射到具体 kb 知识文件
- list_modules     列出 tools/automation-modules 下的模块目录
- describe_module  返回单个模块的 README 摘要、入口文件与依赖
- run_module       执行模块脚本；**唯一非只读工具**，受白名单 + 审计日志 + dry-run 默认三道护栏约束

最终技能选择由 Agent 决定；模块执行默认不落地。

启动：
    python -m automation.routing.mcp_server
或经 entry point：
    python scripts/automation/routing/mcp_server.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from automation.routing import describe_module as _describe_module
    from automation.routing import find_root, load_skill as _load_skill, route as _route
    from automation.routing import kb_route as _kb_route
    from automation.routing import run_module as _run_module
    from automation.routing.index_builder import build_index
else:
    from . import describe_module as _describe_module
    from . import find_root, load_skill as _load_skill, route as _route
    from . import kb_route as _kb_route
    from . import run_module as _run_module
    from .index_builder import build_index

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

try:
    from mcp.types import ToolAnnotations

    READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
    EXECUTES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)
except ImportError:
    READ_ONLY = None
    EXECUTES = None

SERVER_NAME = "automation_suite_router"


def _build_server():
    """构造 SDK 服务器对象，兼容两代 SDK 的构造签名。

    2.x 的 `MCPServer` 接受 `version=`；1.x 的 `FastMCP` **不接受**——传了会
    `TypeError: unexpected keyword argument 'version'`。这里先试带 `version`，
    失败再退回不带。

    两个分支都有实测支撑（`mcp_smoke_check.py --require-mcp`）：
    mcp 2.2.0 走前者，mcp 1.28.1 走后者；两处 serverInfo.name 都是
    `automation_suite_router`。不写这个兜底，`requirements.txt` 里
    `mcp>=1.2.0` 就是在声明一份并不成立的 1.x 兼容。
    """
    try:
        return _Server(SERVER_NAME, version="1.0.0")
    except TypeError:
        return _Server(SERVER_NAME)


mcp = _build_server()

_cache: dict[str, Any] = {"root": None, "index": None, "stamp": None}


def _tool(annotations=None):
    """统一注册工具（兼容有/无 annotations 的 SDK 版本）。"""
    return mcp.tool(annotations=annotations) if annotations is not None else mcp.tool()


def _current_index() -> tuple[Path, dict[str, Any]]:
    """构建索引，并在 source/技能目录未变化时复用缓存（热加载）。"""
    root = Path(os.environ.get("AUTOMATION_SUITE_ROOT") or find_root())
    stamp_parts = []
    source = root / "routing.source.json"
    stamp_parts.append(source.stat().st_mtime_ns if source.is_file() else 0)
    skills_root = root / "skills"
    if skills_root.is_dir():
        for skill_dir in sorted(skills_root.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if skill_file.is_file():
                stamp_parts.append(skill_file.stat().st_mtime_ns)
    stamp = tuple(stamp_parts)

    if _cache["root"] == root and _cache["stamp"] == stamp and _cache["index"] is not None:
        return root, _cache["index"]

    index = build_index(root)
    _cache.update({"root": root, "index": index, "stamp": stamp})
    return root, index


@_tool(READ_ONLY)
def route_task(query: str, top_k: int = 5) -> dict[str, Any]:
    """把一条用户需求路由到相关技能。

    返回三层候选（primary 主选 / complementary 互补 / additional 补充）、命中证据、
    建议的模块分类，以及推荐的下一步。分数用于排序，不是概率。
    """
    _, index = _current_index()
    return _route(query, index, top_k=top_k)


@_tool(READ_ONLY)
def load_skill(name: str, max_chars: int = 24000) -> str:
    """按技能名返回其 SKILL.md 正文。

    仅在确实需要该技能的执行细节时调用，避免把全部技能正文塞进上下文。
    正文超过 max_chars 会截断并附章节目录，便于按需分段读取。
    """
    root, index = _current_index()
    try:
        return _load_skill(name, index, root, max_chars=max_chars)
    except KeyError as exc:
        return f"ERROR: {exc}"


@_tool(READ_ONLY)
def list_skills() -> dict[str, Any]:
    """列出所有已索引技能：名称、版本、角色、调用模式与触发信号数量。"""
    _, index = _current_index()
    return {
        "count": len(index["skills"]),
        "fingerprint": index["fingerprint"],
        "skills": [
            {
                "name": s["name"],
                "version": s["version"],
                "role": s["role"],
                "invocation": s["invocation"],
                "languages": s["languages"],
                "signal_count": len(s["signals"]),
                "path": s["path"],
            }
            for s in index["skills"]
        ],
    }


@_tool(READ_ONLY)
def kb_route(query: str, top_k: int = 10, verify: bool = False) -> dict[str, Any]:
    """技能路由的第二跳：把需求映射到具体知识文件。

    技能路由回答"用哪个技能"，本工具回答"读哪篇知识"。索引来源是各
    `kb/<领域>/techniques/kb-index.json`，与 routing.source.json 是两层关系。
    verify=True 时附带每个候选文件的存在性标记。只读，不执行任何文件。
    """
    root, _ = _current_index()
    return _kb_route(query, root, top_k=top_k, verify=verify)


@_tool(READ_ONLY)
def list_modules(category: str | None = None) -> dict[str, Any]:
    """列出 tools/automation-modules 下的可复用模块；可按分类过滤。

    只读：返回模块路径、入口文件与依赖文件，不执行任何脚本。
    """
    _, index = _current_index()
    modules = index.get("modules", [])
    if category:
        modules = [m for m in modules if m["category"] == category]
    return {
        "count": len(modules),
        "categories": sorted({m["category"] for m in index.get("modules", [])}),
        "modules": modules,
    }


@_tool(READ_ONLY)
def describe_module(name: str, max_chars: int = 4000) -> dict[str, Any]:
    """返回单个模块的详情：README 摘要、入口文件、依赖文件。

    只读：只读文件，不执行任何脚本。
    """
    root, index = _current_index()
    try:
        return _describe_module(name, index, root, max_chars=max_chars)
    except KeyError as exc:
        return {"error": str(exc)}


@_tool(EXECUTES)
def run_module(
    name: str,
    args: list[str] | None = None,
    entry: str | None = None,
    dry_run: bool | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """执行 tools/automation-modules 下的模块脚本（受白名单约束）。

    三道护栏：
    1. 白名单——只有 routing.source.json 的 execution.allowlist 中列出的模块才可能执行，默认白名单为空；
    2. dry-run 默认——不传 dry_run 时只解析命令与工作目录，不真正执行；
    3. 审计日志——每次调用（含被拒绝的）都会追加到 execution.audit_log。

    始终以 argv 列表调用（不经 shell），cwd 固定为模块目录，带超时与输出截断。
    这是本服务器唯一的非只读工具。
    """
    root, index = _current_index()
    return _run_module(
        name,
        index,
        root,
        args=args,
        entry=entry,
        dry_run=dry_run,
        timeout=timeout,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
