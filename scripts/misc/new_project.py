#!/usr/bin/env python3
"""新建一个抓包作业。

从 `projects/_template/` 复制一份到 `projects/<YYYYMMDD>-<slug>/`，
把 `job.json` 的占位值换成本次作业的真实值，然后重建索引表。

**为什么要有这个脚本而不是手抄模板**：手抄会漏字段、会忘记重建索引，
而索引一旦漂移，`check_projects.py` 就会失败——那时候人只会去手改索引表，
于是派生产物变成了第二份事实源。让机器抄，这个口子就堵死了。

零第三方依赖。

用法：
    python scripts/misc/new_project.py avalon-signin --goal "从抓包生成签到脚本"
    python scripts/misc/new_project.py avalon-signin --date 20260925 --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from check_projects import (  # noqa: E402
    PROJECTS_ROOT,
    SLUG_RE,
    STRING_LIST_FIELDS,
    TEMPLATE_DIR_NAME,
    rebuild_index,
)

TEMPLATE_DIR = PROJECTS_ROOT / TEMPLATE_DIR_NAME
PROJECT_PLACEHOLDER = "<日期>-<项目名>"
SLUG_PLACEHOLDER = "<项目名>"
GOAL_PLACEHOLDER = "<一句话：这个作业要拿到什么，不写过程>"
NEXT_STEP_PLACEHOLDER = "<下一步动作；status 为 CONTINUE 时至少一条>"


class NewProjectError(Exception):
    """无法新建作业。"""


def parse_date(raw: str | None) -> str:
    """接受 20260925 或 2026-09-25，统一返回 ISO 形式。"""
    if raw is None:
        return date.today().isoformat()
    text = raw.strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise NewProjectError(f"--date 需要 YYYYMMDD 或 YYYY-MM-DD；当前为 {raw!r}")
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:])).isoformat()
    except ValueError as exc:
        raise NewProjectError(f"--date 不是有效日期：{raw!r}（{exc}）") from exc


def check_slug(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise NewProjectError(
            f"slug 必须匹配 {SLUG_RE.pattern}（小写字母、数字、单连字符）；当前为 {slug!r}"
        )
    return slug


def build_job(slug: str, project: str, iso_date: str, goal: str | None) -> dict:
    """从模板派生一份新的 job.json。

    清空哪几个字段由 `STRING_LIST_FIELDS` 决定——与校验器共用同一份清单，
    新增字段时不会出现"校验器要求、模板里没清"的错位。
    """
    template_path = TEMPLATE_DIR / "job.json"
    try:
        job = json.loads(template_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NewProjectError(f"模板 {template_path} 读不出来：{exc}") from exc

    job["project"] = project
    job["slug"] = slug
    job["created_at"] = iso_date
    job["updated_at"] = iso_date
    job["goal"] = goal.strip() if goal and goal.strip() else GOAL_PLACEHOLDER
    job["status"] = "CONTINUE"

    for field in STRING_LIST_FIELDS:
        job[field] = []
    job["dead_ends"] = []
    # next_actions 也在上面被清空，但 CONTINUE 要求至少一条——补回占位。
    job["next_actions"] = [NEXT_STEP_PLACEHOLDER]

    capture = job.get("capture")
    if not isinstance(capture, dict):
        raise NewProjectError("模板 job.json 的 capture 必须是对象")
    capture["sha256"] = ""
    for field in ("entries", "endpoints", "hosts"):
        capture[field] = 0
    return job


def fill_markdown(path: Path, project: str, slug: str) -> None:
    """把模板里的占位名换成真名。只换名字，不碰正文里的其它占位。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    updated = text.replace(PROJECT_PLACEHOLDER, project).replace(SLUG_PLACEHOLDER, slug)
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def create(slug: str, iso_date: str, goal: str | None, dry_run: bool) -> dict:
    check_slug(slug)
    if not TEMPLATE_DIR.is_dir():
        raise NewProjectError(f"模板目录不存在：{TEMPLATE_DIR}")

    project = f"{iso_date.replace('-', '')}-{slug}"
    target = PROJECTS_ROOT / project
    if target.exists():
        raise NewProjectError(f"{target.relative_to(PROJECTS_ROOT.parent)} 已存在，不覆盖")

    created = [
        path.relative_to(TEMPLATE_DIR).as_posix()
        for path in sorted(TEMPLATE_DIR.rglob("*"))
        if path.is_file()
    ]

    if dry_run:
        return {"project": project, "path": target, "dry_run": True, "would_create": created, "index_rebuilt": False}

    shutil.copytree(TEMPLATE_DIR, target)
    job = build_job(slug, project, iso_date, goal)
    (target / "job.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for path in target.rglob("*.md"):
        fill_markdown(path, project, slug)

    rebuild_index()
    return {"project": project, "path": target, "dry_run": False, "would_create": created, "index_rebuilt": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="新建一个抓包作业目录。")
    parser.add_argument("slug", help="项目名（小写字母、数字、单连字符）")
    parser.add_argument("--date", help="作业日期，YYYYMMDD 或 YYYY-MM-DD，默认今天")
    parser.add_argument("--goal", help="一句话目标，写进 job.json")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要做什么")
    args = parser.parse_args(argv)

    try:
        result = create(args.slug, parse_date(args.date), args.goal, args.dry_run)
    except NewProjectError as exc:
        print(f"[失败] {exc}", file=sys.stderr)
        return 1

    prefix = "将创建" if result["dry_run"] else "已创建"
    print(f"{prefix} {result['project']}/")
    for relative in result["would_create"]:
        print(f"    {relative}")
    if result["index_rebuilt"]:
        print("索引表已重建。")
    else:
        print("（dry-run，未写盘、未重建索引）")
    print()
    print("下一步：照 README.md 的顺序填 抓包 → 目标 → 端点取舍 → 结论 → 待人工完成 → 授权边界")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
