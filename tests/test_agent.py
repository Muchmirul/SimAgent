"""Kernel-side agent tool state tests. The provider loop lives in agent/ (pi)."""
import json
from pathlib import Path

from simagent import agent
from simagent.agent import AgentRun
from simagent.library import get
from simagent.proof import Method


def test_agent_manual_counterexample_by_hand(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    run.dispatch("certify", {})
    run.dispatch("finish", {"summary": "Wide triangle: circumcenter far below."})
    proof, report, artifacts = run.finalize()
    assert proof is not None and proof.method is Method.COUNTEREXAMPLE
    assert report.notes[0].startswith("found interactively")
    assert Path(artifacts["proof"]).is_file()


def test_agent_exhaustion_path(tmp_path):
    run = AgentRun(get("sum-of-odds-square"), tmp_path)
    content, error = run.dispatch("exhaust", {})
    assert not error and "holds_on_domain" in content
    run.dispatch("finish", {"summary": "All cases checked."})
    proof, _report, _artifacts = run.finalize()
    assert proof is not None and proof.method is Method.EXHAUSTION


def test_agent_tool_errors_are_recorded_without_proof(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    content, error = run.dispatch("exhaust", {})
    assert error and "not finite" in content
    run.dispatch("finish", {"summary": "stuck"})
    proof, _report, _artifacts = run.finalize()
    assert proof is None
    lines = [json.loads(line) for line in (tmp_path / "transcript.jsonl").read_text().splitlines()]
    assert lines[0]["tool"] == "exhaust" and lines[0]["error"] is True


def test_python_agent_module_has_no_provider_backend_loop():
    assert not hasattr(agent, "run_agent")
    assert not hasattr(agent, "run_agent_claude_code")
    assert not hasattr(agent, "run")
