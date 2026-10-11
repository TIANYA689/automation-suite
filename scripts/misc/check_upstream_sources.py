#!/usr/bin/env python3
"""Offline schema and hygiene checks for external source records.

Two questions, both answered without network access:

1. Is `docs/upstream-sources.json` well formed (schema, pinned revisions,
   allowlisted licenses, dates)?
2. Does the ledger (`docs/upstream-absorption.md`) name any repository that the
   manifest forgot to register?

Both run in CI. Remote state (does the repo still exist, was the license
changed) is deliberately **not** checked here — see `docs/upstream-absorption.md`.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "docs" / "upstream-sources.json"
DEFAULT_LEDGER = ROOT / "docs" / "upstream-absorption.md"
ALLOWED_LICENSES = {"LicenseRef-NOASSERTION", "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "GPL-3.0-only", "LGPL-3.0-only"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Only the ledger's "sources of this round" table opens a row with `owner/repo`;
# rows in the per-item tables name sources without an owner and do not match.
LEDGER_REPO_RE = re.compile(r"^\|\s*`([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)`", re.MULTILINE)


def validate(path: Path = DEFAULT_MANIFEST) -> dict[str, object]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "path": _display_path(path), "sources": 0, "errors": [str(exc)]}
    if payload.get("version") != "1.0":
        errors.append("version must be 1.0")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty list")
        sources = []
    seen: set[str] = set()
    for index, item in enumerate(sources):
        prefix = f"sources[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key in ("id", "url", "revision", "spdx_license", "checked_at", "scope"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                errors.append(f"{prefix}.{key} is required")
        identifier = item.get("id")
        if isinstance(identifier, str) and identifier in seen:
            errors.append(f"duplicate id: {identifier}")
        if isinstance(identifier, str):
            seen.add(identifier)
        if isinstance(item.get("url"), str) and not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/.*)?", item["url"]):
            errors.append(f"{prefix}.url must be a GitHub HTTPS URL")
        if item.get("revision") == "REVISION_REQUIRED":
            errors.append(f"{prefix}.revision is still a placeholder")
        if item.get("spdx_license") not in ALLOWED_LICENSES:
            errors.append(f"{prefix}.spdx_license is not allowlisted")
        if not isinstance(item.get("checked_at"), str) or not DATE_RE.fullmatch(item.get("checked_at", "")):
            errors.append(f"{prefix}.checked_at must be YYYY-MM-DD")
    return {"ok": not errors, "path": _display_path(path), "sources": len(sources), "errors": errors}


def check_ledger_coverage(
    ledger: Path = DEFAULT_LEDGER, manifest: Path = DEFAULT_MANIFEST
) -> dict[str, object]:
    """Every repository named by the ledger must be registered in the manifest.

    The ledger answers "what was absorbed / excluded"; the manifest answers
    "which revision and license was reviewed". They are two faces of one source
    list, so a repository added to the ledger and forgotten in the manifest
    **fails silently** — the manifest just gets quietly shorter. That gap is
    what this check closes.

    Repository names are compared case-insensitively: GitHub treats them so.
    """
    errors: list[str] = []
    try:
        text = ledger.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "ok": False,
            "ledger": _display_path(ledger),
            "named": 0,
            "listed": 0,
            "errors": [f"cannot read ledger: {exc}"],
        }

    named = {match.group(1).lower() for match in LEDGER_REPO_RE.finditer(text)}
    if not named:
        # An empty parse means the table shape changed: the check would pass
        # vacuously, which is worse than failing (MEMORY rule 101).
        errors.append(
            f"{_display_path(ledger)}: no `owner/repo` rows parsed, so the coverage check is not running"
        )

    listed: set[str] = set()
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read manifest: {exc}")
        payload = {}
    entries = payload.get("sources") if isinstance(payload, dict) else None
    for item in entries if isinstance(entries, list) else []:
        url = item.get("url") if isinstance(item, dict) else None
        if isinstance(url, str):
            parts = url.rstrip("/").split("/")
            if len(parts) >= 2:
                listed.add(f"{parts[-2]}/{parts[-1]}".lower())

    for name in sorted(named - listed):
        errors.append(f"ledger names a repository missing from the manifest: {name}")

    return {
        "ok": not errors,
        "ledger": _display_path(ledger),
        "named": len(named),
        "listed": len(listed),
        "errors": errors,
    }


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate upstream source manifest without network access.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument(
        "--skip-ledger",
        action="store_true",
        help="run only the manifest schema check (the ledger may not exist yet)",
    )
    args = parser.parse_args(argv)

    report = validate(args.manifest)
    schema_ok = bool(report["ok"])
    coverage = None if args.skip_ledger else check_ledger_coverage(args.ledger, args.manifest)
    ok = schema_ok and (coverage is None or bool(coverage["ok"]))

    report["schema_ok"] = schema_ok
    report["ok"] = ok
    if coverage is not None:
        report["ledger_coverage"] = coverage
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
