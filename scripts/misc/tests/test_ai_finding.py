from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_finding  # noqa: E402
from ai_finding import (  # noqa: E402
    KINDS,
    LOCK_STALE_SECONDS,
    STATUSES,
    FindingsLock,
    load,
    search,
    validate_records,
)


def make_record(**overrides) -> dict:
    record = {
        "time": "2026-09-24T21:30:00+08:00",
        "kind": "path",
        "area": "js-reverse",
        "title": "示例结论",
        "trigger": "遇到某信号时",
        "detail": "具体做法",
        "evidence": {"path": "kb/js-reverse/techniques/01-obfuscation-signals.md", "note": ""},
        "reuse": "high",
        "confidence": "high",
        "status": "active",
    }
    record.update(overrides)
    return record


class FindingValidationTests(unittest.TestCase):
    def test_valid_record_passes(self) -> None:
        self.assertEqual(validate_records([make_record()]), [])

    def test_missing_field_is_rejected(self) -> None:
        record = make_record()
        record.pop("trigger")
        self.assertTrue(validate_records([record]))

    def test_invalid_kind_is_rejected(self) -> None:
        self.assertTrue(validate_records([make_record(kind="guess")]))

    def test_invalid_status_is_rejected(self) -> None:
        self.assertTrue(validate_records([make_record(status="done")]))

    def test_all_declared_kinds_are_accepted(self) -> None:
        for kind in sorted(KINDS):
            self.assertEqual(validate_records([make_record(kind=kind)]), [], f"kind {kind} 应被接受")

    def test_all_declared_statuses_are_accepted(self) -> None:
        for status in sorted(STATUSES):
            self.assertEqual(validate_records([make_record(status=status)]), [], f"status {status} 应被接受")

    def test_machine_path_is_rejected(self) -> None:
        record = make_record(detail="证据在 " + "C:" + chr(92) + "Users" + chr(92) + "someone" + chr(92) + "sample.js")
        self.assertTrue(validate_records([record]))


class FindingSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            make_record(title="JSVMP 优先评估环境复现", trigger="遇到 JSVMP", detail="jsdom 路径更快"),
            make_record(
                title="符号恢复靠成对调用",
                kind="signal",
                area="reversing",
                trigger="stripped 二进制",
                detail="分配释放配对",
            ),
            make_record(title="已排除的路径", kind="dead-end", trigger="想反编译字节码", detail="成本极高"),
        ]

    def test_search_matches_title(self) -> None:
        hits = search("jsvmp", self.records, 10)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["title"], "JSVMP 优先评估环境复现")

    def test_search_matches_trigger(self) -> None:
        hits = search("stripped", self.records, 10)
        self.assertTrue(any(hit["title"] == "符号恢复靠成对调用" for hit in hits))

    def test_search_returns_empty_for_unrelated(self) -> None:
        self.assertEqual(search("完全无关的词汇组合", self.records, 10), [])

    def test_dead_end_records_are_searchable(self) -> None:
        hits = search("反编译字节码", self.records, 10)
        self.assertTrue(any(hit["kind"] == "dead-end" for hit in hits))


class FindingsFileTests(unittest.TestCase):
    def test_committed_findings_are_valid(self) -> None:
        records = load()
        self.assertGreater(len(records), 0, "kb/ai-findings/findings.jsonl 不应为空")
        self.assertEqual(validate_records(records), [])

    def test_committed_findings_use_lf_endings(self) -> None:
        """混入 CRLF 会让 diff 与逐行解析都变得不可预期。"""
        raw = ai_finding.FINDINGS.read_bytes()
        self.assertNotIn(b"\r", raw, "findings.jsonl 应只使用 LF 行尾")


class FindingsLockTests(unittest.TestCase):
    def test_second_acquire_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            lock_path = Path(raw) / "findings.jsonl.lock"
            with FindingsLock(lock_path, timeout=0.3):
                with self.assertRaises(TimeoutError):
                    with FindingsLock(lock_path, timeout=0.3):
                        pass

    def test_lock_file_removed_after_exit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            lock_path = Path(raw) / "findings.jsonl.lock"
            with FindingsLock(lock_path, timeout=1.0):
                self.assertTrue(lock_path.exists())
            self.assertFalse(lock_path.exists(), "退出后必须释放锁文件")

    def test_stale_lock_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            lock_path = Path(raw) / "findings.jsonl.lock"
            lock_path.write_text("", encoding="utf-8")
            stale = time.time() - (LOCK_STALE_SECONDS + 10)
            os.utime(lock_path, (stale, stale))
            with FindingsLock(lock_path, timeout=1.0):
                pass
            self.assertFalse(lock_path.exists())


class FindingsAppendTests(unittest.TestCase):
    def _run_add(self, findings: Path, **overrides) -> int:
        arguments = {
            "kind": "tool",
            "area": "testing",
            "title": "示例发现",
            "trigger": "触发信号",
            "detail": "具体做法",
            "evidence": "",
            "note": "",
            "reuse": "high",
            "confidence": "high",
            "status": "active",
        }
        arguments.update(overrides)
        with contextlib.redirect_stdout(io.StringIO()):
            return ai_finding.add(argparse.Namespace(**arguments))

    def test_add_is_lf_only_and_rejects_duplicate_title(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            findings = Path(raw) / "findings.jsonl"
            original = (ai_finding.FINDINGS, ai_finding.LOCK)
            ai_finding.FINDINGS = findings
            ai_finding.LOCK = findings.with_name(findings.name + ".lock")
            try:
                first = self._run_add(findings)
                second = self._run_add(findings)
            finally:
                ai_finding.FINDINGS, ai_finding.LOCK = original

            self.assertEqual(first, 0)
            self.assertEqual(second, 1, "同标题重复追加应被拒绝")
            payload = findings.read_bytes()
            self.assertNotIn(b"\r", payload, "追加内容不得引入 CRLF")
            self.assertEqual(len(payload.splitlines()), 1)

    def test_add_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            findings = Path(raw) / "findings.jsonl"
            original = (ai_finding.FINDINGS, ai_finding.LOCK)
            ai_finding.FINDINGS = findings
            ai_finding.LOCK = findings.with_name(findings.name + ".lock")
            try:
                self._run_add(findings)
                lock_path = ai_finding.LOCK
            finally:
                ai_finding.FINDINGS, ai_finding.LOCK = original
            self.assertFalse(lock_path.exists(), "add 结束后不应残留锁文件")


if __name__ == "__main__":
    unittest.main()
