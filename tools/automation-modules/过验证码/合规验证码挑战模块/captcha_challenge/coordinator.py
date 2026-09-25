"""Challenge lifecycle coordinator with expiry, binding, and one-time use."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from threading import RLock
from typing import Callable, Iterable

from .audit import AuditEvent, AuditSink, NullAuditSink
from .errors import (
    AlreadyConsumed,
    BindingMismatch,
    CapacityExceeded,
    InvalidProviderResult,
    ProviderNotFound,
    TicketExpired,
    TicketNotFound,
    TicketNotReady,
)
from .models import ChallengeContext, ChallengeStatus, ChallengeTicket
from .policy import AuthorizationPolicy, audit_origin, normalized_binding_url
from .providers import ChallengeProvider


@dataclass(slots=True)
class _TicketState:
    context: ChallengeContext
    provider: ChallengeProvider
    ticket: ChallengeTicket
    binding_digest: str
    proof: str | None = None


class ChallengeCoordinator:
    """Coordinate approved providers while keeping proof values out of logs."""

    _TERMINAL = {
        ChallengeStatus.FAILED,
        ChallengeStatus.EXPIRED,
        ChallengeStatus.CONSUMED,
        ChallengeStatus.CANCELLED,
    }

    def __init__(
        self,
        providers: Iterable[ChallengeProvider],
        policy: AuthorizationPolicy,
        *,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
        max_active: int = 8,
        audit_sink: AuditSink | None = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if max_active <= 0:
            raise ValueError("max_active must be positive")
        self._providers = tuple(providers)
        self._policy = policy
        self._timeout = timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._max_active = max_active
        self._audit = audit_sink or NullAuditSink()
        self._clock = clock
        self._sleeper = sleeper
        self._tickets: dict[str, _TicketState] = {}
        self._lock = RLock()

    def start(self, context: ChallengeContext) -> ChallengeTicket:
        self._policy.validate(context)
        with self._lock:
            active = sum(
                state.ticket.status in {ChallengeStatus.WAITING, ChallengeStatus.SOLVED}
                for state in self._tickets.values()
            )
            if active >= self._max_active:
                raise CapacityExceeded(f"active challenge limit reached: {self._max_active}")

            provider = next((item for item in self._providers if item.supports(context)), None)
            if provider is None:
                raise ProviderNotFound(f"no provider supports challenge kind: {context.kind.value}")

            now = self._clock()
            ticket_id = uuid.uuid4().hex
            ticket = ChallengeTicket(
                ticket_id=ticket_id,
                provider=provider.name,
                kind=context.kind,
                status=ChallengeStatus.WAITING,
                created_at=now,
                expires_at=now + self._timeout,
                message="challenge started",
            )
            state = _TicketState(
                context=context,
                provider=provider,
                ticket=ticket,
                binding_digest=self._binding_digest(context.session_id, context.target_url),
            )
            provider.start(ticket_id, context, ticket.expires_at)
            self._tickets[ticket_id] = state
            self._record(state, "started")
            return ticket

    def refresh(self, ticket_id: str) -> ChallengeTicket:
        with self._lock:
            state = self._get(ticket_id)
            if state.ticket.status is not ChallengeStatus.WAITING:
                return state.ticket
            if self._clock() >= state.ticket.expires_at:
                state.provider.cancel(ticket_id)
                return self._transition(state, ChallengeStatus.EXPIRED, "challenge expired")

            result = state.provider.poll(ticket_id)
            if result.status is ChallengeStatus.WAITING:
                return state.ticket
            if result.status is ChallengeStatus.SOLVED:
                if not result.proof:
                    raise InvalidProviderResult("provider returned solved without a proof")
                state.proof = result.proof
                return self._transition(state, ChallengeStatus.SOLVED, "challenge solved")
            if result.status not in {ChallengeStatus.FAILED, ChallengeStatus.CANCELLED}:
                raise InvalidProviderResult(f"unsupported provider status: {result.status.value}")
            message = "provider failed" if result.status is ChallengeStatus.FAILED else "provider cancelled"
            return self._transition(state, result.status, message)

    def wait(self, ticket_id: str) -> ChallengeTicket:
        while True:
            ticket = self.refresh(ticket_id)
            if ticket.status is not ChallengeStatus.WAITING:
                return ticket
            remaining = max(0.0, ticket.expires_at - self._clock())
            self._sleeper(min(self._poll_interval, remaining))

    def consume(self, ticket_id: str, *, session_id: str, target_url: str) -> str:
        """Return a proof once, only to its original session and exact page URL."""

        with self._lock:
            state = self._get(ticket_id)
            if state.ticket.status is ChallengeStatus.CONSUMED:
                raise AlreadyConsumed(ticket_id)
            if self._clock() >= state.ticket.expires_at:
                state.proof = None
                state.provider.cancel(ticket_id)
                self._transition(state, ChallengeStatus.EXPIRED, "proof expired")
                raise TicketExpired(ticket_id)
            if state.ticket.status is not ChallengeStatus.SOLVED or state.proof is None:
                raise TicketNotReady(f"ticket is {state.ticket.status.value}")

            supplied = self._binding_digest(session_id, target_url)
            if not hmac.compare_digest(state.binding_digest, supplied):
                self._record(state, "binding_rejected", message="session or page binding mismatch")
                raise BindingMismatch("proof is bound to a different session or page")

            proof = state.proof
            state.proof = None
            state.provider.cancel(ticket_id)
            self._transition(state, ChallengeStatus.CONSUMED, "proof consumed once")
            return proof

    def cancel(self, ticket_id: str) -> ChallengeTicket:
        with self._lock:
            state = self._get(ticket_id)
            if state.ticket.status in self._TERMINAL:
                return state.ticket
            state.proof = None
            state.provider.cancel(ticket_id)
            return self._transition(state, ChallengeStatus.CANCELLED, "cancelled by caller")

    def get(self, ticket_id: str) -> ChallengeTicket:
        with self._lock:
            return self._get(ticket_id).ticket

    def _get(self, ticket_id: str) -> _TicketState:
        state = self._tickets.get(ticket_id)
        if state is None:
            raise TicketNotFound(ticket_id)
        return state

    def _transition(
        self,
        state: _TicketState,
        status: ChallengeStatus,
        message: str,
    ) -> ChallengeTicket:
        current = state.ticket
        state.ticket = ChallengeTicket(
            ticket_id=current.ticket_id,
            provider=current.provider,
            kind=current.kind,
            status=status,
            created_at=current.created_at,
            expires_at=current.expires_at,
            message=message,
        )
        self._record(state, "status_changed")
        return state.ticket

    def _record(self, state: _TicketState, event: str, message: str | None = None) -> None:
        ticket = state.ticket
        self._audit.record(
            AuditEvent(
                event=event,
                ticket_id=ticket.ticket_id,
                provider=ticket.provider,
                kind=ticket.kind,
                status=ticket.status,
                target_origin=audit_origin(state.context.target_url),
                occurred_at=self._clock(),
                message=ticket.message if message is None else message,
            )
        )

    @staticmethod
    def _binding_digest(session_id: str, target_url: str) -> str:
        material = f"{session_id}\0{normalized_binding_url(target_url)}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()
