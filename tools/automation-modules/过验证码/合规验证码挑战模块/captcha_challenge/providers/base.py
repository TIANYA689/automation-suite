"""Provider contract for approved challenge workflows."""

from __future__ import annotations

from typing import Protocol

from ..models import ChallengeContext, ProviderResult


class ChallengeProvider(Protocol):
    name: str

    def supports(self, context: ChallengeContext) -> bool:
        """Return whether this provider supports the context."""

    def start(self, ticket_id: str, context: ChallengeContext, expires_at: float) -> None:
        """Start a challenge without returning or logging proof data."""

    def poll(self, ticket_id: str) -> ProviderResult:
        """Return the current provider state."""

    def cancel(self, ticket_id: str) -> None:
        """Cancel and clear provider-side state."""

