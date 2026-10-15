"""Doubt phase — confronting anomalies.

Doubt is the pivot from habit to inquiry: the surfaced disruptions ("concerns
about the current BAM", Figure 2) are confronted, the BAM is judged sufficient or
not, and the prior commitments the disruptions challenge are *weakened*. This is
the first phase that moves the belief state.

The weakening is a judgment (default INTERACTIVE), but it is routed through the
Bayesian machinery so it lands on the same credence trajectory as later
experimental evidence — recorded as an EvidenceUpdate whose source marks it
doubt-driven rather than experiment-driven. A disruption is, after all, an
observation that is more consistent with the commitment being wrong than right,
i.e. a Bayes factor below 1. Magnitudes let the researcher say *how much* a doubt
shakes a commitment without hand-computing odds.
"""

from __future__ import annotations

from typing import Any

from .. import bayes
from ..autonomy import Mode, Phase
from ..models import EvidenceUpdate
from .base import PhaseModule

# Qualitative weakening -> Bayes factor (<1). Researcher picks how hard the doubt bites.
_MAGNITUDE_BF: dict[str, float] = {
    "mild": 0.7,
    "moderate": 0.5,
    "strong": 0.33,
    "severe": 0.2,
}


class DoubtPhase(PhaseModule):
    phase = Phase.DOUBT

    def assess_bam(
        self,
        *,
        sufficient: bool,
        rationale: str = "",
        override: Mode | None = None,
    ) -> dict[str, Any]:
        """Record the judgment of whether the current BAM is still sufficient.

        This is the explicit "concerns about current BAM" determination that
        gates entry into inquiry. Judging it insufficient is what warrants
        weakening the challenged priors.
        """
        op = self.operation_id("assess")
        verdict = "sufficient" if sufficient else "INSUFFICIENT"
        self.ctx.gate(
            op,
            f"BAM judged {verdict}",
            override=override,
            payload={"bam_sufficient": sufficient, "rationale": rationale},
        )
        return {"bam_sufficient": sufficient, "rationale": rationale}

    def weaken(
        self,
        commitment_id: str,
        *,
        magnitude: str = "moderate",
        bayes_factor: float | None = None,
        target_strength: float | None = None,
        doubt_id: str | None = None,
        rationale: str = "",
        override: Mode | None = None,
    ) -> EvidenceUpdate:
        """Weaken a challenged prior commitment in light of a doubt.

        Specify the weakening as a qualitative ``magnitude`` (mild/moderate/
        strong/severe), an explicit ``bayes_factor`` (<1 to weaken), or a
        ``target_strength`` (the credence to move to). Precedence:
        bayes_factor > target_strength > magnitude. The change is applied via the
        ledger's Bayesian update, so it appears on the commitment's trajectory
        with ``source`` marking it doubt-driven.
        """
        commitment = self.ctx.ledger.get_commitment(commitment_id)
        if bayes_factor is not None:
            bf = bayes_factor
        elif target_strength is not None:
            bf = bayes.prob_to_odds(target_strength) / bayes.prob_to_odds(commitment.strength)
        else:
            if magnitude not in _MAGNITUDE_BF:
                raise ValueError(
                    f"unknown magnitude {magnitude!r}; use one of {list(_MAGNITUDE_BF)}"
                )
            bf = _MAGNITUDE_BF[magnitude]

        op = self.operation_id("weaken")
        self.ctx.gate(
            op,
            f"weaken (BF={bf:.3g}) {commitment.statement[:50]}",
            override=override,
            payload={
                "commitment_id": commitment_id,
                "bayes_factor": bf,
                "doubt_id": doubt_id,
            },
        )
        label = rationale or f"Doubt weakening ({magnitude})"
        return self.ctx.update_belief(
            commitment_id,
            bayes_factor=bf,
            description=f"Doubt: {label}",
            source=doubt_id or "doubt.weaken",
        )
