#!/usr/bin/env python3
"""路由漂移检查。

比对 routing.index.json（由 routing.source.json + 磁盘扫描生成）与项目内 4 处
Markdown 路由表，报告差集，防止路由表再次失同步。

三类判据：

1. `missing_in_doc` / `stale_references` —— 技能**名单**。
   文档里以「技能名形态」出现的 token（反引号或粗体包裹的 `小写-连字符` 标识）
   必须是真实技能；不在索引里就是**悬空引用**。
   背景（实测踩过）：`skills/automation-architect/SKILL.md` 把 UI/UX 需求路由到
   `ui-ux-pro-max`，而它随 `skills 原始备份/` 一起删掉了——两处都漏在过去：
   名字是**粗体**不是反引号（token 集合看不见），且名字里不含任何技能词根
   （`_is_skillish` 的启发式过滤掉了）。**启发式名单挡不住「没想到的名字」。**
   所以判据改为形态判据 + 显式豁免表 `NON_SKILL_TOKENS`（当前为空）。
2. `skill_count` —— 技能**数量**声明。文档里写「N 个技能」而索引里是 M 个即 drift。
   背景（实测踩过）：`AI-USAGE.md` 长期写着「11 个技能的触发信号」，实际已是 12 个。
   名单校验看不见它——那句话里没有任何技能名，只是数字过期。
   排除「与另外 2 个技能协同」这类**局部**表述（数词前是另/其他/这/那/每）。
   已知不覆盖：数量与量词被拆开写的形态（如「技能共 12 个」）不在此列。
3. `signal_recall` —— `kb/automation/techniques/01-routing.md` 的**信号列**。
   那一列是对 `routing.source.json` 的**复述**，判据是**行为式**的：
   `route(词)` 的主选必须就是本行技能（词的归属之争在 `KNOWN_SIGNAL_CROSS` 里登记）。
   背景（实测踩过）：临时探针在该列发现 3 处笔误（`代理健康池` / `Env 类` / `跑通单个函数`
   都对不上 signals 原文），探针删掉后就再没有东西会报出来——**一次性的探针不是校验器**。
   行内 `（Python）` / `（JS / Node）` 是**语言消歧符**，会作为上下文拼进查询，
   否则 `加密` / `解密` 这类在保护与解密技能里各有一份的词无法分派。

用法：
    python scripts/misc/check_routing_drift.py
    python scripts/misc/check_routing_drift.py --json   # 机器可读输出
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from automation.routing import find_root, route  # noqa: E402
from automation.routing.index_builder import load_index  # noqa: E402

DOCS = [
    "SKILLS.md",
    "AI-USAGE.md",
    "skills/automation-architect/SKILL.md",
    "kb/automation/techniques/01-routing.md",
]

# 信号列表格所在文档：只有它的首列是「信号 → 技能」映射。
SIGNAL_DOC = "kb/automation/techniques/01-routing.md"

# 「技能名形态」：小写字母开头、至少一个连字符的标识符。
# 反引号与粗体都算——两种写法在文档里都用来点名技能。
BACKTICK_RE = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`")
BOLD_RE = re.compile(r"\*\*([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\*\*")

# 形态像技能名、但确实不是技能（工具名 / 外部技能名 / 协议字段）。
# 现在是空的：4 处文档里所有技能名形态的 token 都对应真实技能。
# 加条目时请写清理由——**沉默的豁免与漏检在报告上长得一样**。
NON_SKILL_TOKENS: set[str] = set()

RE_SKILL_COUNT = re.compile(r"(\d+)\s*个技能")
RE_SKILL_COUNT_LOCAL = re.compile(r"(?:另外|另|其他|其它|这|那|每)\s*$")

# 信号列末尾的语言消歧符，如 `保护自有源码（Python）`、`保护自有源码（JS / Node）`。
# 它必须**先**摘掉再按 `/` 切词——`（JS / Node）` 里的斜杠会把词切成 `Node）`。
TRAILING_PAREN_RE = re.compile(r"[（(]([^）)]*)[）)]\s*$")

# 信号列的已登记「归属之争」：键是 (本行技能, 词)，值是实际主选。
# 新增的跨技能命中会失败——请先判断是归属之争，还是 signals 漏了 / 冲突了。
KNOWN_SIGNAL_CROSS: dict[tuple[str, str], str] = {
    # 裸语言词 `Python` 归 python-obfuscator-pro：该技能**名字里**含 python，
    # `name_token` +2.0 压过 dev-py 拿到的语言加成 +2.5-0.2。
    # 这不是信号冲突（规则：裸语言词不进 signals，语言由 detect_languages 处理），
    # 是「技能名里带语言词」与「语言线索」撞车，无法靠词面区分。
    ("automation-script-dev-py", "Python"): "python-obfuscator-pro",
}


def _tokens(text: str) -> set[str]:
    return set(BACKTICK_RE.findall(text)) | set(BOLD_RE.findall(text))


def _skill_count_claims(text: str, expected: int) -> list[dict]:
    """返回文档里过期的「N 个技能」声明（只报与索引不符的）。"""
    claims: list[dict] = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in RE_SKILL_COUNT.finditer(line):
            if RE_SKILL_COUNT_LOCAL.search(line[: match.start()]):
                continue
            declared = int(match.group(1))
            if declared != expected:
                claims.append(
                    {
                        "line": number,
                        "declared": declared,
                        "expected": expected,
                        "text": line.strip()[:120],
                    }
                )
    return claims


def signal_rows(text: str) -> list[dict]:
    """解析「信号 | 技能」表，返回每个词的 {line, skill, hint, word}。"""
    rows: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.startswith("| ") or "`" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        signal_cell, skill_cell = cells[0], cells[1]
        names = BACKTICK_RE.findall(skill_cell)
        if not names:
            continue
        hint = ""
        paren = TRAILING_PAREN_RE.search(signal_cell)
        if paren:
            hint = paren.group(1).strip()
            signal_cell = signal_cell[: paren.start()]
        for word in (part.strip() for part in signal_cell.split("/")):
            if word:
                rows.append({"line": lineno, "skill": names[0], "hint": hint, "word": word})
    return rows


def _signal_recall(text: str, index: dict) -> list[dict]:
    """信号列的词必须把路由引到本行技能；登记过的归属之争按登记值核。"""
    findings: list[dict] = []
    for row in signal_rows(text):
        query = f"{row['word']} {row['hint']}".strip() if row["hint"] else row["word"]
        primary = [item["skill"] for item in route(query, index, top_k=5)["primary"]]
        registered = KNOWN_SIGNAL_CROSS.get((row["skill"], row["word"]))
        if row["skill"] in primary:
            if registered is not None:
                findings.append(
                    {
                        "line": row["line"],
                        "skill": row["skill"],
                        "word": row["word"],
                        "actual": primary[:1],
                        "registered": registered,
                        "reason": "登记已失效：该词现在能正确路由到本行技能，请从 KNOWN_SIGNAL_CROSS 移除",
                    }
                )
            continue
        if registered is not None and primary[:1] == [registered]:
            continue
        findings.append(
            {
                "line": row["line"],
                "skill": row["skill"],
                "word": row["word"],
                "actual": primary[:1] or ["<无匹配>"],
                "registered": registered,
                "reason": (
                    "与登记的归属之争不符" if registered is not None else "信号列复述错误或 signals 缺口"
                ),
            }
        )
    return findings


def check(root: Path | None = None) -> dict:
    root = root or find_root()
    index = load_index(root)
    known = {s["name"] for s in index["skills"]}
    report: dict = {"root": str(root), "index_fingerprint": index["fingerprint"], "known_skills": sorted(known), "docs": {}}
    drift_found = False

    for rel in DOCS:
        path = root / rel
        entry: dict = {
            "exists": path.is_file(),
            "mentioned": [],
            "missing_in_doc": [],
            "stale_references": [],
            "skill_count": [],
            "signal_recall": [],
            "signal_table": {"words": 0, "skills": [], "skills_missing": []},
        }
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            tokens = _tokens(text)
            mentioned = sorted(t for t in tokens if t in known)
            stale = sorted(t for t in tokens if t not in known and t not in NON_SKILL_TOKENS)
            entry["mentioned"] = mentioned
            entry["missing_in_doc"] = sorted(known - set(mentioned))
            entry["stale_references"] = stale
            entry["skill_count"] = _skill_count_claims(text, len(known))
            if rel == SIGNAL_DOC:
                rows = signal_rows(text)
                table_skills = {row["skill"] for row in rows}
                entry["signal_table"] = {
                    "words": len(rows),
                    "skills": sorted(table_skills),
                    "skills_missing": sorted(known - table_skills),
                }
                entry["signal_recall"] = _signal_recall(text, index)
            if (
                entry["missing_in_doc"]
                or stale
                or entry["skill_count"]
                or entry["signal_recall"]
                or entry["signal_table"]["skills_missing"]
                or (rel == SIGNAL_DOC and not entry["signal_table"]["words"])
            ):
                drift_found = True
        else:
            drift_found = True
        report["docs"][rel] = entry

    diagnostics = index.get("diagnostics", {})
    report["index_diagnostics"] = diagnostics
    if any(diagnostics.get(key) for key in ("read_errors", "declared_missing_on_disk", "on_disk_missing_in_source")):
        drift_found = True

    report["drift_found"] = drift_found
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="检查路由表漂移")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    report = check()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"索引指纹: {report['index_fingerprint'][:16]}  已索引技能: {len(report['known_skills'])}")
        for rel, entry in report["docs"].items():
            if not entry["exists"]:
                print(f"[缺失] {rel}")
                continue
            clean = (
                not entry["missing_in_doc"]
                and not entry["stale_references"]
                and not entry["skill_count"]
                and not entry["signal_recall"]
                and not entry["signal_table"]["skills_missing"]
                and not (rel == SIGNAL_DOC and not entry["signal_table"]["words"])
            )
            status = "OK" if clean else "DRIFT"
            extra = ""
            if entry["signal_table"]["words"]:
                extra = f"  信号列 {entry['signal_table']['words']} 词 / {len(entry['signal_table']['skills'])} 技能"
            print(f"[{status}] {rel}  提及 {len(entry['mentioned'])}/{len(report['known_skills'])}{extra}")
            if entry["missing_in_doc"]:
                print(f"        未提及: {', '.join(entry['missing_in_doc'])}")
            if entry["stale_references"]:
                print(f"        悬空引用: {', '.join(entry['stale_references'])}")
            for claim in entry["skill_count"]:
                print(f"        第 {claim['line']} 行技能数过期: 写 {claim['declared']}，实际 {claim['expected']}")
            if entry["signal_table"]["skills_missing"]:
                print(f"        信号列未覆盖技能: {', '.join(entry['signal_table']['skills_missing'])}")
            if entry["exists"] and not entry["signal_table"]["words"] and rel == SIGNAL_DOC:
                print("        信号列为空: 解析不到任何行，本项校验已空转")
            for finding in entry["signal_recall"]:
                print(
                    f"        第 {finding['line']} 行信号「{finding['word']}」未指向 {finding['skill']}: "
                    f"实际 {', '.join(finding['actual'])}（{finding['reason']}）"
                )
        diagnostics = report["index_diagnostics"]
        for key, label in (
            ("read_errors", "读取错误"),
            ("declared_missing_on_disk", "source 声明但磁盘缺失"),
            ("on_disk_missing_in_source", "磁盘存在但 source 未声明"),
        ):
            if diagnostics.get(key):
                print(f"[DRIFT] {label}: {diagnostics[key]}")
        print("结论:", "存在漂移" if report["drift_found"] else "无漂移")
    return 1 if report["drift_found"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
