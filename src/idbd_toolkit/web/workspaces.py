"""Workspaces: whose projects live where, and the live context of each project.

* **Local mode** (default; running on your own machine): one workspace, the
  ``sessions/`` folder, no login.
* **Server mode** (``IDBD_MODE=server``): one private workspace per account under
  ``<data dir>/workspaces/<username>/``; anonymous visitors see only the read-only
  projects (the worked example).

A project's :class:`InquiryContext` is loaded on first use and cached. Each
handle carries a lock: every tool call, save and read of a project happens under
it, so two tabs (or two requests) never interleave writes to the same inquiry.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..context import InquiryContext
from ..interaction import AutoInteractor
from ..tools import ToolRegistry, build_registry
from .sessions import ReadOnlyProject, SessionStore

ANONYMOUS = ".anonymous"


@dataclass
class ProjectHandle:
    store: SessionStore
    slug: str
    ctx: InquiryContext
    registry: ToolRegistry
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def read_only(self) -> bool:
        return self.store.is_read_only(self.slug)

    def save(self) -> None:
        if not self.read_only:
            self.store.save(self.slug, self.ctx.ledger, self.ctx.log)


class Workspaces:
    def __init__(self, *, mode: str, root: Path, read_only: list[ReadOnlyProject]) -> None:
        if mode not in ("local", "server"):
            raise ValueError("mode must be 'local' or 'server'")
        self.mode = mode
        self.root = Path(root)  # local: the sessions folder; server: <data>/workspaces
        self.read_only = read_only
        self._stores: dict[str, SessionStore] = {}
        self._handles: dict[tuple[str, str], ProjectHandle] = {}
        self._lock = threading.Lock()

    def read_only_slugs(self) -> list[str]:
        return [p.slug for p in self.read_only
                if p.ledger_path.exists() and p.log_path.exists()]

    def store_for(self, username: str | None) -> SessionStore:
        """The workspace of ``username`` (None = anonymous; local mode ignores it)."""
        key = "local" if self.mode == "local" else (username or ANONYMOUS)
        with self._lock:
            if key not in self._stores:
                root = self.root if self.mode == "local" else self.root / key
                self._stores[key] = SessionStore(root, read_only=self.read_only)
            return self._stores[key]

    def handle(self, username: str | None, slug: str) -> ProjectHandle:
        """The live context for one project (raises KeyError if it doesn't exist)."""
        store = self.store_for(username)
        if not store.exists(slug):
            raise KeyError(slug)
        # read-only projects are shared by everyone; user projects are per workspace
        key = ("*", slug) if store.is_read_only(slug) else (str(store.root), slug)
        with self._lock:
            h = self._handles.get(key)
            if h is None:
                ledger, log = store.load(slug)
                ctx = InquiryContext(ledger=ledger, log=log, interactor=AutoInteractor())
                h = ProjectHandle(store=store, slug=slug, ctx=ctx, registry=build_registry(ctx))
                self._handles[key] = h
            return h

    def forget(self, username: str | None, slug: str) -> None:
        """Drop a cached project (after delete/restore) so it is re-read from disk."""
        store = self.store_for(username)
        with self._lock:
            self._handles.pop((str(store.root), slug), None)
