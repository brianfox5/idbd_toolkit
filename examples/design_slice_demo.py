"""End-to-end demo of the Design vertical slice, driven through the tool layer.

Simulates an agent session: seed a prior commitment and a doubt, frame the
problem (with a scripted 'researcher' refinement standing in for INTERACTIVE
input), generate multiple working hypotheses (AUTO), and print the resulting
belief state and inquiry-log provenance.

Run:  uv run python examples/design_slice_demo.py
"""

from __future__ import annotations

import json

from idbd_toolkit import InquiryContext, ScriptedInteractor, build_registry


def main() -> None:
    # In a real agent run, the interactor relays to the human; here it is scripted.
    ctx = InquiryContext(
        interactor=ScriptedInteractor(
            answers=["Why does the new team-based incentive slow product innovation?"]
        )
    )
    reg = build_registry(ctx)

    commitment = reg.call(
        "add_commitment",
        {"statement": "Stronger incentives increase innovation output", "strength": 0.8,
         "rationale": "Standard agency-theoretic prior"},
    )
    reg.call(
        "add_doubt",
        {"description": "A new incentive structure paradoxically slowed innovation"},
    )
    reg.call("commit_beliefs", {"note": "initial priors and disruption"})

    reg.call(
        "design_frame",
        {
            "proposed_statement": "Something about the incentive change hurt innovation",
            "data_picture": "Panel of team output, incentive rollout dates, patent filings",
            "mobilized_knowledge": ["agency theory", "self-determination theory"],
        },
    )
    reg.call(
        "design_generate_hypotheses",
        {
            "hypotheses": [
                {"statement": "Incentives crowded out intrinsic motivation",
                 "rationale": "Self-determination theory"},
                {"statement": "Team incentives raised free-riding",
                 "rationale": "Collective-action / social loafing"},
                {"statement": "Short horizons shifted effort to safe, incremental work",
                 "rationale": "Risk aversion under measurable targets"},
            ]
        },
    )

    # --- Bayesian belief updating as experiments are performed --------------
    # Each experiment supplies evidence bearing on the prior commitment. The
    # first is a Bayes factor; the second is given as likelihoods P(E|H), P(E|~H).
    cid = commitment["id"]
    reg.call("update_belief", {
        "commitment_id": cid, "bayes_factor": 0.2,
        "description": "Exp 1: innovation dropped after rollout", "source": "execution.run",
    })
    reg.call("update_belief", {
        "commitment_id": cid,
        "likelihood_given_hypothesis": 0.25, "likelihood_given_not_hypothesis": 0.7,
        "description": "Exp 2: replicated in a second business unit", "source": "enrichment.validate",
    })

    print("=== BELIEF STATE ===")
    print(json.dumps(reg.call("get_belief_state", {}), indent=2))

    print("\n=== BELIEF TRAJECTORY (commitment cmt-1) ===")
    for p in reg.call("get_belief_trajectory", {"commitment_id": cid}):
        bf = f"  (BF={p['bayes_factor']:.3g})" if p.get("bayes_factor") is not None else ""
        print(f"  P(H)={p['probability']:.4f}  {p['label']}{bf}")

    print("\n=== INQUIRY LOG (provenance) ===")
    for e in reg.call("get_inquiry_log", {}):
        print(f"  v{e['ledger_version']} [{e['mode']}] {e['operation']} — {e['summary']}")


if __name__ == "__main__":
    main()
