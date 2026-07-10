from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
from pathlib import Path


def suite_root() -> Path:
    # scripts/misc/install_codex_mcp.py -> repo root
    return Path(__file__).resolve().parents[2]


def default_codex_config() -> Path:
    return Path.home() / ".codex" / "config.toml"


def patch_config(config: Path, root: Path) -> Path:
    mcp_project = root / "tools" / "skills" / "mcp" / "AutomationSuiteMCP"
    mcp_script = mcp_project / "automation_suite_mcp.py"
    config.parent.mkdir(parents=True, exist_ok=True)
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    backup = config.with_name("config.toml.bak-automation-suite-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup.write_text(text, encoding="utf-8")

    text = re.sub(r"\n\[mcp_servers\.automation_suite\]\n.*?(?=\n\[[^\n]+\]|\Z)", "", text, flags=re.S)
    block = """

[mcp_servers.automation_suite]
command = "uv"
args = ["run", "--project", "{project}", "python", "{script}"]
startup_timeout_sec = 60

[mcp_servers.automation_suite.env]
UV_LINK_MODE = "copy"
""".format(project=mcp_project.as_posix(), script=mcp_script.as_posix())
    insert_at = text.find("\n[projects.")
    text = text[:insert_at] + block + text[insert_at:] if insert_at != -1 else text.rstrip() + block + "\n"

    trust_header = "[projects.'{}']".format(str(root).lower().replace("\\", "\\\\"))
    if trust_header.lower() not in text.lower():
        text = text.rstrip() + "\n\n" + trust_header + "\ntrust_level = \"trusted\"\n"
    config.write_text(text, encoding="utf-8")
    return backup


def smoke(root: Path) -> dict:
    mcp_project = root / "tools" / "skills" / "mcp" / "AutomationSuiteMCP"
    code = (
        "import sys; "
        f"sys.path.insert(0, r'{mcp_project.as_posix()}'); "
        "from automation_suite_mcp.tools.router import automation_route; "
        "print(automation_route('解密 base64 zlib exec python脚本','a.py')['recommended_skill'])"
    )
    cmd = ["uv", "run", "--project", str(mcp_project), "python", "-c", code]
    cp = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
    return {"returncode": cp.returncode, "stdout": cp.stdout.strip(), "stderr": cp.stderr.strip()[-2000:]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Install automation_suite MCP into Codex config.toml")
    ap.add_argument("--config", default=str(default_codex_config()), help="Path to Codex config.toml")
    ap.add_argument("--no-smoke", action="store_true", help="Skip uv smoke check")
    args = ap.parse_args()
    root = suite_root()
    config = Path(args.config).expanduser().resolve()
    backup = patch_config(config, root)
    result = None if args.no_smoke else smoke(root)
    ok = result is None or (result["returncode"] == 0 and result["stdout"].strip() == "python-script-decryptor")
    print(json.dumps({
        "ok": ok,
        "suite_root": str(root),
        "updated": str(config),
        "backup": str(backup),
        "smoke": result,
        "next": "Restart Codex or open a new thread so the MCP tool list reloads."
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
