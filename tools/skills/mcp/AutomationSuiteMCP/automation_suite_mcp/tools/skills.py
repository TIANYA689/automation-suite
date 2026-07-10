from __future__ import annotations

from typing import Any
from pathlib import Path
from automation_suite_mcp.config import SKILLS_DIR
from automation_suite_mcp.utils import read_text_lossy


def list_skills() -> dict[str, Any]:
    items = []
    for p in sorted(SKILLS_DIR.iterdir() if SKILLS_DIR.exists() else []):
        if not p.is_dir():
            continue
        skill_md = p / "SKILL.md"
        if skill_md.exists():
            text = read_text_lossy(skill_md, 4096)
            desc = ""
            for line in text.splitlines():
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip().strip('"')
                    break
            items.append({"name": p.name, "path": str(p), "description": desc})
    return {"skills_dir": str(SKILLS_DIR), "count": len(items), "skills": items}


def read_skill(name: str, max_chars: int = 30000) -> dict[str, Any]:
    safe = name.strip().replace("\\", "/").split("/")[-1]
    path = SKILLS_DIR / safe / "SKILL.md"
    if not path.exists():
        return {"error": "skill not found", "name": name, "available": list_skills()["skills"]}
    text = read_text_lossy(path)
    truncated = len(text) > max_chars
    return {"name": safe, "path": str(path), "content": text[:max_chars], "truncated": truncated, "chars": len(text)}
