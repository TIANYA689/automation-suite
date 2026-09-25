"""自动化套件的技能路由包。

- index_builder: 扫描技能/模块，生成单一事实源索引
- router: 确定性打分路由
- kb_index: 知识库文件级路由（技能路由的第二跳）
- mcp_server: 只读路由 MCP 服务器（stdio）
"""

from .index_builder import build_index, find_root, load_index, write_index
from .kb_index import kb_route, load_kb_indexes, route_kb, verify_kb_files
from .router import describe_module, load_skill, route, run_module

__all__ = [
    "build_index",
    "find_root",
    "load_index",
    "write_index",
    "route",
    "load_skill",
    "describe_module",
    "run_module",
    "kb_route",
    "load_kb_indexes",
    "route_kb",
    "verify_kb_files",
]
