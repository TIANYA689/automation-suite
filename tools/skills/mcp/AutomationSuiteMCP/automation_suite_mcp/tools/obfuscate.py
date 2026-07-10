from __future__ import annotations

from pathlib import Path
from typing import Any
import base64, zlib, json, shutil, datetime
from automation_suite_mcp.paths import resolve_path, ensure_child_or_absolute_output
from automation_suite_mcp.config import EXPORTS_DIR
from automation_suite_mcp.utils import read_text_lossy, sha256_file


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def py_obfuscate(path: str, output_path: str = "", mode: str = "light", split_marker: str = "") -> dict[str, Any]:
    src = resolve_path(path, must_exist=True)
    source = read_text_lossy(src)
    header = ""
    body = source
    if mode in {"config-body", "config_body"}:
        if split_marker and split_marker in source:
            idx = source.index(split_marker) + len(split_marker)
            header, body = source[:idx], source[idx:]
        else:
            lines = source.splitlines(True)
            split = 0
            for i, line in enumerate(lines):
                if line.strip() and not line.lstrip().startswith("#") and not line.startswith(("import ", "from ")) and "=" not in line:
                    split = i
                    break
            header, body = "".join(lines[:split]), "".join(lines[split:])
    encoded = base64.b64encode(zlib.compress(body.encode("utf-8"))).decode("ascii")
    loader = """# Protected by automation-suite python-obfuscator-pro\n# Mode: {mode}\n# Original SHA256: {sha}\n{header}\nimport base64 as _b64, zlib as _zlib, sys as _sys\n_payload = \"\"\"{payload}\"\"\"\nif __name__ == \"__main__\":\n    try:\n        exec(_zlib.decompress(_b64.b64decode(_payload)).decode("utf-8"), globals())\n    except Exception as _e:\n        print(f"❌ 执行失败: {{_e}}")\n        _sys.exit(1)\n""".format(mode=mode, sha=sha256_file(src), header=header, payload=encoded)
    out = ensure_child_or_absolute_output(output_path) if output_path else EXPORTS_DIR / "obfuscation" / f"{src.stem}.protected.py"
    out.parent.mkdir(parents=True, exist_ok=True)
    backup = out.with_suffix(out.suffix + f".original-{_timestamp()}.bak")
    shutil.copy2(src, backup)
    out.write_text(loader, encoding="utf-8")
    report = out.with_name(out.stem + "-report.json")
    info = {"source": str(src), "source_sha256": sha256_file(src), "output": str(out), "backup": str(backup), "mode": mode, "output_size": out.stat().st_size}
    report.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    info["report"] = str(report)
    return info


def js_obfuscate(path: str, output_path: str = "", mode: str = "light", keep_header_lines: int = 0) -> dict[str, Any]:
    src = resolve_path(path, must_exist=True)
    source = read_text_lossy(src)
    lines = source.splitlines(True)
    header = "".join(lines[:keep_header_lines]) if keep_header_lines > 0 else ""
    body = "".join(lines[keep_header_lines:]) if keep_header_lines > 0 else source
    payload = base64.b64encode(body.encode("utf-8")).decode("ascii")
    wrapper = f"""// Protected by automation-suite js-script-obfuscator\n// Mode: {mode}\n// Original SHA256: {sha256_file(src)}\n{header}\n(function(){{\n  const _0xpayload = \"{payload}\";\n  const _0xcode = Buffer.from(_0xpayload, 'base64').toString('utf8');\n  return Function(_0xcode)();\n}})();\n"""
    out = ensure_child_or_absolute_output(output_path) if output_path else EXPORTS_DIR / "obfuscation" / f"{src.stem}.obfuscated.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    backup = out.with_suffix(out.suffix + f".original-{_timestamp()}.bak")
    shutil.copy2(src, backup)
    out.write_text(wrapper, encoding="utf-8")
    report = out.with_name(out.stem + "-report.json")
    info = {"source": str(src), "source_sha256": sha256_file(src), "output": str(out), "backup": str(backup), "mode": mode, "keep_header_lines": keep_header_lines, "output_size": out.stat().st_size}
    report.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    info["report"] = str(report)
    return info
