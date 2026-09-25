#!/usr/bin/env python3
"""文档预算度量：给"膨胀"这个没有反向压力的问题装一个仪表。

一致性有天然的对抗力量——路径断了会有人修。膨胀没有：每一轮都会再加一个技能、
一篇知识、一行索引，没有任何东西会因此报错，于是"始终加载的那部分"只会单向变长，
直到技能加载一次就吃掉大半上下文。

本脚本只度量，不自动修剪。阈值是**用本仓库当前实测值标定的**，换仓库必须重新标定。

度量维度：

- **始终加载的部分**：入口文档（`AI-USAGE.md` + `AGENTS.md`）每次会话都读。
- **单个技能体量**：`SKILL.md` 在技能激活时全量读入。
- **索引条目长度**：过长的触发信号会匹配到无关需求。
- **单文件体积**：任何手写文件悄悄长成"没人敢改的样子"。与上面三条不同，
  它度量的不是上下文成本而是**可维护性**——一个 1500 行的脚本，改一处的
  风险远大于三个 500 行的脚本。只增或派生的文件不参与（见下），因为它们的
  体积由"积累"决定、不由"作者克制"决定；已有专属预算的文件也不重复计入。
- **可导航性**（note，不判失败）：长文件的开头有没有标题结构可供跳读。
- **含糊规则趋势**（note，不判失败）："可能/也许/视情况"这类词是规则退化的先行指标。

零第三方依赖。

用法：
    python scripts/misc/check_budget.py
    python scripts/misc/check_budget.py --json
    python scripts/misc/check_budget.py --strict     # warning 也视为失败
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ENTRY_DOCS = ("AI-USAGE.md", "AGENTS.md")
SKILLS_ROOT = ROOT / "skills"
ROUTING_SOURCE = ROOT / "routing.source.json"

# 阈值：SOFT 出 warning，HARD 出 failure。均以本仓库实测值标定（见模块 docstring）。
SOFT_LIMITS = {
    "skill_lines": 600,
    "skill_tokens": 9000,
    "entry_lines": 200,
    "entry_tokens": 4000,
    "signal_chars": 24,
}
HARD_LIMITS = {
    "skill_lines": 1200,
    "skill_tokens": 16000,
    "entry_lines": 320,
    "entry_tokens": 6500,
    "signal_chars": 40,
}

# 单文件体积的预算。与上面的 LIMITS 分开，因为口径不同：上面按"读一次的成本"，
# 这里按"改一处的风险"。标定依据是本仓库 204 个文本文件的实测分布：
# 行数中位 98、p90 380、最大 1598（`scripts/automation/har_to_script.py`）。
# SOFT 取 800：把已经明显偏大的文件变成可见的 warning，但不阻塞任何事
# （CI 里本脚本不带 --strict，见 .github/workflows/ci.yml）。
# HARD 取 2000：留出约 25% 余量。**刻意不贴着当前最大值标定**——若把 HARD 定在
# 1600，`har_to_script.py` 只要再加三行就会让 CI 变红，而那时唯一的出路是
# 拆分一个 1600 行的文件；把"该拆了"的信号交给 SOFT，把 HARD 留给真正的失控。
FILE_SIZE_SOFT = {"lines": 800, "bytes": 50_000}
FILE_SIZE_HARD = {"lines": 2000, "bytes": 120_000}

# 参与体积度量的后缀：手写内容。
FILE_SIZE_SUFFIXES = frozenset(
    {".py", ".md", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".ini",
     ".sh", ".js", ".ts", ".html", ".css"}
)
# 只增或派生的文件：体积由积累决定，度量它只会制造永久噪音。
# `findings.jsonl` 是只增的经验库，`kb-index.json` / `routing.index.json` 是派生产物。
FILE_SIZE_SKIP_SUFFIXES = frozenset({".json", ".jsonl", ".csv", ".lock"})
# 已有专属预算的文件，不重复计入：`SKILL.md` 走 skill_*，入口文档走 entry_*。
FILE_SIZE_SKIP_NAMES = frozenset({"SKILL.md", "AI-USAGE.md", "AGENTS.md"})

# 文件系统回退遍历时的跳过目录（仅在 ROOT 不是 git 仓库时才会用到，即测试沙箱）。
FILE_SIZE_SKIP_DIRS = frozenset(
    {".git", "__pycache__", "node_modules", "venv", ".venv",
     "tmp", "exports", "reports", "cases", "notes", ".workbuddy-ai"}
)

NAV_MIN_LINES = 150
NAV_HEAD_LINES = 60
NAV_MIN_HEADINGS = 2

HEDGES = (
    "可能",
    "也许",
    "大概",
    "视情况",
    "一般来说",
    "尽量",
    "probably",
    "maybe",
    "should consider",
    "if needed",
)

SKILL_EXCLUDE = {"skills 原始备份"}


def estimate_tokens(text: str) -> int:
    """粗略 token 估计：CJK 按 1 字 1 token，其余按 4 字符 1 token。

    刻意不引入 tiktoken：检查脚本要能在任何裸解释器上跑。
    代价是数值是估计值——所以阈值留了余量，且**只用于比较同仓库内的相对体量**，
    不要拿它和别处的 token 计数对比。
    """
    cjk = 0
    for character in text:
        if "\u4e00" <= character <= "\u9fff":
            cjk += 1
        elif "\u3000" <= character <= "\u303f" or "\uff00" <= character <= "\uffef":
            cjk += 1
    return int(cjk + (len(text) - cjk) / 4)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _git_listed_files() -> list[Path] | None:
    """已跟踪 ∪ 未跟踪但未被忽略——「会进仓库的」那一批。

    用 git 算而不是自己维护跳过表：跳过表会漂移，git 的忽略规则不会。
    `-z` 用 NUL 分隔，因为本仓库有中文路径，行分隔 + 引号转义会读错。
    ROOT 不是 git 仓库时返回 None（测试沙箱就是这种情况），由调用方回退。

    先确认仓库根就是 ROOT：否则 `git ls-files` 会向上找到父仓库，返回一批
    相对父仓库的路径，拼到 ROOT 上全是错的——**结果看起来是"没有文件"，
    而不是"找错了仓库"**。
    """
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        if Path(top.stdout.decode("utf-8", errors="replace").strip()).resolve() != ROOT.resolve():
            return None
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    names = completed.stdout.decode("utf-8", errors="replace").split("\0")
    return [ROOT / name for name in names if name]


def _fallback_walk() -> list[Path]:
    """git 不可用时的回退：文件系统遍历 + 跳过目录表。"""
    found = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in FILE_SIZE_SKIP_DIRS for part in relative.parts[:-1]):
            continue
        found.append(path)
    return found


def _measure_files() -> list[dict[str, object]]:
    """度量单个手写文件的体积（行数与字节数）。

    行数与字节数都报，因为两者会脱节：一份 400 行的压缩 JSON 夹具可以有几 MB，
    而一个 1500 行的紧凑脚本只有 60 KB。前者是"读不动"，后者是"改不动"。
    """
    listed = _git_listed_files()
    candidates = listed if listed is not None else _fallback_walk()

    measured = []
    for path in sorted(candidates):
        suffix = path.suffix.lower()
        if suffix not in FILE_SIZE_SUFFIXES or suffix in FILE_SIZE_SKIP_SUFFIXES:
            continue
        if path.name in FILE_SIZE_SKIP_NAMES:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        try:
            lines = len(raw.decode("utf-8").splitlines())
        except UnicodeDecodeError:
            continue
        try:
            name = path.relative_to(ROOT).as_posix()
        except ValueError:
            name = path.as_posix()
        measured.append({"file": name, "lines": lines, "bytes": len(raw)})
    return measured


def _measure_skills() -> list[dict[str, object]]:
    measured = []
    if not SKILLS_ROOT.is_dir():
        return measured
    for directory in sorted(SKILLS_ROOT.iterdir()):
        if not directory.is_dir() or directory.name in SKILL_EXCLUDE:
            continue
        skill_file = directory / "SKILL.md"
        if not skill_file.is_file():
            continue
        text = _read(skill_file)
        measured.append(
            {
                "skill": directory.name,
                "lines": len(text.splitlines()),
                "tokens": estimate_tokens(text),
            }
        )
    return measured


def _measure_signals() -> dict[str, object]:
    try:
        payload = json.loads(ROUTING_SOURCE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"count": 0, "longest": 0, "longest_signal": "", "longest_skill": ""}

    longest = (0, "", "")
    count = 0
    for skill, spec in payload.get("skills", {}).items():
        for signal in spec.get("signals", []):
            count += 1
            if len(signal) > longest[0]:
                longest = (len(signal), skill, signal)
    return {
        "count": count,
        "longest": longest[0],
        "longest_skill": longest[1],
        "longest_signal": longest[2],
    }


def _navigability_notes() -> list[dict[str, object]]:
    notes = []
    candidates = list(ROOT.glob("*.md"))
    for directory in ("kb", "docs", "skills"):
        target = ROOT / directory
        if target.is_dir():
            candidates.extend(sorted(target.rglob("*.md")))

    for path in candidates:
        if "原始备份" in path.as_posix():
            continue
        text = _read(path)
        lines = text.splitlines()
        if len(lines) < NAV_MIN_LINES:
            continue
        headings = sum(1 for line in lines[:NAV_HEAD_LINES] if line.startswith("#"))
        if headings < NAV_MIN_HEADINGS:
            notes.append(
                {
                    "file": path.relative_to(ROOT).as_posix(),
                    "lines": len(lines),
                    "headings_in_head": headings,
                    "note": f"超过 {NAV_MIN_LINES} 行，但前 {NAV_HEAD_LINES} 行只有 {headings} 个标题，难以跳读",
                }
            )
    return notes


def _hedge_trend() -> list[dict[str, object]]:
    trend = []
    for skill in _measure_skills():
        path = SKILLS_ROOT / str(skill["skill"]) / "SKILL.md"
        text = _read(path)
        hits = {word: text.count(word) for word in HEDGES if word in text}
        if hits:
            trend.append({"skill": skill["skill"], "total": sum(hits.values()), "hits": hits})
    return sorted(trend, key=lambda item: -int(item["total"]))


def run() -> dict[str, object]:
    findings: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []

    def record(level: str, subject: str, metric: str, value: object, soft: object, hard: object) -> None:
        if level == "fail":
            findings.append(
                {
                    "subject": subject,
                    "metric": metric,
                    "value": value,
                    "hard_limit": hard,
                    "detail": f"{metric} = {value}，超过硬上限 {hard}",
                }
            )
        else:
            warnings.append(
                {
                    "subject": subject,
                    "metric": metric,
                    "value": value,
                    "soft_limit": soft,
                    "detail": f"{metric} = {value}，超过软上限 {soft}（尚未到硬上限 {hard}）",
                }
            )

    entry_lines = 0
    entry_tokens = 0
    for name in ENTRY_DOCS:
        path = ROOT / name
        if not path.is_file():
            continue
        text = _read(path)
        entry_lines += len(text.splitlines())
        entry_tokens += estimate_tokens(text)

    for metric, value in (("entry_lines", entry_lines), ("entry_tokens", entry_tokens)):
        if value > HARD_LIMITS[metric]:
            record("fail", " + ".join(ENTRY_DOCS), metric, value, SOFT_LIMITS[metric], HARD_LIMITS[metric])
        elif value > SOFT_LIMITS[metric]:
            record("warn", " + ".join(ENTRY_DOCS), metric, value, SOFT_LIMITS[metric], HARD_LIMITS[metric])

    skills = _measure_skills()
    for skill in skills:
        for metric in ("lines", "tokens"):
            key = f"skill_{metric}"
            value = skill[metric]
            if value > HARD_LIMITS[key]:
                record("fail", str(skill["skill"]), metric, value, SOFT_LIMITS[key], HARD_LIMITS[key])
            elif value > SOFT_LIMITS[key]:
                record("warn", str(skill["skill"]), metric, value, SOFT_LIMITS[key], HARD_LIMITS[key])

    signals = _measure_signals()
    if signals["longest"] > HARD_LIMITS["signal_chars"]:
        record(
            "fail",
            f"{signals['longest_skill']}",
            "signal_chars",
            signals["longest"],
            SOFT_LIMITS["signal_chars"],
            HARD_LIMITS["signal_chars"],
        )
    elif signals["longest"] > SOFT_LIMITS["signal_chars"]:
        record(
            "warn",
            f"{signals['longest_skill']}",
            "signal_chars",
            signals["longest"],
            SOFT_LIMITS["signal_chars"],
            HARD_LIMITS["signal_chars"],
        )

    files = _measure_files()
    for item in files:
        for metric in ("lines", "bytes"):
            value = item[metric]
            key = f"file_{metric}"
            if value > FILE_SIZE_HARD[metric]:
                record("fail", str(item["file"]), key, value, FILE_SIZE_SOFT[metric], FILE_SIZE_HARD[metric])
            elif value > FILE_SIZE_SOFT[metric]:
                record("warn", str(item["file"]), key, value, FILE_SIZE_SOFT[metric], FILE_SIZE_HARD[metric])

    return {
        "ok": not findings,
        "measurements": {
            "always_loaded": {"lines": entry_lines, "tokens": entry_tokens},
            "largest_skill": max(skills, key=lambda item: int(item["lines"])) if skills else None,
            "skills_measured": len(skills),
            "signals": signals,
            "files_measured": len(files),
            "largest_file": max(files, key=lambda item: int(item["lines"])) if files else None,
        },
        "limits": {
            "soft": SOFT_LIMITS,
            "hard": HARD_LIMITS,
            "file_size_soft": FILE_SIZE_SOFT,
            "file_size_hard": FILE_SIZE_HARD,
        },
        "failures": findings,
        "warnings": warnings,
        "notes": {
            "navigability": _navigability_notes(),
            "hedging": _hedge_trend(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="度量文档体量，报告膨胀趋势。")
    parser.add_argument("--json", action="store_true", help="只输出 JSON（不追加 RESULT 令牌）")
    parser.add_argument("--strict", action="store_true", help="warning 也视为失败")
    args = parser.parse_args(argv)

    report = run()
    ok = report["ok"] and (not args.strict or not report["warnings"])
    report["strict"] = args.strict
    report["ok"] = ok

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.json:
        print(f"RESULT={'OK' if ok else 'OVER_BUDGET'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
