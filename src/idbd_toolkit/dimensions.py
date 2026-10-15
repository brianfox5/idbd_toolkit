"""The five dimensions that structure every phase of the IDBD cycle.

In Figure 2 the framework is drawn as five horizontal swimlanes. Each phase's
activities are organized by these dimensions, and the Disruption pathways map
one-to-one onto them: a disruption always challenges the current understanding
along one of these axes. Making Dimension a first-class concept lets every phase
(Disruption pathways, Design mobilization, Development inputs, Enrichment
outputs) be tagged consistently.
"""

from __future__ import annotations

from enum import Enum


class Dimension(str, Enum):
    METHODS = "methods"  # how the phenomenon is studied (tools/techniques)
    THEORIES = "theories"  # the conceptual frameworks brought to bear
    MODEL = "model"  # the current best explanation / prototype
    PHENOMENON = "phenomenon"  # the real-world behavior under study
    DATA = "data"  # the empirical observations
