"""Domain errors for challenge coordination."""


class ChallengeError(Exception):
    """Base error for the package."""


class AuthorizationRequired(ChallengeError):
    """Raised when explicit target authorization is missing."""


class TargetNotAllowed(ChallengeError):
    """Raised when a target is outside the configured allowlist."""


class ProviderNotFound(ChallengeError):
    """Raised when no provider supports a challenge kind."""


class CapacityExceeded(ChallengeError):
    """Raised when the active challenge limit has been reached."""


class TicketNotFound(ChallengeError):
    """Raised when a ticket does not exist."""


class TicketNotReady(ChallengeError):
    """Raised when a proof is requested before it is ready."""


class TicketExpired(ChallengeError):
    """Raised when a ticket or proof has expired."""


class BindingMismatch(ChallengeError):
    """Raised when a proof is consumed from a different session or page."""


class AlreadyConsumed(ChallengeError):
    """Raised when a one-time proof is requested more than once."""


class InvalidProviderResult(ChallengeError):
    """Raised when a provider returns an invalid result."""

