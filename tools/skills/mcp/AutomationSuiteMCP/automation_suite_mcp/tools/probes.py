from __future__ import annotations

from pathlib import Path
from typing import Any
import re
from automation_suite_mcp.paths import resolve_path
from automation_suite_mcp.utils import read_text_lossy, sha256_file


def py_decrypt_probe(path: str) -> dict[str, Any]:
    p = resolve_path(path, must_exist=True)
    text = read_text_lossy(p, 300000)
    checks = {
        "base64": bool(re.search(r"base64\.(b64decode|urlsafe_b64decode)|from base64 import", text)),
        "compression": bool(re.search(r"zlib\.decompress|gzip\.decompress|bz2\.decompress|lzma\.decompress", text)),
        "marshal": "marshal.loads" in text or "marshal.load" in text,
        "crypto": bool(re.search(r"Crypto\.Cipher|Fernet|AES|DES|ARC4|RSA", text)),
        "exec_eval": bool(re.search(r"\b(exec|eval)\s*\(", text)),
        "reversed_payload": "[::-1]" in text,
        "large_blob": bool(re.search(r"[A-Za-z0-9+/=]{500,}", text)),
        "config_body": bool(re.search(r"^[A-Z][A-Z0-9_]+\s*=", text, re.M)) and bool(re.search(r"encoded\s*=\s*['\"]{3}", text)),
    }
    patterns = [k for k, v in checks.items() if v]
    if checks["config_body"]:
        recommendation = "Config-Body Separation: 保留头部配置，静态解压业务体"
    elif checks["base64"] and checks["compression"]:
        recommendation = "静态提取 base64 payload 并按压缩链 dump，不直接执行 exec"
    elif checks["marshal"]:
        recommendation = "dump code object，尝试反编译或扫描 co_consts/co_names"
    else:
        recommendation = "未发现强 Python 包装信号，可先做普通源码审计"
    return {"path": str(p), "sha256": sha256_file(p), "size": p.stat().st_size, "patterns": patterns, "checks": checks, "recommendation": recommendation}


def js_deobfuscate_probe(path: str) -> dict[str, Any]:
    p = resolve_path(path, must_exist=True)
    text = read_text_lossy(p, 500000)
    checks = {
        "hex_identifiers": len(re.findall(r"_0x[0-9a-fA-F]{3,}", text)) > 5,
        "string_array_rotation": bool(re.search(r"push\s*\(\s*.*?shift\s*\(", text, re.S)),
        "eval_function": bool(re.search(r"\b(eval|Function)\s*\(", text)),
        "base64_atob": "atob(" in text or "Buffer.from" in text and "base64" in text,
        "control_flow_flattening": bool(re.search(r"split\(['\"]\|['\"]\).*?switch", text, re.S)),
        "self_defending": "(((.+)+)+)$" in text or "toString().search" in text,
        "rc4_hint": "rc4" in text.lower() or "charCodeAt" in text and "% 256" in text,
        "single_line_large": len(text.splitlines()) <= 3 and len(text) > 2000,
    }
    patterns = [k for k, v in checks.items() if v]
    if checks["hex_identifiers"] and checks["string_array_rotation"]:
        recommendation = "优先 Node vm 沙箱导出 decoder，再批量扫描字符串索引"
    elif checks["eval_function"] or checks["base64_atob"]:
        recommendation = "静态提取 eval/Function payload，替换执行为 dump"
    else:
        recommendation = "未发现强 JS 混淆信号，可先 beautify + 普通审计"
    return {"path": str(p), "sha256": sha256_file(p), "size": p.stat().st_size, "patterns": patterns, "checks": checks, "recommendation": recommendation}
