from idbd_toolkit import (
    BeliefLedger, DeferredInteractor, InputRequired, InquiryContext, InquiryLog, cycle_progress,
)
from idbd_toolkit.autonomy import Mode
from idbd_toolkit.models import Model


def _ctx():
    return InquiryContext(ledger=BeliefLedger(), log=InquiryLog())


def _rec(ctx, op, **payload):
    ctx.record(op, Mode.AUTO, op, {"approved": True, **payload})


def test_fresh_inquiry_starts_at_intake():
    p = cycle_progress(*(lambda c: (c.ledger, c.log))(_ctx()))
    assert p["active_stage"] == "intake"
    assert p["next_step"]["tool"] == "record_brief"
    assert [s["status"] for s in p["stages"]][:2] == ["active", "pending"]


def test_declined_checkpoint_does_not_complete_a_step():
    ctx = _ctx()
    _rec(ctx, "intake.received")
    ctx.record("baseline.establish", Mode.CHECKPOINT, "b", {"approved": False})
    p = cycle_progress(ctx.ledger, ctx.log)
    assert p["active_stage"] == "baseline"


def test_optional_steps_do_not_block_and_route_back_reopens_stages():
    ctx = _ctx()
    for op in ["intake.received", "baseline.establish", "disruption.surface",
               "disruption.triage", "doubt.assess",  # doubt.weaken is optional
               "design.mobilize", "design.frame", "design.generate_hypotheses",
               "development.build_prototype", "development.review",
               "execution.run", "execution.reflect"]:
        _rec(ctx, op)
    assert cycle_progress(ctx.ledger, ctx.log)["next_step"]["tool"] == "execution_route"
    _rec(ctx, "execution.route", decision="refine_hypotheses")
    p = cycle_progress(ctx.ledger, ctx.log)
    assert p["active_stage"] == "design"
    assert {s["key"]: s["status"] for s in p["stages"]}["development"] == "pending"
    assert {s["key"]: s["status"] for s in p["stages"]}["doubt"] == "done"


def test_new_cycle_carries_entry_and_resumes_at_disruption():
    ctx = _ctx()
    _rec(ctx, "intake.received")
    _rec(ctx, "baseline.establish")
    ctx.ledger.set_bam(Model(description="m"))
    ctx.ledger.cycle = 2
    ctx.record("orchestrator.rehabituate", Mode.AUTO, "next", {})
    p = cycle_progress(ctx.ledger, ctx.log)
    assert p["cycle"] == 2
    assert [s["status"] for s in p["stages"]][:3] == ["carried", "carried", "active"]
    assert p["next_step"]["tool"] == "disruption_surface"


def test_deferred_interactor_raises_with_the_core_prompt():
    it = DeferredInteractor(confirmations=[True])
    assert it.confirm("first?") is True
    try:
        it.confirm("second?", context={"x": 1})
    except InputRequired as need:
        assert need.to_dict() == {"kind": "confirm", "prompt": "second?", "context": {"x": 1}}
    else:
        raise AssertionError("expected InputRequired")


def test_a_completed_cycle_can_be_reviewed():
    import pytest
    from idbd_toolkit.progress import STAGES
    ctx = _ctx()
    for stage in STAGES:  # run every required step of cycle 1, closing with rehabituation
        for step in stage.steps:
            if step.required:
                _rec(ctx, step.operation)
    _rec(ctx, "disruption.surface")  # cycle 2 under way
    past = cycle_progress(ctx.ledger, ctx.log, cycle=1)
    assert (past["cycle"], past["current_cycle"], past["next_step"]) == (1, 2, None)
    assert {s["status"] for s in past["stages"]} == {"done"}
    assert [s["runs"] for s in past["stages"][2]["steps"]] == [1, 1]  # cycle 2's surface excluded
    now = cycle_progress(ctx.ledger, ctx.log)
    assert (now["cycle"], now["current_cycle"]) == (2, 2)
    assert now["stages"][2]["steps"][0]["runs"] == 1
    with pytest.raises(ValueError):
        cycle_progress(ctx.ledger, ctx.log, cycle=3)
