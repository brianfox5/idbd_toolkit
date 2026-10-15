from idbd_toolkit import InquiryBrief, InquiryContext, build_registry
from idbd_toolkit.intake import Intake


def test_record_logs_brief_as_origin():
    ctx = InquiryContext()
    brief = InquiryBrief(
        domain="team incentives and innovation",
        belief_summary="Stronger incentives are believed to raise innovation.",
        initiating_anomaly="A new team incentive slowed innovation.",
        references=["George et al. 2014"],
        researcher="B. Fox",
    )
    Intake(ctx).record(brief)
    event = ctx.log.events()[0]
    assert event.phase == "intake"
    assert event.operation == "intake.received"
    assert event.payload["brief"]["domain"] == "team incentives and innovation"


def test_from_markdown_parses_sections_and_references():
    md = """# IDBD Inquiry Brief

## Domain
team incentives and innovation

## Researcher
B. Fox

## Current belief summary
Stronger incentives raise innovation output.
This is the agency-theoretic prior.

## References
- George et al. 2014
- Lazer et al. 2009

## Initiating anomaly
A new team incentive paradoxically slowed innovation.
"""
    brief = InquiryBrief.from_markdown(md)
    assert brief.domain == "team incentives and innovation"
    assert brief.researcher == "B. Fox"
    assert "agency-theoretic prior" in brief.belief_summary
    assert brief.references == ["George et al. 2014", "Lazer et al. 2009"]
    assert brief.initiating_anomaly.startswith("A new team incentive")


def test_brief_round_trips_through_json(tmp_path):
    brief = InquiryBrief("d", "b", "a", references=["r1"])
    path = tmp_path / "brief.json"
    brief.save(path)
    assert InquiryBrief.load(path).to_dict() == brief.to_dict()


def test_record_brief_tool():
    ctx = InquiryContext()
    reg = build_registry(ctx)
    out = reg.call("record_brief", {
        "domain": "d", "belief_summary": "b", "initiating_anomaly": "a",
    })
    assert out["domain"] == "d"
    assert ctx.log.by_phase("intake")[0].operation == "intake.received"


def test_anomaly_is_optional_and_seed_pathway_is_settable():
    from idbd_toolkit import InquiryContext, build_registry
    ctx = InquiryContext()
    reg = build_registry(ctx)
    assert "initiating_anomaly" not in reg.get("record_brief").parameters["required"]
    brief = reg.call("record_brief", {"domain": "PE", "belief_summary": "b"})
    assert brief["initiating_anomaly"] == ""
    out = reg.call("disruption_surface", {"seed_anomaly": "worse outcomes",
                                          "seed_pathway": "unexpected_behavior"})
    assert out[0]["pathway"] == "unexpected_behavior" and out[0]["source"] == "researcher_seed"
    assert out[0]["dimension"] == "phenomenon"


def test_markdown_heading_tolerates_optional_suffix():
    b = InquiryBrief.from_markdown("## Domain\nPE\n## Current belief summary\nb\n"
                                   "## Initiating anomaly (optional)\nsurprise\n")
    assert b.initiating_anomaly == "surprise"
