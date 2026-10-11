#!/usr/bin/env python3
"""面向 AI Agent 的自然语言自动化工作台。

工作台把已有的确定性路由器、知识路由和模块护栏串成一个可恢复的运行协议：

* `plan` 只做路由与证据收集，适合 Agent 先消费机器可读计划；
* `run` 自动完成只读发现（技能摘要、知识文件、模块说明）；
* `resume` 从 `exports/automation/workbench/<run_id>/` 继续未完成动作；
* 模块执行必须显式提供 `--execute`，并继续受 routing.source.json 白名单与审计约束。

该文件不调用 shell，也不执行自然语言中出现的任意命令。模块执行统一转交
`automation.routing.router.run_module`。
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    # workbench.py 位于 scripts/automation/，导入顶层 automation 命名空间需要 scripts/。
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.routing import (  # noqa: E402
    build_index,
    describe_module,
    find_root,
    kb_route,
    load_skill,
    route,
    run_module,
)


SCHEMA_VERSION = 1
WORKBENCH_ROOT = Path("exports") / "automation" / "workbench"
MAX_DESCRIBE_WORKERS = 8
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
SLUG_RE = re.compile(r"[^a-z0-9]+")
MAX_QUERY_CHARS = 16_000
MAX_TOP_K = 50


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str) -> str:
    """生成不携带原始需求内容的目录短名，避免路径和敏感信息泄漏。"""
    ascii_text = text.encode("ascii", "ignore").decode("ascii").lower()
    slug = SLUG_RE.sub("-", ascii_text).strip("-")[:40]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"{slug or 'task'}-{digest}"


def _safe_run_id(run_id: str) -> str:
    if not isinstance(run_id, str):
        raise ValueError("run_id 必须是字符串")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id 只能包含小写字母、数字、点、下划线和连字符")
    return run_id


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise ValueError("query 必须是字符串")
    query = query.strip()
    if not query:
        raise ValueError("query 不能为空")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query 超过最大长度 {MAX_QUERY_CHARS}")
    return query


def _validate_top_k(top_k: int) -> int:
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise ValueError("top_k 必须是整数")
    if not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k 必须在 1 到 {MAX_TOP_K} 之间")
    return top_k


def _safe_child(root: Path, relative: Path) -> Path:
    """Return a child path while preventing symlink/path traversal escapes."""
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("工作台产物路径超出项目根目录") from exc
    return candidate


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _action(action_id: str, kind: str, **extra: Any) -> dict[str, Any]:
    return {"id": action_id, "kind": kind, "status": "pending", **extra}


def _module_names(route_result: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for category in route_result.get("modules", []):
        for name in category.get("modules", []):
            if name not in names:
                names.append(name)
    return names


def build_plan(root: Path, query: str, top_k: int = 5) -> dict[str, Any]:
    """执行计划阶段的所有只读步骤，并返回完整的 Agent 消费协议。"""
    query = _validate_query(query)
    top_k = _validate_top_k(top_k)
    root = Path(root).resolve()
    index = build_index(root)
    route_result = route(query, index, top_k=top_k)
    kb_result = kb_route(query, root, top_k=10, verify=True)

    primary = (route_result.get("primary") or [None])[0]
    selected_skill = primary.get("skill") if primary else None
    skill_excerpt = ""
    skill_error = ""
    if selected_skill:
        try:
            skill_excerpt = load_skill(selected_skill, index, root, max_chars=6000)
        except (KeyError, OSError) as exc:
            skill_error = str(exc)

    module_names = _module_names(route_result)
    actions: list[dict[str, Any]] = [
        _action("route", "route_task", status="done"),
        _action("knowledge", "kb_route", status="done"),
        _action(
            "skill",
            "load_skill",
            status="done" if selected_skill and not skill_error else "blocked",
            skill=selected_skill,
            reason=skill_error or ("没有命中主技能" if not selected_skill else ""),
        ),
    ]
    for name in module_names:
        actions.append(_action(f"describe:{name}", "describe_module", module=name))

    status = "READY" if selected_skill and not skill_error else "BLOCKED" if selected_skill else "UNROUTED"
    return {
        "schema_version": SCHEMA_VERSION,
        "workbench": "automation-suite",
        "created_at": utc_now(),
        "root": str(root),
        "query": query,
        "route": route_result,
        "knowledge": kb_result,
        "status": status,
        "selected_skill": selected_skill,
        "skill_excerpt": skill_excerpt,
        "skill_error": skill_error,
        "suggested_modules": module_names,
        "actions": actions,
        "policy": {
            "read_only_discovery": True,
            "module_execution_requires_execute_flag": True,
            "module_execution_delegated_to_router": True,
            "original_files_mutated": False,
        },
    }


class WorkbenchRun:
    """一个运行目录的读写与状态推进器。"""

    def __init__(self, root: Path, run_id: str):
        self.root = Path(root).resolve()
        self.run_id = _safe_run_id(run_id)
        self.directory = _safe_child(self.root, WORKBENCH_ROOT / self.run_id)
        self.plan_path = self.directory / "plan.json"
        self.state_path = self.directory / "state.json"
        self.events_path = self.directory / "events.jsonl"
        self.lock_path = self.directory / ".run.lock"

    @classmethod
    def create(cls, root: Path, query: str, top_k: int = 5) -> "WorkbenchRun":
        root = Path(root).resolve()
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{slugify(query)}-{uuid.uuid4().hex[:6]}"
        instance = cls(root, run_id)
        plan = build_plan(root, query, top_k=top_k)
        plan["run_id"] = run_id
        plan["artifact_paths"] = {
            "plan": str(instance.plan_path.relative_to(root).as_posix()),
            "state": str(instance.state_path.relative_to(root).as_posix()),
            "events": str(instance.events_path.relative_to(root).as_posix()),
        }
        state = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "status": plan["status"],
            "created_at": plan["created_at"],
            "updated_at": utc_now(),
            "completed_actions": [a["id"] for a in plan["actions"] if a["status"] == "done"],
            "blocked_actions": [a["id"] for a in plan["actions"] if a["status"] == "blocked"],
            "failed_actions": [a["id"] for a in plan["actions"] if a["status"] == "failed"],
            "pending_actions": [a["id"] for a in plan["actions"] if a["status"] == "pending"],
            "next_action": next((a["id"] for a in plan["actions"] if a["status"] == "pending"), None),
            "error": None,
        }
        _write_json(instance.plan_path, plan)
        _write_json(instance.state_path, state)
        instance.event("run_created", {"query_sha256": hashlib.sha256(query.encode()).hexdigest()})
        return instance

    @classmethod
    def open(cls, root: Path, run_id: str) -> "WorkbenchRun":
        instance = cls(root, run_id)
        if not instance.plan_path.is_file() or not instance.state_path.is_file():
            raise FileNotFoundError(f"找不到工作台运行：{run_id}")
        return instance

    def read_plan(self) -> dict[str, Any]:
        payload = json.loads(self.plan_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("plan.json schema_version 无效")
        if not isinstance(payload.get("actions"), list):
            raise ValueError("plan.json actions 必须是数组")
        return payload

    def read_state(self) -> dict[str, Any]:
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("state.json schema_version 无效")
        return payload

    def event(self, name: str, data: dict[str, Any] | None = None) -> None:
        _append_jsonl(
            self.events_path,
            {"ts": utc_now(), "run_id": self.run_id, "event": name, "data": data or {}},
        )

    @contextmanager
    def _lock(self):
        """Serialize mutations for one run across threads/processes."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                handle.write(b"0")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def _save(self, plan: dict[str, Any], state: dict[str, Any]) -> None:
        state["updated_at"] = utc_now()
        state["completed_actions"] = [a["id"] for a in plan["actions"] if a["status"] == "done"]
        state["blocked_actions"] = [a["id"] for a in plan["actions"] if a["status"] == "blocked"]
        state["failed_actions"] = [a["id"] for a in plan["actions"] if a["status"] == "failed"]
        state["pending_actions"] = [a["id"] for a in plan["actions"] if a["status"] == "pending"]
        state["next_action"] = next(iter(state["pending_actions"]), None)
        _write_json(self.plan_path, plan)
        _write_json(self.state_path, state)

    def advance(self, execute: bool = False, modules: list[str] | None = None) -> dict[str, Any]:
        with self._lock():
            return self._advance_locked(execute=execute, modules=modules)

    def _advance_locked(self, execute: bool = False, modules: list[str] | None = None) -> dict[str, Any]:
        """推进所有只读动作；只有显式 modules 才会加入模块运行动作。"""
        plan = self.read_plan()
        state = self.read_state()
        index = build_index(self.root)
        selected = set(modules or [])
        if selected:
            known = {m["name"] for m in index.get("modules", [])}
            for name in sorted(selected):
                action_id = f"run:{name}"
                if name not in known:
                    plan["actions"].append(
                        _action(action_id, "run_module", module=name, status="blocked", reason="未知模块")
                    )
                elif not any(a["id"] == action_id for a in plan["actions"]):
                    plan["actions"].append(_action(action_id, "run_module", module=name))

        state["status"] = "RUNNING"
        state["error"] = None
        pending_descriptions = [
            action for action in plan["actions"]
            if action["status"] == "pending" and action["kind"] == "describe_module"
        ]

        def describe(action: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, Exception | None]:
            try:
                return action, describe_module(action["module"], index, self.root, max_chars=4000), None
            except (KeyError, OSError, ValueError) as exc:
                return action, None, exc

        # 描述动作只读且相互独立；集中在主线程落盘，避免 plan/events 并发写竞争。
        if len(pending_descriptions) > 1:
            workers = min(MAX_DESCRIBE_WORKERS, len(pending_descriptions))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="workbench") as pool:
                description_results = [future.result() for future in as_completed(
                    [pool.submit(describe, action) for action in pending_descriptions]
                )]
        else:
            description_results = [describe(action) for action in pending_descriptions]

        for action, detail, error in description_results:
            if error is not None:
                action["status"] = "failed"
                action["reason"] = str(error)
                state["error"] = str(error)
                self.event("action_failed", {"action": action["id"], "error": str(error)})
                continue
            target = _safe_child(self.root, self.directory.relative_to(self.root) / "modules" / f"{slugify(action['module'])}.json")
            _write_json(target, detail or {})
            action["status"] = "done"
            action["result"] = str(target.relative_to(self.root).as_posix())
            self.event("module_described", {"module": action["module"], "path": action["result"]})

        for action in plan["actions"]:
            if action["status"] != "pending":
                continue
            kind = action["kind"]
            try:
                if kind == "run_module":
                    result = run_module(
                        action["module"],
                        index,
                        self.root,
                        dry_run=not execute,
                    )
                    target = _safe_child(self.root, self.directory.relative_to(self.root) / "modules" / f"{slugify(action['module'])}-run.json")
                    _write_json(target, result)
                    if not result.get("allowed"):
                        action["status"] = "blocked"
                    elif not result.get("dry_run", False) and (
                        not result.get("executed") or result.get("exit_code") != 0
                    ):
                        action["status"] = "failed"
                    else:
                        action["status"] = "done"
                    action["result"] = str(target.relative_to(self.root).as_posix())
                    action["reason"] = result.get("reason", "")
                    self.event("module_run", {"module": action["module"], "executed": result.get("executed", False), "allowed": result.get("allowed", False)})
                else:
                    action["status"] = "done"
            except (KeyError, OSError, ValueError) as exc:
                action["status"] = "failed"
                action["reason"] = str(exc)
                state["error"] = str(exc)
                self.event("action_failed", {"action": action["id"], "error": str(exc)})

        pending = [a for a in plan["actions"] if a["status"] == "pending"]
        failed = [a for a in plan["actions"] if a["status"] == "failed"]
        blocked = [a for a in plan["actions"] if a["status"] == "blocked"]
        if failed:
            state["status"] = "FAILED"
        elif pending:
            state["status"] = "RUNNING"
        elif blocked or plan.get("selected_skill") is None:
            state["status"] = "BLOCKED"
        else:
            state["status"] = "DONE"
        self._save(plan, state)
        self.event("run_advanced", {"status": state["status"], "execute": execute})
        return self.summary()

    def summary(self) -> dict[str, Any]:
        state = self.read_state()
        plan = self.read_plan()
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": state["status"],
            "selected_skill": plan.get("selected_skill"),
            "pending_actions": state.get("pending_actions", []),
            "completed_actions": state.get("completed_actions", []),
            "blocked_actions": state.get("blocked_actions", []),
            "failed_actions": state.get("failed_actions", []),
            "artifact_paths": plan.get("artifact_paths", {}),
            "run_directory": str(self.directory),
        }


def _default_root() -> Path:
    return find_root()


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Agent 自然语言自动化工作台")
    parser.add_argument("--root", type=Path, default=None, help="项目根目录，默认自动探测")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan", help="创建只读计划，不推进模块发现")
    plan_parser.add_argument("query")
    plan_parser.add_argument("--top-k", type=int, default=5)

    run_parser = sub.add_parser("run", help="创建并自主推进一轮工作流")
    run_parser.add_argument("query")
    run_parser.add_argument("--top-k", type=int, default=5)
    run_parser.add_argument("--module", action="append", default=[], help="显式加入一个模块运行动作，可重复")
    run_parser.add_argument("--execute", action="store_true", help="允许实际执行已白名单模块；默认仍为 dry-run")

    resume_parser = sub.add_parser("resume", help="恢复一个已有运行")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument("--module", action="append", default=[])
    resume_parser.add_argument("--execute", action="store_true")

    status_parser = sub.add_parser("status", help="读取运行状态")
    status_parser.add_argument("run_id")

    list_parser = sub.add_parser("list", help="列出最近运行")
    list_parser.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)
    root = (args.root or _default_root()).resolve()
    try:
        if args.command == "plan":
            run = WorkbenchRun.create(root, args.query, top_k=max(1, args.top_k))
            _print(run.summary())
        elif args.command == "run":
            run = WorkbenchRun.create(root, args.query, top_k=max(1, args.top_k))
            _print(run.advance(execute=args.execute, modules=args.module))
        elif args.command == "resume":
            run = WorkbenchRun.open(root, args.run_id)
            _print(run.advance(execute=args.execute, modules=args.module))
        elif args.command == "status":
            _print(WorkbenchRun.open(root, args.run_id).summary())
        elif args.command == "list":
            base = root / WORKBENCH_ROOT
            items = []
            for directory in sorted((p for p in base.iterdir() if p.is_dir()), reverse=True) if base.is_dir() else []:
                try:
                    items.append(WorkbenchRun.open(root, directory.name).summary())
                except (FileNotFoundError, ValueError, json.JSONDecodeError):
                    continue
            _print({"runs": items[: max(0, args.limit)]})
        return 0
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
        _print({"error": str(exc), "command": args.command})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
