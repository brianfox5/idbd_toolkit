import pytest

from idbd_toolkit import (
    AutoInteractor,
    BeliefLedger,
    InquiryContext,
    Mode,
    PriorCommitment,
)
from idbd_toolkit.phases import DoubtPhase


def _ctx():
    ledger = BeliefLedger()
    ledger.add_commitment(PriorCommitment("diversity improves performance", 0.60))
    return InquiryContext(ledger=ledger, interactor=AutoInteractor())


def test_assess_records_bam_insufficiency():
    ctx = _ctx()
    out = DoubtPhase(ctx).assess_bam(sufficient=False, rationale="null direct effects")
    assert out["bam_sufficient"] is False
    event = ctx.log.by_phase("doubt")[-1]
    assert event.operation == "doubt.assess"
    assert event.mode == Mode.INTERACTIVE.value
    assert event.payload["bam_sufficient"] is False


def test_weaken_by_magnitude_lowers_credence_and_leaves_trail():
    ctx = _ctx()
    cid = ctx.ledger.commitments[0].id
    update = DoubtPhase(ctx).weaken(cid, magnitude="strong", doubt_id="dbt-9",
                                    rationale="DEI meritocracy critique")
    c = ctx.ledger.get_commitment(cid)
    # 0.60 with BF 0.33: odds 1.5*0.33=0.495 -> p≈0.331
    assert c.strength == pytest.approx(0.3311, abs=1e-3)
    # recorded on the belief trajectory, marked doubt-driven
    assert c.updates[-1].source == "dbt-9"
    assert c.updates[-1].description.startswith("Doubt:")
    assert update.bayes_factor == pytest.approx(0.33)
    # and logged as a doubt-phase op
    assert ctx.log.by_phase("doubt")[-1].operation == "doubt.weaken"


def test_weaken_by_explicit_bayes_factor():
    ctx = _ctx()
    cid = ctx.ledger.commitments[0].id
    DoubtPhase(ctx).weaken(cid, bayes_factor=0.5)
    # odds 1.5*0.5=0.75 -> p=0.4286
    assert ctx.ledger.get_commitment(cid).strength == pytest.approx(0.4286, abs=1e-3)


def test_weaken_to_target_strength_hits_target():
    ctx = _ctx()
    cid = ctx.ledger.commitments[0].id
    DoubtPhase(ctx).weaken(cid, target_strength=0.25)
    assert ctx.ledger.get_commitment(cid).strength == pytest.approx(0.25, abs=1e-6)


def test_unknown_magnitude_raises():
    ctx = _ctx()
    cid = ctx.ledger.commitments[0].id
    with pytest.raises(ValueError):
        DoubtPhase(ctx).weaken(cid, magnitude="catastrophic")


def test_successive_doubts_compose_on_trajectory():
    ctx = _ctx()
    cid = ctx.ledger.commitments[0].id
    dp = DoubtPhase(ctx)
    dp.weaken(cid, magnitude="moderate")   # BF 0.5
    dp.weaken(cid, magnitude="moderate")   # BF 0.5
    c = ctx.ledger.get_commitment(cid)
    # two 0.5 BFs == one 0.25 BF: odds 1.5*0.25=0.375 -> p≈0.2727
    assert c.strength == pytest.approx(0.2727, abs=1e-3)
    assert len(c.updates) == 2
