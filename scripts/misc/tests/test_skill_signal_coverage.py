"""技能承诺的查询词，必须能被路由召回。**两个面**：

- `SKILL.md` 的 `description`（`TestSkillDescriptionRecall`）
- `SKILLS.md` 主表的「何时触发」列（`TestSkillsMdTriggerRecall`）

`routing.source.json` 的 signals 是路由打分的依据。承诺与 signals 由不同的人在不同
时间写，不一致时**用户照着承诺提问会路由不到**——"声明比实现强"的一个具体形态，
而 `check_routing_drift.py` 覆盖不到它（那个只查"四处文档有没有提及技能名"）。

实测（2026-09-26）：`third-party-script-teardown` 的 4 个术语
（别人的写法 / 逻辑分层 / 复用分档 / 知识回填）与 `emulated-execution-debug`
的 `算法复现` 返回**「无匹配」**；补齐 signals 后本文件钉住它们不再漂回去。

判据（校准了三次，每次都是"断言比判据强"）：

1. **只取「用于 … 」这一段**——能力描述段不算。取到结尾会把
   `js-script-obfuscator` 的「支持配置区明文保留、Base64/RC4、代理函数…」
   当成查询词；「并输出 …」是**产出物**，用户也不会拿它当提问。
2. **硬失败 = 无匹配**（`primary` 为空）。这是承诺被破坏的确定形态。
3. 命中别的技能算"归属之争"——同一件事两个技能都能做
   （`控制流扁平化` 既是要混淆的形状、也是要还原的形状），
   用户意图（做 / 解）不在字面上。这类进 `KNOWN_CROSS_SKILL` **显式登记**，
   不静默放过；新增的跨技能命中会失败。

**它在什么情况下会完全不执行**：技能没有 `description`、或 description 里没有
「用于」二字时会被静默跳过。所以 `SKILLS_WITHOUT_QUERY_PHRASES` **显式列出**
这类技能，新增一个这样的技能会失败，而不是悄悄逃过检查。
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "skills"
sys.path.insert(0, str(ROOT / "scripts"))

from automation.routing import load_index, route  # noqa: E402

# 没有「用于…」句式的技能：它们只能靠 `name` 被路由，没有可核对的承诺词。
SKILLS_WITHOUT_QUERY_PHRASES = {"automation-architect", "automation-script-dev-js"}

# 已登记的"归属之争"：承诺词命中了另一个技能。键是 (承诺技能, 词)，值是实际主选。
# 新增的跨技能命中会失败——请先判断它是"归属之争"还是"信号漏了/冲突了"。
KNOWN_CROSS_SKILL: dict[tuple[str, str], str] = {
    # 同一件事两个技能都能做，用户意图（做 / 解）不在字面上——
    # 混淆技能会做出这些形状，解混淆技能要还原这些形状，同一个词两边都成立。
    ("js-script-deobfuscator", "控制流扁平化"): "js-script-obfuscator",
    ("js-script-deobfuscator", "死代码注入"): "js-script-obfuscator",
    ("python-script-decryptor", "marshal"): "python-obfuscator-pro",
    ("python-script-decryptor", "配置区明文+业务体加密"): "python-obfuscator-pro",
    ("emulated-execution-debug", "加密/解密数据提取"): "js-script-deobfuscator",
    # 不是归属之争，是真的该归另一个技能：青龙脚本的**开发**场景归 dev-py，
    # 保护技能只是在它的产物上动手。
    ("js-script-obfuscator", "青龙脚本"): "automation-script-dev-py",
    ("python-obfuscator-pro", "青龙脚本或工具源码"): "automation-script-dev-py",
}

STOP_SUFFIXES = ("时", "的", "等", "以及", "或")
CUT_MARKERS = ("时", "。", "并输出", "并产出", "并给出")


def description_of(skill_md: Path) -> str | None:
    block = re.match(r"^---\n(.*?)\n---", skill_md.read_text(encoding="utf-8"), re.S)
    if not block:
        return None
    line = next((l for l in block.group(1).splitlines() if l.startswith("description:")), None)
    return line.split("description:", 1)[1].strip().strip('"') if line else None


def query_phrases(description: str) -> list[str]:
    if "用于" not in description:
        return []
    tail = description.split("用于", 1)[1]
    cuts = [tail.find(m) for m in CUT_MARKERS if tail.find(m) != -1]
    if cuts:
        tail = tail[: min(cuts)]
    found = re.findall(r"「([^」]{2,12})」", tail)
    for part in re.split(r"[、，,；;：]", tail):
        part = part.strip().strip("。.")
        if 2 <= len(part) <= 12 and not part.endswith(STOP_SUFFIXES):
            found.append(part)
    return list(dict.fromkeys(found))


class TestSkillDescriptionRecall(unittest.TestCase):
    def setUp(self) -> None:
        self.index = load_index()
        self.unrouted: dict[str, list[str]] = {}
        self.cross: dict[tuple[str, str], str] = {}
        self.without_phrases: set[str] = set()
        self.total = 0
        for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
            name = skill_md.parent.name
            phrases = query_phrases(description_of(skill_md) or "")
            if not phrases:
                self.without_phrases.add(name)
                continue
            for phrase in phrases:
                self.total += 1
                primary = [item["skill"] for item in route(phrase, self.index, top_k=5)["primary"]]
                if not primary:
                    self.unrouted.setdefault(name, []).append(phrase)
                elif name not in primary:
                    self.cross[(name, phrase)] = primary[0]

    def test_promised_phrases_are_never_unrouted(self):
        self.assertEqual(
            self.unrouted,
            {},
            "description 承诺了这些说法，但路由返回「无匹配」——"
            "用户照着描述提问会掉进空档：" + json.dumps(self.unrouted, ensure_ascii=False),
        )

    def test_cross_skill_hits_are_registered(self):
        self.assertEqual(
            self.cross,
            KNOWN_CROSS_SKILL,
            "跨技能命中集合变了。新增的请判断是「归属之争」（同一件事两个技能都能做）"
            "还是「信号漏了 / 冲突了」，再决定登记还是补 signals："
            + json.dumps({f"{k[0]} | {k[1]}": v for k, v in self.cross.items()}, ensure_ascii=False),
        )

    def test_skills_without_query_phrases_are_declared_explicitly(self):
        self.assertEqual(
            self.without_phrases,
            SKILLS_WITHOUT_QUERY_PHRASES,
            "无承诺词的技能集合变了：若确实新增了这类技能，请显式更新 "
            "SKILLS_WITHOUT_QUERY_PHRASES 并说明为什么它没有可核对的承诺词",
        )

    def test_coverage_is_not_vacuous(self):
        self.assertGreaterEqual(self.total, 40, f"只抽出 {self.total} 条候选，判据可能已失效")


# --- 第二个面：SKILLS.md 的「何时触发」列 -----------------------------------
#
# SKILLS.md 声称"本表由 `routing.source.json` 驱动校验，不再手工对账"，
# 但 `check_routing_drift.py` 只比对**技能名**：那一列的触发词从来没人核过。
# 实测（2026-09-26）`js-script-deobfuscator` 行的「改写等价验证」返回**「无匹配」**——
# 同一形状的漂移，只是换了个文件。
#
# 判据是**行为**不是词面：只要 route(词) 的主选就是本行技能就算对。
# 这一点很重要——纯词面比对（词在不在 signals 里）会把靠 `description_token`
# 或 `routing_rule` 命中的词误报成缺口，实测 3 个技能被这样误报，
# 而它们其实都路由正确。**「没声明」不等于「路由不到」。**

SKILLS_MD = ROOT / "SKILLS.md"

# SKILLS.md 触发列里已登记的跨技能命中：键是 (本行技能, 词)，值是实际主选。
KNOWN_SKILLS_MD_CROSS: dict[tuple[str, str], str] = {
    # 裸词「青龙」归 dev-py：青龙面板本身以 Python 脚本生态为主，
    # 该行写的是"JS/Node 自动化：青龙、…"，领域前缀被剥掉后只剩裸词。
    # 要 JS 侧，用户会说"青龙 js"；`青龙js` 信号在 dev-js 上。
    ("automation-script-dev-js", "青龙"): "automation-script-dev-py",
}


def skills_md_rows() -> list[tuple[str, str]]:
    """返回 SKILLS.md 主表里的 (技能名, 何时触发列)。"""
    rows: list[tuple[str, str]] = []
    for line in SKILLS_MD.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            rows.append((cells[0].strip("`"), cells[1]))
    return rows


def trigger_phrases(cell: str) -> list[str]:
    """把「何时触发」列切成触发词，丢掉冒号前的领域前缀（如"JS/Node 自动化"）。"""
    cell = cell.replace("**", "")
    segments = re.split(r"[：:]", cell)
    phrases: list[str] = []
    for position, segment in enumerate(segments):
        parts = [x.strip() for x in re.split(r"[、,，]", segment) if x.strip()]
        # 有冒号时，冒号前那一段若是不可再分的整句，判为领域前缀
        if len(segments) > 1 and position == 0 and len(parts) == 1 and len(segment.strip()) <= 24:
            continue
        phrases.extend(parts)
    return list(dict.fromkeys(phrases))


class TestSkillsMdTriggerRecall(unittest.TestCase):
    def setUp(self) -> None:
        self.index = load_index()
        self.rows = skills_md_rows()
        self.unrouted: dict[str, list[str]] = {}
        self.cross: dict[tuple[str, str], str] = {}
        self.total = 0
        for name, cell in self.rows:
            for phrase in trigger_phrases(cell):
                self.total += 1
                primary = [item["skill"] for item in route(phrase, self.index, top_k=5)["primary"]]
                if not primary:
                    self.unrouted.setdefault(name, []).append(phrase)
                elif name not in primary:
                    self.cross[(name, phrase)] = primary[0]

    def test_rows_cover_every_indexed_skill(self):
        self.assertEqual(
            sorted(name for name, _ in self.rows),
            sorted(skill["name"] for skill in self.index["skills"]),
            "SKILLS.md 主表的行与路由索引的技能集合不一致",
        )

    def test_trigger_phrases_are_never_unrouted(self):
        self.assertEqual(
            self.unrouted,
            {},
            "SKILLS.md 把这些都是「何时触发」，但路由返回「无匹配」——"
            "照着自己家的索引提问会掉进空档：" + json.dumps(self.unrouted, ensure_ascii=False),
        )

    def test_trigger_cross_skill_is_registered(self):
        self.assertEqual(
            self.cross,
            KNOWN_SKILLS_MD_CROSS,
            "SKILLS.md 触发列的跨技能命中集合变了。新增的请判断是「归属之争」"
            "还是「信号漏了 / 冲突了」，再决定登记还是补 signals："
            + json.dumps({f"{k[0]} | {k[1]}": v for k, v in self.cross.items()}, ensure_ascii=False),
        )

    def test_coverage_is_not_vacuous(self):
        self.assertGreaterEqual(self.total, 30, f"只抽出 {self.total} 条触发词，判据可能已失效")


if __name__ == "__main__":
    unittest.main()
