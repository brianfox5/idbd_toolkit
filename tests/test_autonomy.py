from idbd_toolkit import autonomy
from idbd_toolkit.autonomy import Mode, Phase, phase_of, resolve_mode


def test_operation_default_beats_phase_default():
    # disruption phase default is AUTO, but the triage operation is CHECKPOINT
    assert resolve_mode("disruption.triage") is Mode.CHECKPOINT
    assert resolve_mode("disruption.surface") is Mode.AUTO


def test_phase_default_fallback_for_unregistered_operation():
    assert resolve_mode("development.something_new") is Mode.AUTO
    assert resolve_mode("doubt.anything") is Mode.INTERACTIVE


def test_override_wins():
    assert resolve_mode("disruption.surface", Mode.INTERACTIVE) is Mode.INTERACTIVE


def test_unknown_phase_falls_back_to_interactive():
    assert resolve_mode("mystery.op") is Mode.INTERACTIVE


def test_phase_of():
    assert phase_of("design.frame") is Phase.DESIGN


def test_set_default_is_tunable():
    original = resolve_mode("execution.run")
    try:
        autonomy.set_default("execution.run", Mode.CHECKPOINT)
        assert resolve_mode("execution.run") is Mode.CHECKPOINT
    finally:
        autonomy.set_default("execution.run", original)
