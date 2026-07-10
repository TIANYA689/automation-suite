from __future__ import annotations

from pathlib import Path
from typing import Any
import json
from automation_suite_mcp.paths import resolve_path


def validate_script_delivery(path: str) -> dict[str, Any]:
    p = resolve_path(path, must_exist=True)
    base = p if p.is_dir() else p.parent
    files = {x.name.lower(): x for x in base.iterdir() if x.is_file()}
    main_scripts = [x for x in base.iterdir() if x.suffix.lower() in {".py", ".js", ".mjs", ".cjs"}]
    checks = {
        "has_main_script": bool(main_scripts),
        "has_readme": "readme.md" in files,
        "has_env_example": ".env.example" in files or "env.example" in files,
        "has_package_or_requirements": "package.json" in files or "requirements.txt" in files or "pyproject.toml" in files,
        "single_folder_delivery": p.is_dir() or len(main_scripts) <= 1,
    }
    score = sum(1 for v in checks.values() if v)
    missing = [k for k, v in checks.items() if not v]
    return {"path": str(p), "base": str(base), "score": score, "total": len(checks), "checks": checks, "missing": missing, "main_scripts": [str(x) for x in main_scripts]}
