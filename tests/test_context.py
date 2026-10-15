from idbd_toolkit import (
    AutoInteractor,
    BeliefLedger,
    InquiryContext,
    Mode,
    PriorCommitment,
    ScriptedInteractor,
)


def test_auto_gate_notifies_and_records():
    interactor = AutoInteractor()
    ctx = InquiryContext(interactor=interactor)
    result = ctx.gate("disruption.surface", "scanning for anomalies")
    assert result.mode is Mode.AUTO
    assert result.approved is True
    assert interactor.notifications == ["[disruption.surface] scanning for anomalies"]
    assert len(ctx.log) == 1
    assert ctx.log.events()[0].phase == "disruption"


def test_checkpoint_gate_declined():
    ctx = InquiryContext(interactor=ScriptedInteractor(confirmations=[False]))
    result = ctx.gate("disruption.triage", "is this anomaly real?")
    assert result.mode is Mode.CHECKPOINT
    assert result.approved is False
    assert ctx.log.events()[0].payload["approved"] is False


def test_event_records_ledger_version():
    ledger = BeliefLedger()
    ledger.add_commitment(PriorCommitment("a", 0.5))
    ledger.commit("v1")
    ctx = InquiryContext(ledger=ledger)
    ctx.gate("development.build_prototype", "building prototype")
    assert ctx.log.events()[0].ledger_version == 1


def test_persistence_of_context_parts(tmp_path):
    ctx = InquiryContext()
    ctx.gate("execution.run", "fit model")
    ctx.ledger.commit("post-run")

    ledger_path = tmp_path / "ledger.json"
    log_path = tmp_path / "log.json"
    ctx.ledger.save(ledger_path)
    ctx.log.save(log_path)

    from idbd_toolkit import BeliefLedger as BL, InquiryLog

    assert BL.load(ledger_path).version == 1
    assert len(InquiryLog.load(log_path)) == 1
