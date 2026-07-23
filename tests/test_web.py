import numpy as np
import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from simagent.web import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(out_root=str(tmp_path))
    with fastapi_testclient.TestClient(app) as c:
        yield c


def test_problems_and_static(client):
    r = client.get("/api/problems")
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert "circumcenter-in-tetrahedron" in ids
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/three.module.min.js").status_code == 200


def test_state_requires_load(client):
    assert client.get("/api/state").status_code == 409


def test_load_set_and_check(client):
    st = client.post("/api/load", json={"problem_id": "circumcenter-in-triangle"}).json()
    assert st["spec"]["id"] == "circumcenter-in-triangle"
    assert np.array(st["vars"]["T"]).shape == (3, 2)
    assert st["scene"], "scene graph must not be empty"

    st2 = client.post("/api/set", json={"name": "T", "row": 0, "values": [0.9, 0.9]}).json()
    assert st2["vars"]["T"][0] == [0.9, 0.9]
    assert "holds" in st2["check"]

    assert client.post("/api/set", json={"name": "nope", "values": [1]}).status_code == 422


def test_hunt_and_certify(client):
    client.post("/api/load", json={"problem_id": "circumcenter-in-triangle"})
    r = client.post("/api/hunt", json={"trials": 300}).json()
    assert r["result"]["verdict"] == "counterexample"
    assert r["result"]["loaded_witness"] is True
    assert r["state"]["check"]["holds"] is False

    c = client.post("/api/certify").json()
    assert c["holds"] is False
    assert c["certified"] is True
    assert c["exact"] is not None


def test_manim_endpoint_graceful_or_job(client, monkeypatch):
    # Force the unavailable path so the test is env-independent and never renders.
    import simagent.web.app as web_app

    monkeypatch.setattr(web_app, "manim_available", lambda: False)
    client.post("/api/load", json={"problem_id": "circumcenter-in-triangle"})
    r = client.post("/api/manim", json={"video": False}).json()
    assert r["available"] is False and r["job"] is None
