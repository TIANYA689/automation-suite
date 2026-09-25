#!/usr/bin/env python3
"""知识库信号路由（CLI）。

把需求文本映射到 `kb/**/techniques/*.md` 的具体文件。

与 `scripts/automation/route_query.py` 的分工：
- route_query 决定"用哪个技能"（skill 级）。
- 本脚本决定"读哪篇知识"（file 级），是技能选定后的第二跳。

打分引擎与 MCP 工具共用 `scripts/automation/routing/kb_index.py`，
因此命令行与 MCP 的结果一致。零第三方依赖，默认只读。

用法：
    python scripts/misc/kb_router.py "jsvmp 环境伪装"
    python scripts/misc/kb_router.py "符号恢复" --json
    python scripts/misc/kb_router.py --list
    python scripts/misc/kb_router.py "混淆" --verify
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from automation.routing import find_root, kb_route  # noqa: E402
from automation.routing.kb_index import TOP_K, load_kb_indexes  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库信号路由（只读）")
    parser.add_argument("query", nargs="?", help="需求文本")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--list", action="store_true", help="列出全部知识条目")
    parser.add_argument("--verify", action="store_true", help="校验命中文件是否存在")
    parser.add_argument("--top-k", type=int, default=TOP_K, help="返回条数")
    args = parser.parse_args()

    root = find_root()

    if args.list:
        entries, errors = load_kb_indexes(root)
        payload = {
            "entries": [
                {"id": e["id"], "priority": e["priority"], "index": e["index"], "files": e["files"]}
                for e in entries
            ],
            "index_errors": errors,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not args.query:
        parser.error("需要提供查询文本，或使用 --list")

    result = kb_route(args.query, root, top_k=args.top_k, verify=args.verify)

    for error in result.get("index_errors", []):
        print(f"[警告] 索引读取失败: {error}", file=sys.stderr)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"查询: {result['query']}")
    print(f"知识条目总数: {result['total_entries']}")
    if not result["matched"]:
        print("未命中任何知识条目。建议先用 route_query.py 确认技能方向，或补充 kb-index.json 的 signals。")
        return 0
    print()
    for rank, item in enumerate(result["matched"], 1):
        print(f"{rank}. [{item['score']}] {item['id']}  (priority={item['priority']})")
        for record in item.get("files_exist", [{"path": p} for p in item["files"]]):
            mark = ""
            if args.verify:
                mark = " ✓" if record.get("exists") else " ✗"
            print(f"     {record['path']}{mark}")
        matched = ", ".join(hit["value"] for hit in item["evidence"] if hit["type"] == "signal")
        if matched:
            print(f"     命中信号: {matched}")
    print()
    print(result["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
