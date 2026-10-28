"""Disruption phase — Stream 2: recognizing anomalies across five pathways.

The researcher's initial anomaly is one seed; searches along five pathways widen
the frame of candidate disruptions, each raising concern about the current BAM.
Per the toolkit's design, the *searches* run in the agent/client (which has web,
literature, and data tools); this phase structures the submitted candidates,
tags each by pathway, de-duplicates, records provenance, and drives triage.

Operations:
  * ``surface`` (AUTO) — intake candidate disruptions tagged by pathway.
  * ``triage``  (CHECKPOINT) — promote genuine ones to ledger Doubts.

The five pathways are the taxonomy from the manuscript's Figure 2. (Definitions
here are the working strawman confirmed with the author; refine against the
figure export.)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from ..autonomy import Mode, Phase
from ..dimensions import Dimension
from ..ids import new_id
from ..models import Doubt
from .base import PhaseModule


class Pathway(str, Enum):
    """Sources of disruption (Figure 2), each aligned to one Dimension."""

    NEW_WAYS_OF_DOING = "new_ways_of_doing"  # Methods: a new tool/technique makes new inquiry feasible
    PERCEIVED_GAPS = "perceived_gaps"  # Theories: a gap in existing theoretical frameworks
    UNSOLVED_PUZZLES = "unsolved_puzzles"  # Model: a puzzle the current best model cannot resolve
    UNEXPECTED_BEHAVIOR = "unexpected_behavior"  # Phenomenon: the phenomenon behaves contrary to expectation
    ANOMALOUS_OBSERVATIONS = "anomalous_observations"  # Data: observations contradicting stylized facts


# One-to-one mapping from Disruption pathway to the Dimension it challenges.
_PATHWAY_DIMENSION: dict[Pathway, Dimension] = {
    Pathway.NEW_WAYS_OF_DOING: Dimension.METHODS,
    Pathway.PERCEIVED_GAPS: Dimension.THEORIES,
    Pathway.UNSOLVED_PUZZLES: Dimension.MODEL,
    Pathway.UNEXPECTED_BEHAVIOR: Dimension.PHENOMENON,
    Pathway.ANOMALOUS_OBSERVATIONS: Dimension.DATA,
}


def dimension_of(pathway: Pathway | str) -> Dimension:
    """Return the Dimension a Disruption pathway challenges."""
    return _PATHWAY_DIMENSION[Pathway(pathway)]


@dataclass
class DisruptionCandidate:
    """A potential source of disruption surfaced during the Disruption phase.

    ``dimension`` is derived from ``pathway`` (which axis of the current
    understanding the disruption challenges) and set during intake.
    """

    description: str
    pathway: str
    source: str = ""  # where it came from (a search, the researcher, a dataset)
    dimension: str = ""  # derived from pathway
    status: str = "surfaced"  # surfaced | selected | dismissed
    id: str = field(default_factory=lambda: new_id("dsr"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coerce(candidate: DisruptionCandidate | dict[str, Any]) -> DisruptionCandidate:
    if isinstance(candidate, DisruptionCandidate):
        cand = candidate
    else:
        cand = DisruptionCandidate(**candidate)
    cand.dimension = dimension_of(cand.pathway).value  # validates pathway too
    return cand


class DisruptionPhase(PhaseModule):
    phase = Phase.DISRUPTION

    def surface(
        self,
        candidates: list[DisruptionCandidate | dict[str, Any]],
        *,
        seed_anomaly: str | None = None,
        seed_pathway: Pathway = Pathway.ANOMALOUS_OBSERVATIONS,
        seed_files: list[str] | None = None,
        override: Mode | None = None,
    ) -> list[DisruptionCandidate]:
        """Intake candidate disruptions (AUTO), each tagged by pathway.

        ``seed_anomaly`` is the researcher's initiating observation, added as a
        candidate (source ``"researcher_seed"``); ``seed_files`` names the project
        files that support it, recorded with the surfaced set so they travel with
        the inquiry (and stay out of the baseline). Candidates are de-duplicated by
        (description, pathway); the surfaced set — with a per-pathway count — is
        recorded to the inquiry log.
        """
        if not seed_anomaly and not candidates:
            raise ValueError("nothing to surface: give an initiating anomaly or at least one candidate")
        surfaced: list[DisruptionCandidate] = []
        if seed_anomaly:
            surfaced.append(
                _coerce(
                    DisruptionCandidate(
                        description=seed_anomaly,
                        pathway=Pathway(seed_pathway).value,
                        source="researcher_seed",
                    )
                )
            )
        surfaced.extend(_coerce(c) for c in candidates)

        # de-duplicate by (description, pathway), preserving order
        seen: set[tuple[str, str]] = set()
        deduped: list[DisruptionCandidate] = []
        for c in surfaced:
            key = (c.description.strip().lower(), c.pathway)
            if key not in seen:
                seen.add(key)
                deduped.append(c)

        by_pathway: dict[str, int] = {}
        by_dimension: dict[str, int] = {}
        for c in deduped:
            by_pathway[c.pathway] = by_pathway.get(c.pathway, 0) + 1
            by_dimension[c.dimension] = by_dimension.get(c.dimension, 0) + 1

        self.ctx.gate(
            self.operation_id("surface"),
            f"surfaced {len(deduped)} disruption candidate(s) across "
            f"{len(by_dimension)} dimension(s)",
            override=override,
            payload={
                "candidates": [c.to_dict() for c in deduped],
                "by_pathway": by_pathway,
                "by_dimension": by_dimension,
                "seed_files": list(seed_files or []),
            },
        )
        return deduped

    def triage(
        self,
        selected: list[DisruptionCandidate | dict[str, Any]],
        *,
        challenged_commitment_ids: list[str] | None = None,
        override: Mode | None = None,
    ) -> list[Doubt]:
        """Promote selected candidates to ledger Doubts (CHECKPOINT).

        Each becomes a Doubt whose description carries its pathway and which links
        to the prior commitment(s) it challenges — the "concern about the current
        BAM" that hands off to the Doubt phase. Returns [] if the checkpoint is
        declined.
        """
        chosen = [_coerce(c) for c in selected]
        result = self.ctx.gate(
            self.operation_id("triage"),
            f"triage: select {len(chosen)} disruption(s) as doubts",
            override=override,
            prompt=f"Promote {len(chosen)} disruption(s) to open doubts about the BAM?",
            payload={"selected": [c.to_dict() for c in chosen]},
        )
        if not result.approved:
            return []

        doubts: list[Doubt] = []
        for c in chosen:
            c.status = "selected"
            doubt = self.ctx.ledger.add_doubt(
                Doubt(
                    description=f"[{c.pathway}] {c.description}",
                    related_commitments=list(challenged_commitment_ids or []),
                )
            )
            doubts.append(doubt)
        return doubts
