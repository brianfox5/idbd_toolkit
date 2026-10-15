from idbd_toolkit import (
    AutoInteractor,
    BeliefLedger,
    Doubt,
    InquiryContext,
    Mode,
    ScriptedInteractor,
)
import pytest

from idbd_toolkit.phases import DesignPhase, WorkingHypothesis


def _ctx_with_doubt(interactor=None):
    ledger = BeliefLedger()
    ledger.add_doubt(Doubt("a new incentive paradoxically slowed innovation"))
    return InquiryContext(ledger=ledger, interactor=interactor or AutoInteractor())


def test_mobilize_tags_roles_by_dimension():
    ctx = _ctx_with_doubt()
    items = DesignPhase(ctx).mobilize([
        {"dimension": "methods", "description": "quasi-experimental DEI-ban designs"},
        {"dimension": "theories", "description": "upper-echelons theory"},
        {"dimension": "phenomenon", "description": "TMT decision processes"},
        {"dimension": "data", "description": "competitive-action panels"},
    ])
    roles = {i.dimension: i.role for i in items}
    assert roles["methods"] == "available tool for inquiry"
    assert roles["theories"] == "extant theoretical framework"
    assert roles["phenomenon"] == "relevant domain knowledge"
    assert roles["data"] == "measurable aspect of domain"
    event = ctx.log.by_phase("design")[-1]
    assert event.operation == "design.mobilize"
    assert event.mode == Mode.AUTO.value
    assert event.payload["by_dimension"]["methods"] == 1
    # agent-found resources default to source agent_search
    assert all(i.source == "agent_search" for i in items)


def test_mobilize_is_anchored_to_open_doubts():
    ctx = _ctx_with_doubt()  # has one open doubt
    doubt_id = ctx.ledger.open_doubts()[0].id
    DesignPhase(ctx).mobilize([{"dimension": "theories", "description": "x"}])
    event = ctx.log.by_phase("design")[-1]
    assert event.payload["prompted_by"] == [doubt_id]


def test_mobilize_seeds_are_researcher_tagged_per_dimension():
    ctx = _ctx_with_doubt()
    items = DesignPhase(ctx).mobilize(
        resources=[{"dimension": "data", "description": "agent-found panel"}],
        seeds={"theories": ["upper-echelons theory", "requisite variety"],
               "methods": ["natural experiments"]},
    )
    seeds = [i for i in items if i.source == "researcher_seed"]
    assert len(seeds) == 3
    assert {s.dimension for s in seeds} == {"theories", "methods"}
    event = ctx.log.by_phase("design")[-1]
    assert event.payload["by_source"] == {"researcher_seed": 3, "agent_search": 1}


def test_mobilize_rejects_model_dimension_in_seeds():
    ctx = _ctx_with_doubt()
    with pytest.raises(ValueError):
        DesignPhase(ctx).mobilize(seeds={"model": ["the prototype"]})


def test_mobilize_rejects_model_dimension():
    ctx = _ctx_with_doubt()
    with pytest.raises(ValueError):
        DesignPhase(ctx).mobilize([{"dimension": "model", "description": "the prototype"}])


def test_frame_interactive_uses_researcher_refinement():
    ctx = _ctx_with_doubt(ScriptedInteractor(answers=["incentives crowd out intrinsic motivation"]))
    design = DesignPhase(ctx)
    frame = design.frame("why did innovation slow?")
    # INTERACTIVE reply replaced the proposed statement
    assert frame.statement == "incentives crowd out intrinsic motivation"
    # open doubt was read in as context
    assert len(frame.doubt_ids) == 1
    # provenance recorded under the design phase
    events = ctx.log.by_phase("design")
    assert len(events) == 1 and events[0].operation == "design.frame"


def test_frame_interactive_blank_reply_accepts_proposed():
    ctx = _ctx_with_doubt(ScriptedInteractor(answers=["   "]))
    frame = DesignPhase(ctx).frame("why did innovation slow?")
    assert frame.statement == "why did innovation slow?"


def test_frame_auto_override_notifies_and_skips_ask():
    interactor = AutoInteractor()  # ask() would raise if called
    ctx = _ctx_with_doubt(interactor)
    frame = DesignPhase(ctx).frame("framed under auto", override=Mode.AUTO)
    assert frame.accepted is True
    assert any("design.frame" in n for n in interactor.notifications)


def test_frame_checkpoint_decline_marks_not_accepted():
    ctx = _ctx_with_doubt(ScriptedInteractor(confirmations=[False]))
    frame = DesignPhase(ctx).frame("framed under checkpoint", override=Mode.CHECKPOINT)
    assert frame.accepted is False


def test_generate_hypotheses_is_auto_and_records_before_results():
    interactor = AutoInteractor()
    ctx = _ctx_with_doubt(interactor)
    design = DesignPhase(ctx)
    hyps = design.generate_hypotheses(
        [
            {"statement": "intrinsic motivation crowded out", "rationale": "SDT"},
            WorkingHypothesis("risk aversion rose", "loss framing"),
        ]
    )
    assert [h.status for h in hyps] == ["working", "working"]
    event = ctx.log.by_phase("design")[-1]
    assert event.operation == "design.generate_hypotheses"
    assert event.mode == Mode.AUTO.value
    assert event.payload["multiple_working_hypotheses"] is True
    # logged at generation time, before any execution/results exist
    assert ctx.log.by_phase("execution") == []


def test_single_hypothesis_triggers_multiplicity_caution():
    interactor = AutoInteractor()
    ctx = _ctx_with_doubt(interactor)
    DesignPhase(ctx).generate_hypotheses([{"statement": "only one idea"}])
    assert any("multiple working hypotheses" in n for n in interactor.notifications)
    event = ctx.log.by_phase("design")[-1]
    assert event.payload["multiple_working_hypotheses"] is False
