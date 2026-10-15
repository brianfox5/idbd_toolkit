"""Front-end trace on a real inquiry: TMT diversity -> firm performance.

Kicked off from Brian Fox's filled inquiry brief; baseline grounded in four cited
papers (Fox/Simsek/Heavey 2022, Ferrier 2001, Ferrier & Lyon 2004, Crossland
et al. 2014). Claude acts as the agent: it synthesizes the BAM, estimates the
priors (flagged agent_estimated for researcher override), surfaces disruptions
across the five dimensions, triages them into doubts, and frames + hypothesizes.

Run:  uv run python examples/tmt_diversity_run.py
"""

from __future__ import annotations

import json
from pathlib import Path

from idbd_toolkit import InquiryContext, ScriptedInteractor, build_registry

# Scripted stand-ins for the human touchpoints:
#   confirmations -> baseline.establish (CHECKPOINT), disruption.triage (CHECKPOINT)
#   answers       -> design.frame (INTERACTIVE); "" = accept the agent's proposed framing
ctx = InquiryContext(interactor=ScriptedInteractor(confirmations=[True, True, True], answers=[""]))
reg = build_registry(ctx)

# --- INTAKE ----------------------------------------------------------------
reg.call("record_brief", {
    "domain": "TMT diversity and firm performance, mediated by the types of "
              "actions a top management team chooses to pursue",
    "belief_summary": "TMTs with diversity of background and experience are "
        "better able to navigate complex decision environments, yielding "
        "superior firm performance.",
    "initiating_anomaly": "DEI backlash and the meritocracy critique: if hiring "
        "for diversity is non-meritocratic, diversity may lower average skill, "
        "decision quality, and thus performance.",
    "references": ["Fox, Simsek & Heavey 2022", "Ferrier 2001",
                   "Ferrier & Lyon 2004", "Crossland et al. 2014"],
    "researcher": "Brian Fox",
})

# --- STREAM 1: baseline BAM + estimated priors -----------------------------
baseline = reg.call("establish_baseline", {
    "bam_description": "TMT diversity enhances firm performance chiefly "
        "INDIRECTLY, by shaping the variety, complexity, and calibration of the "
        "firm's competitive actions; benefits are contingent (requisite fit to "
        "environmental variety), not a direct or monotonic effect of diversity, "
        "and stem more from experiential than demographic diversity.",
    "literature_summary": "Fox/Simsek/Heavey 2022 (experiential variety -> "
        "calibrated repertoire -> ROA; direct effect null); Ferrier 2001 "
        "(heterogeneity -> some attack dims; no direct effect; U-shaped "
        "complexity); Ferrier & Lyon 2004 (heterogeneity moderates "
        "simplicity->performance); Crossland 2014 (CEO career variety -> novelty, "
        "not TMT heterogeneity; volatility not level).",
    "researcher_summary": "Diversity of background/experience helps TMTs navigate "
        "complex decisions, improving performance.",
    "commitments": [
        {"statement": "Greater TMT diversity leads to superior firm performance.",
         "strength": 0.60, "origin": "agent_estimated",
         "origin_note": "Prevailing view, but direct effects often null (Bell et al. 2011; Fox et al. 2022)."},
        {"statement": "Diversity's effect is mediated by the firm's competitive actions (variety/complexity/calibration).",
         "strength": 0.70, "origin": "agent_estimated",
         "origin_note": "Core mechanism in Fox et al. 2022 and the Ferrier lineage."},
        {"statement": "There is little/no DIRECT diversity->performance effect; it operates indirectly.",
         "strength": 0.60, "origin": "agent_estimated",
         "origin_note": "Direct effects n.s. in Fox et al. 2022 and Ferrier 2001."},
        {"statement": "Diversity's benefit is contingent and non-monotonic (requisite variety; moderation), not 'more is better'.",
         "strength": 0.70, "origin": "agent_estimated",
         "origin_note": "Ferrier & Lyon 2004 moderation; Fox 2022 requisite variety; Ferrier 2001 U-shapes."},
        {"statement": "Experiential/task-relevant variety matters more than demographic diversity for performance.",
         "strength": 0.60, "origin": "agent_estimated",
         "origin_note": "Fox 2022 gender diversity n.s.; Crossland career variety."},
        {"statement": "Diverse TMTs make higher-quality decisions via broader information processing and constructive conflict.",
         "strength": 0.55, "origin": "agent_estimated",
         "origin_note": "Upper-echelons premise; support indirect/mixed."},
        {"statement": "TMT diversity is not achieved at the expense of average member competence (diversity vs. merit not in tension).",
         "strength": 0.50, "origin": "agent_estimated",
         "origin_note": "Implicit, rarely tested; directly challenged by the anomaly."},
    ],
})
cid = {i: c["id"] for i, c in enumerate(baseline["commitments"])}

# --- STREAM 2: disruption across the five dimensions -----------------------
surfaced = reg.call("disruption_surface", {"candidates": [
    {"description": "DEI mandates/bans and board-diversity quotas now permit causal "
     "(not merely correlational) tests of diversity->performance.",
     "pathway": "new_ways_of_doing", "source": "search"},
    {"description": "ML/NLP on executive bios/disclosures can measure individual "
     "competence and the TMT skill distribution, separating diversity from average ability.",
     "pathway": "new_ways_of_doing", "source": "search"},
    {"description": "Upper-echelons theory lacks a diversity-competence tradeoff: it "
     "credits diversity with cognitive variety but is silent on whether diversity-driven "
     "selection lowers average ability.",
     "pathway": "perceived_gaps", "source": "search"},
    {"description": "The current best model cannot explain why direct diversity->performance "
     "effects are repeatedly null while diversity is still prescribed - suggesting an "
     "unmodeled offsetting negative (competence/coordination) path.",
     "pathway": "unsolved_puzzles", "source": "search"},
    {"description": "Widespread DEI rollback and the meritocracy critique: boards/executives "
     "increasingly act as if diversity is performance-costly, contrary to prevailing belief.",
     "pathway": "unexpected_behavior", "source": "researcher_seed"},
    {"description": "Diversity-performance correlations appear to weaken or reverse in recent "
     "samples and in quasi-experimental (mandate/ban) settings.",
     "pathway": "anomalous_observations", "source": "search"},
]})

# --- TRIAGE: promote the BAM-threatening candidates to doubts ---------------
selected = [c for c in surfaced if c["pathway"] in
            ("perceived_gaps", "unsolved_puzzles", "unexpected_behavior", "anomalous_observations")]
doubts = reg.call("disruption_triage", {
    "selected": selected,
    "challenged_commitment_ids": [cid[0], cid[5], cid[6]],  # broad, decision-quality, competence
})
doubt_by_pathway = {d["description"].split("]")[0].lstrip("[").strip(): d["id"] for d in doubts}

# --- DOUBT: confront the BAM and weaken the challenged priors ---------------
priors_before = {c["id"]: c["strength"] for c in baseline["commitments"]}
reg.call("doubt_assess", {"sufficient": False,
    "rationale": "Four doubts (theory gap, null-direct-effect puzzle, DEI rollback, "
                 "weakening correlations) together indicate the current BAM is insufficient."})
for c_id, mag, dpath, why in [
    (cid[6], "strong", "perceived_gaps",
     "Competence-dilution mechanism directly contradicts the implicit no-tradeoff assumption."),
    (cid[0], "moderate", "anomalous_observations",
     "Repeated null direct effects plus backlash undercut the broad claim."),
    (cid[5], "moderate", "unsolved_puzzles",
     "Decision-quality premise is questioned by the merit critique."),
]:
    reg.call("doubt_weaken", {"commitment_id": c_id, "magnitude": mag,
                              "doubt_id": doubt_by_pathway.get(dpath), "rationale": why})

# --- DESIGN: mobilize the four dimensions, then frame + hypothesize ---------
# Anchored to the open doubts (the search prompt). The researcher supplies
# starting points per dimension (seeds); the agent adds what it finds, including
# the two Methods disruptions held back at triage.
mobilized = reg.call("design_mobilize", {
    "seeds": {  # researcher-provided starting points
        "theories": ["Upper-echelons theory", "Law of requisite variety"],
        "data": ["The four cited papers' competitive-action + TMT panels"],
    },
    "resources": [  # agent-found (tagged agent_search)
        {"dimension": "methods", "description": "Quasi-experimental designs using DEI mandate/ban variation"},
        {"dimension": "methods", "description": "NLP/ML measurement of executive competence from bios/disclosures"},
        {"dimension": "theories", "description": "Competitive dynamics / competitive repertoire theory"},
        {"dimension": "phenomenon", "description": "TMT decision processes and the DEI/meritocracy discourse"},
        {"dimension": "data", "description": "Firm performance (ROA, market-share change) linked to DEI policy shifts"},
    ],
})

frame = reg.call("design_frame", {
    "proposed_statement": "Under what conditions and through what mechanisms does TMT "
        "diversity raise versus lower firm performance, once we net cognitive-variety "
        "benefits against a possible competence-dilution cost, transmitted through the "
        "calibration and quality of the firm's competitive actions?",
    "data_picture": "TMT panels with competitive-action data (Ferrier/Fox), executive "
        "competence proxies from bios/NLP, and quasi-experimental DEI mandate/ban variation.",
    "mobilized_knowledge": ["upper-echelons theory", "law of requisite variety",
                            "competitive dynamics", "DEI/meritocracy debate"],
})
hyps = reg.call("design_generate_hypotheses", {"hypotheses": [
    {"statement": "Net variety-vs-competence: diversity helps when it adds experiential "
     "variety without lowering average competence, and hurts when it does.",
     "rationale": "Reconciles the anomaly with the variety benefit."},
    {"statement": "Calibration: diversity helps only when it calibrates competitive-action "
     "variety to environmental variety; DEI-driven diversity uncorrelated with requisite variety yields no benefit.",
     "rationale": "Fox et al. 2022 requisite variety."},
    {"statement": "Two opposing mediated paths (variety->better actions +; competence-"
     "dilution->worse execution -) cancel, explaining null direct effects.",
     "rationale": "Explains the repeated null direct effects."},
    {"statement": "Type-of-diversity: experiential/task-relevant diversity is positive; "
     "demographic-only diversity decoupled from experience is null/negative.",
     "rationale": "Fox 2022 gender n.s.; Crossland career variety."},
    {"statement": "Context-contingent: in high-backlash/low-trust settings, diversity raises "
     "coordination and legitimacy costs that suppress action execution.",
     "rationale": "Ferrier & Lyon moderation; the backlash phenomenon."},
]})

# --- DEVELOPMENT: converge to an internally-consistent prototype -----------
prototype = reg.call("development_build_prototype", {
    "description": "Moderated-mediation prototype: TMT experiential variety -> calibration/"
        "quality of competitive actions -> performance, with an offsetting competence-"
        "dilution path that can cancel the variety path.",
    "components": [
        {"kind": "theory", "statement": "Upper-echelons: TMT cognition shapes strategic action"},
        {"kind": "theory", "statement": "Requisite variety: action variety must match environmental variety"},
        {"kind": "stylized_fact", "statement": "Direct diversity->performance effects are repeatedly null"},
        {"kind": "stylized_fact", "statement": "Action complexity->performance is U-shaped, not monotonic"},
        {"kind": "mechanism", "statement": "Competence-dilution: diversity-via-selection can lower average ability"},
    ],
    "hypotheses": [h["statement"] for h in hyps],
    "frame_id": frame["id"],
})
reg.call("development_specify_affordances", {
    "troves": [
        {"description": "TMT composition + executive bios (experiential variety & competence proxies)"},
        {"description": "Competitive-action panels (volume / complexity / consistency)"},
        {"description": "Firm performance (ROA, market-share change) + DEI policy events"},
    ],
    "techniques": [
        {"description": "NLP on bios/disclosures for competence + experiential variety"},
        {"description": "Optimal matching / repertoire-calibration measures"},
        {"description": "Causal forest & quasi-experimental estimators on DEI mandate/ban variation"},
    ],
})
review = reg.call("development_review", {"note": "Internally consistent; ready to seed with data."})

# --- DEVELOPMENT: ingest the real exploratory analysis onto the prototype ---
_expl_path = Path("examples/data/exploration_result.json")
exploration = None
if _expl_path.exists():
    exploration = json.loads(_expl_path.read_text())
    reg.call("development_record_exploration", {
        "findings": exploration,
        "summary": "Demographic diversity -> ROA is ~null across all scopes "
                   "(within-firm ~0); minorities (esp. Black) leak via turnover faster "
                   "than they are built via promotion.",
        "data_ref": {"panel": "firm_year_diversity_panel.parquet",
                     "exploration": "exploration_result.json"},
    })

# --- EXECUTION: fit the production model + experimental belief updates -------
_fit_path = Path("examples/data/fit_result.json")
fit = None
if _fit_path.exists():
    fit = json.loads(_fit_path.read_text())
    label2cid = {"diversity_improves_performance": cid[0], "no_direct_effect": cid[2]}
    evidence = [
        {"commitment_id": label2cid[label], "bayes_factor": ev["bayes_factor"],
         "rationale": ev["rationale"]}
        for label, ev in fit["belief_evidence"].items()
        if label in label2cid and ev.get("bayes_factor")
    ]
    reg.call("execution_record_fit", {
        "metrics": {"model": fit["model"],
                    **{f"beta_{sc}": fit["scopes"][sc]["beta_blau_race"] for sc in fit["scopes"]}},
        "traits": fit["traits"],
        "evidence": evidence,
    })
    reg.call("execution_reflect", {"assessment":
        "Firm+year FE estimates show diversity->ROA is not positive (slightly negative in "
        "management/top-exec), contradicting the original BAM and supporting the mediated/"
        "contingent account."})
    reg.call("execution_route", {"decision": "converge",
        "rationale": "Direct effect stably near/below zero; model is calibrated, consistent, credible."})

# --- ENRICHMENT: validate, IBE -> new BAM, warrant contributions ------------
reg.call("enrichment_validate", {
    "results": {"within_firm_estimate": "null-to-negative", "cross_scope": "consistent",
                "sensitivity": "robust to scope + controls"},
    "summary": "within-firm FE + cross-scope consistency as robustness",
})
reg.call("enrichment_update_bam", {"note":
    "IBE: the moderated-mediation account best explains the null/negative direct effect and the build-leak dynamics."})
warrant = reg.call("enrichment_warrant", {
    "contributions": [
        {"type": "theoretical", "statement": "Demographic TMT diversity is not a direct driver of "
         "performance; within-firm it is null-to-negative, consistent with a competence/coordination "
         "cost offsetting the variety benefit."},
        {"type": "theoretical", "statement": "Diversity erodes via a promotion-turnover asymmetry "
         "(minorities leak faster than they are built), so its persistence is itself contingent."},
        {"type": "practical", "statement": "DEI value depends on calibrating experiential variety and "
         "on retention, not on demographic headcount targets alone."},
    ],
    "resolve_doubt_ids": [d["id"] for d in doubts],
    "new_commitments": [
        {"statement": "Diversity's performance benefit requires experiential variety + action "
         "calibration; demographic diversity alone is null/negative.",
         "strength": 0.75, "origin": "researcher_set",
         "origin_note": "Warranted by the FE fit + exploration in this cycle."},
        {"statement": "Demographic diversity erodes via a promotion-turnover asymmetry (build-leak).",
         "strength": 0.70, "origin": "researcher_set",
         "origin_note": "Warranted by the build-vs-leak finding."},
    ],
})

# Snapshot the prototype before rehabituation clears the working model (for display).
prototype_final = ctx.ledger.working_model.to_dict()

# --- ORCHESTRATOR: close cycle 1, rehabituate, reconnect to Disruption ------
advance = reg.call("orchestrator_advance", {})
# Cycle 2: a fresh anomaly now challenges the NEW BAM — the loop reconnects to step 1.
cycle2 = reg.call("disruption_surface", {"candidates": [
    {"description": "If experiential variety (not demographics) is what matters, does it ALSO erode "
     "via turnover — does the build-leak dynamic apply to experiential variety too?",
     "pathway": "unsolved_puzzles", "source": "researcher_seed"},
]})

# Persist the full final state for review (the inquiry's durable artifact).
ctx.ledger.save("examples/data/final_ledger.json")
ctx.log.save("examples/data/final_inquiry_log.json")


def main() -> None:
    print("=== BASELINE BAM (Stream 1) ===")
    print(" ", ctx.ledger.bam.description)
    print("\n=== PRIOR COMMITMENTS (agent-estimated credences — please review/override) ===")
    for c in ctx.ledger.commitments:
        print(f"  P={c.strength:.2f}  [{c.origin}]  {c.statement}")
        print(f"         note: {c.origin_note}")
    print(f"\n=== DISRUPTIONS SURFACED ({len(surfaced)}) by dimension ===")
    for c in surfaced:
        print(f"  {c['dimension']:<11} [{c['pathway']}] {c['description'][:78]}...")
    print(f"\n=== TRIAGED TO DOUBTS ABOUT THE BAM ({len(doubts)}) ===")
    for d in doubts:
        print(f"  - {d['description'][:96]}")
    print("\n=== DESIGN: MOBILIZED RESOURCES (anchored to the doubts) ===")
    for r in mobilized:
        tag = "researcher" if r["source"] == "researcher_seed" else "agent"
        print(f"  [{tag:<10}] {r['dimension']:<11} ({r['role']}): {r['description'][:56]}")
    print("\n=== DESIGN: FRAMED PROBLEM ===")
    print(" ", frame["statement"])
    print(f"\n=== WORKING HYPOTHESES ({len(hyps)}) ===")
    for h in hyps:
        print(f"  - {h['statement']}")
    print("\n=== DEVELOPMENT: PROTOTYPE MODEL ===")
    spec = prototype_final["spec"]
    print(f"  {prototype_final['description']}")
    print(f"  internally_consistent={spec['internally_consistent']}  "
          f"components={len(spec['components'])}  hypotheses={len(spec['hypotheses'])}")
    print(f"  troves ({len(spec['troves'])}): " + "; ".join(t['description'][:38] for t in spec['troves']))
    print(f"  techniques ({len(spec['techniques'])}): " + "; ".join(t['description'][:34] for t in spec['techniques']))
    print(f"  review approved: {review['approved']}")
    if exploration is not None:
        print("\n=== DEVELOPMENT: EXPLORATION RECORDED ON PROTOTYPE (real data) ===")
        e = exploration
        print(f"  sample: {e['n_firm_years']:,} firm-years, {e['n_firms']:,} firms, "
              f"{e['year_range'][0]}-{e['year_range'][1]}")
        dd = e["direct_diversity_to_roa"]
        print("  direct diversity->ROA corr (blau_race): " + ", ".join(
            f"{sc}={dd[sc].get('corr_roa__blau_race_'+sc)}" for sc in ("firmwide", "mgmt", "topexec")))
        lk = e["build_vs_leak_firmwide"]
        print("  build-vs-leak net (promo-turn): " + ", ".join(
            f"{g}={lk[g]['net_build']}" for g in ("f", "black", "hispanic", "api")))
        print(f"  recorded in working_model.spec['explorations'] "
              f"({len(prototype_final['spec'].get('explorations', []))} entry)")

    if fit is not None:
        print("\n=== EXECUTION: PRODUCTION MODEL + EXPERIMENTAL BELIEF UPDATES ===")
        for sc in fit["scopes"]:
            s = fit["scopes"][sc]
            print(f"  {sc:<9} beta_blau={s['beta_blau_race']:+.4f}  CI95={s['ci95']}  p={s['p_value']}")
        print("  traits: " + ", ".join(f"{k}={v['ok']}" for k, v in fit["traits"].items()))

    print("\n=== CYCLE CLOSED: BELIEF TRAJECTORIES (baseline -> doubt -> experiment) ===")
    for label, c_id in [("diversity->performance (broad)", cid[0]),
                        ("no direct effect", cid[2]),
                        ("diversity NOT at expense of competence", cid[6])]:
        traj = reg.call("get_belief_trajectory", {"commitment_id": c_id})
        path = " -> ".join(f"{p['probability']:.2f}" for p in traj)
        print(f"  {label:<40} {path}")

    print("\n=== ENRICHMENT: NEW BAM (via IBE) ===")
    print(f"  status={ctx.ledger.bam.status}: {ctx.ledger.bam.description[:96]}")
    print(f"  doubts resolved: {len(warrant['resolved_doubts'])}/{len(doubts)}  |  "
          f"open doubts now: {len(ctx.ledger.open_doubts())}")
    print(f"  warranted contributions: {len(warrant['contributions'])}  |  "
          f"new prior commitments seeded for next cycle: {len(warrant['new_commitments'])}")

    print("\n=== RECURSION: CYCLE 1 -> CYCLE 2 (rehabituation) ===")
    print(f"  completed cycle {advance['completed_cycle']}; now on cycle {advance['next_cycle']}")
    print(f"  carried forward: {advance['carried_commitments']} commitments (full trajectories) "
          f"+ the new BAM as the habit")
    print(f"  working model cleared for a fresh prototype")
    print(f"  cycle-2 disruption surfaced ({len(cycle2)}): {cycle2[0]['description'][:70]}...")
    print(f"  -> the loop has reconnected to Disruption, now against the NEW BAM")

    print("\n=== INQUIRY LOG (provenance) ===")
    for e in reg.call("get_inquiry_log", {}):
        print(f"  v{e['ledger_version']} [{e['mode']:<11}] {e['operation']} — {e['summary'][:60]}")


if __name__ == "__main__":
    main()
