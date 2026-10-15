"""Base contract for the six IDBD phase modules.

Phase 0 defines only the contract; the phase logic (starting with the Design
vertical slice) lands in later work. Every phase is constructed with an
:class:`InquiryContext` and exposes named operations; the ``operation_id`` helper
keeps ids consistent with the autonomy registry (``"<phase>.<operation>"``).
"""

from __future__ import annotations

from typing import ClassVar

from ..autonomy import Phase
from ..context import InquiryContext


class PhaseModule:
    """Common base for the six phases.

    Subclasses set ``phase`` and implement operations that call ``self.ctx.gate``
    to enforce autonomy and record provenance before doing their work.
    """

    phase: ClassVar[Phase]

    def __init__(self, ctx: InquiryContext) -> None:
        self.ctx = ctx

    def operation_id(self, operation: str) -> str:
        """Return the dotted id (e.g. ``design.frame``) for an operation name."""
        return f"{self.phase.value}.{operation}"

    def require_working_model(self):
        """Return the ledger's working model or raise if none has been built yet."""
        model = self.ctx.ledger.working_model
        if model is None:
            raise RuntimeError("no working model; build the prototype in Development first")
        return model
