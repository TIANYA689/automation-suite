from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from captcha_challenge import (
    AlreadyConsumed,
    AuthorizationPolicy,
    AuthorizationRequired,
    BindingMismatch,
    CapacityExceeded,
    ChallengeContext,
    ChallengeCoordinator,
    ChallengeKind,
    ChallengeStatus,
    JsonLinesAuditSink,
    ManualChallengeProvider,
    TargetNotAllowed,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def context(**changes: object) -> ChallengeContext:
    values: dict[str, object] = {
        "session_id": "session-1",
        "target_url": "https://auth.example.test/challenge?id=123",
        "kind": ChallengeKind.INTERACTIVE,
        "authorized": True,
        "authorization_reference": "owner-approved-test",
    }
    values.update(changes)
    return ChallengeContext(**values)  # type: ignore[arg-type]


class AuthorizationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = AuthorizationPolicy(("auth.example.test", "*.sandbox.example.test"))

    def test_requires_explicit_authorization(self) -> None:
        with self.assertRaises(AuthorizationRequired):
            self.policy.validate(context(authorized=False))

    def test_rejects_hosts_outside_allowlist(self) -> None:
        with self.assertRaises(TargetNotAllowed):
            self.policy.validate(context(target_url="https://example.org/challenge"))

    def test_rejects_userinfo_and_invalid_ports(self) -> None:
        with self.assertRaises(TargetNotAllowed):
            self.policy.validate(context(target_url="https://user:pass@auth.example.test/challenge"))
        with self.assertRaises(TargetNotAllowed):
            self.policy.validate(context(target_url="https://auth.example.test:not-a-port/challenge"))

    def test_wildcard_matches_subdomain_only(self) -> None:
        self.policy.validate(context(target_url="https://a.sandbox.example.test/challenge"))
        with self.assertRaises(TargetNotAllowed):
            self.policy.validate(context(target_url="https://sandbox.example.test/challenge"))

    def test_context_repr_hides_sensitive_fields(self) -> None:
        request = context(metadata={"cookie": "secret-cookie"})
        rendered = repr(request)
        self.assertNotIn("session-1", rendered)
        self.assertNotIn("id=123", rendered)
        self.assertNotIn("owner-approved-test", rendered)
        self.assertNotIn("secret-cookie", rendered)


class ChallengeCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.provider = ManualChallengeProvider()
        self.coordinator = ChallengeCoordinator(
            [self.provider],
            AuthorizationPolicy(("auth.example.test",)),
            timeout_seconds=30,
            poll_interval_seconds=1,
            clock=self.clock,
        )

    def test_manual_proof_is_bound_and_consumed_once(self) -> None:
        request = context()
        ticket = self.coordinator.start(request)
        self.provider.submit(ticket.ticket_id, "secret-proof-value")
        solved = self.coordinator.refresh(ticket.ticket_id)
        self.assertEqual(ChallengeStatus.SOLVED, solved.status)

        with self.assertRaises(BindingMismatch):
            self.coordinator.consume(
                ticket.ticket_id,
                session_id="another-session",
                target_url=request.target_url,
            )
        with self.assertRaises(BindingMismatch):
            self.coordinator.consume(
                ticket.ticket_id,
                session_id=request.session_id,
                target_url=request.target_url + "#different-state",
            )

        proof = self.coordinator.consume(
            ticket.ticket_id,
            session_id=request.session_id,
            target_url=request.target_url,
        )
        self.assertEqual("secret-proof-value", proof)
        with self.assertRaises(AlreadyConsumed):
            self.coordinator.consume(
                ticket.ticket_id,
                session_id=request.session_id,
                target_url=request.target_url,
            )

    def test_ticket_expires_and_provider_state_is_cleared(self) -> None:
        ticket = self.coordinator.start(context())
        self.clock.now += 31
        refreshed = self.coordinator.refresh(ticket.ticket_id)
        self.assertEqual(ChallengeStatus.EXPIRED, refreshed.status)

    def test_active_capacity_is_enforced(self) -> None:
        limited = ChallengeCoordinator(
            [self.provider],
            AuthorizationPolicy(("auth.example.test",)),
            max_active=1,
            clock=self.clock,
        )
        limited.start(context())
        with self.assertRaises(CapacityExceeded):
            limited.start(context(session_id="session-2"))

    def test_solved_unconsumed_ticket_still_uses_capacity(self) -> None:
        limited = ChallengeCoordinator(
            [self.provider],
            AuthorizationPolicy(("auth.example.test",)),
            max_active=1,
            clock=self.clock,
        )
        ticket = limited.start(context())
        self.provider.submit(ticket.ticket_id, "pending-consumption")
        limited.refresh(ticket.ticket_id)
        with self.assertRaises(CapacityExceeded):
            limited.start(context(session_id="session-2"))

    def test_json_audit_never_contains_proof_or_query(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            provider = ManualChallengeProvider()
            coordinator = ChallengeCoordinator(
                [provider],
                AuthorizationPolicy(("auth.example.test",)),
                audit_sink=JsonLinesAuditSink(path),
                clock=self.clock,
            )
            request = context()
            ticket = coordinator.start(request)
            provider.submit(ticket.ticket_id, "never-write-this-secret")
            coordinator.refresh(ticket.ticket_id)

            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("never-write-this-secret", raw)
            self.assertNotIn("id=123", raw)
            for line in raw.splitlines():
                json.loads(line)


if __name__ == "__main__":
    unittest.main()
