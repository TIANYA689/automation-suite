#!/usr/bin/env python3
"""路由 MCP 服务器冒烟检查。

真实走一遍 MCP stdio 协议：initialize -> tools/list -> 各工具调一次。
未安装 mcp 时优雅跳过（退出码 0），便于在无依赖环境跑。

用法：
    python scripts/misc/mcp_smoke_check.py
    python scripts/misc/mcp_smoke_check.py --python <解释器路径>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "scripts" / "automation" / "routing" / "mcp_server.py"
EXPECTED_SERVER_NAME = "automation_suite_router"
EXPECTED_TOOLS = {
    "route_task",
    "load_skill",
    "list_skills",
    "kb_route",
    "list_modules",
    "describe_module",
    "run_module",
}


def _send(proc: subprocess.Popen, message: dict) -> None:
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()


def _read_until(proc: subprocess.Popen, target_id: int) -> dict:
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"服务器提前关闭，未收到 id={target_id} 的响应")
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if payload.get("id") == target_id:
            return payload


def _call(proc: subprocess.Popen, call_id: int, name: str, arguments: dict) -> dict:
    _send(proc, {"jsonrpc": "2.0", "id": call_id, "method": "tools/call",
                 "params": {"name": name, "arguments": arguments}})
    result = _read_until(proc, call_id)["result"]
    return json.loads(result["content"][0]["text"])


def main() -> int:
    parser = argparse.ArgumentParser(description="路由 MCP 服务器冒烟检查")
    parser.add_argument("--python", default=sys.executable, help="运行服务器的解释器（需已安装 mcp）")
    args = parser.parse_args()

    probe = subprocess.run([args.python, "-c", "import mcp"], capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        print(f"跳过：{args.python} 未安装 mcp（pip install -r scripts/automation/routing/requirements.txt）")
        return 0

    proc = subprocess.Popen(
        [args.python, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
    )
    failures: list[str] = []
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "smoke", "version": "1.0"}}})
        init = _read_until(proc, 1)
        server_name = init.get("result", {}).get("serverInfo", {}).get("name")
        print(f"[initialize] serverInfo.name = {server_name}")
        if server_name != EXPECTED_SERVER_NAME:
            failures.append(f"serverInfo.name 不符：{server_name}")

        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = [t["name"] for t in _read_until(proc, 2)["result"]["tools"]]
        print(f"[tools/list] {sorted(tools)}")
        if set(tools) != EXPECTED_TOOLS:
            failures.append(f"工具集不符：{tools}")

        routed = _call(proc, 3, "route_task", {"query": "加密我的 python 脚本再交付"})
        primary = routed["primary"][0]["skill"] if routed["primary"] else "(无)"
        print(f"[route_task] primary = {primary}  evidence = {len(routed['primary'][0]['evidence']) if routed['primary'] else 0} 条")
        if primary != "python-obfuscator-pro":
            failures.append(f"路由结果不符：{primary}")

        _send(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                     "params": {"name": "load_skill", "arguments": {"name": "automation-architect"}}})
        skill_text = _read_until(proc, 4)["result"]["content"][0]["text"]
        print(f"[load_skill] 返回 {len(skill_text)} 字符")
        if "Automation Architect" not in skill_text:
            failures.append("load_skill 正文异常")

        modules = _call(proc, 5, "list_modules", {})
        print(f"[list_modules] {modules['count']} 个模块，分类 {modules['categories']}")
        if modules["count"] == 0:
            failures.append("模块列表为空")

        skills = _call(proc, 6, "list_skills", {})
        print(f"[list_skills] {skills['count']} 个技能")
        if skills["count"] == 0:
            failures.append("技能列表为空")

        kb = _call(proc, 9, "kb_route", {"query": "jsvmp 环境伪装", "verify": True})
        kb_ids = [item["id"] for item in kb.get("matched", [])]
        print(f"[kb_route] {len(kb_ids)} 条命中 -> {kb_ids[:3]}")
        if not kb_ids:
            failures.append("kb_route 未命中任何知识条目")
        missing = [
            record["path"]
            for item in kb.get("matched", [])
            for record in item.get("files_exist", [])
            if not record.get("exists")
        ]
        if missing:
            failures.append(f"kb_route 命中文件不存在：{missing}")
        if kb.get("index_errors"):
            failures.append(f"kb 索引读取失败：{kb['index_errors']}")

        module_name = modules["modules"][0]["name"] if modules["modules"] else ""
        detail = _call(proc, 7, "describe_module", {"name": module_name})
        print(f"[describe_module] {module_name} -> entries={len(detail.get('entries', []))} readme={detail.get('readme_chars', 0)} 字符")
        if detail.get("error") or detail.get("executes_anything") is not False:
            failures.append(f"describe_module 异常：{detail.get('error')}")
        if not detail.get("entries"):
            failures.append("describe_module 未返回入口文件")

        guard = _call(proc, 8, "run_module", {"name": module_name})
        print(f"[run_module] {module_name} -> allowed={guard.get('allowed')} executed={guard.get('executed')} dry_run={guard.get('dry_run')}")
        if guard.get("allowed") is not False:
            failures.append(f"白名单未生效，模块不应被允许执行：{guard}")
        if guard.get("executed"):
            failures.append("默认应拒绝执行，却已执行")
        if "白名单" not in guard.get("reason", ""):
            failures.append(f"拒绝原因未说明白名单：{guard.get('reason')}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if failures:
        print("\n失败项：")
        for item in failures:
            print(" -", item)
        return 1
    print("\n冒烟检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
