#!/usr/bin/env python3
"""CLI：生成 routing.index.json。

用法：
    python scripts/automation/build_routing_index.py
    python scripts/automation/build_routing_index.py --check   # 只校验不写盘，有差集则非零退出
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.routing import build_index, find_root, write_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="生成路由索引")
    parser.add_argument("--check", action="store_true", help="只校验，不写盘")
    parser.add_argument("--output", default=None, help="索引输出路径（默认项目根 routing.index.json）")
    args = parser.parse_args()

    root = find_root()
    if args.check:
        index = build_index(root)
        diagnostics = index["diagnostics"]
        problems = (
            diagnostics["read_errors"]
            + [{"path": n, "error": "已在 source 声明但磁盘缺失"} for n in diagnostics["declared_missing_on_disk"]]
            + [{"path": n, "error": "磁盘存在但未在 source 声明"} for n in diagnostics["on_disk_missing_in_source"]]
            + [
                {"path": n, "error": "模块分类未在 source 声明"}
                for n in diagnostics["module_categories_missing_in_source"]
            ]
        )
        print(json.dumps({"fingerprint": index["fingerprint"], "problems": problems}, ensure_ascii=False, indent=2))
        return 1 if problems else 0

    target = write_index(root, Path(args.output) if args.output else None)
    print(f"已写入 {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
