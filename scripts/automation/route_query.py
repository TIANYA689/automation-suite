#!/usr/bin/env python3
"""CLI：查询技能路由。

不启动 MCP，直接调用路由引擎，便于人工核对与脚本集成。

用法：
    python scripts/automation/route_query.py "加密我的 python 脚本"
    python scripts/automation/route_query.py "接码注册" --json
    python scripts/automation/route_query.py "随便聊聊" --strict   # 无主选时非零退出
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.routing import load_index, route  # noqa: E402


def _format_evidence(evidence: list[dict]) -> str:
    parts = []
    for hit in evidence:
        sign = "+" if hit["weight"] >= 0 else ""
        label = hit["type"]
        if hit["type"] == "routing_rule":
            parts.append(f"{label}:{hit['value']}({'/'.join(hit.get('matched', []))}){sign}{hit['weight']}")
        else:
            parts.append(f"{label}:{hit['value']}{sign}{hit['weight']}")
    return ", ".join(parts)


def _print_group(title: str, items: list[dict]) -> None:
    if not items:
        return
    for item in items:
        print(f"{title} {item['skill']}  (score={item['score']}, {item['invocation']})")
        if item["evidence"]:
            print(f"       证据: {_format_evidence(item['evidence'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description="查询技能路由")
    parser.add_argument("query", help="用户需求原文")
    parser.add_argument("--top-k", type=int, default=5, help="每组最多返回条数")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--strict", action="store_true", help="无主选时非零退出")
    args = parser.parse_args()

    index = load_index()
    result = route(args.query, index, top_k=args.top_k)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if (args.strict and not result["primary"]) else 0

    print(f"查询: {result['query']}")
    print(f"语言线索: {', '.join(result['detected_languages']) or '(无)'}")
    print()
    if not result["primary"]:
        print("主选: (无匹配) —— 未命中任何技能信号，建议交 automation-architect 澄清需求")
    else:
        _print_group("主选:", result["primary"])
    _print_group("互补:", result["complementary"])
    _print_group("补充:", result["additional"])
    if result["modules"]:
        print()
        for item in result["modules"]:
            print(f"建议模块: {item['category']} -> {', '.join(item['modules']) or '(空)'}")
    print()
    print(f"下一步: {result['next_step'] or '(无)'}")
    print(f"说明: {result['note']}")

    return 1 if (args.strict and not result["primary"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
