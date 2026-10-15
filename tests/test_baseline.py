from idbd_toolkit import Baseline, InquiryContext, ScriptedInteractor


def _commitments():
    return [
        {"statement": "Stronger incentives increase innovation", "strength": 0.75,
         "origin": "agent_estimated", "origin_note": "Estimated from literature synthesis"},
        {"statement": "Autonomy supports intrinsic motivation", "strength": 0.6,
         "origin": "researcher_set", "origin_note": "Researcher's stated prior"},
    ]


def test_establish_seeds_bam_and_priors_with_provenance():
    ctx = InquiryContext(interactor=ScriptedInteractor(confirmations=[True]))
    out = Baseline(ctx).establish(
        bam_description="Incentives drive innovation via agency mechanisms",
        commitments=_commitments(),
        literature_summary="synthesis of 40 papers",
        researcher_summary="my read of the field",
    )
    assert out["approved"] is True
    # BAM established with the two summaries retained as provenance
    assert ctx.ledger.bam is not None
    assert ctx.ledger.bam.status == "bam"
    assert ctx.ledger.bam.spec["literature_summary"] == "synthesis of 40 papers"
    # priors seeded, provenance preserved
    priors = ctx.ledger.commitments
    assert len(priors) == 2
    est = ctx.ledger.get_commitment(priors[0].id)
    assert est.origin == "agent_estimated"
    assert est.origin_note == "Estimated from literature synthesis"
    # baseline committed as version 1
    assert ctx.ledger.version == 1
    # provenance event uses the non-phase 'baseline' label
    assert ctx.log.events()[0].phase == "baseline"


def test_establish_declined_seeds_nothing():
    ctx = InquiryContext(interactor=ScriptedInteractor(confirmations=[False]))
    out = Baseline(ctx).establish(
        bam_description="draft BAM", commitments=_commitments()
    )
    assert out["approved"] is False
    assert ctx.ledger.bam is None
    assert ctx.ledger.commitments == []
    assert ctx.ledger.version == 0


def test_agent_estimated_priors_are_countable():
    ctx = InquiryContext(interactor=ScriptedInteractor(confirmations=[True]))
    Baseline(ctx).establish(bam_description="b", commitments=_commitments())
    n_est = sum(1 for c in ctx.ledger.commitments if c.origin == "agent_estimated")
    assert n_est == 1
