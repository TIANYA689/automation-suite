"""Secret-free audit event sinks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol

from .models import ChallengeKind, ChallengeStatus


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event: str
    ticket_id: str
    provider: str
    kind: ChallengeKind
    status: ChallengeStatus
    target_origin: str
    occurred_at: float
    message: str = ""


class AuditSink(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Persist one event without challenge proof data."""


class NullAuditSink:
    def record(self, event: AuditEvent) -> None:
        del event


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []
        self._lock = Lock()

    def record(self, event: AuditEvent) -> None:
        with self._lock:
            self.events.append(event)


class JsonLinesAuditSink:
    """Append JSON Lines events; challenge proofs are absent by construction."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def record(self, event: AuditEvent) -> None:
        payload = asdict(event)
        payload["kind"] = event.kind.value
        payload["status"] = event.status.value
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

