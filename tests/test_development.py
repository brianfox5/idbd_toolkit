import pytest

from idbd_toolkit import AutoInteractor, InquiryContext, Mode, ScriptedInteractor
from idbd_toolkit.phases import DevelopmentPhase


def test_build_prototype_sets_working_model_and_is_consistent():
    ctx = InquiryContext(interactor=AutoInteractor())
    model = DevelopmentPhase(ctx).build_prototype(
        "net variety-vs-competence model of TMT diversity",
        components=[{"kind": "theory", "statement": "upper-echelons"},
                    "stylized fact: null direct effects"],
        hypotheses=["net variety-vs-competence", "calibration"],
        frame_id="frm-1",
    )
    assert model.status == "prototype"
    assert ctx.ledger.working_model is model
    assert model.spec["internally_consistent"] is True
    # str components are normalized to dicts with a description
    assert model.spec["components"][1]["description"].startswith("stylized fact")
    event = ctx.log.by_phase("development")[-1]
    assert event.operation == "development.build_prototype"
    assert event.mode == Mode.AUTO.value


def test_declared_contradictions_fail_consistency_guardrail():
    interactor = AutoInteractor()
    ctx = InquiryContext(interactor=interactor)
    model = DevelopmentPhase(ctx).build_prototype(
        "incoherent prototype",
        contradictions=["variety both raises and lowers competence simultaneously"],
    )
    assert model.spec["internally_consistent"] is False
    assert any("spaghetti" in n for n in interactor.notifications)


def test_specify_affordances_attaches_troves_and_techniques():
    ctx = InquiryContext(interactor=AutoInteractor())
    dev = DevelopmentPhase(ctx)
    dev.build_prototype("p")
    model = dev.specify_affordances(
        troves=["TMT panel 1986-2017", {"description": "DEI policy events"}],
        techniques=["optimal matching", "causal forest"],
    )
    assert len(model.spec["troves"]) == 2
    assert len(model.spec["techniques"]) == 2
    assert model.spec["troves"][0]["description"] == "TMT panel 1986-2017"


def test_specify_affordances_requires_a_prototype_first():
    ctx = InquiryContext(interactor=AutoInteractor())
    with pytest.raises(RuntimeError):
        DevelopmentPhase(ctx).specify_affordances(troves=["x"])


def test_review_is_checkpoint_and_can_be_declined():
    ctx = InquiryContext(interactor=ScriptedInteractor(confirmations=[False]))
    dev = DevelopmentPhase(ctx)
    dev.build_prototype("p")
    out = dev.review(note="needs more internal consistency")
    assert out["approved"] is False
    assert ctx.log.by_phase("development")[-1].operation == "development.review"


def test_record_exploration_attaches_findings_with_provenance():
    ctx = InquiryContext(interactor=AutoInteractor())
    dev = DevelopmentPhase(ctx)
    dev.build_prototype("p")
    model = dev.record_exploration(
        {"corr_blau_roa": -0.02, "n": 239478},
        summary="firm-year diversity vs ROA, year>=2008",
        data_ref={"panel": "firm_year_diversity_panel.parquet", "code_version": "699a2d36"},
    )
    expl = model.spec["explorations"]
    assert len(expl) == 1
    assert expl[0]["findings"]["n"] == 239478
    assert expl[0]["data_ref"]["code_version"] == "699a2d36"
    assert ctx.log.by_phase("development")[-1].operation == "development.explore"


def test_working_model_survives_persistence(tmp_path):
    from idbd_toolkit import BeliefLedger
    ctx = InquiryContext(interactor=AutoInteractor())
    DevelopmentPhase(ctx).build_prototype("p", hypotheses=["h1"])
    path = tmp_path / "ledger.json"
    ctx.ledger.save(path)
    loaded = BeliefLedger.load(path)
    assert loaded.working_model is not None
    assert loaded.working_model.status == "prototype"
    assert loaded.working_model.spec["hypotheses"] == ["h1"]
