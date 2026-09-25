#!/usr/bin/env python3
"""路由漂移检查。

比对 routing.index.json（由 routing.source.json + 磁盘扫描生成）与项目内 4 处
Markdown 路由表的技能清单，报告差集，防止路由表再次失同步。

用法：
    python scripts/misc/check_routing_drift.py
    python scripts/misc/check_routing_drift.py --json   # 机器可读输出
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from automation.routing import find_root  # noqa: E402
from automation.routing.index_builder import load_index  # noqa: E402

DOCS = [
    "SKILLS.md",
    "AI-USAGE.md",
    "skills/automation-architect/SKILL.md",
    "kb/automation/techniques/01-routing.md",
]

BACKTICK_RE = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`")
SKILLISH_HINTS = ("architect", "obfuscator", "deobfuscator", "script-dev", "knowledge-", "automation-")


def _is_skillish(token: str) -> bool:
    return len(token) >= 6 and any(hint in token for hint in SKILLISH_HINTS)


def check(root: Path | None = None) -> dict:
    root = root or find_root()
    index = load_index(root)
    known = {s["name"] for s in index["skills"]}
    report: dict = {"root": str(root), "index_fingerprint": index["fingerprint"], "known_skills": sorted(known), "docs": {}}
    drift_found = False

    for rel in DOCS:
        path = root / rel
        entry: dict = {"exists": path.is_file(), "mentioned": [], "missing_in_doc": [], "stale_references": []}
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            tokens = set(BACKTICK_RE.findall(text))
            mentioned = sorted(t for t in tokens if t in known)
            stale = sorted(t for t in tokens if t not in known and _is_skillish(t))
            entry["mentioned"] = mentioned
            entry["missing_in_doc"] = sorted(known - set(mentioned))
            entry["stale_references"] = stale
            if entry["missing_in_doc"] or stale:
                drift_found = True
        else:
            drift_found = True
        report["docs"][rel] = entry

    diagnostics = index.get("diagnostics", {})
    report["index_diagnostics"] = diagnostics
    if any(diagnostics.get(key) for key in ("read_errors", "declared_missing_on_disk", "on_disk_missing_in_source")):
        drift_found = True

    report["drift_found"] = drift_found
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="检查路由表漂移")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    report = check()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"索引指纹: {report['index_fingerprint'][:16]}  已索引技能: {len(report['known_skills'])}")
        for rel, entry in report["docs"].items():
            if not entry["exists"]:
                print(f"[缺失] {rel}")
                continue
            status = "OK" if not entry["missing_in_doc"] and not entry["stale_references"] else "DRIFT"
            print(f"[{status}] {rel}  提及 {len(entry['mentioned'])}/{len(report['known_skills'])}")
            if entry["missing_in_doc"]:
                print(f"        未提及: {', '.join(entry['missing_in_doc'])}")
            if entry["stale_references"]:
                print(f"        疑似失效引用: {', '.join(entry['stale_references'])}")
        diagnostics = report["index_diagnostics"]
        for key, label in (
            ("read_errors", "读取错误"),
            ("declared_missing_on_disk", "source 声明但磁盘缺失"),
            ("on_disk_missing_in_source", "磁盘存在但 source 未声明"),
        ):
            if diagnostics.get(key):
                print(f"[DRIFT] {label}: {diagnostics[key]}")
        print("结论:", "存在漂移" if report["drift_found"] else "无漂移")
    return 1 if report["drift_found"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
