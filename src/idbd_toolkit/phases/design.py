"""Design phase — framing anomalies (the first implemented phase).

Design is where the indeterminate situation becomes a tractable problem. The
manuscript describes two intertwined activities:

  * **problem framing** — using big-data affordances, turn the vague "something
    is not right" into a framed problem amenable to analysis. This is judgment
    work, so it defaults to INTERACTIVE (co-produced with the researcher).
  * **hypothesis generation** — an abductive, creative leap to *multiple*
    working hypotheses (Chamberlin, 1965), not formal test hypotheses. This is
    divergent idea-generation, so it defaults to AUTO (idea bursts).

Following the toolkit's design, this module does not itself invent content: the
agent (or the researcher, via the interactor) proposes framings and hypotheses;
the phase structures them, enforces autonomy through ``ctx.gate``, applies the
process guardrails (multiple working hypotheses), and records everything to the
inquiry log — logging hypotheses *when posited*, before any results, which is
the anti-HARKing guarantee.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..autonomy import Mode, Phase
from ..dimensions import Dimension
from ..ids import new_id
from .base import PhaseModule

# The four dimensions Design mobilizes (Figure 2). Model is excluded: it is the
# convergent prototype produced downstream in Development, not a resource gathered here.
_DESIGN_ROLE: dict[Dimension, str] = {
    Dimension.METHODS: "available tool for inquiry",
    Dimension.THEORIES: "extant theoretical framework",
    Dimension.PHENOMENON: "relevant domain knowledge",
    Dimension.DATA: "measurable aspect of domain",
}


@dataclass
class MobilizedResource:
    """A resource gathered during Design, tagged by the dimension it serves.

    ``role`` (e.g. "available tool for inquiry") is derived from ``dimension``.
    """

    dimension: str
    description: str
    role: str = ""  # derived from dimension
    source: str = ""
    id: str = field(default_factory=lambda: new_id("res"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProblemFrame:
    """A data-informed framing of the disruption as a workable problem."""

    statement: str
    data_picture: str = ""
    mobilized_knowledge: list[str] = field(default_factory=list)
    doubt_ids: list[str] = field(default_factory=list)
    accepted: bool = True
    id: str = field(default_factory=lambda: new_id("frm"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkingHypothesis:
    """A plausible, guiding explanation for the disruption (abductive, tentative)."""

    statement: str
    rationale: str = ""
    status: str = "working"
    id: str = field(default_factory=lambda: new_id("hyp"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DesignPhase(PhaseModule):
    phase = Phase.DESIGN

    def mobilize(
        self,
        resources: list[MobilizedResource | dict[str, Any]] | None = None,
        *,
        seeds: dict[str, list[str]] | None = None,
        prompting_doubt_ids: list[str] | None = None,
        override: Mode | None = None,
    ) -> list[MobilizedResource]:
        """Gather resources across the four Design dimensions (AUTO legwork).

        The search is *anchored to the codified doubts*: by default the open
        doubts in the ledger are recorded as what prompted this mobilization
        (override with ``prompting_doubt_ids``). This is the bridge from Doubt —
        the doubt is the prompt that drives both researcher and agent search, and
        Design may legitimately range into a different literature than the baseline.

        ``seeds`` are the researcher's own starting points per dimension
        (``{"theories": ["upper-echelons theory", ...], ...}``), tagged
        ``researcher_seed``; items in ``resources`` are tagged ``agent_search``
        unless they already carry a ``source``. Each resource is tagged
        Methods/Theories/Phenomenon/Data and given a derived role; the Model
        dimension raises (it is the convergent prototype built in Development).
        """
        prompted_by = (
            prompting_doubt_ids
            if prompting_doubt_ids is not None
            else [d.id for d in self.ctx.ledger.open_doubts()]
        )

        items: list[MobilizedResource] = []
        # researcher-provided starting points, per dimension
        for dim_label, descriptions in (seeds or {}).items():
            for description in descriptions:
                items.append(
                    MobilizedResource(
                        dimension=dim_label, description=description, source="researcher_seed"
                    )
                )
        # agent-found resources
        for r in resources or []:
            res = r if isinstance(r, MobilizedResource) else MobilizedResource(**r)
            res.source = res.source or "agent_search"
            items.append(res)

        for res in items:
            dim = Dimension(res.dimension)  # validates the dimension label
            if dim not in _DESIGN_ROLE:
                raise ValueError(
                    f"Design mobilizes {[d.value for d in _DESIGN_ROLE]}; "
                    f"'{dim.value}' is the convergent prototype (Development), not a Design input"
                )
            res.role = _DESIGN_ROLE[dim]

        by_dimension: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for res in items:
            by_dimension[res.dimension] = by_dimension.get(res.dimension, 0) + 1
            by_source[res.source] = by_source.get(res.source, 0) + 1

        self.ctx.gate(
            self.operation_id("mobilize"),
            f"mobilized {len(items)} resource(s) across {len(by_dimension)} dimension(s), "
            f"prompted by {len(prompted_by)} doubt(s)",
            override=override,
            payload={
                "resources": [res.to_dict() for res in items],
                "by_dimension": by_dimension,
                "by_source": by_source,
                "prompted_by": prompted_by,
            },
        )
        return items

    def frame(
        self,
        proposed_statement: str,
        *,
        data_picture: str = "",
        mobilized_knowledge: list[str] | None = None,
        override: Mode | None = None,
    ) -> ProblemFrame:
        """Frame the disruption as a workable problem.

        Reads the ledger's open doubts as context. Under INTERACTIVE (default),
        the researcher may refine the proposed statement via the interactor; a
        non-empty reply replaces it. The framing is recorded to the inquiry log.
        """
        op = self.operation_id("frame")
        mode = self.ctx.resolve_mode(op, override)
        open_doubts = self.ctx.ledger.open_doubts()

        statement = proposed_statement
        if mode is Mode.INTERACTIVE:
            reply = self.ctx.interactor.ask(
                "Refine the problem framing (leave blank to accept as-is).\n"
                f"Proposed: {proposed_statement!r}\n"
                f"Open doubts: {[d.description for d in open_doubts]}",
                context={"proposed_statement": proposed_statement},
            )
            if reply.strip():
                statement = reply.strip()

        frame = ProblemFrame(
            statement=statement,
            data_picture=data_picture,
            mobilized_knowledge=list(mobilized_knowledge or []),
            doubt_ids=[d.id for d in open_doubts],
        )
        result = self.ctx.gate(
            op,
            f"framed problem: {statement}",
            override=override,
            prompt=f"Accept this problem framing?\n  {statement!r}",
            payload={"frame": frame.to_dict()},
        )
        frame.accepted = result.approved
        return frame

    def generate_hypotheses(
        self,
        candidates: list[WorkingHypothesis | dict[str, Any]],
        *,
        frame: ProblemFrame | None = None,
        override: Mode | None = None,
    ) -> list[WorkingHypothesis]:
        """Record a set of abductive working hypotheses for the framed problem.

        Applies the method-of-multiple-working-hypotheses guardrail: fewer than
        two draws a logged caution against premature fixation. Hypotheses are
        recorded to the inquiry log at generation time (before any results).
        """
        op = self.operation_id("generate_hypotheses")
        hypotheses = [
            c if isinstance(c, WorkingHypothesis) else WorkingHypothesis(**c)
            for c in candidates
        ]
        multiple = len(hypotheses) >= 2
        self.ctx.gate(
            op,
            f"generated {len(hypotheses)} working hypotheses",
            override=override,
            payload={
                "hypotheses": [h.to_dict() for h in hypotheses],
                "frame_id": frame.id if frame else None,
                "multiple_working_hypotheses": multiple,
            },
        )
        if not multiple:
            self.ctx.interactor.notify(
                "Caution: fewer than two working hypotheses. The method of "
                "multiple working hypotheses guards against premature fixation "
                "(Chamberlin, 1965)."
            )
        return hypotheses
