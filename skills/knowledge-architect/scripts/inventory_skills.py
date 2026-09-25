#!/usr/bin/env python3
"""Create a deterministic inventory of skill directories without importing them."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

SCALAR_PATTERN = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*?)\s*$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, str) else value
        except json.JSONDecodeError:
            return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def read_frontmatter(text: str) -> tuple[dict[str, str], bool]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, False
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return metadata, True
        match = SCALAR_PATTERN.match(line)
        if match:
            metadata[match.group(1)] = parse_scalar(match.group(2))
    return {}, False


def describe_skill(skill_file: Path, root: Path) -> dict[str, object]:
    text = skill_file.read_text(encoding="utf-8-sig", errors="replace")
    metadata, valid_frontmatter = read_frontmatter(text)
    directory = skill_file.parent
    issues: list[str] = []
    if not valid_frontmatter:
        issues.append("missing_or_unclosed_frontmatter")
    if not metadata.get("name"):
        issues.append("missing_name")
    if not metadata.get("description"):
        issues.append("missing_description")
    line_count = len(text.splitlines())
    if line_count > 500:
        issues.append("skill_over_500_lines")

    return {
        "name": metadata.get("name") or directory.name,
        "description": metadata.get("description", ""),
        "version": metadata.get("version", ""),
        "path": str(directory.resolve()),
        "root": str(root.resolve()),
        "line_count": line_count,
        "size_bytes": skill_file.stat().st_size,
        "sha256": sha256_file(skill_file),
        "resources": {
            "readme": (directory / "README.md").is_file(),
            "scripts": (directory / "scripts").is_dir(),
            "references": (directory / "references").is_dir(),
            "evals": (directory / "evals").is_dir(),
            "assets": (directory / "assets").is_dir(),
        },
        "issues": issues,
    }


def collect_inventory(roots: list[Path]) -> dict[str, object]:
    skills: list[dict[str, object]] = []
    missing_roots: list[str] = []
    seen_files: set[str] = set()

    for root in roots:
        expanded = root.expanduser()
        if not expanded.is_dir():
            missing_roots.append(str(expanded))
            continue
        for skill_file in sorted(expanded.rglob("SKILL.md")):
            if not skill_file.is_file():
                continue
            resolved = os.path.normcase(str(skill_file.resolve()))
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            skills.append(describe_skill(skill_file, expanded))

    name_counts = Counter(str(skill["name"]) for skill in skills)
    duplicate_names = sorted(name for name, count in name_counts.items() if count > 1)
    for skill in skills:
        if skill["name"] in duplicate_names:
            skill["issues"].append("duplicate_name")

    skills.sort(key=lambda item: (str(item["name"]).lower(), str(item["path"]).lower()))
    return {
        "schema_version": 1,
        "roots": [str(root.expanduser()) for root in roots],
        "missing_roots": missing_roots,
        "skill_count": len(skills),
        "duplicate_names": duplicate_names,
        "skills": skills,
    }


def write_atomic(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"output already exists: {path}; use --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        # newline="\n"：Windows 默认会把 \n 翻成 \r\n，让产物在跨平台下不一致。
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan skill roots and emit a non-executing JSON inventory."
    )
    parser.add_argument("roots", nargs="+", type=Path, help="skill root directories")
    parser.add_argument("--output", type=Path, help="write JSON to this file")
    parser.add_argument("--force", action="store_true", help="replace an existing output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        inventory = collect_inventory(args.roots)
        payload = json.dumps(inventory, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            write_atomic(args.output, payload, args.force)
        else:
            sys.stdout.write(payload)
        return 0 if not inventory["missing_roots"] else 1
    except (OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

