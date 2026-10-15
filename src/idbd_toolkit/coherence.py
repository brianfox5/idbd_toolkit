"""Coherence checks over coupled commitments.

Each prior commitment carries its own independent credence — beliefs are not
forced to compete for a shared probability mass. But some pairs of beliefs are
*logically* related, and probability theory then constrains what credences can
be held together without incoherence. A :class:`~.models.Coupling` declares such
a relation; this module checks the constraint:

* ``excludes``   — A and B cannot both be true:      P(A) + P(B) <= 1
* ``entails``    — A implies B (A is the stronger):   P(A) <= P(B)
* ``complements``— exactly one of A, B is true:        P(A) + P(B) == 1

Violations are *flagged, never auto-repaired*: which credence to revise is the
researcher's judgment (the evidence may bear more directly on one side). Each
violation carries the size of the gap and the bound each side would need to move
to, so the repair can be made deliberately — typically via a Bayesian update on
the side the evidence speaks to, or by re-examining whether the coupling holds.

Pure functions only; the ledger supplies commitments and couplings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .models import Coupling, PriorCommitment

RELATIONS = ("excludes", "entails", "complements")

# Slack before a gap counts as incoherent. Independent updates rarely land a
# complementary pair on exactly 1.0, so a small tolerance avoids noise.
DEFAULT_TOLERANCE = 0.02


@dataclass
class Violation:
    coupling_id: str
    relation: str
    a_id: str
    b_id: str
    a_strength: float
    b_strength: float
    gap: float  # how far outside the constraint the pair sits (> tolerance)
    constraint: str
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def message(self) -> str:
        return (
            f"caution: incoherent beliefs ({self.relation}) {self.a_id}="
            f"{self.a_strength:.2f}, {self.b_id}={self.b_strength:.2f} violate "
            f"{self.constraint} by {self.gap:.2f} — {self.suggestion}"
        )


def _check_one(
    coupling: Coupling, a: PriorCommitment, b: PriorCommitment, tolerance: float
) -> Violation | None:
    pa, pb = a.strength, b.strength
    if coupling.relation == "excludes":
        gap = pa + pb - 1.0
        constraint = "P(A)+P(B) <= 1"
        suggestion = (
            f"lower {a.id} to <= {1 - pb:.2f} or {b.id} to <= {1 - pa:.2f}, "
            "or revisit whether they truly exclude each other"
        )
    elif coupling.relation == "entails":
        gap = pa - pb
        constraint = "P(A) <= P(B)  (A entails B)"
        suggestion = (
            f"lower {a.id} to <= {pb:.2f} or raise {b.id} to >= {pa:.2f}, "
            "or revisit whether A really entails B"
        )
    elif coupling.relation == "complements":
        gap = abs(pa + pb - 1.0)
        constraint = "P(A)+P(B) = 1"
        suggestion = (
            f"set {a.id} to {1 - pb:.2f} or {b.id} to {1 - pa:.2f} "
            "(evidence on one is evidence against the other)"
        )
    else:  # pragma: no cover - guarded at construction
        raise ValueError(f"unknown relation {coupling.relation!r}")
    if gap <= tolerance:
        return None
    return Violation(
        coupling_id=coupling.id,
        relation=coupling.relation,
        a_id=a.id,
        b_id=b.id,
        a_strength=pa,
        b_strength=pb,
        gap=gap,
        constraint=constraint,
        suggestion=suggestion,
    )


def check(
    commitments: Iterable[PriorCommitment],
    couplings: Iterable[Coupling],
    *,
    involving: Iterable[str] | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[Violation]:
    """Return the couplings whose credences are currently incoherent.

    ``involving`` restricts the check to couplings touching those commitment ids
    (e.g. just the belief that was updated). Couplings referencing a missing
    commitment are skipped.
    """
    by_id = {c.id: c for c in commitments}
    focus = set(involving) if involving is not None else None
    violations = []
    for cp in couplings:
        if focus is not None and not ({cp.a_id, cp.b_id} & focus):
            continue
        a, b = by_id.get(cp.a_id), by_id.get(cp.b_id)
        if a is None or b is None:
            continue
        v = _check_one(cp, a, b, tolerance)
        if v is not None:
            violations.append(v)
    return violations
