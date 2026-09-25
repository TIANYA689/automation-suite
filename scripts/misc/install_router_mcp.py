#!/usr/bin/env python3
"""把路由 MCP 注册到 WorkBuddy / Claude Code / Codex。

默认 dry-run：只打印将要写入的配置，不落盘。加 --write 才真正写入。

三个目标各自独立，且都只动自己的那一条 server 配置，不碰其他 MCP：

| 目标 | 配置文件 | 格式 |
|---|---|---|
| workbuddy | `~/.workbuddy-ai/mcp.json` | JSON，合并 `mcpServers` |
| claude | `~/.claude.json` | JSON，合并 `mcpServers` |
| codex | `~/.codex/config.toml` | TOML，替换 `[mcp_servers.<name>]` 段（先备份） |

写 TOML 前会备份，写后用 `tomllib` 复解析校验，解析失败则回滚。

用法：
    python scripts/misc/install_router_mcp.py                       # 打印三个客户端的配置
    python scripts/misc/install_router_mcp.py --write all
    python scripts/misc/install_router_mcp.py --write codex
    python scripts/misc/install_router_mcp.py --python /path/to/python --write all
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_NAME = "automation_suite_router"
LEGACY_NAMES = ("automation-suite-router",)
SERVER_SCRIPT = ROOT / "scripts" / "automation" / "routing" / "mcp_server.py"
STARTUP_TIMEOUT_SEC = 60


def _toml_str(value: str) -> str:
    """TOML 字符串：优先单引号字面量（Windows 路径的反斜杠无需转义），含单引号时回退转义。"""
    if "'" in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "'" + value + "'"


def json_targets() -> dict[str, Path]:
    home = Path.home()
    return {
        "workbuddy": home / ".workbuddy-ai" / "mcp.json",
        "claude": home / ".claude.json",
    }


def toml_target() -> Path:
    return Path.home() / ".codex" / "config.toml"


def pick_python(explicit: str | None) -> str:
    if explicit:
        return explicit
    probe = subprocess.run([sys.executable, "-c", "import mcp"], capture_output=True, check=False)
    return sys.executable if probe.returncode == 0 else ""


def json_entry(python_executable: str, *, with_type: bool) -> dict:
    entry: dict = {}
    if with_type:
        entry["type"] = "stdio"
    entry["command"] = python_executable
    entry["args"] = [SERVER_SCRIPT.as_posix()]
    entry["env"] = {"AUTOMATION_SUITE_ROOT": ROOT.as_posix()}
    if with_type:
        entry["startup_timeout_sec"] = STARTUP_TIMEOUT_SEC
    return entry


def toml_block(python_executable: str) -> str:
    return (
        f"[mcp_servers.{SERVER_NAME}]\n"
        f"command = {_toml_str(python_executable)}\n"
        f"args = [{_toml_str(SERVER_SCRIPT.as_posix())}]\n"
        f"startup_timeout_sec = {STARTUP_TIMEOUT_SEC}\n"
        f"\n"
        f"[mcp_servers.{SERVER_NAME}.env]\n"
        f"AUTOMATION_SUITE_ROOT = {_toml_str(ROOT.as_posix())}\n"
    )


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"配置文件不是合法 JSON，已中止以免破坏：{path}（{exc}）")


def write_json(path: Path, entry: dict) -> None:
    data = load_json(path)
    servers = data.setdefault("mcpServers", {})
    for legacy in LEGACY_NAMES:
        servers.pop(legacy, None)
    servers[SERVER_NAME] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(path.read_text(encoding="utf-8"))


def split_toml_sections(text: str) -> list[tuple[str | None, list[str]]]:
    """按 [header] 行切分为 (header, body_lines)，header=None 表示文件开头。"""
    sections: list[tuple[str | None, list[str]]] = []
    header: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            sections.append((header, body))
            header, body = stripped, []
        else:
            body.append(line)
    sections.append((header, body))
    return sections


def render_toml_sections(sections: list[tuple[str | None, list[str]]]) -> str:
    lines: list[str] = []
    for header, body in sections:
        if header is not None:
            lines.append(header)
        lines.extend(body)
    return "\n".join(lines).rstrip("\n") + "\n"


def upsert_toml(text: str, block: str) -> str:
    prefixes = tuple(
        f"[mcp_servers.{name}{suffix}"
        for name in (SERVER_NAME, *LEGACY_NAMES)
        for suffix in ("]", ".")
    )
    sections = [(h, b) for (h, b) in split_toml_sections(text) if not (h and h.startswith(prefixes))]

    insert_at = len(sections)
    for index, (header, _) in enumerate(sections):
        if header and header.startswith("[mcp_servers"):
            insert_at = index + 1
    sections.insert(insert_at, (None, block.splitlines()))

    rendered = render_toml_sections(sections)
    while "\n\n\n" in rendered:
        rendered = rendered.replace("\n\n\n", "\n\n")
    return rendered


def write_toml(path: Path, block: str) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    backup: Path | None = None
    if original:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.bak-automation-suite-{stamp}")
        shutil.copy2(path, backup)

    updated = upsert_toml(original, block)
    path.write_text(updated, encoding="utf-8")
    try:
        parsed = tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        if backup is not None:
            shutil.copy2(backup, path)
        raise SystemExit(f"TOML 校验失败，已回滚：{path}（{exc}）")
    if SERVER_NAME not in parsed.get("mcp_servers", {}):
        if backup is not None:
            shutil.copy2(backup, path)
        raise SystemExit(f"写入后未找到 mcp_servers.{SERVER_NAME}，已回滚：{path}")
    return backup


def _existing_mcp_names(path: Path, kind: str) -> str:
    if not path.is_file():
        return "无（文件不存在）"
    try:
        if kind == "json":
            return ", ".join(load_json(path).get("mcpServers", {})) or "无"
        return ", ".join(tomllib.loads(path.read_text(encoding="utf-8")).get("mcp_servers", {})) or "无"
    except (SystemExit, tomllib.TOMLDecodeError):
        return "（读取失败）"


def main() -> int:
    parser = argparse.ArgumentParser(description="注册路由 MCP 到 WorkBuddy / Claude Code / Codex")
    parser.add_argument("--write", choices=["workbuddy", "claude", "codex", "all"], help="写入目标；缺省为 dry-run")
    parser.add_argument("--python", help="运行 MCP 服务器的 Python 解释器（需已安装 mcp）")
    args = parser.parse_args()

    python_executable = pick_python(args.python)
    if not python_executable:
        print("未找到已安装 mcp 的解释器。请先执行：")
        print("  pip install -r scripts/automation/routing/requirements.txt")
        print("或用 --python 指定解释器路径。")
        return 1

    json_cfg = json_targets()
    codex_cfg = toml_target()

    if not args.write:
        print(f"服务名: {SERVER_NAME}")
        print(f"解释器: {python_executable}\n")
        for name, path in json_cfg.items():
            entry = json_entry(python_executable, with_type=(name == "claude"))
            print(f"--- {name}: {path}  (JSON)")
            print(json.dumps(entry, ensure_ascii=False, indent=2))
            print(f"    该文件现有 MCP: {_existing_mcp_names(path, 'json')}\n")
        print(f"--- codex: {codex_cfg}  (TOML)")
        print(toml_block(python_executable))
        print(f"    该文件现有 MCP: {_existing_mcp_names(codex_cfg, 'toml')}\n")
        print("确认后执行：python scripts/misc/install_router_mcp.py --write all")
        return 0

    names = list(json_cfg) + ["codex"] if args.write == "all" else [args.write]
    for name in names:
        if name == "codex":
            backup = write_toml(codex_cfg, toml_block(python_executable))
            print(f"已写入 codex: {codex_cfg}" + (f"（备份 {backup.name}）" if backup else ""))
        else:
            write_json(json_cfg[name], json_entry(python_executable, with_type=(name == "claude")))
            print(f"已写入 {name}: {json_cfg[name]}")

    if "workbuddy" in names:
        print(f"\n注意：WorkBuddy 的 MCP 不会自动生效，请到连接器管理页找到 `{SERVER_NAME}` 并点击「信任」。")
    if "codex" in names:
        print("注意：Codex 需重启或新开一个 thread 才会重新加载 MCP 工具列表。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
