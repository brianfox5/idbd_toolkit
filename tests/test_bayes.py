import pytest

from idbd_toolkit import BeliefLedger, PriorCommitment
from idbd_toolkit import bayes


def test_bayes_factor_gt_one_raises_credence():
    assert bayes.update_probability(0.5, 3.0) == pytest.approx(0.75)


def test_bayes_factor_lt_one_lowers_credence():
    assert bayes.update_probability(0.5, 1 / 3) == pytest.approx(0.25)


def test_bayes_factor_one_is_noninformative():
    assert bayes.update_probability(0.42, 1.0) == pytest.approx(0.42)


def test_updates_compose_associatively():
    # two experiments in sequence == one update with the product of Bayes factors
    seq = bayes.update_probability(bayes.update_probability(0.5, 2.0), 4.0)
    combined = bayes.update_probability(0.5, 8.0)
    assert seq == pytest.approx(combined)


def test_likelihoods_give_expected_bayes_factor():
    bf = bayes.bayes_factor_from_likelihoods(0.9, 0.3)
    assert bf == pytest.approx(3.0)


def test_extreme_prior_never_saturates():
    # a credence of ~1 can still be moved downward by contrary evidence
    lowered = bayes.update_probability(0.999999, 1e-6)
    assert 0.0 < lowered < 0.999999


def test_invalid_inputs():
    with pytest.raises(ValueError):
        bayes.update_probability(0.5, 0.0)
    with pytest.raises(ValueError):
        bayes.bayes_factor_from_likelihoods(0.5, 0.0)
    with pytest.raises(ValueError):
        bayes.bayes_factor_from_likelihoods(1.5, 0.5)


def test_ledger_update_belief_records_trajectory():
    ledger = BeliefLedger()
    c = ledger.add_commitment(PriorCommitment("incentives raise innovation", 0.8))

    ledger.update_belief(c.id, bayes_factor=0.25, description="anomaly: innovation fell")
    ledger.update_belief(
        c.id,
        likelihood_given_hypothesis=0.2,
        likelihood_given_not_hypothesis=0.6,
        description="replication in second unit",
    )

    assert len(c.updates) == 2
    traj = ledger.belief_trajectory(c.id)
    assert [round(p["probability"], 4) for p in traj][0] == 0.8  # starts at the prior
    assert traj[-1]["probability"] == pytest.approx(c.strength)
    assert c.strength < 0.8  # contrary evidence lowered the credence


def test_update_belief_requires_exactly_one_evidence_form():
    ledger = BeliefLedger()
    c = ledger.add_commitment(PriorCommitment("h", 0.5))
    with pytest.raises(ValueError):
        ledger.update_belief(c.id)  # neither
    with pytest.raises(ValueError):
        ledger.update_belief(c.id, bayes_factor=2.0, likelihood_given_hypothesis=0.5,
                             likelihood_given_not_hypothesis=0.5)  # both


def test_update_belief_survives_persistence(tmp_path):
    ledger = BeliefLedger()
    c = ledger.add_commitment(PriorCommitment("h", 0.5))
    ledger.update_belief(c.id, bayes_factor=4.0, description="strong support")
    path = tmp_path / "ledger.json"
    ledger.save(path)
    loaded = BeliefLedger.load(path)
    lc = loaded.get_commitment(c.id)
    assert lc.strength == pytest.approx(c.strength)
    assert lc.updates[0].bayes_factor == 4.0
    assert lc.updates[0].description == "strong support"
