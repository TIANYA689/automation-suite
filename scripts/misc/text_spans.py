#!/usr/bin/env python3
"""文本区间：识别**散文区间**并把它们等长抹掉。

为什么单独一层：关键词出现在**注释与文档字符串**里时，那是叙述，不是代码证据。
实测这条判断决定了拆解器能不能用——`scripts/automation` 自扫时，四处误报全在这：

- `route_query.py` 文档字符串里的示例命令「接码注册」→ 被报成"接了接码平台"
- `har_origin.py` 用法说明里的 `recaptcha.net` → 被报成"处理验证码"
- `build_routing_index.py` 的 `{"fingerprint": hash}`（**内容**指纹）→ 被报成"设备身份"
- `har_to_fixture.py` 的 `query.split("&")`（拆 URL query）→ 被报成"多账号加载"

误报的代价不对称：它会直接进"复用候选"，而候选是给人照着做的。
所以这里宁可漏（漏了会落进"缺口"被人看到），不可误报。

**只过滤注释与文档字符串，不动普通字符串字面量**：`"User-Agent"`、
`"multipart/form-data"` 是实打实的代码证据，全量剔除会把真命中一起杀掉。

本模块是被 `script_teardown.py` 导入的内部模块，不是命令行入口。
它与检测维度表（`teardown_rules.py`）分开，是因为变更轴不同：
加维度改那张表，加语言/改注释语法解析改这里。
"""

from __future__ import annotations

import ast
import io
import tokenize
from typing import Sequence

__all__ = ["prose_spans", "blank_spans"]

# 区间用四元组表示，与 `ast` 的行列约定一致：**行号从 1 起，列号从 0 起**。
Span = tuple[int, int, int, int]


def _python_prose_spans(text: str, tree: ast.AST | None) -> list[Span]:
    """文档字符串走语法树，注释走分词器——两条路各管一半，缺一不可。

    注释不在语法树里（解析器会丢弃），文档字符串不在分词器的 COMMENT 里
    （它是 STRING），所以两处都得走一遍。
    """
    spans: list[Span] = []

    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            body = getattr(node, "body", None) or []
            if not body:
                continue
            first = body[0]
            # 文档字符串的语法定义就是"块内第一条语句是一个裸字符串表达式"，
            # 不是"第一个字符串"——所以这里要连着 Expr + Constant 一起判。
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                value = first.value
                spans.append(
                    (value.lineno, value.col_offset, value.end_lineno, value.end_col_offset)
                )

    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                spans.append((token.start[0], token.start[1], token.end[0], token.end[1]))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        # 分词失败（未闭合的括号、缩进错乱……）不该让整次扫描失败：
        # 已拿到的文档字符串区间仍然有效，注释这一半放弃。
        pass

    return spans


def _scanned_prose_spans(text: str) -> list[Span]:
    """逐字符扫 `//` 与 `/* */`，**跳过引号内的内容**。

    跳过引号是硬要求，不是优化：JS 里 `const u = "https://x"; const h = {...}`
    这一行，若不认引号就会把 `//` 当成行注释开头，把后半段真证据整段抹掉。
    那是**静默的假阴性**——比误报更难发现，因为报告上什么都不显示。

    模板串（反引号）可以跨行，所以换行只在非模板引号内重置引号状态。
    """
    spans: list[Span] = []
    line, column = 1, 0
    index = 0
    length = len(text)
    quote: str | None = None

    while index < length:
        character = text[index]
        if character == "\n":
            line += 1
            column = 0
            quote = None if quote != "`" else quote
            index += 1
            continue
        if quote:
            if character == "\\":
                index += 2
                column += 2
                continue
            if character == quote:
                quote = None
            index += 1
            column += 1
            continue
        if character in "\"'`":
            quote = character
            index += 1
            column += 1
            continue
        if character == "/" and index + 1 < length and text[index + 1] == "/":
            start = (line, column)
            while index < length and text[index] != "\n":
                index += 1
                column += 1
            spans.append((start[0], start[1], line, column))
            continue
        if character == "/" and index + 1 < length and text[index + 1] == "*":
            start = (line, column)
            index += 2
            column += 2
            while index < length and not (
                text[index] == "*" and index + 1 < length and text[index + 1] == "/"
            ):
                if text[index] == "\n":
                    line += 1
                    column = 0
                else:
                    column += 1
                index += 1
            index += 2
            column += 2
            spans.append((start[0], start[1], line, column))
            continue
        index += 1
        column += 1

    return spans


def prose_spans(text: str, language: str, tree: ast.AST | None) -> list[Span]:
    """散文区间：Python 的注释 + 文档字符串；其它语言只认注释。

    JS/TS/shell 不认文档字符串——那门语言没有这个语法，硬套只会误伤普通字符串。
    """
    if language == "python":
        return _python_prose_spans(text, tree)
    return _scanned_prose_spans(text)


def blank_spans(text: str, spans: Sequence[Span]) -> str:
    """把区间替换成等长空白，**保留换行与偏移**。

    保留偏移是硬要求：行号是本工具唯一能被逐条复核的证据。
    一旦用"删掉再匹配"的写法，行号就会整体前移，读者回看时看到的是另一行——
    而报告上不会显示任何异常。

    越界区间直接跳过：扫描器对畸形输入不能抛异常，
    宁可少抹一段，也不能把整次扫描带走。
    """
    if not spans:
        return text
    lines = text.splitlines(keepends=True)
    for start_row, start_col, end_row, end_col in spans:
        for row in range(start_row, end_row + 1):
            if row < 1 or row > len(lines):
                continue
            raw = lines[row - 1]
            body = raw.rstrip("\r\n")
            ending = raw[len(body):]
            begin = start_col if row == start_row else 0
            end = end_col if row == end_row else len(body)
            begin = max(0, min(begin, len(body)))
            end = max(begin, min(end, len(body)))
            lines[row - 1] = body[:begin] + " " * (end - begin) + body[end:] + ending
    return "".join(lines)
