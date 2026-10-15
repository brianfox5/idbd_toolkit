"""IDBD toolkit — a UI-agnostic core for the Inquiry-Driven Big Data process.

Phase 0 (this release) is the backbone: the belief ledger, the inquiry log, the
autonomy scaffold, the interaction seam, and the phase contract. The six phase
modules and the agent-tool wrappers build on top of these.
"""

from .autonomy import Mode, Phase, resolve_mode, set_default
from .context import GateResult, InquiryContext
from .inquiry_log import InquiryEvent, InquiryLog
from .interaction import (
    AutoInteractor,
    DeferredInteractor,
    InputRequired,
    Interactor,
    ScriptedInteractor,
)
from .baseline import Baseline
from .dimensions import Dimension
from .intake import Intake, InquiryBrief
from .orchestrator import InquiryOrchestrator
from .progress import cycle_progress
from .ledger import BeliefLedger, BeliefSnapshot
from .coherence import Violation
from .models import Coupling, Doubt, EvidenceUpdate, Model, PriorCommitment
from .phases import (
    DesignPhase,
    DevelopmentPhase,
    DisruptionCandidate,
    DisruptionPhase,
    DoubtPhase,
    EnrichmentPhase,
    ExecutionPhase,
    MobilizedResource,
    Pathway,
    ProblemFrame,
    WorkingHypothesis,
    dimension_of,
)
from .tools import Tool, ToolRegistry, build_registry

__version__ = "0.1.0"

__all__ = [
    "Mode",
    "Phase",
    "resolve_mode",
    "set_default",
    "InquiryContext",
    "GateResult",
    "InquiryLog",
    "InquiryEvent",
    "Interactor",
    "AutoInteractor",
    "ScriptedInteractor",
    "DeferredInteractor",
    "InputRequired",
    "cycle_progress",
    "BeliefLedger",
    "BeliefSnapshot",
    "PriorCommitment",
    "Doubt",
    "Model",
    "EvidenceUpdate",
    "Coupling",
    "Violation",
    "DesignPhase",
    "MobilizedResource",
    "ProblemFrame",
    "WorkingHypothesis",
    "DisruptionPhase",
    "DisruptionCandidate",
    "DoubtPhase",
    "DevelopmentPhase",
    "ExecutionPhase",
    "EnrichmentPhase",
    "Pathway",
    "Dimension",
    "dimension_of",
    "Baseline",
    "Intake",
    "InquiryBrief",
    "InquiryOrchestrator",
    "Tool",
    "ToolRegistry",
    "build_registry",
]
