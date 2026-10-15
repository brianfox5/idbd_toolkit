"""Autonomy modes for IDBD operations.

Autonomy is a property of each *operation*, not a global setting, and it varies
even within a phase: the parts that create or crunch lean autonomous, while the
parts that judge, frame, or update beliefs stay interactive. See the v1 default
table below; every default is overridable at call time so the whole thing stays
tunable as the toolkit matures.
"""

from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    """How much a given operation does on its own vs. defers to the researcher."""

    AUTO = "auto"  # human-on-the-loop: run, allow interruption, review after
    CHECKPOINT = "checkpoint"  # run, then pause for go/no-go at the boundary
    INTERACTIVE = "interactive"  # human-in-the-loop: iterative co-production


class Phase(str, Enum):
    """The six phases of the IDBD cycle (Figure 2 of the manuscript)."""

    DISRUPTION = "disruption"  # recognizing anomalies
    DOUBT = "doubt"  # confronting anomalies
    DESIGN = "design"  # framing anomalies
    DEVELOPMENT = "development"  # examining anomalies
    EXECUTION = "execution"  # resolving anomalies
    ENRICHMENT = "enrichment"  # re-habituating theory & practice


# Phase-level fallback when an operation has no explicit default.
_PHASE_DEFAULTS: dict[Phase, Mode] = {
    Phase.DISRUPTION: Mode.AUTO,
    Phase.DOUBT: Mode.INTERACTIVE,
    Phase.DESIGN: Mode.INTERACTIVE,
    Phase.DEVELOPMENT: Mode.AUTO,
    Phase.EXECUTION: Mode.AUTO,
    Phase.ENRICHMENT: Mode.AUTO,
}

# Operation-level defaults encode the within-phase splits from the design table.
# Keys are dotted operation ids: "<phase>.<operation>".
_OPERATION_DEFAULTS: dict[str, Mode] = {
    # intake.* records the raw researcher brief that starts the inquiry.
    "intake.received": Mode.AUTO,
    # baseline.* is the pre-cycle habituation step (establishing the initial
    # BAM + priors); not one of the six phases. Agent proposes, researcher approves.
    "baseline.establish": Mode.CHECKPOINT,
    # coherence.* is cross-cutting: declaring that two beliefs are logically
    # related is a researcher judgment; checking credences against it is mechanical.
    "coherence.couple": Mode.CHECKPOINT,
    "coherence.check": Mode.AUTO,
    "disruption.surface": Mode.AUTO,
    "disruption.triage": Mode.CHECKPOINT,
    "design.mobilize": Mode.AUTO,  # agent legwork: scan tools, gather frameworks/domain/data
    "design.frame": Mode.INTERACTIVE,
    "design.generate_hypotheses": Mode.AUTO,  # divergent idea bursts
    "development.build_prototype": Mode.AUTO,
    "development.review": Mode.CHECKPOINT,
    "execution.run": Mode.AUTO,
    "execution.reflect": Mode.INTERACTIVE,
    "execution.route": Mode.INTERACTIVE,
    "enrichment.validate": Mode.AUTO,
    "enrichment.update_bam": Mode.INTERACTIVE,  # belief update is judgment
    "enrichment.warrant": Mode.INTERACTIVE,
}


def phase_of(operation_id: str) -> Phase:
    """Return the Phase an operation id belongs to (raises on unknown phase)."""
    head = operation_id.split(".", 1)[0]
    return Phase(head)


def phase_label(operation_id: str) -> str:
    """Return a phase label for logging, tolerating non-phase ops like ``baseline``.

    Unlike :func:`phase_of`, this never raises: for an operation whose head is not
    one of the six phases (e.g. ``baseline.establish``) it returns the raw head.
    """
    return operation_id.split(".", 1)[0]


def resolve_mode(operation_id: str, override: Mode | None = None) -> Mode:
    """Resolve the autonomy mode for an operation.

    Precedence: explicit ``override`` > operation default > phase default.
    Interactive is the ultimate fallback (safest: ask the human).
    """
    if override is not None:
        return override
    if operation_id in _OPERATION_DEFAULTS:
        return _OPERATION_DEFAULTS[operation_id]
    try:
        return _PHASE_DEFAULTS[phase_of(operation_id)]
    except ValueError:
        return Mode.INTERACTIVE


def set_default(operation_id: str, mode: Mode) -> None:
    """Tune an operation's default mode in-process (keeps the table adjustable)."""
    _OPERATION_DEFAULTS[operation_id] = mode


def defaults_snapshot() -> dict[str, str]:
    """Return the current operation-level defaults (for inspection/logging)."""
    return {op: mode.value for op, mode in sorted(_OPERATION_DEFAULTS.items())}
