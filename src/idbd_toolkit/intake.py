"""Intake — the front door to the cycle.

An :class:`InquiryBrief` holds the three raw inputs a researcher provides to kick
off an inquiry: the domain and their current belief summary (with references),
plus — optionally — the anomaly that prompted the inquiry. It is deliberately *raw* — the agent later synthesizes it
into the structured baseline (BAM + priors) and disruption candidates. Recording
the brief keeps those raw inputs as provenance, so downstream artifacts can be
traced back to what the researcher actually said.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .context import InquiryContext
from .ids import new_id, now_iso


@dataclass
class InquiryBrief:
    domain: str
    belief_summary: str
    # What prompted the inquiry, if the researcher wants to record it. Optional:
    # in the IDBD order the baseline (the habit) comes before the surprise, so the
    # anomaly is formally entered in Disruption; this is provenance that seeds it.
    initiating_anomaly: str = ""
    references: list[str] = field(default_factory=list)  # citations
    # Source documents stored alongside the inquiry (e.g. PDFs uploaded in the
    # web client), by file name — distinct from the citations above.
    reference_files: list[str] = field(default_factory=list)
    researcher: str = ""
    id: str = field(default_factory=lambda: new_id("brf"))
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InquiryBrief":
        return cls(**data)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "InquiryBrief":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # -- markdown template ----------------------------------------------
    # Map normalized "## Heading" text -> field name.
    _HEADINGS = {
        "domain": "domain",
        "researcher": "researcher",
        "current belief summary": "belief_summary",
        "references": "references",
        "initiating anomaly": "initiating_anomaly",
        "what prompted this inquiry": "initiating_anomaly",
    }

    @classmethod
    def from_markdown(cls, text: str) -> "InquiryBrief":
        """Parse a filled-in brief template (sections split on ``## `` headings).

        The ``References`` section is read as a list (one per line, ``-``/``*``
        bullets stripped); other sections are read as free text.
        """
        sections: dict[str, list[str]] = {}
        current: str | None = None
        for line in text.splitlines():
            if line.startswith("## "):
                # "Initiating anomaly (optional)" -> "initiating anomaly"
                heading = re.sub(r"\s*\(.*\)\s*$", "", line[3:].strip().lower())
                current = cls._HEADINGS.get(heading)
                if current is not None:
                    sections[current] = []
            elif current is not None:
                sections[current].append(line)

        def _text(field_name: str) -> str:
            return "\n".join(sections.get(field_name, [])).strip()

        refs_block = _text("references")
        references = [
            ln.lstrip("-*").strip()
            for ln in refs_block.splitlines()
            if ln.strip() and not ln.strip().startswith("(")
        ]
        return cls(
            domain=_text("domain"),
            belief_summary=_text("belief_summary"),
            initiating_anomaly=_text("initiating_anomaly"),
            references=references,
            researcher=_text("researcher"),
        )

    @classmethod
    def from_markdown_file(cls, path: str | Path) -> "InquiryBrief":
        return cls.from_markdown(Path(path).read_text(encoding="utf-8"))


class Intake:
    def __init__(self, ctx: InquiryContext) -> None:
        self.ctx = ctx

    def record(self, brief: InquiryBrief, *, override=None) -> InquiryBrief:
        """Record the raw brief to the inquiry log as the inquiry's origin."""
        self.ctx.gate(
            "intake.received",
            f"intake for domain: {brief.domain}",
            override=override,
            payload={"brief": brief.to_dict()},
        )
        return brief
