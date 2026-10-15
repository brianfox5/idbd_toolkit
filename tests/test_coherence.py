import pytest

from idbd_toolkit import (
    AutoInteractor,
    BeliefLedger,
    Coupling,
    DeferredInteractor,
    InputRequired,
    InquiryContext,
    PriorCommitment,
    ScriptedInteractor,
    build_registry,
)
from idbd_toolkit.coherence import check
from idbd_toolkit.phases import DevelopmentPhase, DoubtPhase, ExecutionPhase


def _ctx(pa=0.6, pb=0.3, interactor=None):
    ledger = BeliefLedger()
    a = ledger.add_commitment(PriorCommitment("diversity improves performance", pa))
    b = ledger.add_commitment(PriorCommitment("no direct effect", pb))
    ctx = InquiryContext(ledger=ledger, interactor=interactor or AutoInteractor())
    return ctx, a.id, b.id


@pytest.mark.parametrize(
    "relation,pa,pb,incoherent",
    [
        ("excludes", 0.6, 0.3, False),
        ("excludes", 0.6, 0.6, True),
        ("entails", 0.3, 0.6, False),
        ("entails", 0.7, 0.4, True),
        ("complements", 0.7, 0.3, False),
        ("complements", 0.7, 0.31, False),  # within tolerance
        ("complements", 0.7, 0.5, True),
        ("complements", 0.2, 0.3, True),  # under-sums too
    ],
)
def test_constraints(relation, pa, pb, incoherent):
    a, b = PriorCommitment("a", pa), PriorCommitment("b", pb)
    v = check([a, b], [Coupling(a.id, b.id, relation)])
    assert bool(v) is incoherent


def test_coupling_validation():
    with pytest.raises(ValueError):
        Coupling("cmt-1", "cmt-2", "contradicts")
    with pytest.raises(ValueError):
        Coupling("cmt-1", "cmt-1", "excludes")
    ledger = BeliefLedger()
    with pytest.raises(KeyError):
        ledger.add_coupling(Coupling("cmt-x", "cmt-y", "excludes"))


def test_update_flags_but_does_not_repair_coupled_belief():
    ctx, a, b = _ctx(0.6, 0.3)
    ctx.couple(a, b, "excludes")
    n_before = len(ctx.log.to_list())
    ctx.update_belief(b, bayes_factor=8.0, source="exp-1")  # 0.30 -> ~0.77
    # beliefs stay on their own scales: A untouched
    assert ctx.ledger.get_commitment(a).strength == pytest.approx(0.6)
    assert any("incoherent" in n for n in ctx.interactor.notifications)
    events = ctx.log.to_list()[n_before:]
    assert [e["operation"] for e in events] == ["coherence.check"]
    assert events[0]["payload"]["violations"][0]["relation"] == "excludes"


def test_coherent_update_is_silent():
    ctx, a, b = _ctx(0.6, 0.3)
    ctx.couple(a, b, "excludes")
    n_before = len(ctx.log.to_list())
    ctx.update_belief(b, bayes_factor=0.5)
    assert len(ctx.log.to_list()) == n_before


def test_couple_exposes_existing_incoherence_and_can_be_declined():
    ctx, a, b = _ctx(0.6, 0.6, interactor=ScriptedInteractor(confirmations=[False]))
    out = ctx.couple(a, b, "excludes")
    assert out["approved"] is False and ctx.ledger.couplings == []

    ctx, a, b = _ctx(0.6, 0.6)
    out = ctx.couple(a, b, "excludes", rationale="direct effect vs none")
    assert out["approved"] and len(out["incoherent"]) == 1
    assert out["incoherent"][0]["gap"] == pytest.approx(0.2)


def test_couple_is_a_checkpoint_in_deferred_clients():
    ctx, a, b = _ctx(interactor=DeferredInteractor())
    with pytest.raises(InputRequired) as exc:
        ctx.couple(a, b, "excludes")
    assert exc.value.kind == "confirm"


def test_doubt_weaken_triggers_check():
    ctx, a, b = _ctx(0.5, 0.5)
    ctx.couple(a, b, "complements")
    DoubtPhase(ctx).weaken(a, magnitude="severe")  # A drops; B untouched -> sum < 1
    assert ctx.ledger.coherence()[0].relation == "complements"


def test_execution_checks_once_after_batch():
    # Mid-batch the pair is incoherent (A up first), but the batch as a whole
    # restores coherence — no caution should fire.
    ctx, a, b = _ctx(0.3, 0.6)
    ctx.couple(a, b, "excludes")
    DevelopmentPhase(ctx).build_prototype("p")
    out = ExecutionPhase(ctx).record_fit(metrics={}, evidence=[
        {"commitment_id": a, "bayes_factor": 4.0},   # 0.30 -> 0.63 (sum 1.23)
        {"commitment_id": b, "bayes_factor": 0.1},   # 0.60 -> 0.13
    ])
    assert out["incoherent"] == []
    assert not any(e["operation"] == "coherence.check" for e in ctx.log.to_list())


def test_persistence_and_snapshots():
    ctx, a, b = _ctx()
    ctx.couple(a, b, "excludes")
    snap = ctx.ledger.commit("coupled")
    assert snap.couplings[0]["relation"] == "excludes"
    restored = BeliefLedger.from_dict(ctx.ledger.to_dict())
    assert restored.couplings[0].a_id == a
    # older ledgers without couplings still load
    data = ctx.ledger.to_dict()
    data.pop("couplings")
    for s in data["history"]:
        s.pop("couplings")
    assert BeliefLedger.from_dict(data).couplings == []


def test_tools():
    ctx, a, b = _ctx(0.6, 0.6)
    reg = build_registry(ctx)
    out = reg.call("couple_beliefs", {"a_id": a, "b_id": b, "relation": "excludes"})
    cid = out["coupling"]["id"]
    res = reg.call("check_coherence", {})
    assert res["coherent"] is False and len(res["violations"]) == 1
    reg.call("uncouple_beliefs", {"coupling_id": cid})
    assert reg.call("check_coherence", {})["coherent"] is True
