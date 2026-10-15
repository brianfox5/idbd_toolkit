"""LLM providers for agent assist — bring your own key, choose your provider.

One function, :func:`generate_json`, asks a model for a JSON object matching a
schema, given a system prompt, a set of documents and a text request. Each
provider is reached through its official SDK and its own structured-output
mechanism:

=====================  ======================  ============================  ============
provider               SDK                     structured output             PDFs
=====================  ======================  ============================  ============
``anthropic``          ``anthropic``           ``output_config.format``      native
``openai``             ``openai``              ``response_format`` schema    native
``gemini``             ``google-genai``        ``response_json_schema``      native
``openai_compatible``  ``openai`` + base URL   schema → JSON mode → prompt   text only
=====================  ======================  ============================  ============

``openai_compatible`` covers any service speaking the OpenAI API: Ollama and
other local servers, OpenRouter, Mistral, Groq, Azure, institutional gateways.

Keys: the browser sends the researcher's own key with each request; it is used
for that call and never stored or logged. Only when the server operator allows
it (local installs, by default) does a key from the environment / ``.env`` serve
as a fallback.
"""

from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_OUTPUT_TOKENS = 32000

PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "label": "Anthropic (Claude)", "default_model": "claude-opus-5-5",
        "env": ["ANTHROPIC_API_KEY"], "key_url": "https://console.anthropic.com/settings/keys",
    },
    "openai": {
        "label": "OpenAI", "default_model": "gpt-5",
        "env": ["OPENAI_API_KEY"], "key_url": "https://platform.openai.com/api-keys",
    },
    "gemini": {
        "label": "Google Gemini", "default_model": "gemini-2.5-pro",
        "env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "key_url": "https://aistudio.google.com/apikey",
    },
    "openai_compatible": {
        "label": "OpenAI-compatible endpoint (Ollama, OpenRouter, Mistral, …)",
        "default_model": "", "env": ["OPENAI_COMPATIBLE_API_KEY"], "needs_base_url": True,
        "key_optional": True,  # local servers such as Ollama need no key
        "default_base_url": "http://localhost:11434/v1",
    },
}

# Claude models that accept server-side refusal fallbacks and the effort setting.
_CLAUDE_FALLBACKS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}
_CLAUDE_NO_EFFORT = ("claude-haiku-4", "claude-sonnet-4-5", "claude-3")


class LLMError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Provider:
    name: str
    model: str
    api_key: str | None = None
    base_url: str | None = None

    @property
    def label(self) -> str:
        return PROVIDERS[self.name]["label"]


@dataclass
class Document:
    name: str
    data: bytes
    is_pdf: bool

    def text(self) -> str:
        """Plain text, for models that cannot read PDFs."""
        if not self.is_pdf:
            return self.data.decode("utf-8", errors="replace")
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(self.data))
        pages = [f"[page {i}]\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages, 1)]
        return "\n\n".join(pages)


@dataclass
class Result:
    data: dict[str, Any]
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # e.g. "PDFs sent as extracted text"


# -- configuration ------------------------------------------------------------------
def _load_env_file(path: Path | None) -> None:
    """Read KEY=VALUE lines from a local .env into os.environ (no override)."""
    if path is None or not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _server_key(name: str, env_file: Path | None) -> str | None:
    if env_file is None:
        return None  # server keys not allowed
    _load_env_file(env_file)
    return next((os.environ[v] for v in PROVIDERS[name]["env"] if os.environ.get(v)), None)


def catalog(env_file: Path | None) -> dict[str, Any]:
    """What the browser needs to build the provider picker. Never includes keys —
    only whether the server could supply one."""
    return {
        "server_keys_allowed": env_file is not None,
        "providers": [
            {"name": n, "label": p["label"], "default_model": p["default_model"],
             "needs_base_url": p.get("needs_base_url", False),
             "default_base_url": p.get("default_base_url"),
             "key_optional": p.get("key_optional", False), "key_url": p.get("key_url"),
             "server_key": bool(_server_key(n, env_file))}
            for n, p in PROVIDERS.items()
        ],
    }


def resolve(choice: dict[str, Any], *, env_file: Path | None) -> Provider:
    """Turn the browser's provider choice into a usable :class:`Provider`."""
    name = choice.get("name") or "anthropic"
    if name not in PROVIDERS:
        raise LLMError(f"unknown provider {name!r}", 400)
    spec = PROVIDERS[name]
    model = (choice.get("model") or spec["default_model"] or "").strip()
    if not model:
        raise LLMError(f"choose a model for {spec['label']}", 400)
    # Only OpenAI-compatible endpoints take a base URL; ignore one sent for others.
    base_url = ((choice.get("base_url") or "").strip() or None) if spec.get("needs_base_url") else None
    if spec.get("needs_base_url") and not base_url:
        raise LLMError("enter the endpoint's base URL (e.g. http://localhost:11434/v1)", 400)
    key = (choice.get("api_key") or "").strip() or _server_key(name, env_file)
    if not key and not spec.get("key_optional"):
        raise LLMError(f"enter your {spec['label']} API key in Agent settings", 400)
    return Provider(name=name, model=model, api_key=key, base_url=base_url)


# -- calling a model -------------------------------------------------------------------
def generate_json(provider: Provider, *, system: str, documents: list[Document],
                  text: str, schema: dict[str, Any]) -> Result:
    """Ask ``provider`` for a JSON object conforming to ``schema``."""
    handler = {"anthropic": _anthropic, "openai": _openai, "gemini": _gemini,
               "openai_compatible": _openai}[provider.name]
    return handler(provider, system=system, documents=documents, text=text, schema=schema)


def _parse(raw: str, provider: Provider) -> dict[str, Any]:
    raw = (raw or "").strip()
    if raw.startswith("```"):  # some models fence JSON despite instructions
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise LLMError(f"{provider.label} did not return valid JSON. Try again or "
                       "choose a model that supports structured output.", 502)
    if not isinstance(data, dict):
        raise LLMError(f"{provider.label} returned JSON that is not an object.", 502)
    return data


def _anthropic(provider: Provider, *, system, documents, text, schema) -> Result:
    import anthropic

    blocks: list[dict[str, Any]] = []
    for d in documents:
        source = ({"type": "base64", "media_type": "application/pdf",
                   "data": base64.standard_b64encode(d.data).decode("ascii")} if d.is_pdf
                  else {"type": "text", "media_type": "text/plain", "data": d.text()})
        blocks.append({"type": "document", "title": d.name, "source": source})
    if blocks:
        # Cache the documents: drafting several steps of one project re-sends them.
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    blocks.append({"type": "text", "text": text})

    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
    if not provider.model.startswith(_CLAUDE_NO_EFFORT):
        output_config["effort"] = "high"
    extra: dict[str, Any] = {}
    if provider.model in _CLAUDE_FALLBACKS:
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

    client = anthropic.Anthropic(api_key=provider.api_key)
    try:
        with client.beta.messages.stream(
            model=provider.model, max_tokens=MAX_OUTPUT_TOKENS, system=system,
            messages=[{"role": "user", "content": blocks}],
            output_config=output_config, **extra,
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise LLMError("Anthropic rejected the API key. Check it in Agent settings.", 400)
    except anthropic.PermissionDeniedError as e:
        raise LLMError(f"The Anthropic key lacks permission for this request: {e.message}", 400)
    except anthropic.NotFoundError:
        raise LLMError(f"Anthropic has no model {provider.model!r} for this key.", 400)
    except anthropic.RequestTooLargeError:
        raise LLMError("The reference files are too large to send in one request.", 413)
    except anthropic.RateLimitError:
        raise LLMError("Rate limited by Anthropic. Wait a minute and try again.", 429)
    except anthropic.BadRequestError as e:
        raise LLMError(f"Anthropic rejected the request: {e.message}", 400)
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic returned an error ({e.status_code}). Try again shortly.", 502)
    except anthropic.APIConnectionError:
        raise LLMError("Could not reach Anthropic. Check the network connection.", 502)

    if message.stop_reason == "refusal":
        raise LLMError("The model declined to draft this step.", 422)
    if message.stop_reason == "max_tokens":
        raise LLMError("The draft ran past the output limit. Try narrower guidance.", 422)
    raw = next((b.text for b in message.content if b.type == "text"), "")
    return Result(_parse(raw, provider), model=message.model, usage={
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "cache_read_input_tokens": getattr(message.usage, "cache_read_input_tokens", 0) or 0})


def _openai(provider: Provider, *, system, documents, text, schema) -> Result:
    import openai

    compatible = provider.name == "openai_compatible"
    notes: list[str] = []
    parts: list[dict[str, Any]] = []
    for d in documents:
        if d.is_pdf and not compatible:
            parts.append({"type": "file", "file": {
                "filename": d.name,
                "file_data": "data:application/pdf;base64,"
                             + base64.standard_b64encode(d.data).decode("ascii")}})
        else:
            parts.append({"type": "text", "text": f"<document name=\"{d.name}\">\n{d.text()}\n</document>"})
    if compatible and any(d.is_pdf for d in documents):
        notes.append("PDFs were sent as extracted text (endpoint may not read PDFs).")
    parts.append({"type": "text", "text": text})
    messages = [{"role": "system", "content": system}, {"role": "user", "content": parts}]

    client = openai.OpenAI(api_key=provider.api_key or "not-needed", base_url=provider.base_url)
    formats: list[dict[str, Any] | None] = [
        {"type": "json_schema", "json_schema": {"name": "draft", "schema": schema, "strict": False}}]
    if compatible:  # endpoints vary: fall back to JSON mode, then to the prompt alone
        formats += [{"type": "json_object"}, None]
    schema_hint = ("\n\nRespond with only a JSON object matching this JSON Schema:\n"
                   + json.dumps(schema))
    last_error: Exception | None = None
    for fmt in formats:
        kwargs: dict[str, Any] = {"model": provider.model, "messages": messages}
        if fmt is not None:
            kwargs["response_format"] = fmt
        if fmt is None or fmt["type"] == "json_object":
            kwargs["messages"] = [messages[0], {"role": "user",
                                                "content": parts + [{"type": "text", "text": schema_hint}]}]
        try:
            resp = client.chat.completions.create(**kwargs)
            break
        except openai.BadRequestError as e:
            last_error = e
            if compatible and fmt is not None:
                continue  # this endpoint doesn't accept that response_format; try the next
            raise LLMError(f"{provider.label} rejected the request: {e.message}", 400)
        except openai.AuthenticationError:
            raise LLMError(f"{provider.label} rejected the API key. Check it in Agent settings.", 400)
        except openai.PermissionDeniedError as e:
            raise LLMError(f"The {provider.label} key lacks permission: {e.message}", 400)
        except openai.NotFoundError:
            raise LLMError(f"{provider.label} has no model {provider.model!r} (or the base URL is wrong).", 400)
        except openai.RateLimitError:
            raise LLMError(f"Rate limited by {provider.label}. Wait a minute and try again.", 429)
        except openai.APITimeoutError:
            raise LLMError(f"{provider.label} took too long to respond.", 504)
        except openai.APIConnectionError:
            raise LLMError(f"Could not reach {provider.label}"
                           + (f" at {provider.base_url}" if provider.base_url else "") + ".", 502)
        except openai.APIStatusError as e:
            raise LLMError(f"{provider.label} returned an error ({e.status_code}).", 502)
    else:
        raise LLMError(f"{provider.label} rejected every request format: {last_error}", 400)

    choice = resp.choices[0]
    if getattr(choice.message, "refusal", None):
        raise LLMError("The model declined to draft this step.", 422)
    if choice.finish_reason == "length":
        raise LLMError("The draft ran past the output limit. Try narrower guidance.", 422)
    usage = resp.usage
    return Result(_parse(choice.message.content, provider), model=resp.model or provider.model,
                  usage={"input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                         "output_tokens": getattr(usage, "completion_tokens", 0) or 0},
                  notes=notes)


def _gemini(provider: Provider, *, system, documents, text, schema) -> Result:
    from google import genai
    from google.genai import errors, types

    contents: list[Any] = []
    for d in documents:
        if d.is_pdf:
            contents.append(types.Part.from_bytes(data=d.data, mime_type="application/pdf"))
        else:
            contents.append(f"<document name=\"{d.name}\">\n{d.text()}\n</document>")
    contents.append(text)
    client = genai.Client(api_key=provider.api_key)
    try:
        resp = client.models.generate_content(
            model=provider.model, contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system, response_mime_type="application/json",
                response_json_schema=schema, max_output_tokens=MAX_OUTPUT_TOKENS))
    except errors.ClientError as e:
        if e.code in (401, 403):
            raise LLMError("Google rejected the API key. Check it in Agent settings.", 400)
        if e.code == 404:
            raise LLMError(f"Gemini has no model {provider.model!r} for this key.", 400)
        if e.code == 429:
            raise LLMError("Rate limited by Google. Wait a minute and try again.", 429)
        raise LLMError(f"Gemini rejected the request: {e.message}", 400)
    except errors.APIError as e:
        raise LLMError(f"Gemini returned an error ({e.code}). Try again shortly.", 502)
    if not resp.text:
        reason = resp.candidates[0].finish_reason if resp.candidates else "no candidates"
        raise LLMError(f"Gemini returned no draft ({reason}).", 422)
    meta = resp.usage_metadata
    return Result(_parse(resp.text, provider), model=provider.model, usage={
        "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(meta, "candidates_token_count", 0) or 0})


# -- model discovery --------------------------------------------------------------------
def list_models(provider: Provider) -> list[str]:
    """Model ids available to this key (so the picker isn't limited to our defaults)."""
    try:
        if provider.name == "anthropic":
            import anthropic
            return [m.id for m in anthropic.Anthropic(api_key=provider.api_key).models.list()]
        if provider.name in ("openai", "openai_compatible"):
            import openai
            client = openai.OpenAI(api_key=provider.api_key or "not-needed", base_url=provider.base_url)
            return sorted(m.id for m in client.models.list())
        from google import genai
        return sorted(m.name.removeprefix("models/")
                      for m in genai.Client(api_key=provider.api_key).models.list()
                      if "generateContent" in (m.supported_actions or []))
    except Exception as e:  # any provider failure: report, don't crash the request
        raise LLMError(f"Could not list {provider.label} models: {e}", 400)
