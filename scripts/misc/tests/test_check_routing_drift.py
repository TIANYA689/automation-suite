"""路由漂移检查里各判据的测试。

判据一「技能**名单**」：`AI-USAGE.md` 长期写着「11 个技能的触发信号」，实际已是 12 个。
那句话里没有任何技能名，只是数字过期——名单校验看不见它，所以有了判据二。

判据二「技能**数量**」：钉住三件事——过期数字报得出来、对得上时不报、
「与另外 2 个技能协同」这类**局部**表述不算数量声明。

判据三「**信号列**复述」：`01-routing.md` 信号列的词必须把路由引到本行技能。
背景（实测踩过）：临时探针在该列抓到 3 处笔误，探针删掉后就再没有东西会报出来。

名单判据自身的盲区也在这里钉住：`skills/automation-architect/SKILL.md` 用**粗体**写着
已随 `skills 原始备份/` 删除的 `ui-ux-pro-max`，而旧判据只认反引号、且用技能词根启发式过滤，
两处都漏——**启发式名单挡不住「没想到的名字」**。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_routing_drift  # noqa: E402
from automation.routing import load_index  # noqa: E402
from check_routing_drift import (  # noqa: E402
    DOCS,
    NON_SKILL_TOKENS,
    SIGNAL_DOC,
    _signal_recall,
    _skill_count_claims,
    _tokens,
    check,
    signal_rows,
)

ROOT = Path(__file__).resolve().parents[3]


class SkillCountClaimTests(unittest.TestCase):
    def test_stale_count_is_reported(self) -> None:
        claims = _skill_count_claims("本表由 `routing.source.json` 驱动，共 11 个技能的触发信号。", 12)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["declared"], 11)
        self.assertEqual(claims[0]["expected"], 12)
        self.assertEqual(claims[0]["line"], 1)

    def test_matching_count_is_clean(self) -> None:
        self.assertEqual(_skill_count_claims("套件内技能 12 个。", 12), [])

    def test_local_phrase_is_not_a_count_claim(self) -> None:
        # 讲的是"另外几个"，不是"套件一共几个"——不该被当成数量声明。
        for text in ("与另外 2 个技能协同。", "由其他 3 个技能接力。", "这 4 个技能各写一节。"):
            with self.subTest(text=text):
                self.assertEqual(_skill_count_claims(text, 12), [])

    def test_line_number_and_multiplicity(self) -> None:
        text = "第一行\n共 11 个技能\n第三行\n也是 9 个技能\n"
        claims = _skill_count_claims(text, 12)
        self.assertEqual([c["line"] for c in claims], [2, 4])
        self.assertEqual([c["declared"] for c in claims], [11, 9])

    def test_no_number_at_all(self) -> None:
        self.assertEqual(_skill_count_claims("技能清单见下表。", 12), [])


class SkillNameTokenTests(unittest.TestCase):
    """名单判据认两种写法：反引号与粗体。"""

    def test_backtick_token_is_collected(self) -> None:
        self.assertEqual(_tokens("见 `third-party-script-teardown`。"), {"third-party-script-teardown"})

    def test_bold_token_is_collected(self) -> None:
        # 旧判据只认反引号，粗体表里写的技能名整个看不见。
        self.assertEqual(_tokens("| **ui-ux-pro-max** | x |"), {"ui-ux-pro-max"})

    def test_non_hyphenated_identifiers_are_ignored(self) -> None:
        # 技能名形态要求至少一个连字符：`route_task` / `dry_run` 不该被当成技能。
        self.assertEqual(_tokens("`route_task` 与 `load_skill`"), set())

    def test_cjk_bold_is_not_a_skill_token(self) -> None:
        self.assertEqual(_tokens("**自动化注册** 与 **只读**"), set())

    def test_deleted_skill_in_bold_is_stale(self) -> None:
        """形态像技能名、又不在索引里 —— 必须报，不能靠技能词根启发式放行。"""
        blob = "| **ui-ux-pro-max** | UI设计 |\n| **skill-refactor** | 骨架化 |"
        known = {"automation-architect"}
        stale = sorted(t for t in _tokens(blob) if t not in known and t not in NON_SKILL_TOKENS)
        self.assertEqual(stale, ["skill-refactor", "ui-ux-pro-max"])


class SignalRowParsingTests(unittest.TestCase):
    def test_language_hint_is_extracted(self) -> None:
        rows = signal_rows("| 加密 / 混淆（Python） | `python-obfuscator-pro` |")
        self.assertEqual([r["word"] for r in rows], ["加密", "混淆"])
        self.assertEqual({r["hint"] for r in rows}, {"Python"})

    def test_slash_inside_hint_does_not_split_a_word(self) -> None:
        """`（JS / Node）` 里的斜杠曾把词切成 `Node）`——消歧符必须先摘掉再切词。"""
        rows = signal_rows("| 加密 / 混淆（JS / Node） | `js-script-obfuscator` |")
        self.assertEqual([r["word"] for r in rows], ["加密", "混淆"])
        self.assertEqual({r["hint"] for r in rows}, {"JS / Node"})

    def test_row_without_backticked_skill_is_skipped(self) -> None:
        # 表头、分隔行、以及任何不点技能的表格都不该被当成信号行。
        for text in ("| 信号 | 技能 |", "|---|---|", "| 场景 | 示例 |"):
            with self.subTest(text=text):
                self.assertEqual(signal_rows(text), [])

    def test_line_numbers_are_reported(self) -> None:
        rows = signal_rows("前言\n| 甲 / 乙 | `automation-architect` |")
        self.assertEqual([r["line"] for r in rows], [2, 2])


class SignalRecallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = load_index()
        self.text = (ROOT / SIGNAL_DOC).read_text(encoding="utf-8")

    def test_live_signal_column_points_at_its_own_skill(self) -> None:
        self.assertEqual(
            _signal_recall(self.text, self.index),
            [],
            "信号列有词没能路由到本行技能；若是归属之争请登记进 KNOWN_SIGNAL_CROSS",
        )

    def test_misspelled_word_is_reported(self) -> None:
        # 上一轮探针抓到的三处笔误之一：signals 是 `代理池`。
        findings = _signal_recall(self.text.replace("代理池", "代理健康池"), self.index)
        self.assertEqual([f["word"] for f in findings], ["代理健康池"])
        self.assertEqual(findings[0]["actual"], ["<无匹配>"])
        self.assertEqual(findings[0]["skill"], "automation-script-dev-py")

    def test_space_between_ascii_and_cjk_is_reported(self) -> None:
        # `normalize()` 压缩空白但不删除：`env 类` 与 `env类` 是两个词。
        findings = _signal_recall(self.text.replace("env类", "env 类"), self.index)
        self.assertEqual([f["word"] for f in findings], ["env 类"])

    def test_language_hint_is_load_bearing(self) -> None:
        """去掉消歧符，六个「保护/解密」共用的词应当全部翻红——它不是装饰。"""
        stripped = self.text.replace("（Python）", "").replace("（JS / Node）", "").replace("（JS）", "")
        findings = _signal_recall(stripped, self.index)
        self.assertEqual(len(findings), 6, [f["word"] for f in findings])

    def test_wrong_skill_name_in_row_is_reported(self) -> None:
        findings = _signal_recall(
            self.text.replace("`third-party-script-teardown`", "`some-other-skill`"), self.index
        )
        self.assertTrue(findings)
        self.assertEqual({f["skill"] for f in findings}, {"some-other-skill"})

    def test_registry_entry_that_became_correct_is_reported(self) -> None:
        """登记表不能只进不出：词恢复正确路由后，判据要反过来报「登记已失效」。"""
        stale_entry = {("automation-script-dev-py", "青龙"): "automation-script-dev-py"}
        with mock.patch.dict(check_routing_drift.KNOWN_SIGNAL_CROSS, stale_entry, clear=False):
            findings = _signal_recall(self.text, self.index)
        self.assertEqual([f["word"] for f in findings], ["青龙"])
        self.assertIn("登记已失效", findings[0]["reason"])


class RealRepoRoutingDocTests(unittest.TestCase):
    def test_live_docs_have_no_stale_skill_count(self) -> None:
        """四处路由表里不许出现与索引不符的技能数量。"""
        report = check()
        for rel, entry in report["docs"].items():
            with self.subTest(doc=rel):
                self.assertTrue(entry["exists"], f"{rel} 不存在")
                self.assertEqual(
                    entry["skill_count"],
                    [],
                    f"{rel} 技能数量声明过期: {entry['skill_count']}",
                )

    def test_live_docs_have_no_dangling_skill_reference(self) -> None:
        """四处路由表里点名的技能必须真实存在（反引号或粗体都算）。"""
        report = check()
        for rel, entry in report["docs"].items():
            with self.subTest(doc=rel):
                self.assertEqual(
                    entry["stale_references"],
                    [],
                    f"{rel} 引用了不存在的技能: {entry['stale_references']}",
                )

    def test_live_signal_table_is_not_vacuous(self) -> None:
        """判据失效的最隐蔽形态是「解析不到任何行却依然通过」。"""
        report = check()
        table = report["docs"][SIGNAL_DOC]["signal_table"]
        self.assertGreaterEqual(table["words"], 40, f"信号列只解析出 {table['words']} 个词")
        self.assertGreaterEqual(len(table["skills"]), 2)

    def test_live_signal_table_covers_every_indexed_skill(self) -> None:
        """新增技能时若忘了补信号行，这里要报出来。"""
        report = check()
        self.assertEqual(report["docs"][SIGNAL_DOC]["signal_table"]["skills_missing"], [])

    def test_repo_has_skills_indexed(self) -> None:
        """派生自索引，不写死数字：防止上面那些断言在"零技能"时静默通过。"""
        report = check()
        self.assertGreaterEqual(len(report["known_skills"]), 2)

    def test_expected_count_comes_from_index(self) -> None:
        """数量基准必须来自索引，而不是脚本里的常量。"""
        self.assertFalse(hasattr(check_routing_drift, "EXPECTED_SKILL_COUNT"))

    def test_signal_doc_is_one_of_the_checked_docs(self) -> None:
        """信号列所在文档必须在四处清单里，否则判据永远跑不到。"""
        self.assertIn(SIGNAL_DOC, DOCS)
        self.assertTrue((ROOT / SIGNAL_DOC).is_file())


if __name__ == "__main__":
    unittest.main()
