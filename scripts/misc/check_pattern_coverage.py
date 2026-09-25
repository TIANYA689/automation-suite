#!/usr/bin/env python3
"""Verify that automation skill coverage gates list every defined Pattern."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SKILL_PATHS = (
    Path("skills/automation-script-dev-py/SKILL.md"),
    Path("skills/automation-script-dev-js/SKILL.md"),
)
PATTERN_HEADING = re.compile(r"^#{3,4}\s+P(\d+(?:\.\d+)?)\b", re.MULTILINE)
PATTERN_REFERENCE = re.compile(r"\bP(\d+(?:\.\d+)?)\b")
START_MARKER = "<!-- pattern-coverage:start -->"
END_MARKER = "<!-- pattern-coverage:end -->"
REQUIRED_STATES = ("apply", "skip", "pending")


def pattern_key(pattern_id: str) -> tuple[int, ...]:
    return tuple(int(part) for part in pattern_id.split("."))


def ordered_unique(values: list[str]) -> list[str]:
    return sorted(set(values), key=pattern_key)


def inspect_skill(root: Path, relative_path: Path) -> dict[str, object]:
    path = root / relative_path
    text = path.read_text(encoding="utf-8")
    defined = ordered_unique(PATTERN_HEADING.findall(text))

    start = text.find(START_MARKER)
    end = text.find(END_MARKER, start + len(START_MARKER)) if start >= 0 else -1
    marker_error = ""
    gate_text = ""
    if start < 0 or end < 0 or end <= start:
        marker_error = "missing or invalid pattern coverage markers"
    else:
        gate_text = text[start + len(START_MARKER) : end]

    covered = ordered_unique(PATTERN_REFERENCE.findall(gate_text))
    missing = [pattern_id for pattern_id in defined if pattern_id not in covered]
    unknown = [pattern_id for pattern_id in covered if pattern_id not in defined]
    missing_states = [state for state in REQUIRED_STATES if state not in gate_text]
    ok = bool(defined) and not marker_error and not missing and not unknown and not missing_states

    return {
        "path": relative_path.as_posix(),
        "ok": ok,
        "defined_count": len(defined),
        "covered_count": len(covered),
        "defined": [f"P{pattern_id}" for pattern_id in defined],
        "covered": [f"P{pattern_id}" for pattern_id in covered],
        "missing": [f"P{pattern_id}" for pattern_id in missing],
        "unknown": [f"P{pattern_id}" for pattern_id in unknown],
        "missing_states": missing_states,
        "marker_error": marker_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument(
        "--skill",
        action="append",
        type=Path,
        dest="skills",
        help="Skill path relative to root; may be repeated",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()

    root = args.root.resolve()
    skill_paths = tuple(args.skills) if args.skills else SKILL_PATHS
    results = [inspect_skill(root, path) for path in skill_paths]
    report = {
        "ok": all(result["ok"] for result in results),
        "skills": results,
        "defined_total": sum(int(result["defined_count"]) for result in results),
        "covered_total": sum(int(result["covered_count"]) for result in results),
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"

    if args.output:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
