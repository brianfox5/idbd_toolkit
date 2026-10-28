"""The Inquiry Log — append-only provenance of the inquiry path.

Because the IDBD cycle is recursive and non-linear, the log records which
operation ran, in which phase, under which autonomy mode, and against which
belief-ledger version. This is also the structural defense against HARKing:
hypotheses are logged when generated, before results exist, so the record shows
what was posited before what was found.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .ids import now_iso


@dataclass
class InquiryEvent:
    phase: str
    operation: str
    mode: str
    summary: str
    ledger_version: int
    timestamp: str = field(default_factory=now_iso)
    payload: dict[str, Any] = field(default_factory=dict)
    # The inputs the step was called with (what the researcher or agent entered),
    # kept so a completed step can be shown as it was submitted. None for events
    # recorded outside a tool call, or before inputs were kept.
    args: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d["args"] is None:
            del d["args"]  # older logs stay byte-for-byte the same shape
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InquiryEvent":
        return cls(**data)


class InquiryLog:
    """An append-only sequence of inquiry events."""

    def __init__(self) -> None:
        self._events: list[InquiryEvent] = []

    def append(self, event: InquiryEvent) -> InquiryEvent:
        self._events.append(event)
        return event

    def events(self) -> list[InquiryEvent]:
        return list(self._events)

    def by_phase(self, phase: str) -> list[InquiryEvent]:
        return [e for e in self._events if e.phase == phase]

    def __len__(self) -> int:
        return len(self._events)

    # -- persistence -----------------------------------------------------
    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events]

    @classmethod
    def from_list(cls, data: list[dict[str, Any]]) -> "InquiryLog":
        log = cls()
        log._events = [InquiryEvent.from_dict(e) for e in data]
        return log

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_list(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "InquiryLog":
        return cls.from_list(json.loads(Path(path).read_text(encoding="utf-8")))
