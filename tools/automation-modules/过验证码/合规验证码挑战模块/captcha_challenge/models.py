"""Public data models used by challenge providers and the coordinator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ChallengeKind(str, Enum):
    """Challenge categories that can be handed to an approved provider."""

    IMAGE_TEXT = "image_text"
    EMAIL_OTP = "email_otp"
    SMS_OTP = "sms_otp"
    INTERACTIVE = "interactive"
    OFFICIAL_WIDGET = "official_widget"


class ChallengeStatus(str, Enum):
    """Lifecycle states visible to callers and audit sinks."""

    WAITING = "waiting"
    SOLVED = "solved"
    FAILED = "failed"
    EXPIRED = "expired"
    CONSUMED = "consumed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ChallengeContext:
    """Authorized context to which a challenge response is bound."""

    session_id: str = field(repr=False)
    target_url: str = field(repr=False)
    kind: ChallengeKind
    authorized: bool
    authorization_reference: str = field(repr=False)
    metadata: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if not self.authorization_reference.strip():
            raise ValueError("authorization_reference must not be empty")
        clean_metadata = {str(key): str(value) for key, value in self.metadata.items()}
        object.__setattr__(self, "metadata", MappingProxyType(clean_metadata))


@dataclass(frozen=True, slots=True)
class ChallengeTicket:
    """Secret-free snapshot returned to callers."""

    ticket_id: str
    provider: str
    kind: ChallengeKind
    status: ChallengeStatus
    created_at: float
    expires_at: float
    message: str = ""


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Result returned by a provider. Proof values must never be logged."""

    status: ChallengeStatus
    proof: str | None = field(default=None, repr=False)
    message: str = ""

    def __post_init__(self) -> None:
        if self.status is ChallengeStatus.SOLVED and not self.proof:
            raise ValueError("a solved provider result requires a proof")
        if self.status is not ChallengeStatus.SOLVED and self.proof is not None:
            raise ValueError("only solved provider results may include a proof")
