"""InquiryContext — the object every phase operation runs against.

It bundles the four backbone concerns (belief ledger, inquiry log, autonomy
resolution, and the interaction seam) so a phase never wires them up itself.
``gate`` is the single place autonomy is enforced: it resolves an operation's
mode, drives the CHECKPOINT confirmation when needed, and records the operation
to the inquiry log — so provenance is automatic rather than something each phase
has to remember.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import autonomy
from .autonomy import Mode
from .coherence import Violation
from .inquiry_log import InquiryEvent, InquiryLog
from .interaction import AutoInteractor, Interactor
from .ledger import BeliefLedger
from .models import Coupling, EvidenceUpdate


@dataclass
class GateResult:
    """Outcome of gating an operation through its autonomy mode."""

    operation: str
    mode: Mode
    approved: bool


class InquiryContext:
    def __init__(
        self,
        ledger: BeliefLedger | None = None,
        log: InquiryLog | None = None,
        interactor: Interactor | None = None,
    ) -> None:
        self.ledger = ledger or BeliefLedger()
        self.log = log or InquiryLog()
        self.interactor: Interactor = interactor or AutoInteractor()
        # Inputs of the tool call in progress, stamped on the events it records.
        self.call_args: dict[str, Any] | None = None

    def resolve_mode(self, operation_id: str, override: Mode | None = None) -> Mode:
        return autonomy.resolve_mode(operation_id, override)

    def record(
        self,
        operation_id: str,
        mode: Mode,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> InquiryEvent:
        """Append an event to the inquiry log, stamped with the ledger version."""
        event = InquiryEvent(
            phase=autonomy.phase_label(operation_id),
            operation=operation_id,
            mode=mode.value,
            summary=summary,
            ledger_version=self.ledger.version,
            payload=payload or {},
            args=self.call_args,
        )
        return self.log.append(event)

    def gate(
        self,
        operation_id: str,
        summary: str,
        *,
        override: Mode | None = None,
        prompt: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> GateResult:
        """Resolve an operation's mode, enforce a CHECKPOINT if any, and log it.

        Returns a :class:`GateResult`; ``approved`` is False only when a
        CHECKPOINT confirmation is declined. AUTO notifies and proceeds;
        INTERACTIVE proceeds (the phase itself drives the dialog via
        ``interactor.ask``).
        """
        mode = self.resolve_mode(operation_id, override)
        approved = True
        if mode is Mode.CHECKPOINT:
            approved = self.interactor.confirm(
                prompt or f"Proceed with {operation_id}? ({summary})",
                context=payload,
            )
        elif mode is Mode.AUTO:
            self.interactor.notify(f"[{operation_id}] {summary}")
        self.record(
            operation_id,
            mode,
            summary,
            {**(payload or {}), "approved": approved},
        )
        return GateResult(operation=operation_id, mode=mode, approved=approved)

    # -- coherence -------------------------------------------------------
    def check_coherence(
        self, involving: list[str] | None = None, *, trigger: str = ""
    ) -> list[Violation]:
        """Flag coupled beliefs whose credences have become incoherent.

        Never repairs: each violation is surfaced as a caution notification and
        logged (``coherence.check``) so the researcher decides which side to
        revise. Silent when everything is coherent.
        """
        violations = self.ledger.coherence(involving)
        if violations:
            for v in violations:
                self.interactor.notify(v.message())
            self.record(
                "coherence.check",
                self.resolve_mode("coherence.check"),
                f"{len(violations)} incoherent coupling(s)"
                + (f" after {trigger}" if trigger else ""),
                {"trigger": trigger, "violations": [v.to_dict() for v in violations]},
            )
        return violations

    def couple(
        self,
        a_id: str,
        b_id: str,
        relation: str,
        *,
        rationale: str = "",
        override: Mode | None = None,
    ) -> dict[str, Any]:
        """Declare that two commitments are logically related (CHECKPOINT).

        Asserting a coupling is a researcher judgment about what the beliefs
        mean, so it is gated. Once declared, the pair is checked immediately —
        the declaration can expose incoherence that already exists.
        """
        coupling = Coupling(a_id, b_id, relation, rationale=rationale)
        a = self.ledger.get_commitment(a_id)
        b = self.ledger.get_commitment(b_id)
        result = self.gate(
            "coherence.couple",
            f"couple ({relation}): {a.statement[:40]} / {b.statement[:40]}",
            override=override,
            prompt=(
                f"Declare these beliefs coupled ({relation})?\n"
                f"  A: {a.statement!r}\n  B: {b.statement!r}"
            ),
            payload={"coupling": coupling.to_dict()},
        )
        if not result.approved:
            return {"approved": False, "coupling": None, "incoherent": []}
        self.ledger.add_coupling(coupling)
        violations = self.check_coherence([a_id, b_id], trigger="coherence.couple")
        return {
            "approved": True,
            "coupling": coupling.to_dict(),
            "incoherent": [v.to_dict() for v in violations],
        }

    def update_belief(self, commitment_id: str, **kwargs: Any) -> EvidenceUpdate:
        """Bayesian-update a commitment, then check its couplings for coherence.

        The update itself is unchanged (beliefs stay on their own scales); any
        incoherence with coupled beliefs is flagged, not propagated.
        """
        update = self.ledger.update_belief(commitment_id, **kwargs)
        self.check_coherence([commitment_id], trigger=kwargs.get("source") or "update_belief")
        return update
