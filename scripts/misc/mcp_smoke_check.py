from __future__ import annotations

import json
import os
import py_compile
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = ROOT / "tools" / "skills" / "mcp" / "AutomationSuiteMCP"
sys.path.insert(0, str(MCP_ROOT))

from automation_suite_mcp.tools.router import automation_route
from automation_suite_mcp.tools.skills import list_skills, read_skill
from automation_suite_mcp.tools.inventory import script_inventory
from automation_suite_mcp.tools.probes import py_decrypt_probe, js_deobfuscate_probe
from automation_suite_mcp.tools.obfuscate import py_obfuscate, js_obfuscate
from automation_suite_mcp.tools.validate import validate_script_delivery


def main() -> int:
    report = {"root": "<repo>", "checks": []}
    files = [MCP_ROOT / "automation_suite_mcp.py"] + list((MCP_ROOT / "automation_suite_mcp").rglob("*.py"))
    for f in files:
        py_compile.compile(str(f), doraise=True)
    report["checks"].append({"name": "py_compile", "ok": True, "files": len(files)})

    skills = list_skills()
    assert skills["count"] >= 7
    assert read_skill("automation-architect")["chars"] > 100
    report["checks"].append({"name": "skills", "ok": True, "count": skills["count"]})

    route = automation_route("帮我解密一个 base64 zlib exec 的 Python 脚本", "demo.py")
    assert route["recommended_skill"] == "python-script-decryptor"
    report["checks"].append({"name": "route", "ok": True, "recommended": route["recommended_skill"]})

    sample_dir = ROOT / "scripts" / "_smoke"
    sample_dir.mkdir(parents=True, exist_ok=True)
    py_sample = sample_dir / "demo.py"
    py_sample.write_text('import base64, zlib\nencoded = "eJwrKMrMK9FQSEksSVRIzcnJ11Eozy/KSVGwVUhJLEkEAFXdCnI="\nexec(zlib.decompress(base64.b64decode(encoded)))\n', encoding="utf-8")
    js_sample = sample_dir / "demo.js"
    js_sample.write_text("var _0x1234=['log','hello'];(function(a){a.push(a.shift())})(_0x1234);eval('console.log(1)');\n", encoding="utf-8")

    py_probe = py_decrypt_probe(str(py_sample))
    js_probe = js_deobfuscate_probe(str(js_sample))
    assert "base64" in py_probe["patterns"]
    assert js_probe["patterns"]
    report["checks"].append({"name": "probes", "ok": True, "py": py_probe["patterns"], "js": js_probe["patterns"]})

    py_out = sample_dir / "demo.protected.py"
    js_out = sample_dir / "demo.obfuscated.js"
    py_ob = py_obfuscate(str(py_sample), str(py_out), "light")
    js_ob = js_obfuscate(str(js_sample), str(js_out), "light")
    assert Path(py_ob["output"]).exists()
    assert Path(js_ob["output"]).exists()
    report["checks"].append({"name": "obfuscate", "ok": True, "py_output": str(Path(py_ob["output"]).relative_to(ROOT)), "js_output": str(Path(js_ob["output"]).relative_to(ROOT))})

    inv = script_inventory(str(sample_dir), max_files=50)
    assert inv["count"] >= 2
    val = validate_script_delivery(str(sample_dir))
    report["checks"].append({"name": "inventory_validate", "ok": True, "inventory_count": inv["count"], "delivery_score": val["score"]})

    out_dir = ROOT / "reports" / "misc"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "automation-suite-mcp-smoke-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # Keep the repository clean after smoke tests. Reports are ignored by git; temp scripts are removed.
    shutil.rmtree(sample_dir, ignore_errors=True)
    for cache in (MCP_ROOT / "automation_suite_mcp").rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    cache = MCP_ROOT / "__pycache__"
    shutil.rmtree(cache, ignore_errors=True)
    print(json.dumps({"ok": True, "report": str(out), "checks": len(report["checks"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
