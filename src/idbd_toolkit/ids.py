"""Centralized id and timestamp generation.

Kept in one place so tests can inject deterministic clocks/counters and so the
future web app shares the same identity scheme as the agent toolkit.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Callable

_counter = itertools.count(1)

# Overridable seams (tests can monkeypatch these).
now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Return a short, monotonic, human-readable id like ``cmt-1``."""
    return f"{prefix}-{next(_counter)}"


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return now_fn().isoformat()
