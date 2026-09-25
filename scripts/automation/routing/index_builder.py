"""路由索引构建器。

扫描 skills/*/SKILL.md 的 frontmatter、合并 routing.source.json 的触发信号，
并扫描 tools/automation-modules 下的模块目录，产出机器可读的 routing.index.json。

设计约束：
- 零第三方依赖，只用标准库，保证离线可跑。
- 输出稳定：内容除 generated_at 外可重复，fingerprint 用于漂移比对。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SKILLS_DIR = "skills"
SOURCE_FILE = "routing.source.json"
INDEX_FILE = "routing.index.json"
MODULES_DIR = Path("tools") / "automation-modules"
SKIP_SKILL_DIRS = {"skills 原始备份"}
MAX_SKILL_BYTES = 256 * 1024


def find_root(start: Path | None = None) -> Path:
    """从起点向上查找项目根（含 AI-USAGE.md 与 skills/ 的目录）。"""
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "AI-USAGE.md").is_file() and (candidate / SKILLS_DIR).is_dir():
            return candidate
    raise FileNotFoundError("未找到项目根（需要同时存在 AI-USAGE.md 与 skills/）")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> dict[str, Any]:
    """解析 SKILL.md 顶部的 YAML frontmatter（仅支持扁平/一层嵌套的简单结构）。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    body: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        body.append(line)

    data: dict[str, Any] = {}
    parent: str | None = None
    block_key: str | None = None
    block_lines: list[str] = []

    def flush_block() -> None:
        nonlocal block_key, block_lines
        if block_key is not None:
            data[block_key] = " ".join(part.strip() for part in block_lines).strip()
        block_key, block_lines = None, []

    for raw in body:
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if block_key is not None and indent > 0:
            block_lines.append(stripped)
            continue
        flush_block()
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", stripped)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if indent > 0 and parent:
            data[f"{parent}.{key}"] = _strip_quotes(value)
            continue
        if not value:
            parent = key
            continue
        if value in {">", "|", ">-", "|-"}:
            block_key = key
            continue
        parent = None
        data[key] = _strip_quotes(value)
    flush_block()
    return data


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_source(root: Path) -> dict[str, Any]:
    source_path = root / SOURCE_FILE
    if not source_path.is_file():
        raise FileNotFoundError(f"缺少路由单一事实源：{SOURCE_FILE}")
    return json.loads(source_path.read_text(encoding="utf-8"))


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def scan_skills(root: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    skills_root = root / SKILLS_DIR
    declared: dict[str, Any] = source.get("skills", {})
    entries: list[dict[str, Any]] = []
    read_errors: list[dict[str, str]] = []

    for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        if skill_dir.name in SKIP_SKILL_DIRS:
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            read_errors.append({"path": str(skill_file.relative_to(root)), "error": "SKILL.md 缺失"})
            continue
        payload = skill_file.read_bytes()
        if len(payload) > MAX_SKILL_BYTES:
            read_errors.append({"path": str(skill_file.relative_to(root)), "error": "文件超过 256 KiB"})
            continue
        text = payload.decode("utf-8", errors="replace")
        meta = parse_frontmatter(text)
        name = meta.get("name") or skill_dir.name
        override = declared.get(name) or declared.get(skill_dir.name) or {}
        entries.append(
            {
                "name": name,
                "dir": skill_dir.name,
                "description": meta.get("description", ""),
                "version": meta.get("version") or meta.get("metadata.version") or "",
                "role": override.get("role", "leaf"),
                "invocation": override.get("invocation", "automatic"),
                "priority": int(override.get("priority", 50)),
                "languages": _as_list(override.get("languages")),
                "signals": _as_list(override.get("signals")),
                "path": str(skill_file.relative_to(root)).replace("\\", "/"),
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
            }
        )

    declared_names = set(declared)
    scanned_names = {entry["name"] for entry in entries}
    missing = sorted(declared_names - scanned_names)
    undeclared = sorted(scanned_names - declared_names)
    return entries, read_errors, missing, undeclared


ENTRY_SUFFIXES = (".py", ".js", ".ts", ".mjs", ".cjs")
NOISE_DIRS = {
    "__pycache__",
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "site-packages",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


def scan_modules(root: Path, source: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    modules_root = root / MODULES_DIR
    if not modules_root.is_dir():
        return [], []
    declared_categories = source.get("module_categories", {})
    modules: list[dict[str, Any]] = []

    for category_dir in sorted(p for p in modules_root.iterdir() if p.is_dir()):
        category = category_dir.name
        for module_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
            entries: list[str] = []
            readme = ""
            requirements = ""
            for file in sorted(module_dir.rglob("*")):
                if not file.is_file():
                    continue
                if NOISE_DIRS & set(file.parts):
                    continue
                rel = str(file.relative_to(root)).replace("\\", "/")
                if file.name.lower().startswith("readme"):
                    readme = readme or rel
                elif file.name == "requirements.txt":
                    requirements = requirements or rel
                elif file.suffix.lower() in ENTRY_SUFFIXES:
                    entries.append(rel)
            modules.append(
                {
                    "category": category,
                    "name": module_dir.name,
                    "path": str(module_dir.relative_to(root)).replace("\\", "/"),
                    "readme": readme,
                    "requirements": requirements,
                    "entries": entries,
                    "signals": _as_list(declared_categories.get(category, {}).get("signals")),
                }
            )

    on_disk = {p.name for p in modules_root.iterdir() if p.is_dir()}
    undeclared_categories = sorted(on_disk - set(declared_categories))
    return modules, undeclared_categories


DEFAULT_EXECUTION = {
    "enabled": True,
    "default_dry_run": True,
    "allowlist": [],
    "timeout_seconds": 120,
    "max_output_chars": 8000,
    "audit_log": "exports/automation/module-audit.jsonl",
}


def build_index(root: Path | None = None) -> dict[str, Any]:
    root = root or find_root()
    source = load_source(root)
    skills, read_errors, missing, undeclared = scan_skills(root, source)
    modules, undeclared_categories = scan_modules(root, source)

    execution = dict(DEFAULT_EXECUTION)
    execution.update(source.get("execution") or {})

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_FILE,
        "source_sha256": sha256_file(root / SOURCE_FILE),
        "skills": skills,
        "modules": modules,
        "module_categories": source.get("module_categories", {}),
        "routing_rules": source.get("routing_rules", []),
        "execution": execution,
        "diagnostics": {
            "read_errors": read_errors,
            "declared_missing_on_disk": missing,
            "on_disk_missing_in_source": undeclared,
            "module_categories_missing_in_source": undeclared_categories,
            "allowlist_unknown_modules": sorted(
                set(execution.get("allowlist") or []) - {m["name"] for m in modules}
            ),
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    payload["fingerprint"] = sha256_bytes(canonical.encode("utf-8"))
    payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return payload


def write_index(root: Path | None = None, output: Path | None = None) -> Path:
    root = root or find_root()
    index = build_index(root)
    target = output or (root / INDEX_FILE)
    target.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return target


def load_index(root: Path | None = None) -> dict[str, Any]:
    """读取磁盘索引；不存在或与 source 不一致时即时重建。"""
    root = root or find_root()
    index_path = root / INDEX_FILE
    if index_path.is_file():
        try:
            cached = json.loads(index_path.read_text(encoding="utf-8"))
            if cached.get("source_sha256") == sha256_file(root / SOURCE_FILE):
                return cached
        except (json.JSONDecodeError, OSError):
            pass
    return build_index(root)


def normalize(text: str) -> str:
    """归一化：NFKC 统一全半角、转小写、压缩空白。"""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "").lower()).strip()


if __name__ == "__main__":
    target = write_index()
    print(f"已写入 {target}")
