import pytest

from idbd_toolkit import (
    AutoInteractor,
    BeliefLedger,
    Doubt,
    InquiryContext,
    InquiryOrchestrator,
    Model,
    PriorCommitment,
)


def _completed_cycle_ctx():
    """A ledger at the end of a cycle: a BAM is set, a working model exists."""
    ledger = BeliefLedger()
    ledger.add_commitment(PriorCommitment("a warranted prior", 0.7))
    ledger.set_working_model(Model("production model", status="production"))
    ledger.set_bam(ledger.working_model)  # Enrichment IBE promoted it
    return InquiryContext(ledger=ledger, interactor=AutoInteractor())


def test_advance_rehabituates_into_next_cycle():
    ctx = _completed_cycle_ctx()
    orch = InquiryOrchestrator(ctx)
    assert orch.cycle == 1
    out = orch.advance()
    assert out["completed_cycle"] == 1 and out["next_cycle"] == 2
    assert ctx.ledger.cycle == 2
    # the BAM and commitments carry over; the working model is cleared for a fresh prototype
    assert ctx.ledger.bam is not None
    assert ctx.ledger.working_model is None
    assert out["carried_commitments"] == 1
    # the transition is logged and snapshotted
    assert any(e.operation == "orchestrator.rehabituate" for e in ctx.log.events())
    assert ctx.ledger.version == out["snapshot_version"]


def test_advance_requires_a_bam():
    ledger = BeliefLedger()
    ledger.set_working_model(Model("unpromoted prototype", status="production"))
    ctx = InquiryContext(ledger=ledger, interactor=AutoInteractor())
    with pytest.raises(RuntimeError):
        InquiryOrchestrator(ctx).advance()


def test_belief_trajectory_spans_cycles():
    ctx = _completed_cycle_ctx()
    cid = ctx.ledger.commitments[0].id
    orch = InquiryOrchestrator(ctx)
    orch.advance()  # into cycle 2
    # a new disruption in cycle 2 weakens the carried prior — same trajectory continues
    ctx.ledger.update_belief(cid, bayes_factor=0.5, description="Doubt: cycle-2 anomaly",
                             source="doubt.weaken")
    traj = ctx.ledger.belief_trajectory(cid)
    assert len(traj) == 2  # prior + the cycle-2 update, one continuous history
    assert ctx.ledger.get_commitment(cid).strength < 0.7


def test_cycle_counter_persists(tmp_path):
    ctx = _completed_cycle_ctx()
    InquiryOrchestrator(ctx).advance()
    path = tmp_path / "ledger.json"
    ctx.ledger.save(path)
    assert BeliefLedger.load(path).cycle == 2


def test_summary_and_lineage():
    ctx = _completed_cycle_ctx()
    orch = InquiryOrchestrator(ctx)
    orch.advance()
    s = orch.summary()
    assert s["cycle"] == 2 and s["working_model"] is None
    assert len(s["lineage"]) == 1 and "complete" in s["lineage"][0]["note"]
