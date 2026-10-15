"""Server mode: accounts, roles, per-user workspaces, the anonymous demo."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from idbd_toolkit import BeliefLedger, InquiryLog, PriorCommitment  # noqa: E402
from idbd_toolkit.web import create_app  # noqa: E402
from idbd_toolkit.web.auth import UserStore  # noqa: E402

EX = "example-tmt-diversity"
HDR = {"X-Requested-With": "idbd"}
PW = "correct horse battery"


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.delenv("IDBD_SECRET_KEY", raising=False)
    data, ex = tmp_path / "var", tmp_path / "example"
    ex.mkdir()
    ledger = BeliefLedger()
    ledger.add_commitment(PriorCommitment("worked example prior", 0.7))
    ledger.save(ex / "final_ledger.json")
    InquiryLog().save(ex / "final_inquiry_log.json")
    UserStore(data).create("boss", PW, role="admin", display_name="The Admin")

    def make():
        app = create_app(mode="server", data_dir=data, pristine_dir=ex, env_file=None,
                         cookie_secure=False)
        return TestClient(app, headers=HDR)

    return make, data


def _login(client, username="boss", password=PW):
    return client.post("/api/login", json={"username": username, "password": password})


def test_anonymous_visitors_get_the_read_only_demo(site):
    make, data = site
    c = make()
    me = c.get("/api/me").json()
    assert me == {"mode": "server", "user": None, "can_edit": False}
    ss = c.get("/api/sessions").json()
    assert [m["slug"] for m in ss["sessions"]] == [EX] and ss["root"] is None
    assert c.get(f"/api/p/{EX}/state").json()["commitments"][0]["statement"] == "worked example prior"
    assert c.post("/api/sessions", json={"name": "x"}).status_code == 401
    cid = c.get(f"/api/p/{EX}/state").json()["commitments"][0]["id"]
    assert c.post(f"/api/p/{EX}/tools/doubt_weaken",
                  json={"args": {"commitment_id": cid}}).status_code == 401
    assert c.get("/api/admin/users").status_code == 401


def test_login_logout_and_private_workspaces(site):
    make, data = site
    admin = make()
    assert _login(admin, password="wrong password!").status_code == 401
    r = _login(admin)
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert "password_hash" not in r.json()["user"]
    assert admin.get("/api/me").json()["user"]["username"] == "boss"
    slug = admin.post("/api/sessions", json={"name": "Boss project"}).json()["session"]["slug"]

    # the admin adds a researcher, who sees only their own projects
    r = admin.post("/api/admin/users", json={"username": "ana", "password": PW,
                                             "display_name": "Ana"})
    assert r.status_code == 200 and r.json()["role"] == "researcher"
    ana = make()
    _login(ana, "ana")
    assert {m["slug"] for m in ana.get("/api/sessions").json()["sessions"]} == {EX}
    assert ana.get(f"/api/p/{slug}/state").status_code == 404  # not in her workspace
    mine = ana.post("/api/sessions", json={"name": "Boss project"}).json()["session"]["slug"]
    assert mine == slug  # same name, separate workspace
    assert (data / "workspaces" / "ana" / slug).is_dir()
    assert ana.get("/api/admin/users").status_code == 403  # researchers can't administer

    admin.post("/api/logout")
    assert admin.get("/api/me").json()["user"] is None


def test_admin_controls_access(site):
    make, data = site
    admin = make()
    _login(admin)
    admin.post("/api/admin/users", json={"username": "ana", "password": PW})
    ana = make()
    _login(ana, "ana")
    assert ana.post("/api/sessions", json={"name": "x"}).status_code == 200
    # disabling signs her out everywhere and blocks login
    assert admin.patch("/api/admin/users/ana", json={"active": False}).json()["active"] is False
    assert ana.post("/api/sessions", json={"name": "y"}).status_code == 401
    assert _login(make(), "ana").status_code == 401
    admin.patch("/api/admin/users/ana", json={"active": True, "role": "admin"})
    ana2 = make()
    assert _login(ana2, "ana").json()["user"]["role"] == "admin"
    rows = {u["username"]: u for u in admin.get("/api/admin/users").json()}
    assert rows["ana"]["projects"] == 1
    # a password reset revokes existing sessions
    admin.patch("/api/admin/users/ana", json={"password": "a brand new password"})
    assert ana2.get("/api/me").json()["user"] is None
    # there is always an active admin
    admin.patch("/api/admin/users/ana", json={"active": False})
    assert admin.patch("/api/admin/users/boss", json={"active": False}).status_code == 409
    assert admin.post("/api/admin/users", json={"username": "x", "password": "short"}).status_code == 400
    assert admin.post("/api/admin/users", json={"username": "Bad Name!", "password": PW}).status_code == 400


def test_change_own_password_and_login_throttle(site):
    make, data = site
    c = make()
    _login(c)
    r = c.post("/api/me/password", json={"current": PW, "new": "another long password"})
    assert r.status_code == 200
    assert c.get("/api/me").json()["user"] is None  # signed out by the change
    assert _login(make(), password="another long password").status_code == 200
    t = make()
    for _ in range(5):
        assert _login(t, password="nope nope nope").status_code == 401
    assert _login(t, password="another long password").status_code == 429


def test_cookie_is_httponly_and_signed(site):
    make, data = site
    c = make()
    r = _login(c)
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    c.cookies.set("idbd_session", c.cookies.get("idbd_session")[:-4] + "AAAA")
    assert c.get("/api/me").json()["user"] is None  # tampered → rejected


def test_project_limit(site, monkeypatch):
    make, data = site
    monkeypatch.setenv("IDBD_MAX_PROJECTS", "1")
    c = make()
    _login(c)
    assert c.post("/api/sessions", json={"name": "one"}).status_code == 200
    assert c.post("/api/sessions", json={"name": "two"}).status_code == 409


def test_admin_cli(site, capsys, monkeypatch):
    from idbd_toolkit.web import admin
    make, data = site
    monkeypatch.setattr(admin.getpass, "getpass", lambda prompt="": PW)
    admin.main(["--data-dir", str(data), "create-user", "cli-user", "--name", "From CLI"])
    admin.main(["--data-dir", str(data), "list"])
    out = capsys.readouterr().out
    assert "created cli-user (researcher)" in out and "cli-user" in out
    admin.main(["--data-dir", str(data), "disable", "cli-user"])
    assert UserStore(data).get("cli-user").active is False
