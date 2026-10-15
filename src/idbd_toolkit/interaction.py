"""The interaction seam between core and client.

Phase operations never talk to a terminal, an LLM, or a browser directly; they
call an ``Interactor``. The agent toolkit supplies one implementation, the
future web app another, and tests a scripted one — while the phase logic stays
in the core exactly once. This is the rule that makes "agent now, web app later"
free: keep interaction here, keep logic in the phases.
"""

from __future__ import annotations

from typing import Any, Protocol


class Interactor(Protocol):
    """How the core reaches the researcher (or an agent acting for them)."""

    def notify(self, message: str) -> None:
        """One-way status message (AUTO operations report progress this way)."""

    def confirm(self, prompt: str, *, context: dict[str, Any] | None = None) -> bool:
        """Go/no-go decision at a CHECKPOINT boundary."""

    def ask(self, prompt: str, *, context: dict[str, Any] | None = None) -> str:
        """Open-ended input for INTERACTIVE co-production."""


class AutoInteractor:
    """Non-interactive default: auto-approves checkpoints, records notifications.

    Suitable for AUTO operations and headless runs. ``ask`` raises, because an
    operation that needs open-ended human input should not be running unattended
    — that is a sign its mode was mis-set.
    """

    def __init__(self) -> None:
        self.notifications: list[str] = []

    def notify(self, message: str) -> None:
        self.notifications.append(message)

    def confirm(self, prompt: str, *, context: dict[str, Any] | None = None) -> bool:
        return True

    def ask(self, prompt: str, *, context: dict[str, Any] | None = None) -> str:
        raise RuntimeError(
            f"AutoInteractor cannot answer an INTERACTIVE prompt: {prompt!r}"
        )


class ScriptedInteractor:
    """Test/replay interactor driven by queued answers and confirmations."""

    def __init__(
        self,
        answers: list[str] | None = None,
        confirmations: list[bool] | None = None,
    ) -> None:
        self._answers = list(answers or [])
        self._confirmations = list(confirmations or [])
        self.notifications: list[str] = []

    def notify(self, message: str) -> None:
        self.notifications.append(message)

    def confirm(self, prompt: str, *, context: dict[str, Any] | None = None) -> bool:
        if not self._confirmations:
            raise AssertionError(f"no scripted confirmation for prompt: {prompt!r}")
        return self._confirmations.pop(0)

    def ask(self, prompt: str, *, context: dict[str, Any] | None = None) -> str:
        if not self._answers:
            raise AssertionError(f"no scripted answer for prompt: {prompt!r}")
        return self._answers.pop(0)


class InputRequired(Exception):
    """Raised when an operation needs human input the client has not yet supplied.

    Carries the core's own prompt so a client (e.g. the browser) can put the exact
    question to the researcher, then replay the call with the answer appended.
    ``kind`` is ``"ask"`` (INTERACTIVE, open-ended) or ``"confirm"`` (CHECKPOINT).
    """

    def __init__(self, kind: str, prompt: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(prompt)
        self.kind = kind
        self.prompt = prompt
        self.context = context or {}

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "prompt": self.prompt, "context": self.context}


class DeferredInteractor(ScriptedInteractor):
    """Replay interactor for request/response clients.

    Consumes the answers/confirmations gathered so far; when it runs dry it raises
    :class:`InputRequired` with the pending prompt instead of failing, so the client
    can collect the input and resend the whole call.
    """

    def confirm(self, prompt: str, *, context: dict[str, Any] | None = None) -> bool:
        if not self._confirmations:
            raise InputRequired("confirm", prompt, context)
        return self._confirmations.pop(0)

    def ask(self, prompt: str, *, context: dict[str, Any] | None = None) -> str:
        if not self._answers:
            raise InputRequired("ask", prompt, context)
        return self._answers.pop(0)
