from idbd_toolkit import InquiryContext, ScriptedInteractor, build_registry


def test_registry_exposes_schemas():
    reg = build_registry(InquiryContext())
    names = set(reg.names())
    assert {"add_doubt", "design_frame", "design_generate_hypotheses"} <= names
    schema = next(s for s in reg.schemas() if s["name"] == "design_frame")
    assert schema["parameters"]["required"] == ["proposed_statement"]


def test_wrappers_are_thin_translation_over_core():
    # a full mini Design session driven entirely through the tool layer
    ctx = InquiryContext(interactor=ScriptedInteractor(answers=["framed via tools"]))
    reg = build_registry(ctx)

    reg.call("add_doubt", {"description": "anomaly X"})
    frame = reg.call("design_frame", {"proposed_statement": "why anomaly X?"})
    assert frame["statement"] == "framed via tools"

    hyps = reg.call(
        "design_generate_hypotheses",
        {"hypotheses": [{"statement": "h1"}, {"statement": "h2"}]},
    )
    assert len(hyps) == 2

    # state and provenance are visible through read tools
    log = reg.call("get_inquiry_log", {})
    ops = [e["operation"] for e in log]
    assert ops == ["design.frame", "design.generate_hypotheses"]

    state = reg.call("get_belief_state", {})
    assert len(state["doubts"]) == 1


def test_tool_calls_record_their_inputs_on_the_log():
    from idbd_toolkit import InquiryContext, InquiryLog, Mode, build_registry
    ctx = InquiryContext()
    reg = build_registry(ctx)
    args = {"seed_anomaly": "a surprise", "seed_pathway": "unexpected_behavior"}
    reg.call("disruption_surface", args)
    ev = ctx.log.events()[-1]
    assert ev.args == args and ev.args is not args  # a copy, not the caller's dict
    assert ctx.call_args is None
    ctx.record("baseline.establish", Mode.AUTO, "outside a tool call")
    assert "args" not in ctx.log.to_list()[-1]  # such events keep the old shape
    assert InquiryLog.from_list(ctx.log.to_list()).events()[0].args == args
