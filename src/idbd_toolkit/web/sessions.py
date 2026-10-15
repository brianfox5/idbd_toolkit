"""Named, persistent web sessions.

Each inquiry run in the browser lives in its own folder under a sessions root::

    sessions/
      .current                  <- slug of the session the server resumes on start
      .trash/<slug>--<stamp>/   <- deleted sessions, restorable
      <slug>/references/        <- source files uploaded with the brief
      <slug>/drafts.json        <- form input typed per step (UI state)
      tmt-diversity/
        ledger.json             <- BeliefLedger
        log.json                <- InquiryLog
        meta.json               <- name, created/updated, origin, summary

Sessions are never overwritten by starting another one: "new" always creates a
new folder (and refuses an existing name), and every successful call saves the
open session in place, so a session is picked up exactly where it was left.
Writes go through a temp file + rename so an interrupted save cannot corrupt a
session. Deleting moves a session to ``.trash`` rather than erasing it, so an
administrator's misclick in the browser is recoverable.

A store can also present **read-only projects** (e.g. the worked example): they
are listed and opened like any other but served straight from their source files,
and every write (save, edit, delete) raises ``PermissionError``. To work on one,
duplicate it into an ordinary session. No web-framework dependency — the server is a thin client of this.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..ids import now_iso
from ..inquiry_log import InquiryLog
from ..ledger import BeliefLedger
from ..progress import cycle_progress

_LEDGER, _LOG, _META, _CURRENT = "ledger.json", "log.json", "meta.json", ".current"
_TRASH = ".trash"
_REFS = "references"
_DRAFTS = "drafts.json"
MAX_REFERENCE_BYTES = 100 * 1024 * 1024


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError("session name must contain letters or digits")
    return slug[:60]


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


@dataclass(frozen=True)
class ReadOnlyProject:
    """A project served read-only from existing ledger/log files."""

    slug: str
    name: str
    ledger_path: Path
    log_path: Path
    description: str = ""
    references_dir: Path | None = None


def _summary(ledger: BeliefLedger, log: InquiryLog) -> dict[str, Any]:
    return {"cycle": ledger.cycle, "events": len(log),
            "commitments": len(ledger.commitments),
            "stage": cycle_progress(ledger, log).get("active_stage"),
            "bam": ledger.bam.description[:160] if ledger.bam else None}


class SessionStore:
    def __init__(self, root: str | Path,
                 read_only: list[ReadOnlyProject] | tuple = ()) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._ro = {p.slug: p for p in read_only
                    if p.ledger_path.exists() and p.log_path.exists()}
        self._ro_meta: dict[str, tuple[float, dict[str, Any]]] = {}

    def _dir(self, slug: str) -> Path:
        return self.root / slug

    def exists(self, slug: str) -> bool:
        return slug in self._ro or (
            not slug.startswith(".") and (self._dir(slug) / _META).exists())

    def is_read_only(self, slug: str) -> bool:
        return slug in self._ro

    def _guard(self, slug: str) -> None:
        if slug in self._ro:
            raise PermissionError(
                f"{self._ro[slug].name!r} is read-only — duplicate it to work on it")

    def _name_taken(self, name: str, *, except_slug: str | None = None) -> bool:
        key = name.strip().lower()
        return any(m["name"].strip().lower() == key and m["slug"] != except_slug
                   for m in self.list())

    # -- read --------------------------------------------------------------
    def meta(self, slug: str) -> dict[str, Any]:
        if slug in self._ro:
            return self._read_only_meta(self._ro[slug])
        if not self.exists(slug):
            raise KeyError(f"no session {slug!r}")
        return json.loads((self._dir(slug) / _META).read_text(encoding="utf-8"))

    def _read_only_meta(self, p: ReadOnlyProject) -> dict[str, Any]:
        mtime = max(p.ledger_path.stat().st_mtime, p.log_path.stat().st_mtime)
        cached = self._ro_meta.get(p.slug)
        if cached is None or cached[0] != mtime:  # recompute only if the files changed
            stamp = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
            meta = {"slug": p.slug, "name": p.name, "description": p.description,
                    "origin": "built-in example", "read_only": True,
                    "created": stamp, "updated": stamp,
                    **_summary(*self.load(p.slug))}
            self._ro_meta[p.slug] = cached = (mtime, meta)
        return dict(cached[1])

    def user_sessions(self) -> list[dict[str, Any]]:
        metas = [self.meta(p.name) for p in self.root.iterdir()
                 if p.is_dir() and not p.name.startswith(".") and (p / _META).exists()]
        return sorted(metas, key=lambda m: m.get("updated", ""), reverse=True)

    def list(self) -> list[dict[str, Any]]:
        """Read-only projects first, then the user's sessions, newest first."""
        return [self.meta(s) for s in self._ro] + self.user_sessions()

    def load(self, slug: str) -> tuple[BeliefLedger, InquiryLog]:
        if slug in self._ro:
            p = self._ro[slug]
            return BeliefLedger.load(p.ledger_path), InquiryLog.load(p.log_path)
        if not self.exists(slug):
            raise KeyError(f"no session {slug!r}")
        d = self._dir(slug)
        return BeliefLedger.load(d / _LEDGER), InquiryLog.load(d / _LOG)

    # -- write -------------------------------------------------------------
    def create(
        self, name: str, ledger: BeliefLedger, log: InquiryLog, *, origin: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a new session; refuses to overwrite an existing one."""
        slug = slugify(name)
        if self.exists(slug) or self._name_taken(name):
            raise FileExistsError(f"a project named {name.strip()!r} already exists")
        self._dir(slug).mkdir(parents=True, exist_ok=True)
        now = now_iso()
        meta = {"slug": slug, "name": name.strip(), "description": description.strip(),
                "origin": origin, "created": now, "updated": now}
        _write_json(self._dir(slug) / _META, meta)
        return self.save(slug, ledger, log)

    def save(self, slug: str, ledger: BeliefLedger, log: InquiryLog) -> dict[str, Any]:
        self._guard(slug)
        meta = self.meta(slug)
        d = self._dir(slug)
        _write_json(d / _LEDGER, ledger.to_dict())
        _write_json(d / _LOG, log.to_list())
        meta.update(updated=now_iso(), **_summary(ledger, log))
        _write_json(d / _META, meta)
        return meta

    def edit(self, slug: str, *, name: str | None = None,
             description: str | None = None) -> dict[str, Any]:
        """Rename / re-describe a session. The folder (slug) stays put, so links
        and the resume pointer remain valid."""
        self._guard(slug)
        meta = self.meta(slug)
        if name is not None:
            slugify(name)  # validates
            if self._name_taken(name, except_slug=slug):
                raise FileExistsError(f"a project named {name.strip()!r} already exists")
            meta["name"] = name.strip()
        if description is not None:
            meta["description"] = description.strip()
        _write_json(self._dir(slug) / _META, meta)
        return meta

    # -- trash -------------------------------------------------------------
    def delete(self, slug: str) -> str:
        """Move a session to the trash (recoverable). Returns its trash id."""
        self._guard(slug)
        if not self.exists(slug):
            raise KeyError(f"no session {slug!r}")
        trash = self.root / _TRASH
        trash.mkdir(exist_ok=True)
        deleted = now_iso()
        trash_id = f"{slug}--{deleted.replace(':', '').replace('+', '_')}"
        _write_json(self._dir(slug) / _META, {**self.meta(slug), "deleted": deleted})
        shutil.move(str(self._dir(slug)), str(trash / trash_id))
        if (self.root / _CURRENT).exists() and \
                (self.root / _CURRENT).read_text(encoding="utf-8").strip() == slug:
            (self.root / _CURRENT).unlink()
        return trash_id

    def trash(self) -> list[dict[str, Any]]:
        root = self.root / _TRASH
        if not root.exists():
            return []
        items = []
        for p in root.iterdir():
            if (p / _META).exists():
                meta = json.loads((p / _META).read_text(encoding="utf-8"))
                items.append({**meta, "trash_id": p.name})
        return sorted(items, key=lambda m: m.get("deleted", ""), reverse=True)

    def restore(self, trash_id: str) -> dict[str, Any]:
        """Bring a deleted session back (renamed if its name has been reused)."""
        src = self.root / _TRASH / trash_id
        if "/" in trash_id or trash_id.startswith(".") or not (src / _META).exists():
            raise KeyError(f"nothing in the trash named {trash_id!r}")
        meta = json.loads((src / _META).read_text(encoding="utf-8"))
        name, slug = meta["name"], meta["slug"]
        if self._dir(slug).exists() or slug in self._ro or self._name_taken(name):
            name = self.unique_name(f"{name} (restored)")
            slug = slugify(name)
        shutil.move(str(src), str(self._dir(slug)))
        meta.update(slug=slug, name=name)
        meta.pop("deleted", None)
        _write_json(self._dir(slug) / _META, meta)
        return meta

    # -- form drafts -------------------------------------------------------
    def drafts(self, slug: str) -> dict[str, Any]:
        """Unsubmitted (or last-submitted) form input per tool. UI state only —
        not part of the ledger or the inquiry log."""
        if slug in self._ro:
            return {}
        path = self._dir(slug) / _DRAFTS
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def save_draft(self, slug: str, tool: str, args: dict[str, Any] | None) -> None:
        self._guard(slug)
        drafts = self.drafts(slug)
        if args:
            drafts[tool] = args
        else:
            drafts.pop(tool, None)
        _write_json(self._dir(slug) / _DRAFTS, drafts)

    # -- reference files ---------------------------------------------------
    def _refs_dir(self, slug: str) -> Path | None:
        if slug in self._ro:
            return self._ro[slug].references_dir
        if not self.exists(slug):
            raise KeyError(f"no session {slug!r}")
        return self._dir(slug) / _REFS

    def references(self, slug: str) -> list[dict[str, Any]]:
        d = self._refs_dir(slug)
        if d is None or not d.is_dir():
            return []
        return [{"name": f.name, "size": f.stat().st_size,
                 "modified": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()}
                for f in sorted(d.iterdir(), key=lambda f: f.name.lower())
                if f.is_file() and not f.name.startswith(".")]

    def reference_path(self, slug: str, name: str) -> Path:
        d = self._refs_dir(slug)
        if d is None or name != Path(name).name or name.startswith("."):
            raise KeyError(f"no reference {name!r}")
        path = d / name
        if not path.is_file():
            raise KeyError(f"no reference {name!r}")
        return path

    def add_reference(self, slug: str, filename: str, data: bytes) -> dict[str, Any]:
        """Store an uploaded file with the session. Re-uploading identical content
        is a no-op; a different file with a taken name gets a numbered name."""
        self._guard(slug)
        if len(data) > MAX_REFERENCE_BYTES:
            raise ValueError(f"file exceeds {MAX_REFERENCE_BYTES // (1024 * 1024)} MB")
        name = re.sub(r"[\x00-\x1f/\\:]", "_", Path(filename.replace("\\", "/")).name).strip()
        name = name.lstrip(".") or "upload"
        d = self._refs_dir(slug)
        d.mkdir(exist_ok=True)
        stem, suffix = Path(name).stem, Path(name).suffix
        candidate, n = name, 1
        while (d / candidate).exists():
            if (d / candidate).read_bytes() == data:
                break
            n += 1
            candidate = f"{stem} ({n}){suffix}"
        else:
            tmp = d / f".{candidate}.tmp"
            tmp.write_bytes(data)
            os.replace(tmp, d / candidate)
        return next(r for r in self.references(slug) if r["name"] == candidate)

    def remove_reference(self, slug: str, name: str) -> None:
        self._guard(slug)
        self.reference_path(slug, name).unlink()

    def copy_references(self, src_slug: str, dst_slug: str) -> None:
        src = self._refs_dir(src_slug)
        if src is None or not src.is_dir():
            return
        dst = self._refs_dir(dst_slug)
        dst.mkdir(exist_ok=True)
        for r in self.references(src_slug):
            shutil.copy2(src / r["name"], dst / r["name"])

    def unique_name(self, base: str) -> str:
        """``base``, or ``base 2``, ``base 3``… — the first name not yet taken."""
        name, n = base, 1
        while self.exists(slugify(name)) or self._name_taken(name):
            n += 1
            name = f"{base} {n}"
        return name

    # -- current pointer ---------------------------------------------------
    def current(self) -> str | None:
        p = self.root / _CURRENT
        if not p.exists():
            return None
        slug = p.read_text(encoding="utf-8").strip()
        return slug if self.exists(slug) else None

    def set_current(self, slug: str) -> None:
        if not self.exists(slug):
            raise KeyError(f"no session {slug!r}")
        (self.root / _CURRENT).write_text(slug, encoding="utf-8")

    def import_legacy(self, directory: Path, ledger_name: str, log_name: str,
                      name: str) -> str | None:
        """Adopt a pre-sessions ``web_session_*`` pair as a named session (copied,
        originals left in place). Returns the new slug, or None if absent."""
        src_ledger, src_log = directory / ledger_name, directory / log_name
        if not (src_ledger.exists() and src_log.exists()):
            return None
        meta = self.create(self.unique_name(name), BeliefLedger(), InquiryLog(),
                           origin=f"imported from {directory / ledger_name}")
        shutil.copyfile(src_ledger, self._dir(meta["slug"]) / _LEDGER)
        shutil.copyfile(src_log, self._dir(meta["slug"]) / _LOG)
        ledger, log = self.load(meta["slug"])
        self.save(meta["slug"], ledger, log)
        return meta["slug"]
