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

    return {
        "ok": not findings,
        "measurements": {
            "always_loaded": {"lines": entry_lines, "tokens": entry_tokens},
            "largest_skill": max(skills, key=lambda item: int(item["lines"])) if skills else None,
            "skills_measured": len(skills),
            "signals": signals,
        },
        "limits": {"soft": SOFT_LIMITS, "hard": HARD_LIMITS},
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
