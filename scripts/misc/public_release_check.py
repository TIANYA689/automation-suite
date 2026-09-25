from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IGNORE_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__"}
IGNORE_DIRS_PREFIX = {"tmp", "cases", "exports", "reports", "notes"}
# `projects/` 是**部分提交**的目录：只有索引与模板进版本库，作业目录是本地产物
# （含真实抓包、真实域名、可用脚本）。所以不能整个前缀忽略，要按第二段精确判。
PROJECTS_DIR = "projects"
PROJECTS_TRACKED = {"README.md", "_template"}
TEXT_SUFFIXES = {".md", ".py", ".json", ".toml", ".txt", ".yml", ".yaml", ".gitignore"}
REQUIRED_FILES = [
    "LICENSE",
    "README.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    ".github/workflows/ci.yml",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
    ".github/pull_request_template.md",
]

PATH_PATTERNS = [
    ("windows_user_path", re.compile(r"C:\\Users\\[^\\\s]+", re.I)),
    ("hardcoded_d_git", re.compile(r"D:[\\/]Git[\\/]", re.I)),
    ("hardcoded_suite_path", re.compile(r"D:[\\/]aaaaa[\\/]automation-suite", re.I)),
]
SECRET_KEYS = r"api[_-]?key|password|secret|private[_-]?key"
SECRET_ASSIGNMENT_PATTERNS = [
    re.compile(
        rf"(?i)\b(?P<key>{SECRET_KEYS})\b(?:\s*:\s*[^=\n]+)?\s*=\s*(?P<value>\"[^\"\n]*\"|'[^'\n]*')"
    ),
    re.compile(
        rf"(?i)[\"'](?P<key>{SECRET_KEYS})[\"']\s*:\s*(?P<value>\"[^\"\n]*\"|'[^'\n]*')"
    ),
]
BEARER_PATTERN = re.compile(r"(?i)authorization\s*:\s*bearer\s+(?P<value>[^\s`]+)")
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----")
PLACEHOLDER_MARKERS = (
    "xxx",
    "example",
    "sample",
    "placeholder",
    "changeme",
    "replace-me",
    "replace_me",
    "your-",
    "your_",
    "api-密码",
    "占位",
    "示例",
)
PLACEHOLDER_EXACT = {"pwd", "pass", "password", "secret", "token"}


def is_ignored(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = set(rel.parts)
    if parts & IGNORE_PARTS:
        return True
    if rel.parts and rel.parts[0] in IGNORE_DIRS_PREFIX and path.name != ".gitkeep":
        return True
    # projects/ 只保留索引与模板：README.md 与 _template/ 要照常检查，
    # 其余（各作业目录）是本地产物。整个前缀忽略会连模板一起放过。
    if rel.parts and rel.parts[0] == PROJECTS_DIR:
        if len(rel.parts) < 2 or rel.parts[1] not in PROJECTS_TRACKED:
            return True
    return False


def _is_placeholder(raw_value: str) -> bool:
    value = raw_value.strip().strip(",;")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    lowered = value.casefold()
    if not lowered or lowered in {"none", "null", "false", "true"} | PLACEHOLDER_EXACT:
        return True
    if (value.startswith("<") and value.endswith(">")) or value.startswith("${"):
        return True
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return True
    return bool(re.fullmatch(r"[xX*_.-]+", value))


def find_private_config(text: str) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for pattern in SECRET_ASSIGNMENT_PATTERNS:
        for match in pattern.finditer(text):
            if not _is_placeholder(match.group("value")):
                matches.append((match.start(), match.group(0)))
    for match in BEARER_PATTERN.finditer(text):
        if not _is_placeholder(match.group("value")):
            matches.append((match.start(), match.group(0)))
    for match in PRIVATE_KEY_PATTERN.finditer(text):
        matches.append((match.start(), match.group(0)))
    return matches


def main() -> int:
    issues = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            issues.append({"file": rel, "line": 0, "type": "missing_required_file", "snippet": "required for public GitHub release"})

    for p in ROOT.rglob("*"):
        if not p.is_file() or is_ignored(p):
            continue
        rel = p.relative_to(ROOT).as_posix()
        if p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, rx in PATH_PATTERNS:
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                snippet = text[m.start():m.start()+120]
                issues.append({"file": rel, "line": line, "type": name, "snippet": snippet})
        for start, snippet in find_private_config(text):
            line = text.count("\n", 0, start) + 1
            issues.append({"file": rel, "line": line, "type": "private_config", "snippet": snippet})
    result = {"root": "<repo>", "ok": not issues, "issue_count": len(issues), "issues": issues[:200]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
