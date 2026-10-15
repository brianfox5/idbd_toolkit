"""Execution phase — resolving anomalies by fitting the production model.

Execution completes the inquiry by constructing the production model and treating
its performance not as an end but as a mechanism for refining beliefs — a
"conversation with the situation" (Schon, 1992). A fitted result is ingested as
*experimental evidence*: each piece carries a Bayes factor that updates a
commitment's credence via the ledger. This is the first belief movement driven by
an experiment rather than by doubt. The reflective tail (reflect/route) decides
whether to converge or loop back to Design/Development.
"""

from __future__ import annotations

from typing import Any

from ..autonomy import Mode, Phase
from .base import PhaseModule


class ExecutionPhase(PhaseModule):
    phase = Phase.EXECUTION

    def record_fit(
        self,
        *,
        metrics: dict[str, Any],
        evidence: list[dict[str, Any]] | None = None,
        traits: dict[str, Any] | None = None,
        override: Mode | None = None,
    ) -> dict[str, Any]:
        """Record the production-model fit and apply its experimental evidence.

        Promotes the working model to ``production``, attaches metrics and the
        calibrated/consistent/credible ``traits``, then for each evidence item
        ``{commitment_id, bayes_factor, rationale}`` updates that commitment's
        credence via the ledger (source ``execution.run``). AUTO.
        """
        model = self.require_working_model()
        model.status = "production"
        model.metrics = {**(model.metrics or {}), **(metrics or {})}
        if traits:
            model.spec["traits"] = traits

        self.ctx.gate(
            self.operation_id("run"),
            f"fit production model; applying {len(evidence or [])} evidence update(s)",
            override=override,
            payload={"metrics": metrics, "traits": traits},
        )
        updates = []
        for ev in evidence or []:
            u = self.ctx.ledger.update_belief(
                ev["commitment_id"],
                bayes_factor=ev["bayes_factor"],
                description=f"Execution: {ev.get('rationale', '')}",
                source="execution.run",
            )
            updates.append(u.to_dict())
        # Check coupled beliefs once, after the whole batch: an intermediate state
        # can look incoherent until the evidence on the other side lands.
        violations = self.ctx.check_coherence(
            [ev["commitment_id"] for ev in evidence or []], trigger="execution.run"
        ) if evidence else []
        return {"model": model.to_dict(), "updates": updates,
                "incoherent": [v.to_dict() for v in violations]}

    def reflect(self, assessment: str, *, override: Mode | None = None) -> dict[str, Any]:
        """Record the 'conversation with the situation' (INTERACTIVE).

        Do the findings support, contradict, or refine the model? This judgment
        is the researcher's.
        """
        self.ctx.gate(
            self.operation_id("reflect"),
            f"reflect: {assessment[:60]}",
            override=override,
            payload={"assessment": assessment},
        )
        return {"assessment": assessment}

    def route(
        self, decision: str, *, rationale: str = "", override: Mode | None = None
    ) -> dict[str, Any]:
        """Record the next-step decision (INTERACTIVE).

        ``decision`` is typically one of ``converge`` / ``refine_hypotheses``
        (return to Design) / ``new_prototype`` (return to Development).
        """
        self.ctx.gate(
            self.operation_id("route"),
            f"route: {decision}",
            override=override,
            payload={"decision": decision, "rationale": rationale},
        )
        return {"decision": decision, "rationale": rationale}
