from idbd_toolkit import BeliefLedger, Doubt, Model, PriorCommitment


def test_commitment_strength_is_clamped():
    c = PriorCommitment("incentives raise innovation", strength=1.7)
    assert c.strength == 1.0
    c2 = PriorCommitment("x", strength=-0.2)
    assert c2.strength == 0.0


def test_adjust_strength_and_doubt_lifecycle():
    ledger = BeliefLedger()
    c = ledger.add_commitment(PriorCommitment("incentives raise innovation", 0.8))
    d = ledger.add_doubt(Doubt("new incentive slowed innovation", related_commitments=[c.id]))

    ledger.adjust_strength(c.id, 0.3)  # Doubt weakens the prior
    assert ledger.get_commitment(c.id).strength == 0.3
    assert ledger.open_doubts() == [d]

    ledger.resolve_doubt(d.id)
    assert ledger.open_doubts() == []


def test_set_bam_marks_status():
    ledger = BeliefLedger()
    model = Model("prototype of the mechanism")
    assert model.status == "prototype"
    ledger.set_bam(model)
    assert ledger.bam is model
    assert ledger.bam.status == "bam"


def test_versioning_increments_on_commit():
    ledger = BeliefLedger()
    assert ledger.version == 0
    ledger.add_commitment(PriorCommitment("a", 0.5))
    s1 = ledger.commit("initial priors")
    assert s1.version == 1 and ledger.version == 1
    ledger.add_doubt(Doubt("anomaly"))
    s2 = ledger.commit("logged a doubt")
    assert s2.version == 2
    # history snapshots are immutable captures, not live references
    assert len(ledger.history()[0].commitments) == 1
    assert len(ledger.history()[1].doubts) == 1


def test_persistence_round_trip(tmp_path):
    ledger = BeliefLedger()
    ledger.add_commitment(PriorCommitment("a", 0.6, rationale="prior work"))
    ledger.add_doubt(Doubt("why did it slow?"))
    ledger.set_bam(Model("m", spec={"k": 1}, metrics={"auc": 0.7}))
    ledger.commit("state one")

    path = tmp_path / "ledger.json"
    ledger.save(path)
    loaded = BeliefLedger.load(path)

    assert loaded.to_dict() == ledger.to_dict()
    assert loaded.version == 1
    assert loaded.bam.status == "bam"
    assert loaded.commitments[0].rationale == "prior work"
