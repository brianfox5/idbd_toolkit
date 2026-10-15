"""Domain model for the IDBD belief state.

These are the nouns the whole toolkit revolves around: the researcher's prior
theoretical commitments (whose *strength* rises and falls across the cycle), the
open doubts/anomalies driving inquiry, and the model that is the current Best
Achievable Model (BAM). All are plain, serializable dataclasses so the ledger
can snapshot and persist them without any UI or LLM assumptions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .ids import new_id, now_iso


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass
class EvidenceUpdate:
    """One Bayesian revision of a commitment's credence from a piece of evidence."""

    prior: float
    posterior: float
    bayes_factor: float
    description: str = ""
    source: str = ""  # e.g. the experiment / execution operation that produced E
    timestamp: str = field(default_factory=now_iso)
    id: str = field(default_factory=lambda: new_id("ev"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PriorCommitment:
    """A theoretical assumption the researcher holds, as a Bayesian credence.

    ``strength`` in [0, 1] is the current credence P(H): Doubt weakens it, and
    evidence revises it via :class:`EvidenceUpdate` records (see
    ``BeliefLedger.update_belief``). ``updates`` is the ordered belief trajectory
    — how this commitment's credence moved as experiments were performed.

    ``origin`` records how the *initial* credence was set — ``"agent_estimated"``
    (a model's estimate from the literature synthesis, to be treated tentatively)
    or ``"researcher_set"`` (a researcher override/assertion) — with an
    ``origin_note`` explaining the basis. This keeps the baseline transparent
    about which priors are machine guesses versus human judgments.
    """

    statement: str
    strength: float = 0.5
    rationale: str = ""
    origin: str = "researcher_set"  # agent_estimated | researcher_set
    origin_note: str = ""
    updates: list[EvidenceUpdate] = field(default_factory=list)
    id: str = field(default_factory=lambda: new_id("cmt"))

    def __post_init__(self) -> None:
        self.strength = _clamp01(self.strength)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PriorCommitment":
        data = dict(data)
        updates = [EvidenceUpdate(**u) for u in data.pop("updates", [])]
        obj = cls(**data)
        obj.updates = updates
        return obj


@dataclass
class Coupling:
    """A declared logical relation between two prior commitments.

    Commitments keep independent credences; a coupling does not make them
    compete, it states what coherence requires of them together (see
    :mod:`~.coherence`). ``relation`` is one of ``excludes`` (not both true),
    ``entails`` (``a`` implies ``b``), or ``complements`` (exactly one true).
    """

    a_id: str
    b_id: str
    relation: str
    rationale: str = ""
    id: str = field(default_factory=lambda: new_id("cpl"))

    def __post_init__(self) -> None:
        if self.relation not in ("excludes", "entails", "complements"):
            raise ValueError(
                f"unknown relation {self.relation!r}; "
                "use excludes, entails, or complements"
            )
        if self.a_id == self.b_id:
            raise ValueError("a commitment cannot be coupled to itself")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Coupling":
        return cls(**data)


@dataclass
class Doubt:
    """An open question or anomaly that inquiry aims to resolve."""

    description: str
    status: str = "open"  # open | resolved
    related_commitments: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: new_id("dbt"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Doubt":
        return cls(**data)


@dataclass
class Model:
    """A representation of the phenomenon under study.

    ``status`` tracks its place in the cycle: a Development ``prototype`` becomes
    an Execution ``production`` model, which Enrichment may promote to ``bam``
    (the new Best Achievable Model) via inference to the best explanation.
    """

    description: str
    spec: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    status: str = "prototype"  # prototype | production | bam
    id: str = field(default_factory=lambda: new_id("mdl"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Model":
        return cls(**data)
