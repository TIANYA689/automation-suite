#!/usr/bin/env python3
"""拆解报告的**呈现层**：把结构化报告渲染成人读文本。

为什么单独一层：这个工具里有三个各自独立的变更轴——

| 层 | 装什么 | 什么时候改 |
|---|---|---|
| `teardown_rules.py` | 检测什么维度、什么风险 | 加维度 |
| `text_spans.py` | 文本怎么切成"代码 / 叙述" | 加语言、改注释语法解析 |
| `script_teardown.py` | 扫描、分类、检测、CLI | 加分析能力 |
| **本文件** | **报告长什么样** | 改排版 |

混在一起时，每次调排版都要动一个千行文件。拆开的判据是变更频率，不是行数。

本文件是被 `script_teardown.py` 导入的内部模块，不是命令行入口。
零第三方依赖。
"""

from __future__ import annotations

import unicodedata
from typing import Any

from teardown_rules import CLASSIFICATION_LABELS, TIERS, TIER_LABELS

__all__ = ["supports_box", "display_width", "pad", "clip", "clip_where", "render"]


def supports_box(encoding: str | None) -> bool:
    """控制台编码能不能画出制表符。画不出就退回 ASCII，而不是抛异常。

    一个因终端编码崩掉的工具，会让人以为它本身有问题。
    """
    if not encoding:
        return False
    try:
        "═─╭╰│├└".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def display_width(text: str) -> int:
    """按**终端显示列**算宽度：CJK 与全角符号占 2 列。

    不能用 `len()`：`f"{'配置集中':<10}"` 补的是**字符数**，而 4 个汉字占 8 列，
    于是它和 6 个汉字的标签在屏幕上差 4 列，整张表看起来是歪的——
    而"看起来是歪的"正是本工具的输出最容易被判定为"不可信"的方式。
    """
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, width: int, align: str = "left") -> str:
    """按显示宽度补齐（超出则原样返回，**不截断**）。"""
    gap = max(width - display_width(text), 0)
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def clip(text: str, width: int) -> str:
    """按**显示宽度**截断并加省略号。

    为什么必须有这一层：`pad()` 明确不截断（超出原样返回），所以过长的名字会顶穿列宽。
    实测 2128 行的中文名脚本 `雨云每日签到+自动提现（自动过验证.py` 显示宽度 36，
    在 34 列里把整张表挤歪，行号跟文件名黏在一起——**表格歪掉就等于不可读**。

    按显示宽度而不是字符数：中文名 20 个字符占 36 列，`name[:29]` 几乎等于没截。
    """
    if display_width(text) <= width:
        return text
    budget = max(width - 1, 0)
    kept: list[str] = []
    used = 0
    for character in text:
        step = display_width(character)
        if used + step > budget:
            break
        kept.append(character)
        used += step
    return "".join(kept) + "…"


def clip_where(where: str, width: int) -> str:
    """截断 `文件:行号`，**行号必须留住**。

    行号是本工具唯一能被逐条复核的证据，截掉它这条命中就没法核了。
    所以从文件名那一头截，`:行号` 整体保留。
    """
    name, sep, line = where.rpartition(":")
    if not sep or not line.isdigit():
        return clip(where, width)
    tail = sep + line
    room = width - display_width(tail)
    if room < 4:
        return clip(where, width)
    return clip(name, room) + tail


def _rule(width: int, heavy: bool, box: bool) -> str:
    if not box:
        return ("=" if heavy else "-") * width
    return ("═" if heavy else "─") * width


def _section(title: str, width: int, box: bool) -> str:
    """`── 标题 ──────`：破折号补到整宽，节与节之间的视觉重量才一致。"""
    dash = "─" if box else "-"
    head = f"{dash}{dash} {title} "
    return head + dash * max(width - display_width(head), 0)


def render(report: dict[str, Any], *, box: bool = True, top: int = 12) -> str:
    """把报告渲染成人读文本。

    设计取舍：**先给结论，再给证据**。用户是"扫"不是"读"，所以
    表格按显示宽度对齐、每节一条横线、缺口与风险单独成节——
    而不是把 JSON 直接吐出来。

    对齐一律走 `pad()` 而不是 f-string 的 `:<n`：后者按字符数补，
    中文标签会整列歪掉（见 `display_width` 的说明）。
    """
    width = 66
    out: list[str] = []
    counts = report["counts"]
    heavy = _rule(width, True, box)
    if box:
        out.append("╭" + heavy + "╮")
        out.append("│" + pad(" 第三方脚本静态拆解", width) + "│")
        out.append("╰" + heavy + "╯")
    else:
        out.append("+" + heavy + "+")
        out.append("|" + pad(" 第三方脚本静态拆解", width) + "|")
        out.append("+" + heavy + "+")
    out.append(f"目标   : {', '.join(report['targets'])}")
    out.append(
        f"扫描   : {counts['files']} 个脚本  "
        f"可读 {counts['readable']} / 压缩 {counts['minified']} / "
        f"混淆 {counts['obfuscated']} / 静态库 {counts['vendor']} / 读不出 {counts['unreadable']}"
    )
    out.append("口径   : 只读解析（ast + 正则），未导入、未执行、未联网")
    out.append("")

    out.append(_section("1. 结构清单", width, box))
    out.append(f"  {pad('#', 3, 'right')}  {pad('文件', 34)}{pad('类型', 8)}{pad('行数', 6, 'right')}")
    for index, item in enumerate(report["files"][:top], 1):
        out.append(
            f"  {pad(str(index), 3, 'right')}  {pad(clip(item['name'], 33), 34)}"
            f"{pad(CLASSIFICATION_LABELS[item['kind']], 8)}{pad(str(item['lines']), 6, 'right')}"
        )
    if len(report["files"]) > top:
        out.append(f"  … 其余 {len(report['files']) - top} 个文件见 --json（--top 可调）")
    unparsed = [item["name"] for item in report["files"] if item.get("parse_ok") is False]
    if unparsed:
        # 「读得出」与「解析得了」是两件事，必须分开说。语法解析失败时符号表为空、
        # 文档字符串也没参与去散文过滤——报告不写出来，读者会把"没有结构"
        # 当成"这个脚本就是没结构"。这正是本工具最容易犯的那类错。
        out.append(
            f"  ⚠ {len(unparsed)} 个 Python 文件**语法解析失败**（符号表为空、"
            "文档字符串未过滤）：能力矩阵偏多、结构清单不全，按「材料不全」对待"
        )
        for name in unparsed[:3]:
            out.append(f"    · {clip(name, 58)}")
    out.append("")

    out.append(_section("2. 能力矩阵", width, box))
    if not report["features"]:
        out.append("  （无命中）")
    current_group = ""
    for bucket in report["features"]:
        if bucket["group"] != current_group:
            current_group = bucket["group"]
            out.append(f"  [{current_group}]")
        first = bucket.get("preferred") or bucket["hits"][0]
        where = first["file"] if not first["line"] else f"{first['file']}:{first['line']}"
        # 截到 25 再补到 26：截断结果正好填满时文件名会与 Pattern 编号黏在一起，
        # 看起来像同一个词。留一列空隙，列位仍然对齐。
        out.append(
            f"    {pad(bucket['label'], 14)}{pad(clip_where(where, 25), 26)}{bucket['pattern_ref']}"
        )
    out.append("")

    out.append(_section("3. 复用候选", width, box))
    if not any(report["reuse"].values()):
        out.append("  （无可复用的可读命中）")
    for tier in TIERS:
        items = report["reuse"][tier]
        if not items:
            continue
        # 标签先**去重**再展示：同一个风险规则在多个文件里命中时，
        # 原样列举会得到「硬编码凭据、代理凭据明文、硬编码凭据、代理凭据明文、…」——
        # 同一句话重复三遍且**没有归属**，读者既看不出有几类、也看不出哪个对应哪个文件。
        # 命中数与类数不等时两个都报：只说类数会丢掉"这条规则在多个文件里都犯了"，
        # 只说命中数会让人以为有三条不同的规则。
        labels = list(dict.fromkeys(item["label"] for item in items))
        count = (
            f"{len(items)} 项"
            if len(labels) == len(items)
            else f"{len(items)} 处 / {len(labels)} 类"
        )
        out.append(f"  {pad(TIER_LABELS[tier], 12)}{pad(count, 12)}  {'、'.join(labels)}")
    out.append("")

    out.append(_section("4. 缺口", width, box))
    if not report["gaps"]:
        out.append("  （本项目全部维度都有命中）")
    else:
        for item in report["gaps"]:
            out.append(f"    {pad(item['label'], 14)}{pad(item['group'], 12)}{item['pattern_ref']}")
    if report["non_reference"]:
        out.append("  仅出现在不可读文件里（是信号，不是范本）：")
        for item in report["non_reference"]:
            out.append(f"    {pad(item['label'], 14)}{'、'.join(item['files'])}")
    out.append("")

    if report["risks"]:
        out.append(_section("5. 风险与拒绝吸收", width, box))
        for risk in report["risks"]:
            mark = "拒绝" if risk["tier"] == "refuse" else "注意"
            where = clip_where(f"{risk['file']}:{risk['line']}", 44)
            out.append(f"  [{mark}] {risk['label']}  {where}")
            out.append(f"         {risk['why']}")
            if risk["snippet"]:
                out.append(f"         {risk['snippet']}")
        out.append("")

    out.append(_section("提示", width, box))
    if not report["notes"]:
        out.append("  · 无")
    for note in report["notes"]:
        out.append(f"  · {note}")
    out.append("")
    out.append(f"结论：{report['disclosure']}")
    return "\n".join(out)
