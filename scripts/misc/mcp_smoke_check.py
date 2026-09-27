#!/usr/bin/env python3
"""路由 MCP 服务器冒烟检查。

真实走一遍 MCP stdio 协议：initialize -> tools/list -> 各工具调一次。
未安装 mcp 时默认优雅跳过（退出码 0），便于在无依赖环境跑。

但"跳过"与"通过"退出码相同，是一处看不见的失效：CI 装了 mcp 却因故没生效时，
这条门禁会从"真跑"悄悄退回"永远跳过"，而 CI 依然全绿。所以在**必须有 mcp** 的
场合（CI）传 `--require-mcp`，把"缺依赖"从跳过改成失败。

用法：
    python scripts/misc/mcp_smoke_check.py
    python scripts/misc/mcp_smoke_check.py --python <解释器路径>
    python scripts/misc/mcp_smoke_check.py --require-mcp   # CI：缺 mcp 即失败
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
    "workbench_plan",
    "workbench_run",
    "workbench_resume",
    "workbench_status",
    "workbench_list",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="路由 MCP 服务器冒烟检查")
    parser.add_argument("--python", default=sys.executable, help="运行服务器的解释器（需已安装 mcp）")
    parser.add_argument(
        "--require-mcp",
        action="store_true",
        help="缺 mcp 时失败而非跳过。CI 用这个开关，避免"
        "「依赖装失败 → 门禁静默跳过 → CI 仍绿」这条退化路径。",
    )
    args = parser.parse_args(argv)

    probe = subprocess.run([args.python, "-c", "import mcp"], capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        install_hint = "pip install -r scripts/automation/routing/requirements.txt"
        if args.require_mcp:
            print(f"失败：{args.python} 未安装 mcp，但已要求必须运行（{install_hint}）")
            print(probe.stderr.strip())
            return 1
        print(f"跳过：{args.python} 未安装 mcp（{install_hint}）")
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
    server_stderr = ""
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

        workbench = _call(proc, 10, "workbench_run", {"query": "设计自动化工作台路由"})
        print(f"[workbench_run] status={workbench.get('status')} run_id={workbench.get('run_id')}")
        if workbench.get("status") != "DONE" or not workbench.get("run_id"):
            failures.append(f"workbench_run 未完成只读流程：{workbench}")
        run_id = workbench.get("run_id")
        if run_id:
            status = _call(proc, 11, "workbench_status", {"run_id": run_id})
            if status.get("run_id") != run_id:
                failures.append(f"workbench_status run_id 不符：{status}")
            listed = _call(proc, 12, "workbench_list", {"limit": 5})
            if not any(item.get("run_id") == run_id for item in listed.get("runs", [])):
                failures.append("workbench_list 未返回刚创建的运行")
    except (RuntimeError, json.JSONDecodeError, KeyError, IndexError) as exc:
        # 服务器中途死掉时，裸异常是「服务器提前关闭」，看不出为什么——
        # 而这正是这条门禁最需要说清楚的一种失败（SDK 版本不兼容就在这一类）。
        # 收成一条失败项，并连同 stderr 一起打印（见下）。
        failures.append(f"协议交互中断：{type(exc).__name__}: {exc}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        server_stderr = proc.stderr.read() if proc.stderr else ""
        # 关掉管道，否则解释器退出时会报 ResourceWarning（测试里尤其显眼）。
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()

    if failures:
        if server_stderr.strip():
            print("\n服务器 stderr（失败根因通常在这里）：")
            print(server_stderr.strip())
        print("\n失败项：")
        for item in failures:
            print(" -", item)
        return 1
    print("\n冒烟检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
