#!/usr/bin/env python3
"""文档命令真实性校验。

文档里写的命令是一种**断言**：它断言某个脚本存在、某个子命令存在、某个选项存在。
这些断言会随代码演进静默失效——脚本改了选项名，文档照旧，读者照抄，命令报错。
锚点检查（路径存在）看不见这类漂移，因为路径是对的，错的是参数。

本脚本静态解析每个被引用脚本的 argparse 表（`ast`，不执行脚本），
再把文档里的命令行逐条对上去。

判据（任何一条命中即 drift）：

- `script_missing`   —— 文档引用的脚本文件不存在
- `unknown_subcommand` —— 脚本有子命令，但文档写的那个不在表里
- `unknown_option`   —— 选项不在该（子）命令的 argparse 表里
- `missing_value`    —— 选项需要值，但后面没有值（或紧跟另一个选项）

豁免是显式常量并**全量打印**：可审计的排除不是漏洞，沉默的排除才是。

零第三方依赖。

用法：
    python scripts/misc/check_commands.py
    python scripts/misc/check_commands.py --json
    python scripts/misc/check_commands.py --strict      # 有 drift 即非零退出（默认行为）
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCAN_ROOTS = (
    "README.md",
    "AI-USAGE.md",
    "AGENTS.md",
    "SKILLS.md",
    "CONTRIBUTING.md",
    "docs",
    "skills",
    "kb",
    "projects",
    "tools",
    ".github",
)
SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "tmp",
    "exports",
    "reports",
    "cases",
    "notes",
}

COMMAND_RE = re.compile(r"^(?:\$|>|PS[^>]*>)?\s*(?:python3?|py)\s+(?P<rest>.+)$")

# 无需值的 argparse action。其余 action 默认需要一个值。
VALUELESS_ACTIONS = {
    "store_true",
    "store_false",
    "store_const",
    "append_const",
    "count",
    "help",
    "version",
}

# 不检查的理由必须写在这里，且会被打印出来。
EXEMPTIONS: tuple[tuple[str, str], ...] = (
    (
        "interpreter -m",
        "`python -m <module>` 调用的是已安装模块而非仓库内脚本，没有本地 argparse 表可对",
    ),
    (
        "synopsis",
        "参数位含 `|` 的写法是用法概要（如 `ai_finding.py add|search|list`），不是可执行命令",
    ),
    (
        "placeholder",
        "参数里含 `...`、`<...>`、`{...}`、`$VAR` 的写法是模板，值由读者填",
    ),
    (
        "unparsable",
        "引号不闭合等无法分词的行；强行分词只会产出假 drift",
    ),
)


def _iter_docs() -> list[Path]:
    found: list[Path] = []
    for entry in SCAN_ROOTS:
        target = ROOT / entry
        if target.is_file():
            found.append(target)
            continue
        if not target.is_dir():
            continue
        for path in sorted(target.rglob("*.md")):
            if any(part in SKIP_DIR_NAMES for part in path.relative_to(ROOT).parts):
                continue
            found.append(path)
    return found


class CliSpec:
    """一个脚本的 argparse 表面：顶层选项、子命令及其选项。"""

    def __init__(self) -> None:
        self.options: dict[str, bool] = {}  # 选项串 -> 是否需要值
        self.subcommands: dict[str, dict[str, bool]] = {}
        self.has_subparsers = False
        self.subparsers_required = False


def _option_strings(node: ast.Call) -> list[str]:
    found = []
    for argument in node.args:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            if argument.value.startswith("-") and argument.value != "-":
                found.append(argument.value)
    return found


def _needs_value(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg == "action":
            if isinstance(keyword.value, ast.Constant) and keyword.value.value in VALUELESS_ACTIONS:
                return False
        if keyword.arg == "nargs":
            if isinstance(keyword.value, ast.Constant):
                if keyword.value.value == 0:
                    return False
                if keyword.value.value == "?":
                    return False
    return True


def _receiver_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id
    return None


def _subcommand_name(node: ast.Call) -> str | None:
    if node.args and isinstance(node.args[0], ast.Constant):
        value = node.args[0].value
        if isinstance(value, str) and value:
            return value
    return None


def _subparsers_required(node: ast.Call) -> bool:
    """`add_subparsers(required=True)`：不给子命令本身就是用法错误。"""
    for keyword in node.keywords:
        if keyword.arg == "required" and isinstance(keyword.value, ast.Constant):
            return bool(keyword.value.value)
    return False


def _normalise_separators(command: str) -> str:
    """把 Windows 反斜杠路径转成正斜杠。

    文档里写 `python .\\main.py` 或 `python scripts\\x.py` 是合法的，
    但 shlex 的 posix 模式会把 `\\m` 当成转义，吃掉反斜杠，
    于是脚本名变成 `.main.py`，报出假 drift。转义引号的反斜杠保留。
    """
    return re.sub(r"\\(?![\\'\"])", "/", command)


def extract_cli(script: Path) -> CliSpec | None:
    """静态提取 argparse 表面。解析失败返回 None（调用方按豁免处理）。"""
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    spec = CliSpec()
    parsers: dict[str, str] = {}  # 变量名 -> "top" 或 "sub:<name>"

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Attribute):
                continue
            attribute = value.func.attr
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                if attribute == "ArgumentParser":
                    parsers[target.id] = "top"
                elif attribute == "add_subparsers":
                    spec.has_subparsers = True
                    spec.subparsers_required = _subparsers_required(value)
                elif attribute == "add_parser":
                    name = _subcommand_name(value)
                    if name is not None:
                        parsers[target.id] = f"sub:{name}"
                        spec.subcommands.setdefault(name, {})

    # `add_parser(...)` 也常写成不赋值的形式（无参数子命令，如 `sub.add_parser("validate")`）。
    # 只在赋值分支里登记子命令名会漏掉它们，把真命令误报成未知子命令。
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_parser":
            continue
        name = _subcommand_name(node)
        if name is not None:
            spec.subcommands.setdefault(name, {})

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument":
            continue
        receiver = _receiver_name(node)
        if receiver is None or receiver not in parsers:
            continue
        bucket = "top" if parsers[receiver] == "top" else parsers[receiver].split(":", 1)[1]
        needs_value = _needs_value(node)
        for option in _option_strings(node):
            if bucket == "top":
                spec.options[option] = needs_value
            else:
                spec.subcommands[bucket][option] = needs_value

    return spec


def _strip_comment(line: str) -> str:
    """去掉行尾注释，但不动引号内的 `#`。"""
    quote: str | None = None
    for index, character in enumerate(line):
        if quote:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        if character == "#":
            return line[:index]
    return line


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """合并续行，返回 (起始行号, 逻辑行)。

    两种续行符都要认：shell 的 `\\` 与 PowerShell 的反引号。反引号只在代码块内
    算续行——正文里以反引号结尾是行内代码的收尾，合并会把两段散文拼成假命令。
    """
    merged: list[tuple[int, str]] = []
    buffer = ""
    start = 0
    in_fence = False

    for offset, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        line = raw.rstrip()
        if not buffer:
            start = offset
        continuation = line.endswith("\\") or (in_fence and line.endswith("`"))
        if continuation:
            buffer += line[:-1] + " "
            continue
        buffer += line
        if buffer.strip():
            merged.append((start, buffer))
        buffer = ""

    if buffer.strip():
        merged.append((start, buffer))
    return merged


def _tokenize(command: str) -> list[str] | None:
    try:
        lexer = shlex.shlex(command, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def _placeholder_reason(rest: str) -> str | None:
    if "..." in rest:
        return "placeholder"
    if re.search(r"<[^>]+>", rest):
        return "placeholder"
    if re.search(r"\{[^}]+\}", rest):
        return "placeholder"
    if "$" in rest:
        return "placeholder"
    if "|" in rest:
        return "synopsis"
    return None


def _drift(file: Path, line: int, kind: str, detail: str) -> dict[str, object]:
    return {
        "file": file.relative_to(ROOT).as_posix(),
        "line": line,
        "kind": kind,
        "detail": detail,
    }


def _resolve_script(doc: Path, token: str) -> Path | None:
    """按四步解析脚本路径。

    第 3 步是必需的：`docs/automation-modules/` 是 `tools/automation-modules/` 的
    README 快照，模块 README 里的 `python main.py` 指的是 tools 下的真脚本，
    不认这条镜像规则会把整批模块文档误判成缺失。
    """
    candidates = [ROOT / token, doc.parent / token]
    parts = doc.relative_to(ROOT).parts
    if parts and parts[0] == "docs":
        candidates.append(ROOT / "tools" / Path(*parts[1:]).parent / token)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _check_command(
    doc: Path,
    line: int,
    tokens: list[str],
) -> list[dict[str, object]]:
    drifts: list[dict[str, object]] = []
    script_token = tokens[1]
    if script_token in {"-m", "-c"}:
        return drifts

    candidate = _resolve_script(doc, script_token)
    if candidate is None:
        drifts.append(_drift(doc, line, "script_missing", f"找不到脚本 {script_token}"))
        return drifts

    spec = extract_cli(candidate)
    if spec is None or (not spec.options and not spec.subcommands):
        return drifts

    rest = tokens[2:]
    # argparse 允许顶层选项出现在子命令之前，所以这里是**扫描**而不是"先取子命令再校验选项"。
    # 早先的写法把"有子命令"和"有顶层选项"当成了互斥，会误报 `tool.py --verbose add`。
    table = spec.options
    subcommand: str | None = None
    first_positional: str | None = None

    index = 0
    while index < len(rest):
        token = rest[index]
        if not token.startswith("-") or token == "-":
            if subcommand is None and spec.has_subparsers and token in spec.subcommands:
                subcommand = token
                table = spec.subcommands[token]
            elif first_positional is None:
                first_positional = token
            index += 1
            continue

        name, _, inline_value = token.partition("=")
        if name not in table:
            owner = f"{script_token} {subcommand}" if subcommand else script_token
            drifts.append(_drift(doc, line, "unknown_option", f"{owner} 没有选项 {name}"))
            index += 1
            continue
        if inline_value or not table[name]:
            index += 1
            continue
        following = rest[index + 1] if index + 1 < len(rest) else None
        if following is None:
            drifts.append(_drift(doc, line, "missing_value", f"{name} 需要一个值，但命令到此结束"))
            index += 1
            continue
        if following.startswith("-") and not re.fullmatch(r"-\d+(?:\.\d+)?", following):
            drifts.append(_drift(doc, line, "missing_value", f"{name} 需要一个值，但紧跟的是 {following}"))
            index += 1
            continue
        index += 2

    if spec.has_subparsers and spec.subparsers_required and subcommand is None:
        if first_positional is None:
            detail = f"{script_token} 需要子命令，但一个也没给；可选 {sorted(spec.subcommands)}"
        else:
            detail = (
                f"{script_token} 没有子命令 {first_positional}；可选 {sorted(spec.subcommands)}"
            )
        drifts.append(_drift(doc, line, "unknown_subcommand", detail))

    return drifts


def run() -> dict[str, object]:
    drifts: list[dict[str, object]] = []
    exempt_hits: dict[str, int] = {reason: 0 for reason, _ in EXEMPTIONS}
    checked = 0
    scripts_seen: set[str] = set()

    for doc in _iter_docs():
        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, logical in _logical_lines(text):
            command = _normalise_separators(_strip_comment(logical).strip())
            match = COMMAND_RE.match(command)
            if not match:
                continue
            rest = match.group("rest").strip()
            if rest.startswith("-"):
                exempt_hits["interpreter -m"] += 1
                continue
            reason = _placeholder_reason(rest)
            if reason is not None:
                exempt_hits[reason] += 1
                continue
            tokens = _tokenize(command)
            if tokens is None or len(tokens) < 2:
                exempt_hits["unparsable"] += 1
                continue
            if not tokens[1].endswith(".py"):
                exempt_hits["interpreter -m"] += 1
                continue
            checked += 1
            scripts_seen.add(tokens[1])
            drifts.extend(_check_command(doc, line_number, tokens))

    return {
        "ok": not drifts,
        "checked_commands": checked,
        "distinct_scripts": len(scripts_seen),
        "drift_count": len(drifts),
        "drifts": drifts,
        "exemptions": [
            {"reason": reason, "hits": exempt_hits.get(reason, 0), "why": why}
            for reason, why in EXEMPTIONS
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验文档里的命令是否真实存在。")
    parser.add_argument("--json", action="store_true", help="只输出 JSON（不追加 RESULT 令牌）")
    parser.add_argument("--strict", action="store_true", help="保留给 CI 显式表达；本脚本默认即严格")
    args = parser.parse_args(argv)

    report = run()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"RESULT={'OK' if report['ok'] else 'DRIFT'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
