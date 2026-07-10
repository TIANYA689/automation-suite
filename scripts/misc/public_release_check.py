from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IGNORE_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__"}
IGNORE_DIRS_PREFIX = {"tmp", "cases", "exports", "reports", "notes"}
TEXT_SUFFIXES = {".md", ".py", ".json", ".toml", ".txt", ".yml", ".yaml", ".gitignore"}
REQUIRED_FILES = [
    "LICENSE",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    ".github/workflows/ci.yml",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
    ".github/pull_request_template.md",
]

PRIVATE_PATTERNS = [
    ("windows_user_path", re.compile(r"C:\\Users\\[^\\\s]+", re.I)),
    ("hardcoded_d_git", re.compile(r"D:[\\/]Git[\\/]", re.I)),
    ("hardcoded_suite_path", re.compile(r"D:[\\/]aaaaa[\\/]automation-suite", re.I)),
    # personal-name patterns should be added by downstream users if needed; no project-specific names here.
    ("private_config", re.compile(r"api[_-]?key\s*=|authorization:\s*bearer|password\s*=|secret\s*=|private[_-]?key", re.I)),
]
ALLOW = [
    "APP_TOKEN", "token 占位符", "API token", "Cookie管理", "userCookie", "knowledge-architect",
    "public_release_check.py", "secret=''", "password =", "YOUR_PROXY_SECRET", "private[_-]?key",
    "private keys", "*.key",
]


def is_ignored(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = set(rel.parts)
    if parts & IGNORE_PARTS:
        return True
    if rel.parts and rel.parts[0] in IGNORE_DIRS_PREFIX and path.name != ".gitkeep":
        return True
    return False


def main() -> int:
    issues = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            issues.append({"file": rel, "line": 0, "type": "missing_required_file", "snippet": "required for public GitHub release"})

    for p in ROOT.rglob("*"):
        if not p.is_file() or is_ignored(p):
            continue
        rel = p.relative_to(ROOT).as_posix()
        if p.suffix.lower() not in TEXT_SUFFIXES and p.name != ".mcp.json":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, rx in PRIVATE_PATTERNS:
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                snippet = text[m.start():m.start()+120]
                if any(a in snippet for a in ALLOW):
                    continue
                # .mcp.json is intentionally relative and portable; no absolute path expected.
                issues.append({"file": rel, "line": line, "type": name, "snippet": snippet})
    result = {"root": "<repo>", "ok": not issues, "issue_count": len(issues), "issues": issues[:200]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
