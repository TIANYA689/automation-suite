from __future__ import annotations

from pathlib import Path
from typing import Any
import re
from automation_suite_mcp.config import IGNORED_DIRS
from automation_suite_mcp.paths import resolve_path
from automation_suite_mcp.utils import read_text_lossy, sha256_file

OBFUSCATION_PATTERNS = [r"_0x[0-9a-fA-F]{3,}", r"eval\s*\(", r"Function\s*\(", r"base64\.b64decode", r"zlib\.decompress", r"marshal\.loads", r"atob\s*\("]
VENDOR_PATTERNS = [".min.js", "jquery", "bootstrap", "vendor", "bundle"]


def classify(path: Path, text: str) -> str:
    lower = path.name.lower()
    if any(v in lower for v in VENDOR_PATTERNS):
        return "vendor-static"
    if len(text.splitlines()) <= 3 and len(text) > 2000:
        return "compressed-obfuscated"
    hits = sum(1 for p in OBFUSCATION_PATTERNS if re.search(p, text))
    if hits >= 2:
        return "compressed-obfuscated"
    if path.suffix.lower() in {".py", ".js", ".ts", ".mjs", ".cjs"}:
        return "first-party-readable"
    return "other"


def script_inventory(root: str = ".", max_files: int = 500) -> dict[str, Any]:
    base = resolve_path(root, must_exist=True)
    files = []
    for p in base.rglob("*"):
        if len(files) >= max_files:
            break
        rel_parts = p.relative_to(base).parts
        if any(part in IGNORED_DIRS for part in rel_parts):
            continue
        if p.is_file() and p.suffix.lower() in {".py", ".js", ".ts", ".mjs", ".cjs"}:
            text = read_text_lossy(p, 20000)
            files.append({
                "path": str(p),
                "name": p.name,
                "suffix": p.suffix.lower(),
                "size": p.stat().st_size,
                "sha256": sha256_file(p),
                "line_count": text.count("\n") + 1,
                "class": classify(p, text),
                "signals": [pat for pat in OBFUSCATION_PATTERNS if re.search(pat, text)],
            })
    summary: dict[str, int] = {}
    for f in files:
        summary[f["class"]] = summary.get(f["class"], 0) + 1
    return {"root": str(base), "count": len(files), "summary": summary, "files": files}
