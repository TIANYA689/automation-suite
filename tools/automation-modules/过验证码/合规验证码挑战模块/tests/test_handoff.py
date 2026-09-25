from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from captcha_challenge import (
    AuthorizationPolicy,
    ChallengeKind,
    ChallengeRequest,
    HandoffAborted,
    HandoffError,
    JsonLinesAuditSink,
    ManualHandoff,
    TargetNotAllowed,
    apply_to_environ,
    export_lines,
    parse_challenge_requests,
    summarize,
)


def declaration() -> dict[str, object]:
    return {
        "target_url": "https://auth.example.test/register",
        "authorization_reference": "owner-approved-test",
        "challenges": [
            {
                "env_name": "EXAMPLE_WIDGET_TOKEN",
                "label": "第三方组件令牌",
                "kind": "official_widget",
                "hint": "从自己的浏览器会话里取",
            },
            {
                "env_name": "EXAMPLE_EMAIL_CODE",
                "label": "邮箱验证码",
                "kind": "email_otp",
            },
        ],
    }


def handoff(**changes: object) -> ManualHandoff:
    values: dict[str, object] = {
        "session_id": "session-1",
        "authorization_reference": "owner-approved-test",
        "target_url": "https://auth.example.test/register",
    }
    values.update(changes)
    policy = AuthorizationPolicy(("auth.example.test",))
    return ManualHandoff(policy, sleeper=lambda _seconds: None, **values)  # type: ignore[arg-type]


def answers(*responses: str):
    """Return a submit callable that answers in order and records what it was asked."""

    asked: list[ChallengeRequest] = []
    queue = list(responses)

    def submit(request: ChallengeRequest) -> str:
        asked.append(request)
        return queue.pop(0)

    submit.asked = asked  # type: ignore[attr-defined]
    return submit


class ParseChallengeRequestsTests(unittest.TestCase):
    def test_accepts_a_declaration_and_keeps_order(self) -> None:
        requests = parse_challenge_requests(declaration()["challenges"])
        self.assertEqual(
            ["EXAMPLE_WIDGET_TOKEN", "EXAMPLE_EMAIL_CODE"],
            [item.env_name for item in requests],
        )
        self.assertIs(ChallengeKind.OFFICIAL_WIDGET, requests[0].kind)
        self.assertIs(ChallengeKind.EMAIL_OTP, requests[1].kind)
        self.assertTrue(all(item.fresh_per_run for item in requests))
        self.assertEqual("从自己的浏览器会话里取", requests[0].hint)

    def test_unknown_kind_is_rejected_and_allowed_values_are_named(self) -> None:
        raw = [{"env_name": "X", "label": "x", "kind": "recaptcha_v3"}]
        with self.assertRaises(HandoffError) as caught:
            parse_challenge_requests(raw)
        self.assertIn("official_widget", str(caught.exception))

    def test_duplicate_slots_are_rejected(self) -> None:
        raw = [
            {"env_name": "X", "label": "one", "kind": "interactive"},
            {"env_name": "X", "label": "two", "kind": "interactive"},
        ]
        with self.assertRaises(HandoffError):
            parse_challenge_requests(raw)

    def test_missing_label_is_rejected(self) -> None:
        with self.assertRaises(HandoffError):
            parse_challenge_requests([{"env_name": "X", "kind": "interactive"}])

    def test_empty_or_non_list_declaration_is_rejected(self) -> None:
        for raw in ([], "not-a-list", {"env_name": "X"}, None):
            with self.assertRaises(HandoffError):
                parse_challenge_requests(raw)

    def test_fresh_per_run_can_be_declared_false(self) -> None:
        raw = [{"env_name": "X", "label": "x", "kind": "interactive", "fresh_per_run": False}]
        self.assertFalse(parse_challenge_requests(raw)[0].fresh_per_run)

    def test_request_requires_both_name_and_label(self) -> None:
        with self.assertRaises(ValueError):
            ChallengeRequest(env_name="  ", label="x", kind=ChallengeKind.INTERACTIVE)
        with self.assertRaises(ValueError):
            ChallengeRequest(env_name="X", label=" ", kind=ChallengeKind.INTERACTIVE)


class ManualHandoffTests(unittest.TestCase):
    def test_collect_returns_one_proof_per_declared_slot(self) -> None:
        requests = parse_challenge_requests(declaration()["challenges"])
        submit = answers("widget-proof", "123456")

        proofs = handoff().collect(requests, submit)

        self.assertEqual(
            {"EXAMPLE_WIDGET_TOKEN": "widget-proof", "EXAMPLE_EMAIL_CODE": "123456"},
            proofs,
        )
        self.assertEqual(
            ["EXAMPLE_WIDGET_TOKEN", "EXAMPLE_EMAIL_CODE"],
            [item.env_name for item in submit.asked],  # type: ignore[attr-defined]
        )

    def test_each_challenge_is_asked_with_its_own_kind(self) -> None:
        requests = parse_challenge_requests(declaration()["challenges"])
        submit = answers("a", "b")

        handoff().collect(requests, submit)

        self.assertIs(ChallengeKind.OFFICIAL_WIDGET, submit.asked[0].kind)  # type: ignore[attr-defined]
        self.assertIs(ChallengeKind.EMAIL_OTP, submit.asked[1].kind)  # type: ignore[attr-defined]

    def test_empty_response_aborts_and_skips_remaining_slots(self) -> None:
        requests = parse_challenge_requests(declaration()["challenges"])
        submit = answers("   ")

        with self.assertRaises(HandoffAborted):
            handoff().collect(requests, submit)

        self.assertEqual(1, len(submit.asked))  # type: ignore[attr-defined]

    def test_target_outside_the_allowlist_is_refused(self) -> None:
        requests = parse_challenge_requests(declaration()["challenges"])
        submit = answers("widget-proof", "123456")

        with self.assertRaises(TargetNotAllowed):
            handoff(target_url="https://auth.example.org/register").collect(requests, submit)

        self.assertEqual([], submit.asked)  # type: ignore[attr-defined]

    def test_per_request_target_url_overrides_the_default(self) -> None:
        requests = (
            ChallengeRequest(
                env_name="EXAMPLE_WIDGET_TOKEN",
                label="第三方组件令牌",
                kind=ChallengeKind.OFFICIAL_WIDGET,
                target_url="https://auth.example.test/login",
            ),
        )
        proofs = handoff().collect(requests, answers("widget-proof"))
        self.assertEqual({"EXAMPLE_WIDGET_TOKEN": "widget-proof"}, proofs)

    def test_handoff_requires_a_default_target(self) -> None:
        with self.assertRaises(HandoffError):
            handoff(target_url="   ")

    def test_describe_is_secret_free_and_marks_single_use(self) -> None:
        requests = parse_challenge_requests(declaration()["challenges"])
        rendered = "\n".join(handoff().describe(requests))
        self.assertIn("EXAMPLE_WIDGET_TOKEN", rendered)
        self.assertIn("每次运行都需新值", rendered)
        self.assertIn("从自己的浏览器会话里取", rendered)

    def test_audit_never_contains_a_collected_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            requests = parse_challenge_requests(declaration()["challenges"])

            handoff(audit_sink=JsonLinesAuditSink(path)).collect(
                requests, answers("never-write-this", "654321")
            )

            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("never-write-this", raw)
            self.assertNotIn("654321", raw)
            self.assertIn("official_widget", raw)
            for line in raw.splitlines():
                json.loads(line)


class SlotDeliveryTests(unittest.TestCase):
    def test_summarize_reports_lengths_without_values(self) -> None:
        requests = parse_challenge_requests(declaration()["challenges"])
        proofs = {"EXAMPLE_WIDGET_TOKEN": "widget-proof", "EXAMPLE_EMAIL_CODE": "123456"}

        outcomes = summarize(requests, proofs)

        self.assertEqual(["EXAMPLE_WIDGET_TOKEN", "EXAMPLE_EMAIL_CODE"], [o.env_name for o in outcomes])
        self.assertEqual([12, 6], [o.length for o in outcomes])
        self.assertIs(ChallengeKind.EMAIL_OTP, outcomes[1].kind)
        self.assertTrue(all(o.fresh_per_run for o in outcomes))

    def test_summarize_rejects_an_undeclared_slot(self) -> None:
        requests = parse_challenge_requests(declaration()["challenges"])
        with self.assertRaises(HandoffError):
            summarize(requests, {"SOMETHING_ELSE": "value"})

    def test_apply_to_environ_writes_every_slot(self) -> None:
        target: dict[str, str] = {}
        names = apply_to_environ({"A": "1", "B": "2"}, target)
        self.assertEqual(("A", "B"), names)
        self.assertEqual({"A": "1", "B": "2"}, target)

    def test_export_lines_quote_values_containing_quotes(self) -> None:
        lines = export_lines({"TOKEN": "plain", "QUOTED": "it's"})
        self.assertEqual("export TOKEN='plain'", lines[0])
        self.assertEqual('export QUOTED="it\'s"', lines[1])


if __name__ == "__main__":
    unittest.main()
