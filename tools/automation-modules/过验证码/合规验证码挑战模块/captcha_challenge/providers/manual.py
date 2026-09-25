"""Thread-safe human handoff provider."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from ..errors import TicketNotFound
from ..models import ChallengeContext, ChallengeKind, ChallengeStatus, ProviderResult


@dataclass(slots=True)
class _ManualState:
    proof: str | None = None
    cancelled: bool = False


class ManualChallengeProvider:
    """Accept a response completed by the authorized user in the same workflow."""

    name = "manual"

    def __init__(self, supported_kinds: set[ChallengeKind] | None = None) -> None:
        self._supported_kinds = set(ChallengeKind) if supported_kinds is None else set(supported_kinds)
        self._states: dict[str, _ManualState] = {}
        self._lock = Lock()

    def supports(self, context: ChallengeContext) -> bool:
        return context.kind in self._supported_kinds

    def start(self, ticket_id: str, context: ChallengeContext, expires_at: float) -> None:
        del context, expires_at
        with self._lock:
            self._states[ticket_id] = _ManualState()

    def submit(self, ticket_id: str, proof: str) -> None:
        """Submit a user-completed response. The value is never logged."""

        clean_proof = proof.strip()
        if not clean_proof:
            raise ValueError("proof must not be empty")
        with self._lock:
            state = self._states.get(ticket_id)
            if state is None:
                raise TicketNotFound(ticket_id)
            if state.cancelled:
                raise TicketNotFound(ticket_id)
            state.proof = clean_proof

    def poll(self, ticket_id: str) -> ProviderResult:
        with self._lock:
            state = self._states.get(ticket_id)
            if state is None:
                return ProviderResult(ChallengeStatus.FAILED, message="manual ticket not found")
            if state.cancelled:
                return ProviderResult(ChallengeStatus.CANCELLED, message="manual ticket cancelled")
            if state.proof is None:
                return ProviderResult(ChallengeStatus.WAITING, message="waiting for user completion")
            proof = state.proof
            state.proof = None
            return ProviderResult(ChallengeStatus.SOLVED, proof=proof, message="user completed")

    def cancel(self, ticket_id: str) -> None:
        with self._lock:
            state = self._states.pop(ticket_id, None)
            if state is not None:
                state.proof = None
                state.cancelled = True
