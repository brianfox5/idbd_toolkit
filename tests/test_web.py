"""Web app in local mode: projects, steps, references, drafts (no accounts)."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from idbd_toolkit import BeliefLedger, InquiryLog, PriorCommitment  # noqa: E402
from idbd_toolkit.web import create_app  # noqa: E402

EX = "example-tmt-diversity"
HDR = {"X-Requested-With": "idbd"}
BRIEF = {"args": {"domain": "d", "belief_summary": "b", "initiating_anomaly": "a"}}


def _pristine(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    ledger = BeliefLedger()
    ledger.add_commitment(PriorCommitment("worked example prior", 0.7))
    ledger.save(d / "final_ledger.json")
    InquiryLog().save(d / "final_inquiry_log.json")
    return d


def _app(tmp_path):
    root, pristine = tmp_path / "sessions", _pristine(tmp_path)
    app = create_app(mode="local", sessions_dir=root, pristine_dir=pristine, env_file=None)
    return TestClient(app, headers=HDR), root, pristine


def _project(client, name="P", **body):
    r = client.post("/api/sessions", json={"name": name, **body})
    assert r.status_code == 200, r.text
    return r.json()["session"]["slug"]


def _seeded(client):
    """A project with one commitment and one doubt (via the worked example copy)."""
    slug = _project(client, "Seeded", source="worked_example")
    p = f"/api/p/{slug}"
    return slug, p


def test_page_tools_and_base_href(tmp_path):
    client, _, _ = _app(tmp_path)
    html = client.get("/").text
    assert '<base href="/">' in html
    names = [t["name"] for t in client.get("/api/tools").json()]
    assert "doubt_weaken" in names and "execution_record_fit" in names
    assert client.get("/api/me").json()["mode"] == "local"


def test_base_href_follows_root_path(tmp_path):
    root, pristine = tmp_path / "s", _pristine(tmp_path)
    app = create_app(mode="local", sessions_dir=root, pristine_dir=pristine, env_file=None)
    client = TestClient(app, root_path="/idbd")
    assert '<base href="/idbd/">' in client.get("/").text


def test_mutations_need_the_csrf_header(tmp_path):
    client, root, pristine = _app(tmp_path)
    bare = TestClient(client.app)
    assert bare.post("/api/sessions", json={"name": "x"}).status_code == 403
    assert bare.get("/api/sessions").status_code == 200  # reads are fine


def test_tool_call_updates_belief_and_trajectory(tmp_path):
    client, _, _ = _app(tmp_path)
    slug, p = _seeded(client)
    cid = client.get(f"{p}/state").json()["commitments"][0]["id"]
    r = client.post(f"{p}/tools/doubt_weaken",
                    json={"args": {"commitment_id": cid, "magnitude": "strong"}})
    assert r.status_code == 200
    assert r.json()["state"]["commitments"][0]["strength"] < 0.7
    assert any(e["operation"] == "doubt.weaken" for e in client.get(f"{p}/log").json())
    traj = client.get(f"{p}/trajectory/{cid}").json()
    assert len(traj) == 2 and traj[0]["label"] == "prior"
    assert client.get(f"{p}/trajectory/nope").status_code == 404


def test_checkpoint_needs_confirmation_over_http(tmp_path):
    client, _, _ = _app(tmp_path)
    p = f"/api/p/{_project(client)}"
    body = {"args": {"bam_description": "b", "commitments": [{"statement": "x", "strength": 0.5}]}}
    assert client.post(f"{p}/tools/establish_baseline", json=body).status_code == 409
    body["confirmations"] = [True]
    assert client.post(f"{p}/tools/establish_baseline", json=body).status_code == 200


def test_input_required_returns_core_prompt_and_rolls_back(tmp_path):
    client, _, _ = _app(tmp_path)
    p = f"/api/p/{_project(client)}"
    before = (client.get(f"{p}/state").json(), len(client.get(f"{p}/log").json()))
    body = {"args": {"proposed_statement": "why does X happen?"}}
    r = client.post(f"{p}/tools/design_frame", json=body)
    assert r.status_code == 409
    need = r.json()["input_required"]
    assert need["kind"] == "ask" and "Refine the problem framing" in need["prompt"]
    assert (client.get(f"{p}/state").json(), len(client.get(f"{p}/log").json())) == before
    body["answers"] = ["Why does X happen only in large firms?"]
    r = client.post(f"{p}/tools/design_frame", json=body)
    assert r.status_code == 200
    assert r.json()["result"]["statement"] == "Why does X happen only in large firms?"


def test_declined_checkpoint_and_failed_call(tmp_path):
    client, _, _ = _app(tmp_path)
    p = f"/api/p/{_project(client)}"
    body = {"args": {"bam_description": "b", "commitments": [{"statement": "x"}]},
            "confirmations": [False]}
    r = client.post(f"{p}/tools/establish_baseline", json=body)
    assert r.status_code == 200 and r.json()["result"]["approved"] is False
    assert client.get(f"{p}/progress").json()["active_stage"] in {"intake", "baseline"}
    n = client.get(f"{p}/version").json()["events"]
    r = client.post(f"{p}/tools/execution_record_fit", json={"args": {}})
    assert r.status_code == 400 and client.get(f"{p}/version").json()["events"] == n
    assert client.post(f"{p}/tools/no_such_tool", json={}).status_code == 404


def test_projects_are_independent_and_persist(tmp_path):
    client, root, pristine = _app(tmp_path)
    a, b = _project(client, "Alpha"), _project(client, "Beta")
    client.post(f"/api/p/{a}/tools/record_brief", json=BRIEF)
    assert len(client.get(f"/api/p/{a}/log").json()) == 1
    assert client.get(f"/api/p/{b}/log").json() == []  # no shared "open project"
    assert client.post("/api/sessions", json={"name": "alpha"}).status_code == 409
    client.post(f"/api/sessions/{a}/open")
    # a restarted server finds everything, and remembers the last opened project
    client2 = TestClient(create_app(mode="local", sessions_dir=root, pristine_dir=pristine,
                                    env_file=None), headers=HDR)
    ss = client2.get("/api/sessions").json()
    assert ss["last_open"] == a
    assert client2.get(f"/api/p/{a}/log").json()[0]["operation"] == "intake.received"
    assert client2.get("/api/p/nope/state").status_code == 404


def test_worked_example_is_read_only(tmp_path):
    client, root, pristine = _app(tmp_path)
    ex = client.get("/api/sessions").json()["sessions"][0]
    assert ex["slug"] == EX and ex["read_only"] is True
    p = f"/api/p/{EX}"
    cid = client.get(f"{p}/state").json()["commitments"][0]["id"]
    before = (pristine / "final_ledger.json").read_text()
    r = client.post(f"{p}/tools/doubt_weaken", json={"args": {"commitment_id": cid}})
    assert r.status_code == 403 and "read-only" in r.json()["detail"]
    assert client.patch(f"/api/sessions/{EX}", json={"name": "x"}).status_code == 403
    assert client.delete(f"/api/sessions/{EX}").status_code == 403
    assert client.put(f"{p}/drafts/record_brief", json={"args": {}}).status_code == 403
    assert (pristine / "final_ledger.json").read_text() == before
    assert not (root / EX).exists()


def test_duplicate_is_an_independent_branch(tmp_path):
    client, _, _ = _app(tmp_path)
    r = client.post("/api/sessions", json={"source": "duplicate", "from_slug": EX})
    copy = r.json()["session"]
    assert copy["slug"] == "tmt-diversity-worked-example-copy"
    assert copy["origin"] == "duplicate of TMT diversity (worked example)"
    cid = client.get(f"/api/p/{copy['slug']}/state").json()["commitments"][0]["id"]
    client.post(f"/api/p/{copy['slug']}/tools/doubt_weaken", json={"args": {"commitment_id": cid}})
    assert client.get(f"/api/p/{EX}/state").json()["commitments"][0]["strength"] == 0.7
    assert client.post("/api/sessions", json={"source": "duplicate"}).status_code == 400


def test_edit_delete_restore(tmp_path):
    client, _, _ = _app(tmp_path)
    _project(client, "Alpha", description="first")
    _project(client, "Beta")
    r = client.patch("/api/sessions/alpha", json={"name": "Alpha prime", "description": "renamed"})
    alpha = next(m for m in r.json()["sessions"] if m["slug"] == "alpha")
    assert alpha["name"] == "Alpha prime" and alpha["description"] == "renamed"
    assert client.patch("/api/sessions/alpha", json={"name": "BETA"}).status_code == 409
    r = client.delete("/api/sessions/alpha")
    assert r.json()["trash"][0]["slug"] == "alpha"
    assert client.get("/api/p/alpha/state").status_code == 404
    tid = r.json()["trash"][0]["trash_id"]
    r = client.post(f"/api/sessions/trash/{tid}/restore")
    assert {m["slug"] for m in r.json()["sessions"]} == {EX, "alpha", "beta"}
    assert client.get("/api/p/alpha/state").status_code == 200


def test_reference_uploads(tmp_path):
    client, root, pristine = _app(tmp_path)
    slug = _project(client, "Refs")
    p = f"/api/p/{slug}"
    up = lambda name, data: client.post(f"{p}/references", params={"filename": name}, content=data)
    assert up("Ferrier 2001.pdf", b"%PDF-1 a").json()["name"] == "Ferrier 2001.pdf"
    assert up("Ferrier 2001.pdf", b"%PDF-1 a").json()["name"] == "Ferrier 2001.pdf"
    assert up("Ferrier 2001.pdf", b"%PDF-1 b").json()["name"] == "Ferrier 2001 (2).pdf"
    assert up("../../evil.txt", b"x").json()["name"] == "evil.txt"
    assert (root / slug / "references" / "evil.txt").exists()
    assert client.get(f"{p}/references/Ferrier 2001.pdf").content == b"%PDF-1 a"
    assert client.get(f"{p}/references/..%2Fmeta.json").status_code == 404
    assert client.delete(f"{p}/references/evil.txt").status_code == 200
    client.post(f"{p}/tools/record_brief", json={"args": {
        **BRIEF["args"], "references": ["Hambrick & Mason (1984)"],
        "reference_files": ["Ferrier 2001.pdf"]}})
    refs = {r["name"]: r["cited"] for r in client.get(f"{p}/references").json()}
    assert refs == {"Ferrier 2001 (2).pdf": False, "Ferrier 2001.pdf": True}
    assert client.delete(f"{p}/references/Ferrier 2001.pdf").status_code == 409
    # duplicates carry their files
    r = client.post("/api/sessions", json={"source": "duplicate", "from_slug": slug})
    assert len(client.get(f"/api/p/{r.json()['session']['slug']}/references").json()) == 2
    # the read-only example lists its files but refuses changes
    (pristine.parent / "references").mkdir()
    (pristine.parent / "references" / "Fox 2022.pdf").write_bytes(b"%PDF fox")
    assert [r["name"] for r in client.get(f"/api/p/{EX}/references").json()] == ["Fox 2022.pdf"]
    assert client.post(f"/api/p/{EX}/references", params={"filename": "x.pdf"},
                       content=b"x").status_code == 403


def test_form_drafts_persist_per_project(tmp_path):
    client, root, pristine = _app(tmp_path)
    a, b = _project(client, "Drafty"), _project(client, "Other")
    draft = {"domain": "Upper echelons", "references": ["Hambrick & Mason (1984)"]}
    assert client.put(f"/api/p/{a}/drafts/record_brief", json={"args": draft}).status_code == 200
    assert client.put(f"/api/p/{a}/drafts/no_such_tool", json={"args": {}}).status_code == 404
    client2 = TestClient(create_app(mode="local", sessions_dir=root, pristine_dir=pristine,
                                    env_file=None), headers=HDR)
    assert client2.get(f"/api/p/{a}/drafts").json() == {"record_brief": draft}
    assert client2.get(f"/api/p/{b}/drafts").json() == {}
    client2.put(f"/api/p/{a}/drafts/record_brief", json={"args": None})
    assert client2.get(f"/api/p/{a}/drafts").json() == {}
