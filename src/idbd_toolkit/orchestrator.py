"""Multi-cycle orchestrator — closing the recursion (Enrichment -> Disruption).

The IDBD cycle is recursive: the warranted end-state of one turn becomes the
habit the next anomaly disrupts. This orchestrator performs that *rehabituation*
between cycles — it does not run the phases (the agent/web client does), it only
carries state across the loop boundary:

  * the production model promoted by Enrichment's IBE is now the established BAM
    (the habit), and the updated + warranted commitments are the next cycle's
    priors — both already in the ledger, so they carry over untouched;
  * the working model is cleared, so the next cycle's Development builds a fresh
    prototype rather than inheriting the last one;
  * the cycle counter advances and the boundary is snapshotted and logged.

A commitment's ``updates`` trajectory already spans cycles, so belief evolution is
inspectable across the whole recursion.
"""

from __future__ import annotations

from typing import Any

from .autonomy import Mode
from .context import InquiryContext


class InquiryOrchestrator:
    def __init__(self, ctx: InquiryContext) -> None:
        self.ctx = ctx

    @property
    def cycle(self) -> int:
        return self.ctx.ledger.cycle

    def advance(self, *, note: str = "") -> dict[str, Any]:
        """Close the current cycle and rehabituate into the next.

        Requires a BAM (Enrichment's ``update_bam`` / IBE must have run). Snapshots
        the boundary, clears the working model, advances the cycle counter, and
        logs the transition. Returns a summary of the completed and next cycle.
        """
        bam = self.ctx.ledger.bam
        if bam is None:
            raise RuntimeError(
                "cannot advance: no BAM — run Enrichment's update_bam (IBE) first")

        completed = self.ctx.ledger.cycle
        snapshot = self.ctx.ledger.commit(
            note or f"cycle {completed} complete; rehabituated to new BAM")

        # rehabituation: the production model is now the habit; start the next
        # cycle's prototype from scratch.
        self.ctx.ledger.working_model = None
        self.ctx.ledger.cycle = completed + 1

        self.ctx.record(
            "orchestrator.rehabituate",
            Mode.AUTO,
            f"cycle {completed} -> {self.ctx.ledger.cycle}: new BAM is the habit",
            {"completed_cycle": completed, "next_cycle": self.ctx.ledger.cycle,
             "bam_id": bam.id, "snapshot_version": snapshot.version},
        )
        return {
            "completed_cycle": completed,
            "next_cycle": self.ctx.ledger.cycle,
            "bam": bam.description,
            "carried_commitments": len(self.ctx.ledger.commitments),
            "open_doubts": len(self.ctx.ledger.open_doubts()),
            "snapshot_version": snapshot.version,
        }

    def lineage(self) -> list[dict[str, Any]]:
        """The sequence of cycle-boundary snapshots across the whole recursion."""
        return [
            {"version": s.version, "note": s.note, "timestamp": s.timestamp,
             "bam": (s.bam or {}).get("description") if s.bam else None}
            for s in self.ctx.ledger.history()
            if "rehabituated" in s.note or "complete" in s.note
        ]

    def summary(self) -> dict[str, Any]:
        ledger = self.ctx.ledger
        return {
            "cycle": ledger.cycle,
            "bam": ledger.bam.description if ledger.bam else None,
            "working_model": ledger.working_model.status if ledger.working_model else None,
            "commitments": len(ledger.commitments),
            "open_doubts": len(ledger.open_doubts()),
            "lineage": self.lineage(),
        }
