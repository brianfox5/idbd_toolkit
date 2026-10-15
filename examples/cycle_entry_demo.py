"""Cycle-entry demo: Stream 1 (baseline -> BAM) then Stream 2 (disruption).

Run:  uv run python examples/cycle_entry_demo.py
"""

from __future__ import annotations

import json

from idbd_toolkit import InquiryContext, ScriptedInteractor, build_registry


def main() -> None:
    # Two CHECKPOINT approvals: baseline.establish and disruption.triage.
    ctx = InquiryContext(interactor=ScriptedInteractor(confirmations=[True, True]))
    reg = build_registry(ctx)

    # --- STREAM 1: literature + researcher summary -> the initial BAM ---------
    reg.call("establish_baseline", {
        "bam_description": "Stronger incentives increase innovation via agency mechanisms",
        "literature_summary": "Synthesis of ~40 agency-theory and incentive studies",
        "researcher_summary": "My read: incentive intensity is the dominant lever",
        "commitments": [
            {"statement": "Stronger incentives increase innovation output",
             "strength": 0.8, "origin": "agent_estimated",
             "origin_note": "Estimated from literature synthesis"},
            {"statement": "Team-based pay raises coordination costs",
             "strength": 0.45, "origin": "researcher_set",
             "origin_note": "Researcher's stated prior"},
        ],
    })

    # --- STREAM 2: initial anomaly + five-pathway search results --------------
    surfaced = reg.call("disruption_surface", {
        "seed_anomaly": "A new team incentive paradoxically slowed innovation",
        "candidates": [
            {"description": "Causal ML now exposes crowding-out effects",
             "pathway": "new_ways_of_doing"},
            {"description": "No theory links team pay to innovation slowdown",
             "pathway": "perceived_gaps"},
            {"description": "Why do incentives sometimes backfire? (long-standing)",
             "pathway": "unsolved_puzzles"},
            {"description": "Top performers reduced idea submissions post-rollout",
             "pathway": "unexpected_behavior"},
            {"description": "Patent filings dropped 30% despite higher pay",
             "pathway": "anomalous_observations"},
        ],
    })
    print(f"Surfaced {len(surfaced)} candidates across dimensions:")
    for c in surfaced:
        print(f"  - {c['dimension']:<11} [{c['pathway']}] {c['description']}")

    # Researcher triages the most compelling into doubts about the BAM.
    cid = ctx.ledger.commitments[0].id
    doubts = reg.call("disruption_triage", {
        "selected": [surfaced[0], surfaced[4]],
        "challenged_commitment_ids": [cid],
    })
    print(f"\nPromoted {len(doubts)} to doubts about the BAM:")
    for d in doubts:
        print(f"  - {d['description']}")

    print("\n=== BAM (from Stream 1) ===")
    print(json.dumps(ctx.ledger.bam.to_dict(), indent=2))

    print("\n=== INQUIRY LOG (provenance) ===")
    for e in reg.call("get_inquiry_log", {}):
        print(f"  v{e['ledger_version']} [{e['mode']}] {e['operation']} — {e['summary']}")


if __name__ == "__main__":
    main()
