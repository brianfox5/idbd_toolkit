"""FastAPI server exposing the IDBD core as a REST API + guided workspace.

Every project endpoint is a thin pass-through to that project's
``InquiryContext`` and ``ToolRegistry``: the web app calls exactly the tools the
agent calls. The only web-specific piece is binding a per-request
``DeferredInteractor`` (seeded from the request body) so INTERACTIVE/CHECKPOINT
operations can collect human input over HTTP — the same seam, a different
implementation.

The input protocol: when an operation reaches a prompt the browser has not yet
answered, the core raises ``InputRequired``; the server rolls the call back and
returns 409 with the core's own prompt. The browser puts that question to the
researcher and replays the call with the answer appended. Calls are therefore
all-or-nothing: a paused or failed call never leaves half-applied state.

Projects are addressed explicitly (``/api/p/<project>/…``), so there is no
server-wide "open project" for browsers to collide on. Where projects live and
who may touch them is decided by :mod:`.workspaces` (local vs server mode) and
:mod:`.auth` (accounts, in server mode).

Configuration (environment variables; all optional in local mode):

=====================  ==========================================================
``IDBD_MODE``          ``local`` (default: no login, one workspace) or ``server``
``IDBD_DATA_DIR``      server mode: users, secret key, per-user workspaces
``IDBD_SESSIONS_DIR``  local mode: the projects folder (default ``./sessions``)
``IDBD_EXAMPLE_DIR``   where the worked example's ``final_*`` files live
``IDBD_ROOT_PATH``     URL prefix when served under a subdirectory, e.g. ``/idbd``
``IDBD_HOST/PORT``     bind address (default 127.0.0.1:8000)
``IDBD_COOKIE_SECURE`` ``0`` to allow login over plain http (default: https only)
``IDBD_MAX_PROJECTS``  server mode: projects per user (default 50)
``IDBD_QUOTA_MB``      server mode: storage per user (default 1000)
``IDBD_SERVER_KEYS``   ``1`` to let the agent fall back to API keys in the
                       server's environment / ``.env`` (default: local mode only)
=====================  ==========================================================
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from ..context import InquiryContext
from ..inquiry_log import InquiryLog
from ..interaction import DeferredInteractor, InputRequired
from ..ledger import BeliefLedger
from ..progress import cycle_progress
from ..tools import build_registry
from .auth import COOKIE_NAME, SESSION_SECONDS, AuthError, User, UserStore
from .sessions import ReadOnlyProject, SessionStore, slugify
from .workspaces import ProjectHandle, Workspaces

_STATIC = Path(__file__).parent / "static"
# Anchored to the project folder (not the launch directory), so where data is
# kept never depends on where the server was started from.
_PROJECT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT / ".env"  # optional API keys (local fallback for the agent)
_PRISTINE = ("final_ledger.json", "final_inquiry_log.json")
EXAMPLE_SLUG = "example-tmt-diversity"
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
LOCAL_USER = User(username="local", role="admin", display_name="Local user")


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


def _example_projects(pristine_dir: Path | None) -> list[ReadOnlyProject]:
    """The worked example, served read-only straight from its ``final_*`` files."""
    if pristine_dir is None:
        return []
    return [ReadOnlyProject(
        slug=EXAMPLE_SLUG,
        name="TMT diversity (worked example)",
        description=("The full IDBD cycle run end to end on TMT diversity → firm "
                     "performance (Revelio + Compustat). Read-only: duplicate it to "
                     "experiment."),
        ledger_path=pristine_dir / _PRISTINE[0],
        log_path=pristine_dir / _PRISTINE[1],
        references_dir=pristine_dir.parent / "references",
    )]


# -- request bodies (module level: FastAPI resolves annotations against globals) --
class ToolCall(BaseModel):
    """Body for a tool invocation; answers/confirmations feed the web Interactor."""

    args: dict[str, Any] = {}
    answers: list[str] | None = None
    confirmations: list[bool] | None = None


class NewSession(BaseModel):
    """Start a new project: blank, from the worked example, or a copy of another."""

    name: str = ""
    description: str = ""
    source: Literal["blank", "worked_example", "duplicate"] = "blank"
    from_slug: str | None = None


class ProviderChoice(BaseModel):
    name: str = "anthropic"
    model: str | None = None
    api_key: str | None = None  # bring-your-own key: used for this call only
    base_url: str | None = None  # OpenAI-compatible endpoints


class AssistRequest(BaseModel):
    guidance: str = ""
    draft: dict[str, Any] | None = None  # what the researcher has typed so far
    provider: ProviderChoice = ProviderChoice()


class Draft(BaseModel):
    args: dict[str, Any] | None = None  # None clears the draft


class EditSession(BaseModel):
    name: str | None = None
    description: str | None = None


class Login(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current: str
    new: str


class NewUser(BaseModel):
    username: str
    password: str
    role: Literal["admin", "researcher"] = "researcher"
    display_name: str = ""


class UserUpdate(BaseModel):
    role: Literal["admin", "researcher"] | None = None
    active: bool | None = None
    display_name: str | None = None
    password: str | None = None


def create_app(
    *,
    mode: str | None = None,
    sessions_dir: Path | None = None,
    data_dir: Path | None = None,
    pristine_dir: Path | None = None,
    env_file: Path | None = _ENV_FILE,
    cookie_secure: bool | None = None,
):
    """Build the app. Arguments override the ``IDBD_*`` environment variables."""
    mode = mode or os.environ.get("IDBD_MODE", "local")
    pristine_dir = pristine_dir or Path(os.environ.get(
        "IDBD_EXAMPLE_DIR", _PROJECT / "examples" / "data"))
    read_only = _example_projects(pristine_dir if pristine_dir.exists() else None)
    users: UserStore | None = None
    if mode == "server":
        data_dir = Path(data_dir or os.environ.get("IDBD_DATA_DIR", _PROJECT / "var"))
        users = UserStore(data_dir)
        ws = Workspaces(mode="server", root=data_dir / "workspaces", read_only=read_only)
    else:
        sessions_dir = Path(sessions_dir or os.environ.get(
            "IDBD_SESSIONS_DIR", _PROJECT / "sessions"))
        ws = Workspaces(mode="local", root=sessions_dir, read_only=read_only)
    secure = cookie_secure if cookie_secure is not None else _env_flag("IDBD_COOKIE_SECURE", True)
    server_keys = _env_flag("IDBD_SERVER_KEYS", mode == "local")
    max_projects = int(os.environ.get("IDBD_MAX_PROJECTS", "50"))
    quota_bytes = int(os.environ.get("IDBD_QUOTA_MB", "1000")) * 1024 * 1024
    schemas = build_registry(InquiryContext()).schemas()  # tool shapes don't depend on state

    app = FastAPI(title="IDBD Toolkit")

    # -- guards ------------------------------------------------------------------
    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        """Mutations must carry a header a cross-site form cannot set."""
        if request.method in _MUTATING and request.headers.get("x-requested-with") != "idbd":
            return JSONResponse(status_code=403, content={"detail": "missing request header"})
        return await call_next(request)

    def _user(request: Request) -> User | None:
        if users is None:
            return LOCAL_USER
        return users.resolve(request.cookies.get(COOKIE_NAME))

    def _owner(user: User | None) -> str | None:
        return None if user is None or users is None else user.username

    def _require_user(request: Request) -> User:
        user = _user(request)
        if user is None:
            raise HTTPException(401, "log in to do this")
        return user

    def _require_admin(request: Request) -> User:
        user = _require_user(request)
        if users is None or user.role != "admin":
            raise HTTPException(403, "administrators only")
        return user

    def _store(request: Request, *, write: bool = False) -> SessionStore:
        user = _require_user(request) if write else _user(request)
        return ws.store_for(_owner(user))

    def _project(request: Request, slug: str, *, write: bool = False) -> ProjectHandle:
        user = _require_user(request) if write else _user(request)
        try:
            h = ws.handle(_owner(user), slug)
        except KeyError:
            raise HTTPException(404, f"no project {slug!r}")
        if write and h.read_only:
            raise HTTPException(403, f"{h.store.meta(slug)['name']} is read-only — "
                                     "make an editable copy to work on it")
        return h

    def _snapshot(h: ProjectHandle) -> dict[str, Any]:
        return {"state": h.ctx.ledger.to_dict(),
                "progress": cycle_progress(h.ctx.ledger, h.ctx.log),
                "session": h.store.meta(h.slug)}

    def _workspace_bytes(store: SessionStore) -> int:
        return sum(f.stat().st_size for f in store.root.rglob("*") if f.is_file())

    # -- page ----------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> str:
        # <base> makes every relative URL in the page resolve under the prefix the
        # app is served at (e.g. /idbd/), so it works in a subdirectory unchanged.
        root = request.scope.get("root_path", "").rstrip("/")
        html = (_STATIC / "index.html").read_text(encoding="utf-8")
        return html.replace("<head>", f'<head>\n<base href="{root}/">', 1)

    # -- identity ------------------------------------------------------------------
    @app.get("/api/me")
    def me(request: Request) -> dict[str, Any]:
        user = _user(request)
        return {"mode": mode, "user": user.public() if user else None,
                "can_edit": user is not None}

    @app.post("/api/login")
    def login(body: Login, request: Request):
        if users is None:
            raise HTTPException(400, "this server runs without accounts (local mode)")
        try:
            user = users.authenticate(body.username, body.password,
                                      client=request.client.host if request.client else "")
        except AuthError as e:
            raise HTTPException(e.status, str(e))
        resp = JSONResponse({"user": user.public()})
        resp.set_cookie(COOKIE_NAME, users.issue(user), max_age=SESSION_SECONDS, httponly=True,
                        samesite="lax", secure=secure,
                        path=(request.scope.get("root_path", "").rstrip("/") or "") + "/")
        return resp

    @app.post("/api/logout")
    def logout(request: Request):
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE_NAME,
                           path=(request.scope.get("root_path", "").rstrip("/") or "") + "/")
        return resp

    @app.post("/api/me/password")
    def change_password(body: PasswordChange, request: Request) -> dict[str, Any]:
        user = _require_user(request)
        if users is None:
            raise HTTPException(400, "no accounts in local mode")
        try:
            users.authenticate(user.username, body.current)
            users.update(user.username, password=body.new)
        except AuthError as e:
            raise HTTPException(e.status, str(e))
        return {"ok": True, "detail": "password changed — log in again"}

    # -- administration ------------------------------------------------------------
    def _admin_row(u: User) -> dict[str, Any]:
        store = ws.store_for(u.username)
        return {**u.public(), "projects": len(store.user_sessions()),
                "storage_mb": round(_workspace_bytes(store) / 1048576, 1)}

    @app.get("/api/admin/users")
    def admin_users(request: Request) -> list[dict[str, Any]]:
        _require_admin(request)
        return [_admin_row(u) for u in users.list()]

    @app.post("/api/admin/users")
    def admin_create(body: NewUser, request: Request) -> dict[str, Any]:
        _require_admin(request)
        try:
            return _admin_row(users.create(body.username, body.password, role=body.role,
                                           display_name=body.display_name))
        except AuthError as e:
            raise HTTPException(e.status, str(e))

    @app.patch("/api/admin/users/{username}")
    def admin_update(username: str, body: UserUpdate, request: Request) -> dict[str, Any]:
        _require_admin(request)
        try:
            return _admin_row(users.update(username, role=body.role, active=body.active,
                                           display_name=body.display_name,
                                           password=body.password))
        except AuthError as e:
            raise HTTPException(e.status, str(e))

    # -- the project list ------------------------------------------------------------
    @app.get("/api/tools")
    def tools() -> list[dict[str, Any]]:
        return schemas

    def _sessions_payload(request: Request) -> dict[str, Any]:
        user = _user(request)
        store = ws.store_for(_owner(user))
        show_root = users is None or (user is not None and user.role == "admin")
        return {
            "saving": user is not None,
            "root": str(store.root) if show_root else None,
            "last_open": store.current() if user is not None else None,
            "sessions": store.list() if user is not None else [
                store.meta(s) for s in ws.read_only_slugs()],
            "trash": store.trash() if user is not None else [],
        }

    @app.get("/api/sessions")
    def sessions(request: Request) -> dict[str, Any]:
        return _sessions_payload(request)

    @app.post("/api/sessions")
    def new_session(body: NewSession, request: Request) -> dict[str, Any]:
        """Create a project. Never overwrites an existing one."""
        st = _store(request, write=True)
        if users is not None and len(st.user_sessions()) >= max_projects:
            raise HTTPException(409, f"project limit reached ({max_projects}); delete one first")
        source_slug = None
        if body.source == "duplicate":
            if not body.from_slug:
                raise HTTPException(400, "say which project to duplicate (from_slug)")
            source_slug = body.from_slug
        elif body.source == "worked_example":
            source_slug = EXAMPLE_SLUG
        if source_slug:
            src = _project(request, source_slug)
            with src.lock:
                ledger = BeliefLedger.from_dict(src.ctx.ledger.to_dict())
                log = InquiryLog.from_list(src.ctx.log.to_list())
            src_name = st.meta(source_slug)["name"]
        else:
            ledger, log, src_name = BeliefLedger(), InquiryLog(), None
        default = {"blank": "untitled inquiry", "worked_example": "worked example",
                   "duplicate": f"{src_name} copy"}[body.source]
        name = body.name.strip() or st.unique_name(default)
        try:
            slugify(name)
            origin = (f"duplicate of {src_name}" if body.source == "duplicate" else body.source)
            meta = st.create(name, ledger, log, origin=origin, description=body.description)
            if source_slug:
                st.copy_references(source_slug, meta["slug"])
        except FileExistsError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        st.set_current(meta["slug"])
        return {"session": meta, "sessions": _sessions_payload(request)}

    @app.post("/api/sessions/{slug}/open")
    def open_session(slug: str, request: Request) -> dict[str, Any]:
        """Note a project as the user's last opened (for the landing page)."""
        h = _project(request, slug)
        if _user(request) is not None:
            h.store.set_current(slug)
        return {"session": h.store.meta(slug)}

    @app.patch("/api/sessions/{slug}")
    def edit_session(slug: str, body: EditSession, request: Request) -> dict[str, Any]:
        try:
            _store(request, write=True).edit(slug, name=body.name, description=body.description)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except KeyError:
            raise HTTPException(404, f"no project {slug!r}")
        except FileExistsError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _sessions_payload(request)

    @app.delete("/api/sessions/{slug}")
    def delete_session(slug: str, request: Request) -> dict[str, Any]:
        """Move a project to the trash (restorable)."""
        user = _require_user(request)
        try:
            ws.store_for(_owner(user)).delete(slug)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except KeyError:
            raise HTTPException(404, f"no project {slug!r}")
        ws.forget(_owner(user), slug)
        return _sessions_payload(request)

    @app.post("/api/sessions/trash/{trash_id}/restore")
    def restore_session(trash_id: str, request: Request) -> dict[str, Any]:
        user = _require_user(request)
        try:
            meta = ws.store_for(_owner(user)).restore(trash_id)
        except KeyError as e:
            raise HTTPException(404, str(e))
        ws.forget(_owner(user), meta["slug"])
        return _sessions_payload(request)

    # -- one project: state, steps ---------------------------------------------------
    @app.get("/api/p/{slug}/state")
    def state(slug: str, request: Request) -> dict[str, Any]:
        h = _project(request, slug)
        with h.lock:
            return h.ctx.ledger.to_dict()

    @app.get("/api/p/{slug}/log")
    def log(slug: str, request: Request) -> list[dict[str, Any]]:
        h = _project(request, slug)
        with h.lock:
            return h.ctx.log.to_list()

    @app.get("/api/p/{slug}/progress")
    def progress(slug: str, request: Request, cycle: int | None = None) -> dict[str, Any]:
        h = _project(request, slug)
        with h.lock:
            try:
                return cycle_progress(h.ctx.ledger, h.ctx.log, cycle)
            except ValueError as e:
                raise HTTPException(404, str(e))

    @app.get("/api/p/{slug}/version")
    def version(slug: str, request: Request) -> dict[str, Any]:
        """Cheap change token for polling clients (ledger version + log length)."""
        h = _project(request, slug)
        with h.lock:
            return {"ledger_version": h.ctx.ledger.version, "events": len(h.ctx.log),
                    "cycle": h.ctx.ledger.cycle}

    @app.get("/api/p/{slug}/trajectory/{commitment_id}")
    def trajectory(slug: str, commitment_id: str, request: Request) -> list[dict[str, Any]]:
        h = _project(request, slug)
        with h.lock:
            try:
                return h.ctx.ledger.belief_trajectory(commitment_id)
            except KeyError:
                raise HTTPException(404, f"no commitment {commitment_id}")

    @app.post("/api/p/{slug}/tools/{name}")
    def call_tool(slug: str, name: str, body: ToolCall, request: Request):
        h = _project(request, slug, write=True)
        with h.lock:
            if name not in h.registry.names():
                raise HTTPException(404, f"no tool {name!r}")
            ctx = h.ctx
            interactor = DeferredInteractor(
                answers=body.answers or [], confirmations=body.confirmations or [])
            ctx.interactor = interactor
            saved_ledger, saved_log = ctx.ledger.to_dict(), ctx.log.to_list()

            def rollback() -> None:
                ctx.ledger = BeliefLedger.from_dict(saved_ledger)
                ctx.log = InquiryLog.from_list(saved_log)

            try:
                result = h.registry.call(name, body.args)
            except InputRequired as need:
                rollback()
                return JSONResponse(status_code=409, content=jsonable_encoder({
                    "detail": "operation needs human input",
                    "input_required": need.to_dict(),
                }))
            except (KeyError, ValueError, RuntimeError, TypeError) as e:
                rollback()
                raise HTTPException(400, f"{type(e).__name__}: {e}")
            h.save()
            return jsonable_encoder({"result": result,
                                     "notifications": interactor.notifications,
                                     **_snapshot(h)})

    # -- one project: reference files ------------------------------------------------
    def _cited(h: ProjectHandle) -> set[str]:
        """Files named by a brief or a surfaced anomaly already recorded in this
        project's log (``references`` too, for briefs recorded before
        ``reference_files``)."""
        names = set()
        for e in h.ctx.log.events():
            if e.operation == "intake.received":
                brief = e.payload.get("brief") or {}
                names.update(brief.get("reference_files") or [])
                names.update(brief.get("references") or [])
            elif e.operation == "disruption.surface":
                names.update(e.payload.get("seed_files") or [])
        return names

    @app.get("/api/p/{slug}/references")
    def list_references(slug: str, request: Request) -> list[dict[str, Any]]:
        h = _project(request, slug)
        with h.lock:
            cited = _cited(h)
        return [{**r, "cited": r["name"] in cited} for r in h.store.references(slug)]

    @app.post("/api/p/{slug}/references")
    async def upload_reference(slug: str, filename: str, request: Request) -> dict[str, Any]:
        """Upload one file as the raw request body (``?filename=`` names it)."""
        h = _project(request, slug, write=True)
        data = await request.body()
        if users is not None and _workspace_bytes(h.store) + len(data) > quota_bytes:
            raise HTTPException(413, "this upload would exceed your storage quota")
        try:
            return h.store.add_reference(slug, filename, data)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(413, str(e))

    @app.get("/api/p/{slug}/references/{name}")
    def get_reference(slug: str, name: str, request: Request):
        h = _project(request, slug)
        try:
            path = h.store.reference_path(slug, name)
        except KeyError as e:
            raise HTTPException(404, str(e))
        return FileResponse(path, filename=name, content_disposition_type="inline")

    @app.delete("/api/p/{slug}/references/{name}")
    def delete_reference(slug: str, name: str, request: Request) -> dict[str, Any]:
        h = _project(request, slug, write=True)
        with h.lock:
            if name in _cited(h):
                raise HTTPException(409, f"{name!r} is cited by the recorded brief and is "
                                         "kept as part of the inquiry's provenance")
        try:
            h.store.remove_reference(slug, name)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"removed": name}

    # -- one project: form drafts ----------------------------------------------------
    @app.get("/api/p/{slug}/drafts")
    def get_drafts(slug: str, request: Request) -> dict[str, Any]:
        h = _project(request, slug)
        return {} if _user(request) is None else h.store.drafts(slug)

    @app.put("/api/p/{slug}/drafts/{tool}")
    def put_draft(slug: str, tool: str, body: Draft, request: Request) -> dict[str, Any]:
        h = _project(request, slug, write=True)
        if tool not in h.registry.names():
            raise HTTPException(404, f"no tool {tool!r}")
        h.store.save_draft(slug, tool, body.args)
        return {"saved": tool}

    # -- agent assist: an LLM drafts a step's inputs for review ----------------------
    def _brief_files(h: ProjectHandle, *, blind: bool = False,
                     selected: list[str] = ()) -> list[Path]:
        """Files the latest recorded brief cites (all project files if none yet),
        those supporting a surfaced anomaly, and any ticked in the form being
        drafted. ``blind`` steps (the baseline) never see the anomaly's files."""
        events = h.ctx.log.events()
        briefs = [e.payload.get("brief") or {} for e in events
                  if e.operation == "intake.received"]
        names = ([*(briefs[-1].get("reference_files") or []),
                  *(briefs[-1].get("references") or [])] if briefs
                 else [r["name"] for r in h.store.references(h.slug)])
        anomaly = [n for e in events if e.operation == "disruption.surface"
                   for n in e.payload.get("seed_files") or []]
        if blind:
            names = [n for n in names if briefs or n not in anomaly]
        else:
            names = [*names, *anomaly, *selected]
        paths = []
        for n in dict.fromkeys(names):
            try:
                paths.append(h.store.reference_path(h.slug, n))
            except KeyError:
                pass  # a citation, not a file
        return paths

    @app.get("/api/assist")
    def assist_status() -> dict[str, Any]:
        from . import llm
        return llm.catalog(env_file if server_keys else None)

    @app.post("/api/assist/models")
    def assist_models(body: ProviderChoice, request: Request) -> dict[str, Any]:
        """Models available to the given key (POST: the key travels in the body)."""
        from . import llm
        _require_user(request)
        choice = body.model_dump()
        choice["model"] = choice.get("model") or "any"  # not needed to list models
        try:
            provider = llm.resolve(choice, env_file=env_file if server_keys else None)
            return {"models": llm.list_models(provider)}
        except llm.LLMError as e:
            raise HTTPException(e.status, str(e))

    @app.post("/api/p/{slug}/assist/{tool}")
    def assist_draft(slug: str, tool: str, body: AssistRequest, request: Request) -> dict[str, Any]:
        from . import assist, llm
        h = _project(request, slug, write=True)
        if tool not in h.registry.names():
            raise HTTPException(404, f"no tool {tool!r}")
        try:
            provider = llm.resolve(body.provider.model_dump(),
                                   env_file=env_file if server_keys else None)
        except llm.LLMError as e:
            raise HTTPException(e.status, str(e))
        # Snapshot under the lock, then call the model without holding it: a
        # draft can take a minute and must not block the project.
        with h.lock:
            snapshot = InquiryContext(ledger=BeliefLedger.from_dict(h.ctx.ledger.to_dict()),
                                      log=InquiryLog.from_list(h.ctx.log.to_list()))
            ticked = [n for k in ("reference_files", "seed_files")
                      for n in (body.draft or {}).get(k) or [] if isinstance(n, str)]
            files = _brief_files(h, blind=tool in assist.BLIND_TO_ANOMALY, selected=ticked)
            tool_schema = h.registry.get(tool).schema()
        try:
            return assist.draft(snapshot, tool_schema, reference_paths=files,
                                current_draft=body.draft, guidance=body.guidance,
                                provider=provider)
        except llm.LLMError as e:
            raise HTTPException(e.status, str(e))

    return app


def main() -> None:  # pragma: no cover
    import uvicorn
    uvicorn.run(create_app(), host=os.environ.get("IDBD_HOST", "127.0.0.1"),
                port=int(os.environ.get("IDBD_PORT", "8000")),
                root_path=os.environ.get("IDBD_ROOT_PATH", ""),
                proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":  # pragma: no cover
    main()
