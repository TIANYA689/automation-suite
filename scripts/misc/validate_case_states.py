#!/usr/bin/env python3
"""长任务案例状态校验。

同时校验两类文件：

- `state.json`      —— 人读的状态摘要（目标、状态、产物、下一步）
- `ai_manifest.json` —— 代理用的恢复点（已完成步骤、证据、已排除路径、下一步）

校验范围包含 `cases/*/` 与 `templates/case/`。模板进版本库，因此必须始终可校验通过；
`cases/` 默认不提交，只在本地校验。

用法：
    python scripts/misc/validate_case_states.py
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES_ROOT = ROOT / "cases"
TEMPLATE_ROOT = ROOT / "templates" / "case"

VALID_STATUSES = {"in_progress", "completed", "blocked"}
VALID_MANIFEST_STATUSES = {"CONTINUE", "DONE", "EXHAUSTED"}
MANIFEST_SCHEMA_VERSION = 1
LIST_FIELDS = ("inputs", "steps_done", "evidence", "dead_ends", "next_actions", "open_questions")


def _load(path: Path) -> tuple[dict | None, list[str]]:
    relative = path.relative_to(ROOT).as_posix()
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{relative}: invalid JSON: {exc}"]


def _check_case_name(state: dict, path: Path, errors: list[str]) -> None:
    relative = path.relative_to(ROOT).as_posix()
    expected_case = path.parent.name
    if state.get("case") != expected_case:
        errors.append(f"{relative}: case must equal directory name {expected_case!r}")


def _check_updated_at(state: dict, path: Path, errors: list[str]) -> None:
    relative = path.relative_to(ROOT).as_posix()
    try:
        date.fromisoformat(state.get("updated_at", ""))
    except (TypeError, ValueError):
        errors.append(f"{relative}: updated_at must use YYYY-MM-DD")


def validate_state(path: Path) -> list[str]:
    errors: list[str] = []
    relative = path.relative_to(ROOT).as_posix()
    state, load_errors = _load(path)
    if state is None:
        return load_errors

    _check_case_name(state, path, errors)
    if not isinstance(state.get("goal"), str) or not state["goal"].strip():
        errors.append(f"{relative}: goal must be a non-empty string")
    if state.get("status") not in VALID_STATUSES:
        errors.append(f"{relative}: status must be one of {sorted(VALID_STATUSES)}")
    if not isinstance(state.get("next_steps"), list) or not all(
        isinstance(item, str) and item.strip() for item in state.get("next_steps", [])
    ):
        errors.append(f"{relative}: next_steps must be a list of non-empty strings")
    if "artifacts" in state and (
        not isinstance(state["artifacts"], list)
        or not all(isinstance(item, str) and item.strip() for item in state["artifacts"])
    ):
        errors.append(f"{relative}: artifacts must be a list of non-empty strings")
    _check_updated_at(state, path, errors)
    return errors


def validate_manifest(path: Path) -> list[str]:
    errors: list[str] = []
    relative = path.relative_to(ROOT).as_posix()
    manifest, load_errors = _load(path)
    if manifest is None:
        return load_errors

    _check_case_name(manifest, path, errors)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append(f"{relative}: schema_version must be {MANIFEST_SCHEMA_VERSION}")
    if not isinstance(manifest.get("goal"), str) or not manifest["goal"].strip():
        errors.append(f"{relative}: goal must be a non-empty string")
    status = manifest.get("status")
    if status not in VALID_MANIFEST_STATUSES:
        errors.append(f"{relative}: status must be one of {sorted(VALID_MANIFEST_STATUSES)}")

    for field in LIST_FIELDS:
        value = manifest.get(field)
        if not isinstance(value, list):
            errors.append(f"{relative}: {field} must be a list")

    # 按状态施加下限约束：三种状态都必须留下可复查的痕迹
    if status == "CONTINUE" and not manifest.get("next_actions"):
        errors.append(f"{relative}: CONTINUE 状态必须有至少一条 next_actions")
    if status == "DONE" and not manifest.get("evidence"):
        errors.append(f"{relative}: DONE 状态必须有至少一条 evidence")
    if status == "EXHAUSTED" and not manifest.get("dead_ends"):
        errors.append(f"{relative}: EXHAUSTED 状态必须记录 dead_ends 及原因")

    for index, item in enumerate(manifest.get("dead_ends") or []):
        if not isinstance(item, dict):
            errors.append(f"{relative}: dead_ends[{index}] must be an object")
            continue
        if not str(item.get("reason", "")).strip():
            errors.append(f"{relative}: dead_ends[{index}] 必须写明排除原因")

    for index, item in enumerate(manifest.get("steps_done") or []):
        if not isinstance(item, dict):
            errors.append(f"{relative}: steps_done[{index}] must be an object")
            continue
        if not str(item.get("step", "")).strip():
            errors.append(f"{relative}: steps_done[{index}] 缺少 step")

    _check_updated_at(manifest, path, errors)
    return errors


def collect() -> tuple[list[Path], list[Path], dict[str, int]]:
    """返回 (state 文件, manifest 文件, 覆盖度)。

    覆盖度把 `cases/` 与 `templates/` **分开报**。`cases/` 被 `.gitignore` 挡住，
    新克隆里它一个文件都没有——那种情况下「通过」只说明模板没问题。
    不分开报，这个差别在退出码上看不见（两种情形都是 exit=0）。
    """
    case_states = sorted(CASES_ROOT.glob("*/state.json"))
    case_manifests = sorted(CASES_ROOT.glob("*/ai_manifest.json"))
    template_states = sorted(TEMPLATE_ROOT.glob("state.json")) if TEMPLATE_ROOT.is_dir() else []
    template_manifests = sorted(TEMPLATE_ROOT.glob("ai_manifest.json")) if TEMPLATE_ROOT.is_dir() else []
    coverage = {
        "case_items": len(case_states) + len(case_manifests),
        "template_items": len(template_states) + len(template_manifests),
    }
    return case_states + template_states, case_manifests + template_manifests, coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验长任务案例状态。")
    parser.add_argument(
        "--expect-cases",
        type=int,
        default=None,
        metavar="N",
        help="cases/ 下的校验项（state.json + ai_manifest.json）数量必须是 N（默认不检查）。"
        "CI 上显式传 0：cases/ 被 .gitignore 挡住，新克隆里只有 templates/case/ 会被校验。"
        "把「空集」写成断言，将来若有人把 cases/ 纳入版本库，CI 会红，"
        "而不是悄悄改变这条门禁的含义。",
    )
    args = parser.parse_args(argv)

    state_files, manifest_files, coverage = collect()

    errors = [error for path in state_files for error in validate_state(path)]
    errors += [error for path in manifest_files for error in validate_manifest(path)]

    if args.expect_cases is not None and coverage["case_items"] != args.expect_cases:
        errors.append(
            f"cases/ 下的校验项（state.json + ai_manifest.json）应为 {args.expect_cases} 个，"
            f"实际 {coverage['case_items']} 个"
            "——若这是有意改动（例如把 cases/ 纳入版本库），请同步更新 CI 的 --expect-cases"
        )

    result = {
        "ok": not errors,
        "state_count": len(state_files),
        "manifest_count": len(manifest_files),
        "coverage": coverage,
        "valid_statuses": sorted(VALID_STATUSES),
        "valid_manifest_statuses": sorted(VALID_MANIFEST_STATUSES),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not coverage["case_items"]:
        print(
            "NOTE: cases/ 下没有可校验项（新克隆的常态，该目录被 .gitignore 挡住）——"
            f"本次只校验了 templates/case/ 的 {coverage['template_items']} 项。"
        )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
