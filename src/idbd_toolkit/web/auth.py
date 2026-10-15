"""Accounts for server mode: users, roles, password hashing, signed session cookies.

Standard library only. Users live in ``users.json`` in the data directory;
passwords are stored as scrypt hashes. A login issues a signed, HttpOnly session
cookie carrying the username, an expiry, and the user's ``token_version`` —
bumping that version (password reset, disabling the account) invalidates every
cookie issued before it.

Roles: ``admin`` (everything, including managing users) and ``researcher`` (their
own private workspace). Anonymous visitors get the read-only demo.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..ids import now_iso

ROLES = ("admin", "researcher")
COOKIE_NAME = "idbd_session"
SESSION_SECONDS = 14 * 24 * 3600
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
MIN_PASSWORD = 10


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class User:
    username: str
    role: str = "researcher"
    display_name: str = ""
    active: bool = True
    password_hash: str = ""
    token_version: int = 1
    created: str = field(default_factory=now_iso)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("password_hash")
        d.pop("token_version")
        return d


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt${n}${r}${p}${s}${h}".format(
        **_SCRYPT, s=base64.b64encode(salt).decode(), h=base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt),
                         n=int(n), r=int(r), p=int(p))
    return hmac.compare_digest(got, base64.b64decode(digest))


def check_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"passwords must be at least {MIN_PASSWORD} characters")


class UserStore:
    """``users.json`` + the cookie-signing secret, in the data directory."""

    def __init__(self, data_dir: Path) -> None:
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "users.json"
        self._lock = threading.Lock()
        self._secret = self._load_secret()
        self._failures: dict[str, list[float]] = {}

    # -- persistence -----------------------------------------------------------
    def _load_secret(self) -> bytes:
        env = os.environ.get("IDBD_SECRET_KEY")
        if env:
            return env.encode()
        key_file = self.dir / "secret.key"
        if not key_file.exists():
            key_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            key_file.chmod(0o600)
        return key_file.read_text(encoding="utf-8").strip().encode()

    def _read(self) -> dict[str, User]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {u["username"]: User(**u) for u in raw}

    def _write(self, users: dict[str, User]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(u) for u in users.values()], indent=2), encoding="utf-8")
        tmp.chmod(0o600)
        os.replace(tmp, self.path)

    # -- queries ---------------------------------------------------------------
    def get(self, username: str) -> User | None:
        return self._read().get(username)

    def list(self) -> list[User]:
        return sorted(self._read().values(), key=lambda u: u.username)

    def has_admin(self) -> bool:
        return any(u.role == "admin" and u.active for u in self._read().values())

    # -- mutations -------------------------------------------------------------
    def create(self, username: str, password: str, *, role: str = "researcher",
               display_name: str = "") -> User:
        username = username.strip().lower()
        if not _USERNAME.match(username):
            raise AuthError("usernames are 2-32 characters: lowercase letters, digits, . _ -")
        if role not in ROLES:
            raise AuthError(f"role must be one of {', '.join(ROLES)}")
        check_password_strength(password)
        with self._lock:
            users = self._read()
            if username in users:
                raise AuthError(f"user {username!r} already exists", 409)
            user = User(username=username, role=role, display_name=display_name.strip(),
                        password_hash=hash_password(password))
            users[username] = user
            self._write(users)
        return user

    def update(self, username: str, *, role: str | None = None, active: bool | None = None,
               display_name: str | None = None, password: str | None = None) -> User:
        with self._lock:
            users = self._read()
            user = users.get(username)
            if user is None:
                raise AuthError(f"no user {username!r}", 404)
            if role is not None:
                if role not in ROLES:
                    raise AuthError(f"role must be one of {', '.join(ROLES)}")
                user.role = role
            if active is not None and active != user.active:
                user.active = active
                user.token_version += 1  # signs them out everywhere
            if display_name is not None:
                user.display_name = display_name.strip()
            if password is not None:
                check_password_strength(password)
                user.password_hash = hash_password(password)
                user.token_version += 1
            if not any(u.role == "admin" and u.active for u in users.values()):
                raise AuthError("there must always be at least one active admin", 409)
            self._write(users)
        return user

    # -- login + cookies -------------------------------------------------------
    def authenticate(self, username: str, password: str, client: str = "") -> User:
        """Check credentials, with a per-(client, username) throttle on failures."""
        username = username.strip().lower()
        key = f"{client}|{username}"
        now = time.monotonic()
        recent = [t for t in self._failures.get(key, []) if now - t < 900]
        if len(recent) >= 5:
            raise AuthError("too many failed attempts; try again in a few minutes", 429)
        user = self.get(username)
        # verify even for unknown users so timing doesn't reveal which exist
        ok = verify_password(password, user.password_hash if user else hash_password("x" * 12))
        if not (user and ok and user.active):
            self._failures[key] = recent + [now]
            raise AuthError("incorrect username or password", 401)
        self._failures.pop(key, None)
        return user

    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()

    def issue(self, user: User) -> str:
        payload = f"{user.username}|{int(time.time()) + SESSION_SECONDS}|{user.token_version}"
        return base64.urlsafe_b64encode(f"{payload}|{self._sign(payload)}".encode()).decode()

    def resolve(self, token: str | None) -> User | None:
        """The active user a cookie belongs to, or None (bad/expired/revoked)."""
        if not token:
            return None
        try:
            username, expiry, version, sig = base64.urlsafe_b64decode(token).decode().split("|")
        except (ValueError, UnicodeDecodeError):
            return None
        if not hmac.compare_digest(sig, self._sign(f"{username}|{expiry}|{version}")):
            return None
        if int(expiry) < time.time():
            return None
        user = self.get(username)
        if user is None or not user.active or str(user.token_version) != version:
            return None
        return user
