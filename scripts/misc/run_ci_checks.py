#!/usr/bin/env python3
"""本地跑完 CI 定义的全部检查步骤。

为什么需要它：`ci.yml` 只在 GitHub Actions 上执行，而 Actions 在新建仓库里
**需要手动启用**——没启用时 `README.md` 那句「CI 在 `windows-latest` 上执行以上检查」
就没有执行面。判据的有效面是**两段**的（判据写对 + 判据真的跑起来），
第二段在本地等于零。这个脚本把那一段补回来。

判据只有一处：**步骤列表从 `.github/workflows/ci.yml` 派生**，不在这里另抄一份。
两份判据必然漂移（MEMORY 规则「工具的两半共用同一份判据」）。

取哪些步骤：`run:` 是**单行**且形如 `python <某脚本>.py ...` 的。
不取的三类**全量打印**——跳过要说出来，否则「本地绿」会静默地比 CI 少一截：

- `uses:` 步骤（checkout / setup-python）——CI 的环境准备，本地已有；
- `run: |` 多行步骤——都是 `pip install`，是**准备**不是**检查**；
- `python -m pip install ...`——同上，且隐式改环境。

与 CI 有一处**有意差异**：CI 遇错即停，本脚本默认跑完再汇总（一次看全比逐个修快）；
要完全对齐用 `--fail-fast`。

本地缺 `mcp` 时 `mcp_smoke_check --require-mcp` 会红——那是**正确**的，
CI 会先装依赖，本地要自己装：

    python -m pip install -r scripts/automation/routing/requirements.txt

**预演 CI**：`--as-ci` 不应用任何本地改写，断言与 `ci.yml` 逐字一致。
但它必须在**干净的克隆**里跑——CI 的 `actions/checkout` 就是 clone，
所以正确的预演方式是 `git clone` 到临时目录再跑，**不要**用 `git archive`
（不带 `.git`、行尾语义不同，跑出来的 drift 是伪影）：

    git clone <本仓库路径> /tmp/ci-probe && cd /tmp/ci-probe
    python scripts/misc/run_ci_checks.py --as-ci

**失败分类**：性质相反的失败在汇总里必须分得开，否则读的人会把「预期失败」
当成「CI 红了」，或者反过来把真回归当成环境问题。每个失败步骤归入三类之一：

- `expected`：当前目录不是干净克隆，且该步骤的 CI 断言（`--expect-cases`
  之类）恰恰假设空克隆；
- `env`：输出含 `ModuleNotFoundError: No module named 'X'`，**且** `ci.yml`
  里在它之前有一个名称含 `Install` 的步骤提及 `X`——两个条件缺一不可；
- `real`：其余一切，**包括判不准的情况**。归错方向等于放行。

`--allow-expected`（默认关闭）只在所有失败都属 `expected`/`env` 时把退出码
置 0，并明确打印「这是被显式放行的，不是真绿」。

用法：

    python scripts/misc/run_ci_checks.py                  # 跑全部
    python scripts/misc/run_ci_checks.py --list           # 只列出派生出的步骤
    python scripts/misc/run_ci_checks.py --only 引用      # 只跑名字/命令含该串的步骤
    python scripts/misc/run_ci_checks.py --skip mcp       # 跳过名字/命令含该串的步骤
    python scripts/misc/run_ci_checks.py --fail-fast      # 对齐 CI 的遇错即停
    python scripts/misc/run_ci_checks.py --as-ci          # 按 CI 原样（用于克隆里预演）
    python scripts/misc/run_ci_checks.py --as-ci --allow-expected  # 显式放行预期/环境失败
    python scripts/misc/run_ci_checks.py --json           # 机器可读

零第三方依赖。
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

STEP_RE = re.compile(r"^\s*-\s*name:\s*(?P<name>.+?)\s*$")
RUN_RE = re.compile(r"^\s*run:\s*(?P<value>\S.*)$")
CHECK_COMMAND_RE = re.compile(r"^python\s+\S+\.py(?:\s|$)")
BLOCK_SCALARS = ("|", ">", "|-", ">-", "|+", ">+")

# 对「空克隆」的断言参数。新增同类参数时加到这里，不要按步骤名写死列表。
EMPTY_CLONE_ASSERTION_RE = re.compile(r"--expect-(?:cases|jobs)\b")
MODULE_NOT_FOUND_RE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")

OUTPUT_TAIL_LINES = 12

CATEGORY_ORDER = ("expected", "env", "real")
CATEGORY_TITLES = {
    "expected": "预期失败（当前目录不是干净克隆）",
    "env": "环境缺失（本机缺 CI 会先装的依赖）",
    "real": "真失败（需要修的）",
}

# 有些步骤的参数是**为 CI 环境写的断言**，照搬到本地会失真。逐条说明并改写，
# 且**全量打印**——悄悄改参数等于悄悄换判据。
# 键是步骤名；`test_run_ci_checks.py` 钉住每个键都对应 ci.yml 里真实存在的步骤，
# 所以 ci.yml 改了步骤名，这里是**测试红**而不是「改写静默失效」。
LOCAL_OVERRIDES: tuple[tuple[str, str, str], ...] = (
    (
        "Case state validation",
        "python scripts/misc/validate_case_states.py",
        "CI 里 `cases/` 一个文件都没有（被 .gitignore 挡住），`--expect-cases 0` 是"
        "**对 CI 环境的断言**；本地 `cases/` 有真实作业，带它必然红。"
        "本地跑同一支脚本、去掉那句环境断言。",
    ),
)


def _blocks(text: str) -> list[tuple[str, list[str]]]:
    """把工作流切成 (步骤名, 该步骤的所有行)。"""
    blocks: list[tuple[str, list[str]]] = []
    name: str | None = None
    lines: list[str] = []

    for line in text.splitlines():
        match = STEP_RE.match(line)
        if match:
            if name is not None:
                blocks.append((name, lines))
            name, lines = match.group("name"), []
            continue
        if name is not None:
            lines.append(line)

    if name is not None:
        blocks.append((name, lines))
    return blocks


def derive_steps(text: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """把 `ci.yml` 拆成 (要跑的步骤, 跳过的步骤)。

    **完整记账**：`steps + skipped` 等于文件里所有 `- name:` 步骤——
    一个步骤不许凭空消失，否则「本地等价」就是一句空话。
    """
    steps: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for name, lines in _blocks(text):
        run_value: str | None = None
        for line in lines:
            match = RUN_RE.match(line)
            if match:
                run_value = match.group("value").strip()
                break

        if run_value is None:
            skipped.append(
                {"name": name, "command": "", "why": "无 run（uses 类环境准备步骤）"}
            )
        elif run_value in BLOCK_SCALARS:
            skipped.append(
                {"name": name, "command": run_value, "why": "多行 run（安装类准备步骤）"}
            )
        elif CHECK_COMMAND_RE.match(run_value):
            steps.append({"name": name, "command": run_value})
        else:
            skipped.append(
                {
                    "name": name,
                    "command": run_value,
                    "why": "不是 `python <脚本>.py` 形式的检查",
                }
            )

    return steps, skipped


def apply_local_overrides(
    steps: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """按 `LOCAL_OVERRIDES` 把「CI 环境断言」换成本地等价物。

    返回 (改写后的步骤, 改写记录)。改写记录要全量打印——**改了参数就是改了判据**，
    不说出来就等于偷偷换了一把尺子。
    """
    table = {name: (command, why) for name, command, why in LOCAL_OVERRIDES}
    rewritten: list[dict[str, str]] = []
    applied: list[dict[str, str]] = []

    for step in steps:
        override = table.get(step["name"])
        if override is None:
            rewritten.append(step)
            continue
        command, why = override
        applied.append(
            {
                "name": step["name"],
                "from": step["command"],
                "to": command,
                "why": why,
            }
        )
        rewritten.append({**step, "command": command})

    return rewritten, applied


def _not_a_clean_clone() -> str | None:
    """`--as-ci` 的断言假设「干净克隆」。返回一句说明，或 None 表示看起来干净。

    判据只用**两个廉价信号**，不跑 `git status --ignored`（`tmp/` 有几千个文件，太慢）：
    `cases/` 有除 `.gitkeep` 之外的条目、或 `routing.index.json` 存在——这两样在
    干净克隆里都不该有。
    """
    cases = ROOT / "cases"
    if cases.is_dir():
        # `.gitkeep` 是被**跟踪**的占位文件，真实克隆里 `cases/` 恒含它一个。
        # 把它算作「脏」会让 `--as-ci` 在干净克隆里恒定误报——判据要按
        # 「本仓库拥有什么」算，而不是「目录里有什么」。
        entries = [p for p in cases.iterdir() if p.name != ".gitkeep"]
        if entries:
            has_keep = (cases / ".gitkeep").exists()
            tracked_keep = "（另有被跟踪的 .gitkeep）" if has_keep else ""
            return (
                f"cases/ 下有 {len(entries)} 个作业目录{tracked_keep}"
                "；干净克隆里 cases/ 只有被跟踪的 .gitkeep，其余被 .gitignore 挡住"
            )
    if (ROOT / "routing.index.json").exists():
        return "routing.index.json 存在（干净克隆里没有：它是派生文件且被 .gitignore 挡住）"
    return None


def _module_not_found(output: str) -> list[str]:
    """取出输出里所有 `ModuleNotFoundError: No module named 'X'` 的 X。"""
    return sorted(set(MODULE_NOT_FOUND_RE.findall(output)))


def _install_step_before(
    blocks: list[tuple[str, list[str]]], index: int, module: str
) -> tuple[str, str] | None:
    """在 `index` 之前找一个名称含 `Install`、且提及 `module` 的步骤。

    返回 (步骤名, 步骤正文) 或 None。名称也算「提及」——`Install routing MCP
    dependencies` 的正文里只有 requirements 路径，模块名写在步骤名上。
    """
    pattern = re.compile(
        rf"(?<![\w.-]){re.escape(module)}(?![\w.-])", re.IGNORECASE
    )
    for name, lines in blocks[:index]:
        if "install" not in name.lower():
            continue
        body = "\n".join(lines)
        if pattern.search(name + "\n" + body):
            return name, body
    return None


def _install_remedy(body: str, module: str) -> str:
    """从 Install 步骤的命令里推出补救动作；推不出就退回装模块名。"""
    match = re.search(r"pip\s+install\s+-r\s+(\S+)", body)
    if match:
        return f"python -m pip install -r {match.group(1)}"
    return f"python -m pip install {module}"


def classify_failure(
    result: dict[str, object],
    blocks: list[tuple[str, list[str]]],
    dirty_reason: str | None,
) -> dict[str, str]:
    """给一个失败步骤判定 `expected` / `env` / `real`。

    **判不准一律 `real`**：`expected`/`env` 只影响汇总呈现与 `--allow-expected`
    的放行，归错方向等于把真失败放行。
    """
    name = str(result["name"])
    command = str(result["command"])
    output = str(result["output"])
    exit_code = result["exit_code"]

    index = next(
        (i for i, (block_name, _) in enumerate(blocks) if block_name == name), None
    )

    modules = _module_not_found(output)
    if modules:
        # 有缺依赖信号：必须每个缺失模块都能对上 CI 的 Install 步骤，才算 env。
        resolved: list[tuple[str, str, str]] = []
        if index is not None:
            for module in modules:
                found = _install_step_before(blocks, index, module)
                if found is None:
                    break
                resolved.append((module, found[0], found[1]))
        if index is not None and len(resolved) == len(modules):
            module, install_name, install_body = resolved[0]
            return {
                "category": "env",
                "reason": (
                    f"输出含 `ModuleNotFoundError: No module named '{module}'`，"
                    f"且 ci.yml 前置步骤 `{install_name}` 提及它"
                ),
                "remedy": _install_remedy(install_body, module),
            }
        return {
            "category": "real",
            "reason": (
                f"输出含 `ModuleNotFoundError: No module named '{modules[0]}'`，"
                "但 ci.yml 里没有前置 Install 步骤提及它——不能当作环境缺失放行"
            ),
            "remedy": f"确认缺失依赖是否应由 CI 安装，然后修脚本：{name}",
        }

    assertion = EMPTY_CLONE_ASSERTION_RE.search(command)
    if dirty_reason and assertion:
        return {
            "category": "expected",
            "reason": f"{dirty_reason}；命令含 `{assertion.group(0)}`（对空克隆的断言）",
            "remedy": (
                "在干净克隆里跑：`git clone <仓库> <临时目录>`，"
                "再在克隆里执行 `python scripts/misc/run_ci_checks.py --as-ci`"
            ),
        }

    return {
        "category": "real",
        "reason": f"未匹配到预期失败或环境缺失的信号（exit={exit_code}），按真失败处理",
        "remedy": (
            "单独复跑看完整输出："
            f'`python scripts/misc/run_ci_checks.py --only "{name}" --verbose`'
        ),
    }


def run_step(step: dict[str, str], timeout: int) -> dict[str, object]:
    argv = shlex.split(step["command"])
    argv[0] = sys.executable  # CI 里的 `python` 换成当前解释器，参数原样保留
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv, cwd=ROOT, capture_output=True, text=True, timeout=timeout
        )
        exit_code = completed.returncode
        output = (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired:
        exit_code = 124
        output = f"超时：超过 {timeout} 秒未结束"
    return {
        "name": step["name"],
        "command": step["command"],
        "exit_code": exit_code,
        "seconds": round(time.monotonic() - started, 2),
        "output": output,
    }


def _tail(text: str, lines: int = OUTPUT_TAIL_LINES) -> str:
    kept = [line for line in text.splitlines() if line.strip()]
    return "\n".join(kept[-lines:])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="本地跑完 CI 定义的全部检查步骤（步骤列表从 ci.yml 派生）。"
    )
    parser.add_argument("--list", action="store_true", help="只列出派生出的步骤，不执行")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument(
        "--only", action="append", default=[], help="只跑名字或命令含该串的步骤（可重复）"
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        help="跳过名字或命令含该串的步骤（可重复）；被跳过的会打印出来",
    )
    parser.add_argument("--fail-fast", action="store_true", help="遇错即停（对齐 CI）")
    parser.add_argument(
        "--as-ci",
        action="store_true",
        help="按 CI 原样跑：不应用本地改写（用于在 git clone 出来的目录里预演 CI）",
    )
    parser.add_argument("--verbose", action="store_true", help="成功的步骤也打印完整输出")
    parser.add_argument("--timeout", type=int, default=900, help="单步超时秒数")
    parser.add_argument(
        "--allow-expected",
        action="store_true",
        help=(
            "若所有失败都属预期失败/环境缺失，退出码置 0；"
            "输出会明确说明这是显式放行，不是真绿（默认关闭）"
        ),
    )
    args = parser.parse_args(argv)

    if not WORKFLOW.exists():
        print(f"FAIL: 找不到 {WORKFLOW.relative_to(ROOT).as_posix()}")
        return 1

    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    steps, skipped = derive_steps(workflow_text)
    # 分类要看 ci.yml 的**全部**步骤（含被跳过的 Install 步骤），所以用未过滤的块。
    blocks = _blocks(workflow_text)

    # 空表守卫：派生不到步骤 = 判据空转（派生规则或工作流结构变了）。
    # 放在 --only 过滤**之前**，否则用户筛空了也会被当成判据坏了。
    if not steps:
        print("FAIL: 没从 ci.yml 派生出任何检查步骤——判据空转（派生规则或工作流结构变了）")
        return 1

    # 无论哪种模式都算一次：默认模式的失败分类同样需要「像不像干净克隆」。
    dirty = _not_a_clean_clone()

    if args.as_ci:
        # 按 CI 原样：不应用 LOCAL_OVERRIDES。这是唯一能回答「CI 会不会绿」的模式。
        # 但它照搬的是 CI 对**空克隆**的断言，所以要先说清当前目录像不像克隆。
        steps, overrides = steps, []
        if dirty:
            print(f"提示：{dirty}")
            print("      `--as-ci` 照搬 CI 对**空克隆**的断言，当前目录不是干净克隆，")
            print("      相关步骤失败属预期。要在克隆里预演：git clone <仓库> <临时目录>。")
    else:
        steps, overrides = apply_local_overrides(steps)

    selected = steps
    if args.only:
        selected = [
            step
            for step in steps
            if any(key in step["name"] or key in step["command"] for key in args.only)
        ]
        # 筛空也是「空集」：`--only` 打错一个字就变成一次什么都不跑的绿——
        # 与审计 F5 是同一类缺陷（空集与通过同为 exit=0），必须报错。
        if not selected:
            print(f"FAIL: --only {args.only} 没有匹配到任何步骤，拒绝以「空集」充当通过")
            return 1

    deselected: list[dict[str, str]] = []
    if args.skip:
        deselected = [
            step
            for step in selected
            if any(key in step["name"] or key in step["command"] for key in args.skip)
        ]
        selected = [step for step in selected if step not in deselected]
        if not selected:
            print(f"FAIL: --skip {args.skip} 跳掉了全部步骤，拒绝以「空集」充当通过")
            return 1

    if args.list:
        print(f"从 ci.yml 派生出 {len(steps)} 个检查步骤：")
        for step in steps:
            print(f"  - {step['name']}：{step['command']}")
        print(f"\n跳过 {len(skipped)} 个非检查步骤：")
        for item in skipped:
            print(f"  - {item['name']}：{item['why']}")
        if deselected:
            print(f"\n被 --skip 跳过的 {len(deselected)} 个检查步骤（这些这次没校验）：")
            for item in deselected:
                print(f"  - {item['name']}")
        if overrides:
            print(f"\n本地改写了 {len(overrides)} 个步骤（CI 环境断言 → 本地等价物）：")
            for item in overrides:
                print(f"  - {item['name']}")
                print(f"      CI：{item['from']}")
                print(f"      本地：{item['to']}")
                print(f"      为什么：{item['why']}")
        elif args.as_ci:
            print("\n按 CI 原样跑：未应用任何本地改写（断言与 ci.yml 逐字一致）。")
        return 0

    results: list[dict[str, object]] = []
    for step in selected:
        if not args.json:
            print(f"… {step['name']}", flush=True)
        result = run_step(step, args.timeout)
        results.append(result)
        if not args.json:
            mark = "PASS" if result["exit_code"] == 0 else "FAIL"
            print(f"[{mark}] {step['name']}（exit={result['exit_code']}，{result['seconds']}s）")
            if result["exit_code"] != 0 or args.verbose:
                body = _tail(str(result["output"]))
                if body:
                    print("\n".join(f"      {line}" for line in body.splitlines()))
        if args.fail_fast and result["exit_code"] != 0:
            break

    failed = [r for r in results if r["exit_code"] != 0]

    # 逐条判定类别。判不准一律 real（见 classify_failure 的说明）。
    buckets: dict[str, list[tuple[dict[str, object], dict[str, str]]]] = {
        key: [] for key in CATEGORY_ORDER
    }
    for result in failed:
        info = classify_failure(result, blocks, dirty)
        buckets[info["category"]].append((result, info))

    real_failures = buckets["real"]
    allowed = bool(failed) and not real_failures and args.allow_expected

    if args.json:
        print(
            json.dumps(
                {
                    "ok": not failed,
                    "allowed": allowed,
                    "allow_expected": args.allow_expected,
                    "workflow": WORKFLOW.relative_to(ROOT).as_posix(),
                    "as_ci": args.as_ci,
                    "derived": len(steps),
                    "ran": len(results),
                    "failed": [r["name"] for r in failed],
                    "failed_by_category": {
                        key: [r["name"] for r, _ in buckets[key]]
                        for key in CATEGORY_ORDER
                    },
                    "skipped": skipped,
                    "deselected": [step["name"] for step in deselected],
                    "overrides": overrides,
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if allowed or not failed else 1

    print()
    print(f"派生 {len(steps)} 步，执行 {len(results)} 步，失败 {len(failed)} 步。")
    if overrides:
        print(f"本地改写了 {len(overrides)} 个步骤（改了参数就是改了判据，故全量列出）：")
        for item in overrides:
            print(f"  - {item['name']}：CI `{item['from']}` → 本地 `{item['to']}`")
            print(f"      为什么：{item['why']}")
    elif args.as_ci:
        print("按 CI 原样跑：未应用任何本地改写（断言与 ci.yml 逐字一致）。")
    print(f"未执行（非检查步骤，共 {len(skipped)} 个）：")
    for item in skipped:
        print(f"  - {item['name']}：{item['why']}")
    if deselected:
        print(f"被 --skip 跳过、本次未校验的检查步骤（共 {len(deselected)} 个）：")
        for item in deselected:
            print(f"  - {item['name']}")

    if failed:
        print("按类别分开（预期失败与环境缺失不是「CI 红了」，真失败才是）：")
        for key in CATEGORY_ORDER:
            items = buckets[key]
            if not items:
                continue
            print(f"[{CATEGORY_TITLES[key]}] {len(items)} 步")
            for result, info in items:
                print(f"  - {result['name']}")
                print(f"      原因：{info['reason']}")
                print(f"      补救：{info['remedy']}")

    if not failed:
        print("RESULT=OK")
        return 0

    if not real_failures:
        if allowed:
            print()
            print("=" * 78)
            print("显式放行（--allow-expected）：所有失败都属预期失败/环境缺失，退出码置 0。")
            print("这不是真绿——换到干净克隆或补齐依赖后必须复跑。")
            print("=" * 78)
            return 0
        if args.as_ci:
            print(
                "没有任何「真失败」，但退出码仍为 1，"
                "因为 `--as-ci` 的语义就是按 CI 原样跑。"
            )
        else:
            print(
                "没有任何「真失败」，但退出码仍为 1；"
                "要显式放行请加 `--allow-expected`。"
            )
        return 1

    print(
        "失败的步骤（真失败）："
        + "、".join(str(result["name"]) for result, _ in real_failures)
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
