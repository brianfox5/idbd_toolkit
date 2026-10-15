import pytest

from idbd_toolkit import (
    AutoInteractor,
    BeliefLedger,
    Doubt,
    InquiryContext,
    Mode,
    PriorCommitment,
)
from idbd_toolkit.phases import DevelopmentPhase, EnrichmentPhase, ExecutionPhase


def _ctx_with_prototype():
    ledger = BeliefLedger()
    ledger.add_commitment(PriorCommitment("diversity improves performance", 0.43))  # cmt-1
    ledger.add_commitment(PriorCommitment("no direct effect", 0.60))               # cmt-2
    ctx = InquiryContext(ledger=ledger, interactor=AutoInteractor())
    DevelopmentPhase(ctx).build_prototype("prototype")
    return ctx


def test_record_fit_promotes_model_and_updates_beliefs_from_evidence():
    ctx = _ctx_with_prototype()
    c1, c2 = ctx.ledger.commitments[0].id, ctx.ledger.commitments[1].id
    out = ExecutionPhase(ctx).record_fit(
        metrics={"beta_blau_race": -0.0575, "p": 0.13},
        traits={"calibrated": True, "consistent": True, "credible": True},
        evidence=[
            {"commitment_id": c1, "bayes_factor": 0.06, "rationale": "FE estimate refutes +0.05"},
            {"commitment_id": c2, "bayes_factor": 16.6, "rationale": "tight CI around zero"},
        ],
    )
    assert ctx.ledger.working_model.status == "production"
    assert ctx.ledger.working_model.metrics["beta_blau_race"] == -0.0575
    # experimental evidence moved the credences
    assert ctx.ledger.get_commitment(c1).strength < 0.43   # weakened hard
    assert ctx.ledger.get_commitment(c2).strength > 0.60   # strengthened hard
    # recorded as execution-driven on the trajectory
    assert ctx.ledger.get_commitment(c1).updates[-1].source == "execution.run"
    assert len(out["updates"]) == 2
    ev = ctx.log.by_phase("execution")[-1]
    assert ev.operation == "execution.run" and ev.mode == Mode.AUTO.value


def test_reflect_and_route_are_interactive():
    ctx = _ctx_with_prototype()
    ex = ExecutionPhase(ctx)
    ex.reflect("Findings contradict the positive-direct-effect model.")
    r = ex.route("converge", rationale="stable negative/near-zero direct effect")
    assert r["decision"] == "converge"
    ops = [e.operation for e in ctx.log.by_phase("execution")]
    assert "execution.reflect" in ops and "execution.route" in ops
    assert ctx.log.by_phase("execution")[-1].mode == Mode.INTERACTIVE.value


def test_enrichment_validate_update_bam_and_warrant_close_the_cycle():
    ctx = _ctx_with_prototype()
    ctx.ledger.working_model.status = "production"
    d = ctx.ledger.add_doubt(Doubt("the triaged doubt"))
    enr = EnrichmentPhase(ctx)

    enr.validate({"oos_r2": 0.03, "sensitivity": "stable"}, summary="out-of-sample + sensitivity")
    assert ctx.ledger.working_model.spec["validation"][0]["results"]["oos_r2"] == 0.03

    out = enr.update_bam(note="IBE: best available explanation")
    assert out["approved"] is True
    assert ctx.ledger.bam is ctx.ledger.working_model
    assert ctx.ledger.bam.status == "bam"

    w = enr.warrant(
        [{"type": "theoretical", "statement": "demographic diversity is not a direct driver"}],
        resolve_doubt_ids=[d.id],
        new_commitments=[{"statement": "diversity benefits require experiential variety + calibration",
                          "strength": 0.7, "origin": "researcher_set"}],
    )
    assert w["resolved_doubts"] == [d.id]
    assert ctx.ledger.open_doubts() == []          # doubt resolved
    assert len(w["new_commitments"]) == 1
    # a new warranted prior now seeds the next cycle
    assert any(c.statement.startswith("diversity benefits require") for c in ctx.ledger.commitments)


def test_execution_requires_a_working_model():
    ctx = InquiryContext(interactor=AutoInteractor())
    with pytest.raises(RuntimeError):
        ExecutionPhase(ctx).record_fit(metrics={})
