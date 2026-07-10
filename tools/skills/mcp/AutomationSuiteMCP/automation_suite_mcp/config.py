from __future__ import annotations

from pathlib import Path

SERVER_NAME = "automation_suite"
MCP_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = MCP_ROOT.parents[3]
SKILLS_DIR = SUITE_ROOT / "skills"
EXPORTS_DIR = SUITE_ROOT / "exports"
REPORTS_DIR = SUITE_ROOT / "reports"
TMP_DIR = SUITE_ROOT / "tmp"

IGNORED_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "exports", "reports", "tmp", "dist", "build"}
