"""Notebook-facing web API: per-step scene renders, kernel outcome on the
trace, and the background agent job runner (with an injected fake runner —
offline, no LLM)."""
import threading
import time
from types import SimpleNamespace

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from simagent.agent import AgentRun  # noqa: E402
from simagent.library import get  # noqa: E402
from simagent.web import create_app  # noqa: E402


@pytest.fixture()
def traced_run(tmp_path):
    """A finished agent run with a certified counterexample on disk."""
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path / "agent-demo")
    run.note_thought("wide triangle should break it")
    run.dispatch("look", {})
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    run.dispatch("certify", {})
    run.dispatch("finish", {"summary": "done"})
    run.finalize()
    return tmp_path


def make_client(root, agent_runner=None):
    app = create_app(out_root=str(root / "web"), runs_root=str(root), agent_runner=agent_runner)
    return fastapi_testclient.TestClient(app)


def test_render_endpoint_renders_and_caches(traced_run):
    with make_client(traced_run) as client:
        r = client.get("/api/trace/agent-demo/render/2")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        cache = traced_run / "agent-demo" / "trace_renders" / "step_002.png"
        assert cache.is_file()
        stamp = cache.stat().st_mtime_ns
        assert client.get("/api/trace/agent-demo/render/2").status_code == 200
        assert cache.stat().st_mtime_ns == stamp, "second hit must come from the cache"
        assert client.get("/api/trace/agent-demo/render/99").status_code == 404


def test_trace_carries_kernel_outcome(traced_run):
    with make_client(traced_run) as client:
        tr = client.get("/api/trace/agent-demo").json()
        assert tr["proof"]["method"] == "counterexample"
        assert tr["proof"]["verified_by"] in ("sandbox", "sandbox+lean")
        assert tr["verdict"] and "DISPROVED" in tr["verdict"]


def _wait_status(client, run, wanted, timeout=90.0):
    """Generous timeout: a certified run's finalize() includes a real Lean
    kernel check, which can take ~10s cold."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = client.get(f"/api/agent/{run}/status").json()
        if st["status"] in wanted:
            return st
        time.sleep(0.05)
    raise AssertionError(f"status never reached {wanted}")


def test_agent_start_runs_injected_runner_and_streams_trace(tmp_path):
    def fake_runner(spec, out_dir, backend=None, max_turns=40, log=print, on_run=None):
        run = AgentRun(spec, out_dir)
        if on_run:
            on_run(run)
        run.note_thought("scripted session")
        run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
        run.dispatch("certify", {})
        run.dispatch("finish", {"summary": "done"})
        proof, _report, _artifacts = run.finalize()
        log("[fake] finished")
        return SimpleNamespace(proof=proof)

    with make_client(tmp_path, agent_runner=fake_runner) as client:
        r = client.post("/api/agent/start", json={"problem_id": "circumcenter-in-triangle"})
        assert r.status_code == 200
        run = r.json()["run"]
        assert run.startswith("agent-circumcenter-in-triangle")
        st = _wait_status(client, run, {"done", "failed"})
        assert st["status"] == "done"
        assert st["proof"]["method"] == "counterexample"
        assert any("[fake] finished" in l for l in st["log"])
        tr = client.get(f"/api/trace/{run}").json()
        assert tr["done"] is True and tr["total"] == 3
        assert tr["proof"]["method"] == "counterexample"


def test_agent_start_is_single_flight_and_validates(tmp_path):
    gate = threading.Event()

    def slow_runner(spec, out_dir, backend=None, max_turns=40, log=print, on_run=None):
        AgentRun(spec, out_dir).finalize()
        assert gate.wait(8)
        return SimpleNamespace(proof=None)

    with make_client(tmp_path, agent_runner=slow_runner) as client:
        assert client.post("/api/agent/start", json={}).status_code == 422
        assert (
            client.post(
                "/api/agent/start",
                json={"problem_id": "circumcenter-in-triangle", "conjecture": "both"},
            ).status_code
            == 422
        )
        assert client.post("/api/agent/start", json={"problem_id": "nope"}).status_code == 404

        first = client.post("/api/agent/start", json={"problem_id": "circumcenter-in-triangle"})
        assert first.status_code == 200
        busy = client.post("/api/agent/start", json={"problem_id": "sum-of-odds-square"})
        assert busy.status_code == 409
        gate.set()
        st = _wait_status(client, first.json()["run"], {"done"})
        assert st["proof"] is None
        # a second run may start now and gets a fresh, non-clobbering name
        gate.set()
        second = client.post("/api/agent/start", json={"problem_id": "circumcenter-in-triangle"})
        assert second.status_code == 200
        assert second.json()["run"] != first.json()["run"]
        _wait_status(client, second.json()["run"], {"done"})


def test_unknown_agent_job_is_404(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/api/agent/nope/status").status_code == 404
        assert client.post("/api/agent/nope/stop").status_code == 404


def test_stop_ends_a_running_session_and_frees_the_slot(tmp_path):
    def stoppable_runner(spec, out_dir, backend=None, max_turns=40, log=print, on_run=None):
        run = AgentRun(spec, out_dir)
        if on_run:
            on_run(run)  # registers the handle; a pre-arrived stop applies here
        deadline = time.monotonic() + 20
        while not run.stop_requested and time.monotonic() < deadline:
            time.sleep(0.05)
        assert run.stop_requested, "runner should have been stopped, not timed out"
        run.dispatch("finish", {"summary": "wound down"})
        run.finalize()
        return SimpleNamespace(proof=None)

    with make_client(tmp_path, agent_runner=stoppable_runner) as client:
        run = client.post(
            "/api/agent/start", json={"problem_id": "circumcenter-in-triangle"}
        ).json()["run"]
        r = client.post(f"/api/agent/{run}/stop")
        assert r.status_code == 200 and r.json()["status"] == "stopping"
        st = _wait_status(client, run, {"stopped", "done", "failed"})
        assert st["status"] == "stopped"
        # stopping twice is a clean 409, not a crash
        assert client.post(f"/api/agent/{run}/stop").status_code == 409
        # the trace was finalized (end marker) and the slot is free again
        tr = client.get(f"/api/trace/{run}").json()
        assert tr["done"] is True
        second = client.post("/api/agent/start", json={"problem_id": "circumcenter-in-triangle"})
        assert second.status_code == 200
        client.post(f"/api/agent/{second.json()['run']}/stop")
        _wait_status(client, second.json()["run"], {"stopped"})


def test_agent_run_stop_blocks_tools_but_allows_finish(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("check", {})
    run.stop()
    content, err = run.dispatch("hunt", {"trials": 10})
    assert err and "stopped" in content
    _content, err2 = run.dispatch("finish", {"summary": "s"})
    assert not err2
    run.finalize()
    assert run.summary == "s"
