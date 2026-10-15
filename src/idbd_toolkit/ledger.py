"""The BAM / Belief Ledger — the spine of the IDBD toolkit.

Everything in IDBD is belief updating, so the ledger is versioned: mutations
change the *working* state, and ``commit`` snapshots it into an append-only
history. That history is both the record of how beliefs evolved and the seam a
future web app reads to render the cycle. Persistence is plain JSON so the
ledger never lives only in an agent's conversation memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import bayes, coherence
from .ids import now_iso
from .models import Coupling, Doubt, EvidenceUpdate, Model, PriorCommitment


@dataclass
class BeliefSnapshot:
    """An immutable point-in-time capture of the belief state."""

    version: int
    note: str
    timestamp: str
    bam: dict[str, Any] | None
    commitments: list[dict[str, Any]]
    doubts: list[dict[str, Any]]
    couplings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "note": self.note,
            "timestamp": self.timestamp,
            "bam": self.bam,
            "commitments": self.commitments,
            "doubts": self.doubts,
            "couplings": self.couplings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BeliefSnapshot":
        return cls(**data)


class BeliefLedger:
    """Mutable working belief state plus an append-only snapshot history."""

    def __init__(self) -> None:
        self.commitments: list[PriorCommitment] = []
        self.doubts: list[Doubt] = []
        # Declared logical relations between commitments (coherence constraints;
        # the credences themselves stay independent).
        self.couplings: list[Coupling] = []
        self.bam: Model | None = None
        # The model currently under construction/testing (Development -> Execution),
        # distinct from the established BAM. Enrichment's IBE promotes it to the BAM.
        self.working_model: Model | None = None
        # Which turn of the recursive cycle this belief state is on (the orchestrator
        # advances it as Enrichment's end-state rehabituates into the next baseline).
        self.cycle: int = 1
        self._history: list[BeliefSnapshot] = []

    # -- commitments -----------------------------------------------------
    def add_commitment(self, commitment: PriorCommitment) -> PriorCommitment:
        self.commitments.append(commitment)
        return commitment

    def get_commitment(self, commitment_id: str) -> PriorCommitment:
        for c in self.commitments:
            if c.id == commitment_id:
                return c
        raise KeyError(f"no commitment with id {commitment_id!r}")

    def adjust_strength(self, commitment_id: str, strength: float) -> PriorCommitment:
        """Directly set a commitment's credence (e.g. Doubt weakening a prior).

        This is a manual override that does *not* record an evidence trail. For
        evidence-driven revision, use :meth:`update_belief`.
        """
        commitment = self.get_commitment(commitment_id)
        commitment.strength = max(0.0, min(1.0, float(strength)))
        return commitment

    def update_belief(
        self,
        commitment_id: str,
        *,
        bayes_factor: float | None = None,
        likelihood_given_hypothesis: float | None = None,
        likelihood_given_not_hypothesis: float | None = None,
        description: str = "",
        source: str = "",
    ) -> EvidenceUpdate:
        """Bayesian-update a commitment's credence from a piece of evidence.

        Supply either ``bayes_factor`` directly, or the pair of likelihoods
        ``P(E|H)`` and ``P(E|not H)`` from which the Bayes factor is computed.
        Returns the :class:`EvidenceUpdate` appended to the commitment's
        trajectory; the commitment's ``strength`` is set to the posterior.
        """
        have_bf = bayes_factor is not None
        have_likelihoods = (
            likelihood_given_hypothesis is not None
            and likelihood_given_not_hypothesis is not None
        )
        if have_bf == have_likelihoods:
            raise ValueError(
                "provide exactly one of bayes_factor or the likelihood pair"
            )
        if have_likelihoods:
            bayes_factor = bayes.bayes_factor_from_likelihoods(
                likelihood_given_hypothesis, likelihood_given_not_hypothesis
            )

        commitment = self.get_commitment(commitment_id)
        prior = commitment.strength
        posterior = bayes.update_probability(prior, bayes_factor)
        update = EvidenceUpdate(
            prior=prior,
            posterior=posterior,
            bayes_factor=bayes_factor,
            description=description,
            source=source,
        )
        commitment.strength = posterior
        commitment.updates.append(update)
        return update

    def belief_trajectory(self, commitment_id: str) -> list[dict[str, Any]]:
        """Return the credence path for a commitment: the initial prior followed
        by the posterior after each evidence update (for plotting/inspection)."""
        commitment = self.get_commitment(commitment_id)
        if not commitment.updates:
            return [{"label": "prior", "probability": commitment.strength, "timestamp": None}]
        points = [
            {
                "label": "prior",
                "probability": commitment.updates[0].prior,
                "timestamp": None,
            }
        ]
        for u in commitment.updates:
            points.append(
                {
                    "label": u.description or u.source or u.id,
                    "probability": u.posterior,
                    "bayes_factor": u.bayes_factor,
                    "timestamp": u.timestamp,
                }
            )
        return points

    # -- couplings -------------------------------------------------------
    def add_coupling(self, coupling: Coupling) -> Coupling:
        """Declare a logical relation between two existing commitments."""
        self.get_commitment(coupling.a_id)
        self.get_commitment(coupling.b_id)
        self.couplings.append(coupling)
        return coupling

    def remove_coupling(self, coupling_id: str) -> Coupling:
        for i, cp in enumerate(self.couplings):
            if cp.id == coupling_id:
                return self.couplings.pop(i)
        raise KeyError(f"no coupling with id {coupling_id!r}")

    def couplings_for(self, commitment_id: str) -> list[Coupling]:
        return [cp for cp in self.couplings if commitment_id in (cp.a_id, cp.b_id)]

    def coherence(
        self,
        involving: list[str] | None = None,
        tolerance: float = coherence.DEFAULT_TOLERANCE,
    ) -> list[coherence.Violation]:
        """Return coupled pairs whose current credences are incoherent."""
        return coherence.check(
            self.commitments, self.couplings, involving=involving, tolerance=tolerance
        )

    # -- doubts ----------------------------------------------------------
    def add_doubt(self, doubt: Doubt) -> Doubt:
        self.doubts.append(doubt)
        return doubt

    def resolve_doubt(self, doubt_id: str) -> Doubt:
        for d in self.doubts:
            if d.id == doubt_id:
                d.status = "resolved"
                return d
        raise KeyError(f"no doubt with id {doubt_id!r}")

    def open_doubts(self) -> list[Doubt]:
        return [d for d in self.doubts if d.status == "open"]

    # -- best achievable model ------------------------------------------
    def set_bam(self, model: Model) -> Model:
        """Promote a model to the Best Achievable Model (used by Enrichment/IBE)."""
        model.status = "bam"
        self.bam = model
        return model

    def set_working_model(self, model: Model) -> Model:
        """Set the model currently under construction/testing (Development/Execution)."""
        self.working_model = model
        return model

    # -- versioning ------------------------------------------------------
    def commit(self, note: str) -> BeliefSnapshot:
        """Snapshot the current working state into history and return it."""
        snapshot = BeliefSnapshot(
            version=len(self._history) + 1,
            note=note,
            timestamp=now_iso(),
            bam=self.bam.to_dict() if self.bam else None,
            commitments=[c.to_dict() for c in self.commitments],
            doubts=[d.to_dict() for d in self.doubts],
            couplings=[cp.to_dict() for cp in self.couplings],
        )
        self._history.append(snapshot)
        return snapshot

    @property
    def version(self) -> int:
        """Version of the last commit (0 if nothing committed yet)."""
        return self._history[-1].version if self._history else 0

    def history(self) -> list[BeliefSnapshot]:
        return list(self._history)

    # -- persistence -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "commitments": [c.to_dict() for c in self.commitments],
            "doubts": [d.to_dict() for d in self.doubts],
            "couplings": [cp.to_dict() for cp in self.couplings],
            "bam": self.bam.to_dict() if self.bam else None,
            "working_model": self.working_model.to_dict() if self.working_model else None,
            "cycle": self.cycle,
            "history": [s.to_dict() for s in self._history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BeliefLedger":
        ledger = cls()
        ledger.commitments = [PriorCommitment.from_dict(c) for c in data.get("commitments", [])]
        ledger.doubts = [Doubt.from_dict(d) for d in data.get("doubts", [])]
        ledger.couplings = [Coupling.from_dict(c) for c in data.get("couplings", [])]
        bam = data.get("bam")
        ledger.bam = Model.from_dict(bam) if bam else None
        working = data.get("working_model")
        ledger.working_model = Model.from_dict(working) if working else None
        ledger.cycle = data.get("cycle", 1)
        ledger._history = [BeliefSnapshot.from_dict(s) for s in data.get("history", [])]
        return ledger

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "BeliefLedger":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
