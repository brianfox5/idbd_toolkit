"""Agent assist: prompt/context building, the four providers, BYOK endpoints.

Every provider SDK is replaced by a fake that records the request, so these run
offline and cost nothing.
"""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

pytest.importorskip("anthropic")
pytest.importorskip("fastapi")
import anthropic  # noqa: E402
import httpx  # noqa: E402
import openai  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from idbd_toolkit import BeliefLedger, Doubt, InquiryContext, InquiryLog, Mode, build_registry  # noqa: E402
from idbd_toolkit.intake import InquiryBrief, Intake  # noqa: E402
from idbd_toolkit.web import assist, create_app, llm  # noqa: E402

HDR = {"X-Requested-With": "idbd"}
BASELINE = {"args": {"bam_description": "PE ownership raises efficiency",
                     "commitments": [{"statement": "PE improves operations", "strength": 0.6,
                                      "origin": "agent_estimated", "origin_note": "doc 1"}]},
            "notes": "Drawn from the attached report."}


def _tool(name="establish_baseline"):
    return build_registry(InquiryContext()).get(name).schema()


# -- fakes ----------------------------------------------------------------------------
class FakeAnthropic:
    def __init__(self, reply, stop_reason="end_turn"):
        self.reply, self.stop_reason, self.calls = reply, stop_reason, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    @contextmanager
    def _stream(self, **kw):
        self.calls.append(kw)
        msg = SimpleNamespace(
            stop_reason=self.stop_reason, model=kw["model"],
            content=[SimpleNamespace(type="text", text=json.dumps(self.reply))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0))
        yield SimpleNamespace(get_final_message=lambda: msg)


class FakeOpenAI:
    """Replies with ``replies`` in turn; an Exception instance is raised instead."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(model=kw["model"], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                               choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
                                   content=json.dumps(reply), refusal=None))])


def _bad_request(msg="response_format not supported"):
    req = httpx.Request("POST", "http://x/v1/chat/completions")
    return openai.BadRequestError(msg, response=httpx.Response(400, request=req), body=None)


def _ctx_with_brief():
    ctx = InquiryContext()
    Intake(ctx).record(InquiryBrief(domain="PE", belief_summary="PE improves efficiency",
                                    initiating_anomaly="PE-owned hospitals have worse outcomes"))
    return ctx


def _docs(tmp_path):
    pdf = tmp_path / "Report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    notes = tmp_path / "notes.txt"
    notes.write_text("my notes")
    other = tmp_path / "slides.pptx"
    other.write_bytes(b"x")
    return [pdf, notes, other]


# -- prompt and schema ------------------------------------------------------------------
def test_output_schema_is_strict_and_constraint_free():
    schema = assist.output_schema(_tool()["parameters"])
    args = schema["properties"]["args"]
    item = args["properties"]["commitments"]["items"]
    assert schema["additionalProperties"] is False and item["additionalProperties"] is False
    assert "minimum" not in item["properties"]["strength"]


def test_anthropic_request_documents_caching_and_fallbacks(tmp_path, monkeypatch):
    fake = FakeAnthropic(BASELINE)
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key=None: fake)
    out = assist.draft(InquiryContext(), _tool(), reference_paths=_docs(tmp_path),
                       current_draft={"bam_description": "my start"}, guidance="be brief",
                       provider=llm.Provider("anthropic", "claude-opus-5-5", "sk-test"))
    assert out["args"]["commitments"][0]["origin"] == "agent_estimated"
    assert out["provider"] == "Anthropic (Claude)"
    assert out["skipped"] == ["slides.pptx (file type not readable by the agent; use PDF or text)"]
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert call["output_config"]["format"]["type"] == "json_schema"
    blocks = call["messages"][0]["content"]
    assert blocks[0]["source"]["media_type"] == "application/pdf"
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}
    assert "my start" in blocks[-1]["text"] and "be brief" in blocks[-1]["text"]


def test_older_claude_models_skip_unsupported_parameters(monkeypatch):
    fake = FakeAnthropic(BASELINE)
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key=None: fake)
    assist.draft(InquiryContext(), _tool(), reference_paths=[],
                 provider=llm.Provider("anthropic", "claude-haiku-4-5", "k"))
    assert "fallbacks" not in fake.calls[0] and "effort" not in fake.calls[0]["output_config"]


def test_refusal_and_truncation_are_reported(monkeypatch):
    for stop in ("refusal", "max_tokens"):
        monkeypatch.setattr(anthropic, "Anthropic", lambda api_key=None, s=stop: FakeAnthropic(BASELINE, s))
        with pytest.raises(llm.LLMError):
            assist.draft(InquiryContext(), _tool(), reference_paths=[],
                         provider=llm.Provider("anthropic", "claude-opus-5-5", "k"))


def test_openai_sends_pdfs_natively_with_a_json_schema(tmp_path, monkeypatch):
    fake = FakeOpenAI(BASELINE)
    monkeypatch.setattr(openai, "OpenAI", lambda api_key=None, base_url=None: fake)
    out = assist.draft(InquiryContext(), _tool(), reference_paths=_docs(tmp_path)[:1],
                       provider=llm.Provider("openai", "gpt-5", "sk-test"))
    assert out["args"]["bam_description"].startswith("PE")
    call = fake.calls[0]
    assert call["response_format"]["type"] == "json_schema"
    parts = call["messages"][1]["content"]
    assert parts[0]["type"] == "file" and parts[0]["file"]["file_data"].startswith("data:application/pdf;base64,")


def test_compatible_endpoint_falls_back_and_uses_pdf_text(tmp_path, monkeypatch):
    fake = FakeOpenAI(_bad_request(), BASELINE)  # endpoint rejects json_schema, accepts JSON mode
    seen = {}
    monkeypatch.setattr(openai, "OpenAI", lambda api_key=None, base_url=None: (seen.update(url=base_url), fake)[1])
    monkeypatch.setattr(llm.Document, "text", lambda self: "EXTRACTED TEXT")
    out = assist.draft(InquiryContext(), _tool(), reference_paths=_docs(tmp_path)[:1],
                       provider=llm.Provider("openai_compatible", "llama3.1", None,
                                             "http://localhost:11434/v1"))
    assert seen["url"] == "http://localhost:11434/v1"
    assert [c.get("response_format", {}).get("type") for c in fake.calls] == ["json_schema", "json_object"]
    assert "EXTRACTED TEXT" in json.dumps(fake.calls[1]["messages"])
    assert any("extracted text" in s for s in out["skipped"])


def test_invalid_draft_gets_one_corrective_retry(monkeypatch):
    bad = {"args": {"commitments": "not a list"}, "notes": ""}
    fake = FakeOpenAI(bad, BASELINE)
    monkeypatch.setattr(openai, "OpenAI", lambda api_key=None, base_url=None: fake)
    out = assist.draft(InquiryContext(), _tool(), reference_paths=[],
                       provider=llm.Provider("openai", "gpt-5", "k"))
    assert out["args"]["commitments"][0]["strength"] == 0.6
    assert "did not match the required JSON Schema" in json.dumps(fake.calls[1]["messages"])
    fake2 = FakeOpenAI(bad, bad)
    monkeypatch.setattr(openai, "OpenAI", lambda api_key=None, base_url=None: fake2)
    with pytest.raises(llm.LLMError, match="required shape"):
        assist.draft(InquiryContext(), _tool(), reference_paths=[],
                     provider=llm.Provider("openai", "gpt-5", "k"))


def test_gemini_request(tmp_path, monkeypatch):
    from google import genai
    calls = []

    class FakeModels:
        def generate_content(self, **kw):
            calls.append(kw)
            return SimpleNamespace(text=json.dumps(BASELINE), candidates=[],
                                   usage_metadata=SimpleNamespace(prompt_token_count=7, candidates_token_count=3))

    monkeypatch.setattr(genai, "Client", lambda api_key=None: SimpleNamespace(models=FakeModels()))
    out = assist.draft(InquiryContext(), _tool(), reference_paths=_docs(tmp_path)[:1],
                       provider=llm.Provider("gemini", "gemini-2.5-pro", "g-key"))
    assert out["usage"] == {"input_tokens": 7, "output_tokens": 3}
    cfg = calls[0]["config"]
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema["type"] == "object"
    assert calls[0]["contents"][0].inline_data.mime_type == "application/pdf"


def test_baseline_is_drafted_blind_to_the_anomaly(monkeypatch):
    ctx = _ctx_with_brief()
    ctx.record("disruption.surface", Mode.AUTO, "surfaced 1",
               {"candidates": [{"description": "PE-owned hospitals have worse outcomes"}]})
    ctx.ledger.add_doubt(Doubt("outcomes may suffer"))
    fake = FakeAnthropic(BASELINE)
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key=None: fake)
    p = llm.Provider("anthropic", "claude-opus-5-5", "k")
    assist.draft(ctx, _tool(), reference_paths=[], provider=p)
    sent = fake.calls[0]["messages"][0]["content"][-1]["text"]
    assert "worse outcomes" not in sent and "outcomes may suffer" not in sent
    assert "PE improves efficiency" in sent and "deliberately not" in sent
    fake.reply = {"args": {}, "notes": ""}
    assist.draft(ctx, _tool("disruption_surface"), reference_paths=[], provider=p)
    assert "worse outcomes" in fake.calls[1]["messages"][0]["content"][-1]["text"]


# -- key resolution -----------------------------------------------------------------------
def test_resolve_bring_your_own_key(tmp_path, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    with pytest.raises(llm.LLMError, match="API key"):
        llm.resolve({"name": "anthropic"}, env_file=None)
    p = llm.resolve({"name": "openai", "api_key": " sk-mine "}, env_file=None)
    assert (p.api_key, p.model) == ("sk-mine", "gpt-5")
    with pytest.raises(llm.LLMError, match="base URL"):
        llm.resolve({"name": "openai_compatible", "model": "llama3.1"}, env_file=None)
    p = llm.resolve({"name": "openai_compatible", "model": "llama3.1",
                     "base_url": "http://localhost:11434/v1"}, env_file=None)
    assert p.api_key is None  # local servers need no key
    # the server's .env is only consulted when the operator allows it
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-server\n")
    with pytest.raises(llm.LLMError):
        llm.resolve({"name": "anthropic"}, env_file=None)
    assert llm.resolve({"name": "anthropic"}, env_file=env).api_key == "sk-server"
    cat = llm.catalog(env)
    assert next(x for x in cat["providers"] if x["name"] == "anthropic")["server_key"] is True
    assert "sk-server" not in json.dumps(cat)  # never reveal keys


# -- endpoints ----------------------------------------------------------------------------
def _site(tmp_path, mode="local"):
    ex = tmp_path / "ex"
    ex.mkdir()
    BeliefLedger().save(ex / "final_ledger.json")
    InquiryLog().save(ex / "final_inquiry_log.json")
    kw = {"sessions_dir": tmp_path / "s"} if mode == "local" else {"data_dir": tmp_path / "var"}
    return TestClient(create_app(mode=mode, pristine_dir=ex, env_file=None,
                                 cookie_secure=False, **kw), headers=HDR)


def test_assist_endpoint_uses_the_key_from_the_request(tmp_path, monkeypatch):
    c = _site(tmp_path)
    slug = c.post("/api/sessions", json={"name": "PE"}).json()["session"]["slug"]
    p = f"/api/p/{slug}"
    c.post(f"{p}/references", params={"filename": "Report.pdf"}, content=b"%PDF-1.4")
    c.post(f"{p}/tools/record_brief", json={"args": {
        "domain": "PE", "belief_summary": "b", "references": ["Smith (2020)"],
        "reference_files": ["Report.pdf"]}})
    r = c.post(f"{p}/assist/establish_baseline", json={"provider": {"name": "anthropic"}})
    assert r.status_code == 400 and "API key" in r.json()["detail"]
    keys = []
    fake = FakeAnthropic(BASELINE)
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key=None: (keys.append(api_key), fake)[1])
    r = c.post(f"{p}/assist/establish_baseline", json={
        "guidance": "focus on outcomes",
        "provider": {"name": "anthropic", "api_key": "sk-user-own"}})
    assert r.status_code == 200 and r.json()["args"]["bam_description"].startswith("PE")
    assert keys == ["sk-user-own"]
    titles = [b.get("title") for b in fake.calls[0]["messages"][0]["content"]]
    assert "Report.pdf" in titles
    assert [e["operation"] for e in c.get(f"{p}/log").json()] == ["intake.received"]  # nothing recorded
    assert c.post("/api/p/example-tmt-diversity/assist/establish_baseline",
                  json={"provider": {"name": "anthropic", "api_key": "k"}}).status_code == 403
    cat = c.get("/api/assist").json()
    assert {x["name"] for x in cat["providers"]} == {"anthropic", "openai", "gemini", "openai_compatible"}


def test_server_mode_requires_login_for_the_agent(tmp_path):
    c = _site(tmp_path, mode="server")
    assert c.get("/api/assist").json()["server_keys_allowed"] is False
    assert c.post("/api/assist/models", json={"name": "openai", "api_key": "k"}).status_code == 401


def test_base_url_is_ignored_for_providers_that_do_not_use_one():
    p = llm.resolve({"name": "openai", "api_key": "k", "base_url": "http://localhost:11434/v1"},
                    env_file=None)
    assert p.base_url is None
