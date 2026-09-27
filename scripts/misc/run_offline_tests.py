"""运行全部离线测试套件。

设计要点：

- **逐套件解释器解析**：套件目录下若存在 `venv/` 或 `.venv/`，优先用它执行，
  否则退回当前解释器。模块可以声明自己的依赖，而运行器不去污染公共环境。
- **缺依赖即跳过而非失败**：套件显式声明所需第三方模块（`SUITES` 第三项）。
  解释器里缺依赖时标记 `skipped` 并给出原因，而不是伪装成红灯。
  发布前想强制全绿时用 `--strict`，跳过会被视为失败。
- **零第三方依赖**：本脚本只使用标准库，可被 CI 直接调用。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]

# (套件名, 套件目录, 该套件需要的第三方模块)
SUITES: list[tuple[str, Path, tuple[str, ...]]] = [
    ("release_checker", ROOT / "scripts" / "misc", ()),
    (
        "22do_free_receiver",
        ROOT / "tools" / "automation-modules" / "邮箱" / "22do_free_receiver",
        ("requests",),
    ),
    (
        "captcha_challenge",
        ROOT / "tools" / "automation-modules" / "过验证码" / "合规验证码挑战模块",
        (),
    ),
]

# 按优先级探测套件自带解释器（Windows 与 POSIX 布局都覆盖）。
VENV_LAYOUTS: tuple[tuple[str, ...], ...] = (
    ("venv", "Scripts", "python.exe"),
    ("venv", "bin", "python"),
    (".venv", "Scripts", "python.exe"),
    (".venv", "bin", "python"),
)

TEST_PATTERN = "test_*.py"


def resolve_interpreter(working_directory: Path) -> tuple[str, str]:
    """返回 (解释器路径, 来源标签)。套件自带 venv 优先，否则用当前解释器。"""
    for layout in VENV_LAYOUTS:
        candidate = working_directory.joinpath(*layout)
        if candidate.is_file():
            return str(candidate), "module-venv"
    return sys.executable, "current"


def missing_modules(interpreter: str, modules: Sequence[str]) -> list[str]:
    """用目标解释器探测缺哪些模块。探测失败时保守地认为全部缺失。"""
    if not modules:
        return []
    program = (
        "import importlib.util, json\n"
        f"names = {list(modules)!r}\n"
        "missing = [name for name in names if importlib.util.find_spec(name) is None]\n"
        "print(json.dumps(missing))\n"
    )
    completed = subprocess.run(
        [interpreter, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return list(modules)
    try:
        payload = json.loads(completed.stdout.strip() or "[]")
    except json.JSONDecodeError:
        return list(modules)
    return [str(item) for item in payload]


def run_suite(
    name: str,
    working_directory: Path,
    required: Sequence[str],
    environment: dict[str, str],
) -> dict[str, object]:
    if not working_directory.is_dir():
        return {
            "suite": name,
            "status": "skipped",
            "tests": 0,
            "interpreter": "n/a",
            "reason": "suite_directory_missing",
        }

    interpreter, source = resolve_interpreter(working_directory)
    absent = missing_modules(interpreter, required)
    if absent:
        return {
            "suite": name,
            "status": "skipped",
            "tests": 0,
            "interpreter": source,
            "reason": "missing_dependency: " + ", ".join(absent),
        }

    command = [
        interpreter,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-p",
        TEST_PATTERN,
        "-v",
    ]
    completed = subprocess.run(
        command,
        cwd=working_directory,
        env=environment,
        capture_output=True,
        # 测试子进程统一按 UTF-8 解码；Windows 中文代码页会把子进程的
        # UTF-8 输出误当成 GBK，导致解码线程异常并让 stdout/stderr 变成 None。
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = completed.stdout + completed.stderr
    # 取最后一次匹配：套件内部若嵌套运行了别的 unittest（例如运行器自身的测试），
    # 更早的 "Ran N tests" 会污染计数。
    counts = re.findall(r"Ran (\d+) tests?", output)
    passed = completed.returncode == 0
    if not passed:
        sys.stderr.write(output)
    return {
        "suite": name,
        "status": "passed" if passed else "failed",
        "tests": int(counts[-1]) if counts else 0,
        "interpreter": source,
    }


def declared_requirements() -> list[str]:
    """所有套件声明的第三方依赖去重后的列表（保持声明顺序）。"""
    seen: list[str] = []
    for _, _, required in SUITES:
        for module in required:
            if module not in seen:
                seen.append(module)
    return seen


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行全部离线测试套件。")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="跳过的套件也视为失败，用于发布前要求全绿。",
    )
    parser.add_argument(
        "--suite",
        action="append",
        default=None,
        help="只运行指定套件，可重复传入。",
    )
    parser.add_argument(
        "--print-requirements",
        action="store_true",
        help="只打印套件声明的第三方依赖（空格分隔），供 CI 安装使用。",
    )
    args = parser.parse_args(argv)

    if args.print_requirements:
        print(" ".join(declared_requirements()))
        return 0

    selected = [
        entry for entry in SUITES if args.suite is None or entry[0] in set(args.suite)
    ]

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"

    results = [
        run_suite(name, working_directory, required, environment)
        for name, working_directory, required in selected
    ]

    failed = [result["suite"] for result in results if result["status"] == "failed"]
    skipped = [result["suite"] for result in results if result["status"] == "skipped"]
    ok = not failed and (not args.strict or not skipped)

    summary = {
        "ok": ok,
        "strict": args.strict,
        "test_count": sum(int(result["tests"]) for result in results),
        "failed": failed,
        "skipped": skipped,
        "suites": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
