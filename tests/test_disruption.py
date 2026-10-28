import pytest

from idbd_toolkit import (
    AutoInteractor,
    InquiryContext,
    Mode,
    ScriptedInteractor,
)
from idbd_toolkit import Dimension
from idbd_toolkit.phases import (
    DisruptionCandidate,
    DisruptionPhase,
    Pathway,
    dimension_of,
)


def test_each_pathway_maps_to_its_figure2_dimension():
    assert dimension_of(Pathway.NEW_WAYS_OF_DOING) is Dimension.METHODS
    assert dimension_of(Pathway.PERCEIVED_GAPS) is Dimension.THEORIES
    assert dimension_of(Pathway.UNSOLVED_PUZZLES) is Dimension.MODEL
    assert dimension_of(Pathway.UNEXPECTED_BEHAVIOR) is Dimension.PHENOMENON
    assert dimension_of("anomalous_observations") is Dimension.DATA


def test_surface_tags_pathways_seeds_and_dedupes():
    interactor = AutoInteractor()
    ctx = InquiryContext(interactor=interactor)
    dp = DisruptionPhase(ctx)
    cands = dp.surface(
        [
            {"description": "new causal ML makes hidden effects visible",
             "pathway": Pathway.NEW_WAYS_OF_DOING.value},
            {"description": "output fell after rollout",
             "pathway": Pathway.ANOMALOUS_OBSERVATIONS.value},
            {"description": "output fell after rollout",  # duplicate
             "pathway": Pathway.ANOMALOUS_OBSERVATIONS.value},
        ],
        seed_anomaly="a new incentive slowed innovation",
    )
    # 1 seed + 2 unique (duplicate dropped) = 3
    assert len(cands) == 3
    assert cands[0].source == "researcher_seed"
    # dimension derived from pathway during intake
    assert cands[0].dimension == "data"  # seed is anomalous_observations
    assert cands[1].dimension == "methods"  # new_ways_of_doing
    event = ctx.log.by_phase("disruption")[-1]
    assert event.operation == "disruption.surface"
    assert event.mode == Mode.AUTO.value
    assert event.payload["by_pathway"][Pathway.ANOMALOUS_OBSERVATIONS.value] == 2
    assert event.payload["by_dimension"]["data"] == 2


def test_unknown_pathway_rejected():
    ctx = InquiryContext()
    with pytest.raises(ValueError):
        DisruptionPhase(ctx).surface([{"description": "x", "pathway": "made_up"}])


def test_triage_promotes_selected_to_doubts_linked_to_commitments():
    ctx = InquiryContext(interactor=ScriptedInteractor(confirmations=[True]))
    dp = DisruptionPhase(ctx)
    selected = [
        DisruptionCandidate("output fell after rollout",
                            Pathway.ANOMALOUS_OBSERVATIONS.value),
    ]
    doubts = dp.triage(selected, challenged_commitment_ids=["cmt-1"])
    assert len(doubts) == 1
    assert doubts[0].description.startswith("[anomalous_observations]")
    assert doubts[0].related_commitments == ["cmt-1"]
    assert ctx.ledger.open_doubts() == doubts


def test_triage_declined_creates_no_doubts():
    ctx = InquiryContext(interactor=ScriptedInteractor(confirmations=[False]))
    doubts = DisruptionPhase(ctx).triage(
        [{"description": "x", "pathway": Pathway.PERCEIVED_GAPS.value}]
    )
    assert doubts == []
    assert ctx.ledger.open_doubts() == []


def test_surface_needs_an_anomaly_or_a_candidate():
    import pytest
    from idbd_toolkit import InquiryContext, build_registry
    reg = build_registry(InquiryContext())
    with pytest.raises(ValueError):
        reg.call("disruption_surface", {})
    assert len(reg.call("disruption_surface", {"seed_anomaly": "a surprise"})) == 1


def test_surface_records_files_supporting_the_anomaly():
    from idbd_toolkit import InquiryContext, build_registry
    ctx = InquiryContext()
    reg = build_registry(ctx)
    reg.call("disruption_surface", {"seed_anomaly": "a surprise",
                                    "seed_files": ["Board minutes 2019.pdf"]})
    assert ctx.log.events()[-1].payload["seed_files"] == ["Board minutes 2019.pdf"]
    reg.call("disruption_surface", {"seed_anomaly": "another surprise"})
    assert ctx.log.events()[-1].payload["seed_files"] == []
