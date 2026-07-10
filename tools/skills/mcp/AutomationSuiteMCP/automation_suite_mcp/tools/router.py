from __future__ import annotations

from typing import Any

ROUTES = [
    ("python-script-decryptor", ["python", ".py", "解密", "脱壳", "exec", "eval", "base64", "zlib", "marshal", "fernet", "pyc"]),
    ("js-script-deobfuscator", ["javascript", "node", ".js", "解混淆", "还原", "_0x", "obfuscator", "eval", "function(", "rc4"]),
    ("python-obfuscator-pro", ["python", ".py", "保护", "混淆", "加密源码", "config-body", "配置区"]),
    ("js-script-obfuscator", ["javascript", "node", ".js", "保护", "混淆", "javascript-obfuscator", "obfuscator.io"]),
    ("automation-script-dev-js", ["javascript", "node", "axios", "青龙", "surge", "loon", "quanx", "env类", "js脚本"]),
    ("automation-script-dev-py", ["python", "requests", "httpx", "aiohttp", "签到", "养号", "多账号", "青龙", "py脚本"]),
]


def automation_route(request: str, file_name: str = "") -> dict[str, Any]:
    text = f"{request}\n{file_name}".lower()
    scores: list[dict[str, Any]] = []
    for skill, keywords in ROUTES:
        hits = [kw for kw in keywords if kw.lower() in text]
        if hits:
            scores.append({"skill": skill, "score": len(hits), "hits": hits})
    scores.sort(key=lambda x: x["score"], reverse=True)
    if not scores:
        recommended = "automation-architect"
        reason = "无明确语言/方向信号，交给上层架构技能继续澄清和路由"
    else:
        recommended = scores[0]["skill"]
        reason = f"命中信号: {', '.join(scores[0]['hits'])}"
    followups = {
        "automation-script-dev-py": ["read_skill", "script_inventory", "validate_script_delivery"],
        "automation-script-dev-js": ["read_skill", "script_inventory", "validate_script_delivery"],
        "python-obfuscator-pro": ["read_skill", "py_obfuscate"],
        "js-script-obfuscator": ["read_skill", "js_obfuscate"],
        "python-script-decryptor": ["read_skill", "py_decrypt_probe"],
        "js-script-deobfuscator": ["read_skill", "js_deobfuscate_probe"],
        "automation-architect": ["read_skill", "automation_route"],
    }
    return {
        "request": request,
        "file_name": file_name,
        "recommended_skill": recommended,
        "reason": reason,
        "ranked": scores,
        "next_tools": followups.get(recommended, ["read_skill"]),
    }
