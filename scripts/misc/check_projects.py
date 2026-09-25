#!/usr/bin/env python3
"""抓包作业区校验与索引重建。

作业区 `projects/` 的约定：每个作业一个目录 `<YYYYMMDD>-<slug>/`，
目录里的 `job.json` 是**唯一事实源**，`projects/README.md` 的索引表是**派生产物**。

这与路由层同构（`routing.source.json` → `routing.index.json`）：
改作业只改 `job.json`，然后重建索引，不要手改索引表。

校验范围包含 `projects/_template/`：模板进版本库，因此必须始终可校验通过。

判据（任何一条命中即 drift）：

- `schema_version` 不是 1
- `project` 不等于目录名
- `slug` 不合 `[a-z0-9]+(-[a-z0-9]+)*`
- `goal` 为空
- `status` 不是三态之一
- `created_at` / `updated_at` 不是 `YYYY-MM-DD`
- 列表字段不是「非空字符串列表」
- `dead_ends[i]` 缺 `path` 或 `reason`
- `capture` 结构不合法（单份要是个对象、多份要是对象列表；`sha256` 非空时必须是 64 位十六进制）
- 三态下限：`CONTINUE` 要有 `next_actions`、`DONE` 要有 `evidence`、
  `EXHAUSTED` 要有写明原因的 `dead_ends`
- 索引块与作业集合不一致

零第三方依赖。

用法：
    python scripts/misc/check_projects.py
    python scripts/misc/check_projects.py --json
    python scripts/misc/check_projects.py --rebuild-index
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECTS_ROOT = ROOT / "projects"
TEMPLATE_DIR_NAME = "_template"
INDEX_DOC = PROJECTS_ROOT / "README.md"

SCHEMA_VERSION = 1
VALID_STATUSES = {"CONTINUE", "DONE", "EXHAUSTED"}

# 这些字段必须是「非空字符串列表」。新建作业时按同一份清单清空——
# 判据只有一处定义，新增字段不会漏改一边。
STRING_LIST_FIELDS = (
    "artifacts",
    "knowledge_returned",
    "evidence",
    "open_questions",
    "next_actions",
)

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

BEGIN_MARK = "<!-- BEGIN: projects-index -->"
END_MARK = "<!-- END: projects-index -->"
EMPTY_TABLE = "（暂无作业）"
TABLE_HEADER = (
    "| 日期 | 项目 | 目标 | 抓包 | 状态 | 知识回流 |",
    "|---|---|---|---|---|---|",
)


def job_dirs() -> list[Path]:
    """作业目录（按名字倒序，新的在前）。模板目录不算作业。"""
    if not PROJECTS_ROOT.is_dir():
        return []
    found = [
        path
        for path in PROJECTS_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    ]
    return sorted(found, key=lambda path: path.name, reverse=True)


def _load(path: Path) -> tuple[dict | None, list[str]]:
    relative = path.relative_to(ROOT).as_posix()
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{relative}: invalid JSON: {exc}"]


def _check_date(value: object, field: str, relative: str, errors: list[str]) -> None:
    try:
        date.fromisoformat(str(value))
    except (TypeError, ValueError):
        errors.append(f"{relative}: {field} must use YYYY-MM-DD")


def _check_capture(capture: object, relative: str, errors: list[str]) -> None:
    """capture 可以是单个对象，也可以是对象列表。

    为什么允许列表：一次作业常常要同时用好几份抓包。阿瓦隆的「注册 → 登录」链
    就是两份（注册一份、注册+登录+实名一份），而且后者是前者的超集——
    只记一份等于把另一半证据丢掉。索引里按各份求和展示。
    """
    if isinstance(capture, list):
        if not capture:
            errors.append(f"{relative}: capture 是空列表——至少要有一份抓包")
        for index, item in enumerate(capture):
            _check_capture(item, f"{relative}: capture[{index}]", errors)
        return
    if not isinstance(capture, dict):
        errors.append(f"{relative}: capture 必须是对象或对象列表")
        return
    if not str(capture.get("name", "")).strip():
        errors.append(f"{relative}: capture.name must be a non-empty string")
    sha = capture.get("sha256", "")
    if sha and not HEX64_RE.match(str(sha)):
        errors.append(f"{relative}: capture.sha256 非空时必须是 64 位小写十六进制")
    for field in ("entries", "endpoints", "hosts"):
        value = capture.get(field, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"{relative}: capture.{field} must be a non-negative integer")


def validate_job(path: Path) -> list[str]:
    """校验一个 job.json。返回错误清单，空表示通过。"""
    errors: list[str] = []
    relative = path.relative_to(ROOT).as_posix()
    job, load_errors = _load(path)
    if job is None:
        return load_errors

    if job.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"{relative}: schema_version must be {SCHEMA_VERSION}")

    expected_project = path.parent.name
    if job.get("project") != expected_project:
        errors.append(f"{relative}: project 必须等于目录名 {expected_project!r}")

    slug = job.get("slug")
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        errors.append(f"{relative}: slug 必须匹配 {SLUG_RE.pattern}；当前为 {slug!r}")

    if not isinstance(job.get("goal"), str) or not job["goal"].strip():
        errors.append(f"{relative}: goal must be a non-empty string")

    status = job.get("status")
    if status not in VALID_STATUSES:
        errors.append(f"{relative}: status must be one of {sorted(VALID_STATUSES)}")

    _check_date(job.get("created_at"), "created_at", relative, errors)
    _check_date(job.get("updated_at"), "updated_at", relative, errors)
    _check_capture(job.get("capture"), relative, errors)

    for field in STRING_LIST_FIELDS:
        value = job.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            errors.append(f"{relative}: {field} must be a list of non-empty strings")

    dead_ends = job.get("dead_ends")
    if not isinstance(dead_ends, list):
        errors.append(f"{relative}: dead_ends must be a list")
    else:
        for index, item in enumerate(dead_ends):
            if not isinstance(item, dict):
                errors.append(f"{relative}: dead_ends[{index}] must be an object")
                continue
            if not str(item.get("path", "")).strip():
                errors.append(f"{relative}: dead_ends[{index}] 缺 path")
            if not str(item.get("reason", "")).strip():
                errors.append(f"{relative}: dead_ends[{index}] 必须写明排除原因")

    # 三态下限：三种状态都必须留下可复查的痕迹
    if status == "CONTINUE" and not job.get("next_actions"):
        errors.append(f"{relative}: CONTINUE 状态必须有至少一条 next_actions")
    if status == "DONE" and not job.get("evidence"):
        errors.append(f"{relative}: DONE 状态必须有至少一条 evidence")
    if status == "EXHAUSTED" and not dead_ends:
        errors.append(f"{relative}: EXHAUSTED 状态必须记录 dead_ends 及原因")

    return errors


def _capture_summary(capture: object) -> str:
    """索引里的"抓包"列。多份抓包求和展示，并在份数上点名。"""
    if isinstance(capture, list):
        parts = [item for item in capture if isinstance(item, dict)]
        if not parts:
            return "—"
        entries = sum(int(item.get("entries") or 0) for item in parts)
        endpoints = sum(int(item.get("endpoints") or 0) for item in parts)
        if not entries and not endpoints:
            return "—"
        return f"{len(parts)} 份 / {entries} 条 / {endpoints} 端点"
    if not isinstance(capture, dict):
        return "—"
    entries = capture.get("entries", 0)
    endpoints = capture.get("endpoints", 0)
    if not entries and not endpoints:
        return "—"
    return f"{entries} 条 / {endpoints} 端点"


def _escape_cell(text: str) -> str:
    """表格单元格里不能出现裸竖线，否则整行错列。"""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_index() -> str:
    """从各作业的 job.json 渲染索引表。确定性：同一批 job.json 永远得到同一段文本。

    作业名写成反引号目录引用而不是 Markdown 链接：作业目录不在版本库里，
    新克隆中并不存在，写成链接就是假声明。反引号目录引用恰好是诚实的形态，
    也命中 `check_doc_refs.py` 既有的 `directory_ref` 豁免，不必新增笼统豁免。
    """
    rows: list[str] = []
    for directory in job_dirs():
        job_path = directory / "job.json"
        job, _ = _load(job_path)
        if not isinstance(job, dict):
            rows.append(
                f"| — | `{directory.name}` | job.json 读不出来，先修它 | — | — | — |"
            )
            continue
        knowledge = len(job.get("knowledge_returned") or [])
        rows.append(
            "| {date} | `{name}` | {goal} | {capture} | {status} | {knowledge} |".format(
                date=_escape_cell(str(job.get("created_at", "—"))),
                name=directory.name,
                goal=_escape_cell(str(job.get("goal", "—"))),
                capture=_escape_cell(_capture_summary(job.get("capture"))),
                status=_escape_cell(str(job.get("status", "—"))),
                knowledge=f"{knowledge} 项" if knowledge else "**无**",
            )
        )
    if not rows:
        return EMPTY_TABLE
    return "\n".join([*TABLE_HEADER, *rows])


def read_index_block(text: str) -> tuple[str | None, list[str]]:
    """取出 README 里两个标记之间的内容。缺标记或标记乱序都算错误。"""
    errors: list[str] = []
    relative = INDEX_DOC.relative_to(ROOT).as_posix()
    if BEGIN_MARK not in text or END_MARK not in text:
        return None, [f"{relative}: 缺少 {BEGIN_MARK} / {END_MARK} 标记"]
    begin = text.index(BEGIN_MARK) + len(BEGIN_MARK)
    end = text.index(END_MARK)
    if end < begin:
        errors.append(f"{relative}: 索引标记顺序颠倒")
        return None, errors
    return text[begin:end].strip(), errors


def rebuild_index() -> str:
    """把渲染结果写回 README，返回写回的表格文本。"""
    text = INDEX_DOC.read_text(encoding="utf-8")
    current, errors = read_index_block(text)
    if current is None:
        raise ValueError("; ".join(errors))
    table = render_index()
    updated = text.replace(
        f"{BEGIN_MARK}\n{current}\n{END_MARK}",
        f"{BEGIN_MARK}\n{table}\n{END_MARK}",
    )
    INDEX_DOC.write_text(updated, encoding="utf-8")
    return table


def run() -> dict[str, object]:
    errors: list[str] = []

    job_paths = [directory / "job.json" for directory in job_dirs()]
    template_job = PROJECTS_ROOT / TEMPLATE_DIR_NAME / "job.json"
    if template_job.is_file():
        job_paths.append(template_job)

    for path in job_paths:
        errors.extend(validate_job(path))

    if INDEX_DOC.is_file():
        block, block_errors = read_index_block(INDEX_DOC.read_text(encoding="utf-8"))
        errors.extend(block_errors)
        if block is not None and block != render_index():
            errors.append(
                f"{INDEX_DOC.relative_to(ROOT).as_posix()}: 索引表与各作业的 job.json 不一致"
                "——跑 --rebuild-index 重建，不要手改表"
            )
    else:
        errors.append("projects/README.md 不存在")

    return {
        "ok": not errors,
        "job_count": len(job_dirs()),
        "checked_files": [path.relative_to(ROOT).as_posix() for path in job_paths],
        "valid_statuses": sorted(VALID_STATUSES),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验抓包作业区与索引是否一致。")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    parser.add_argument("--rebuild-index", action="store_true", help="从各作业的 job.json 重建索引表")
    args = parser.parse_args(argv)

    if args.rebuild_index:
        table = rebuild_index()
        if args.json:
            print(json.dumps({"ok": True, "table": table}, ensure_ascii=False, indent=2))
        else:
            print("索引表已重建：")
            print(table)
        return 0

    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.json:
        print(f"RESULT={'OK' if report['ok'] else 'DRIFT'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
