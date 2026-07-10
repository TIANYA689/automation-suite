# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2.0,<2"]
# ///
from __future__ import annotations

from typing import Any, Callable
from mcp.server.fastmcp import FastMCP

from automation_suite_mcp.config import SERVER_NAME
from automation_suite_mcp.tools.router import automation_route as _automation_route
from automation_suite_mcp.tools.skills import list_skills as _list_skills, read_skill as _read_skill
from automation_suite_mcp.tools.inventory import script_inventory as _script_inventory
from automation_suite_mcp.tools.probes import py_decrypt_probe as _py_decrypt_probe, js_deobfuscate_probe as _js_deobfuscate_probe
from automation_suite_mcp.tools.obfuscate import py_obfuscate as _py_obfuscate, js_obfuscate as _js_obfuscate
from automation_suite_mcp.tools.validate import validate_script_delivery as _validate_script_delivery

mcp = FastMCP(SERVER_NAME)


def _safe_call(func: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        return {"error": str(exc), "type": type(exc).__name__}


@mcp.tool()
def automation_route(request: str, file_name: str = "") -> dict[str, Any]:
    """根据用户需求和文件名路由到 automation suite 的推荐 skill 与下一步 MCP 工具。"""
    return _safe_call(_automation_route, request, file_name)


@mcp.tool()
def list_skills() -> dict[str, Any]:
    """列出 automation-suite/skills 下可用技能。"""
    return _safe_call(_list_skills)


@mcp.tool()
def read_skill(name: str, max_chars: int = 30000) -> dict[str, Any]:
    """读取 automation-suite 中指定 skill 的 SKILL.md。"""
    return _safe_call(_read_skill, name, max_chars)


@mcp.tool()
def script_inventory(root: str = ".", max_files: int = 500) -> dict[str, Any]:
    """扫描目录中的 py/js/ts 脚本，分类 first-party、vendor、compressed/obfuscated 并返回信号。"""
    return _safe_call(_script_inventory, root, max_files)


@mcp.tool()
def py_decrypt_probe(path: str) -> dict[str, Any]:
    """静态识别 Python 脚本加密/包装/exec/marshal/base64/zlib 等信号，不执行 payload。"""
    return _safe_call(_py_decrypt_probe, path)


@mcp.tool()
def js_deobfuscate_probe(path: str) -> dict[str, Any]:
    """静态识别 JS 混淆信号，如 _0x、字符串数组旋转、eval、控制流扁平化。"""
    return _safe_call(_js_deobfuscate_probe, path)


@mcp.tool()
def py_obfuscate(path: str, output_path: str = "", mode: str = "light", split_marker: str = "") -> dict[str, Any]:
    """生成 Python 保护版脚本；默认标准库 base64+zlib，可选 config-body。原文件会备份。"""
    return _safe_call(_py_obfuscate, path, output_path, mode, split_marker)


@mcp.tool()
def js_obfuscate(path: str, output_path: str = "", mode: str = "light", keep_header_lines: int = 0) -> dict[str, Any]:
    """生成 JS 保护版脚本；默认 base64 loader，可保留顶部配置行。原文件会备份。"""
    return _safe_call(_js_obfuscate, path, output_path, mode, keep_header_lines)


@mcp.tool()
def validate_script_delivery(path: str) -> dict[str, Any]:
    """检查自动化脚本交付目录是否包含主脚本、README、env 示例和依赖说明。"""
    return _safe_call(_validate_script_delivery, path)


if __name__ == "__main__":
    mcp.run()
