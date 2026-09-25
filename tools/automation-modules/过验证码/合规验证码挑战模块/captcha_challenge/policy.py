"""Authorization and target allowlist policy."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from .errors import AuthorizationRequired, TargetNotAllowed
from .models import ChallengeContext


@dataclass(frozen=True, slots=True)
class AuthorizationPolicy:
    """Require explicit authorization and an exact or wildcard host allowlist."""

    allowed_hosts: tuple[str, ...]
    allow_http_localhost: bool = True

    def __post_init__(self) -> None:
        normalized = tuple(item.strip().lower().rstrip(".") for item in self.allowed_hosts)
        if not normalized or any(not item for item in normalized):
            raise ValueError("allowed_hosts must contain at least one non-empty host")
        object.__setattr__(self, "allowed_hosts", normalized)

    def validate(self, context: ChallengeContext) -> None:
        if not context.authorized:
            raise AuthorizationRequired("explicit target authorization is required")

        parsed = urlsplit(context.target_url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not host:
            raise TargetNotAllowed("target_url must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise TargetNotAllowed("target_url must not contain userinfo")
        try:
            parsed.port
        except ValueError as exc:
            raise TargetNotAllowed("target_url contains an invalid port") from exc

        is_local = host in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (self.allow_http_localhost and is_local):
            raise TargetNotAllowed("HTTPS is required for non-local targets")
        if not any(self._host_matches(host, rule) for rule in self.allowed_hosts):
            raise TargetNotAllowed(f"target host is not allowlisted: {host}")

    @staticmethod
    def _host_matches(host: str, rule: str) -> bool:
        if rule.startswith("*."):
            suffix = rule[2:]
            return host.endswith(f".{suffix}") and host != suffix
        return host == rule


def normalized_binding_url(target_url: str) -> str:
    """Normalize a page URL for binding without exposing it to audit output."""

    parsed = urlsplit(target_url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    netloc = host if port is None or default_port else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, parsed.fragment))


def audit_origin(target_url: str) -> str:
    """Return a query-free origin suitable for logs and audit files."""

    parsed = urlsplit(target_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    default_port = (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80)
    netloc = host if port is None or default_port else f"{host}:{port}"
    return f"{parsed.scheme.lower()}://{netloc}"
