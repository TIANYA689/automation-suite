"""Declarative handoff from authorized manual challenges into named output slots.

The coordinator already binds, expires and consumes one challenge. What it does not
do is *know which* challenges a workflow needs. That knowledge otherwise lives in
prose — "remember to fetch a fresh token before each run" — which is exactly the kind
of instruction that gets silently skipped.

This module turns that prose into a declaration: each manual step names the slot it
fills, the kind of challenge it is, and whether its value survives a single call.
The declaration is data, so it can be reviewed, diffed and checked for coverage
against the workflow that consumes it.

Values collected here are returned once and never written to the audit sink.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Mapping, MutableMapping, Sequence

from .audit import AuditSink
from .coordinator import ChallengeCoordinator
from .models import ChallengeContext, ChallengeKind, ChallengeStatus
from .policy import AuthorizationPolicy
from .providers import ManualChallengeProvider

__all__ = [
    "ChallengeRequest",
    "HandoffAborted",
    "HandoffError",
    "HandoffOutcome",
    "ManualHandoff",
    "apply_to_environ",
    "export_lines",
    "parse_challenge_requests",
    "summarize",
]


class HandoffError(Exception):
    """Raised when a handoff declaration or run is inconsistent."""


class HandoffAborted(HandoffError):
    """Raised when the operator declines a challenge or returns nothing."""


@dataclass(frozen=True, slots=True)
class ChallengeRequest:
    """One declared manual step, identified by the output slot it fills.

    ``fresh_per_run`` is the field that carries the cost of a single-use challenge:
    a reCAPTCHA-style token expires in minutes and is bound to the session that
    produced it, so a workflow needing it three times needs it three times *fresh*.
    Recording that as data is what stops it from being discovered at runtime.
    """

    env_name: str
    label: str
    kind: ChallengeKind
    target_url: str = ""
    fresh_per_run: bool = True
    hint: str = ""

    def __post_init__(self) -> None:
        if not self.env_name.strip():
            raise ValueError("env_name must not be empty")
        if not self.label.strip():
            raise ValueError("label must not be empty")


@dataclass(frozen=True, slots=True)
class HandoffOutcome:
    """Proof-free summary of one collected slot, safe to print or log."""

    env_name: str
    label: str
    kind: ChallengeKind
    length: int
    fresh_per_run: bool


def parse_challenge_requests(raw: object) -> tuple[ChallengeRequest, ...]:
    """Build declarations from JSON-like data.

    An unknown ``kind`` is rejected rather than defaulted. A default here would
    decide, on the operator's behalf, what kind of challenge they are facing —
    and a wrong kind means a provider that looks like it works but does not.
    """

    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise HandoffError("challenges must be a list of objects")
    allowed = ", ".join(sorted(item.value for item in ChallengeKind))
    requests: list[ChallengeRequest] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise HandoffError(f"challenges[{index}] must be an object")
        env_name = str(item.get("env_name", "")).strip()
        if not env_name:
            raise HandoffError(f"challenges[{index}] is missing env_name")
        if env_name in seen:
            raise HandoffError(f"duplicate env_name: {env_name}")
        seen.add(env_name)
        raw_kind = str(item.get("kind", "")).strip()
        try:
            kind = ChallengeKind(raw_kind)
        except ValueError as exc:
            raise HandoffError(
                f"challenges[{index}] has unknown kind {raw_kind!r}; allowed: {allowed}"
            ) from exc
        label = str(item.get("label", "")).strip()
        if not label:
            raise HandoffError(f"challenges[{index}] ({env_name}) is missing label")
        requests.append(
            ChallengeRequest(
                env_name=env_name,
                label=label,
                kind=kind,
                target_url=str(item.get("target_url", "")).strip(),
                fresh_per_run=bool(item.get("fresh_per_run", True)),
                hint=str(item.get("hint", "")).strip(),
            )
        )
    if not requests:
        raise HandoffError("challenges must declare at least one step")
    return tuple(requests)


class ManualHandoff:
    """Collect authorized manual challenges into their declared slots, in order."""

    def __init__(
        self,
        policy: AuthorizationPolicy,
        *,
        session_id: str,
        authorization_reference: str,
        target_url: str,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
        audit_sink: AuditSink | None = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not target_url.strip():
            raise HandoffError("a default target_url is required")
        self._policy = policy
        self._session_id = session_id
        self._authorization_reference = authorization_reference
        self._target_url = target_url
        self._timeout = timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._audit = audit_sink
        self._clock = clock
        self._sleeper = sleeper

    def collect(
        self,
        requests: Sequence[ChallengeRequest],
        submit: Callable[[ChallengeRequest], str],
    ) -> dict[str, str]:
        """Run every declared challenge and return ``{slot: proof}`` once.

        ``submit`` is the human step: it receives the declaration and returns the
        response the operator completed in their own session. It is injected so the
        whole flow — policy, binding, expiry, one-time consumption — is testable
        without a browser and without a human.
        """

        provider = ManualChallengeProvider()
        coordinator = ChallengeCoordinator(
            [provider],
            self._policy,
            timeout_seconds=self._timeout,
            poll_interval_seconds=self._poll_interval,
            audit_sink=self._audit,
            clock=self._clock,
            sleeper=self._sleeper,
        )
        proofs: dict[str, str] = {}
        for request in requests:
            page = request.target_url or self._target_url
            context = ChallengeContext(
                session_id=self._session_id,
                target_url=page,
                kind=request.kind,
                authorized=True,
                authorization_reference=self._authorization_reference,
                metadata={"slot": request.env_name},
            )
            ticket = coordinator.start(context)
            response = submit(request)
            if not response.strip():
                coordinator.cancel(ticket.ticket_id)
                raise HandoffAborted(f"{request.env_name}: operator returned an empty response")
            provider.submit(ticket.ticket_id, response)
            settled = coordinator.wait(ticket.ticket_id)
            if settled.status is not ChallengeStatus.SOLVED:
                raise HandoffAborted(
                    f"{request.env_name}: challenge ended as {settled.status.value}"
                )
            proofs[request.env_name] = coordinator.consume(
                ticket.ticket_id,
                session_id=context.session_id,
                target_url=context.target_url,
            )
        return proofs

    def describe(self, requests: Sequence[ChallengeRequest]) -> tuple[str, ...]:
        """Return a secret-free run plan, suitable for ``--dry-run`` output."""

        lines: list[str] = []
        for request in requests:
            freshness = "每次运行都需新值" if request.fresh_per_run else "可跨运行复用"
            lines.append(
                f"{request.env_name}  <-  {request.label}  [{request.kind.value} · {freshness}]"
            )
            if request.hint:
                lines.append(f"    提示: {request.hint}")
        return tuple(lines)


def summarize(
    requests: Sequence[ChallengeRequest],
    proofs: Mapping[str, str],
) -> tuple[HandoffOutcome, ...]:
    """Describe collected slots by length only, so callers never print values."""

    declared = {request.env_name: request for request in requests}
    outcomes: list[HandoffOutcome] = []
    for env_name, value in proofs.items():
        request = declared.get(env_name)
        if request is None:
            raise HandoffError(f"collected a slot that was never declared: {env_name}")
        outcomes.append(
            HandoffOutcome(
                env_name=env_name,
                label=request.label,
                kind=request.kind,
                length=len(value),
                fresh_per_run=request.fresh_per_run,
            )
        )
    return tuple(outcomes)


def apply_to_environ(
    proofs: Mapping[str, str],
    environ: MutableMapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Write collected proofs into the process environment, returning the names set."""

    target: MutableMapping[str, str] = os.environ if environ is None else environ
    for name, value in proofs.items():
        target[name] = value
    return tuple(proofs)


def export_lines(proofs: Mapping[str, str]) -> tuple[str, ...]:
    """Render POSIX shell exports.

    The terminal is the delivery channel for a manual handoff, so the value does
    appear here. It must not appear in the audit sink, in a job record, or in any
    file that outlives the run.
    """

    return tuple(f"export {name}={value!r}" for name, value in proofs.items())
