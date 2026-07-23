"""Agent-mode tests with a scripted fake model — the loop, tools, and kernel
finalization are fully exercised offline; no API access needed."""
import json
from pathlib import Path
from types import SimpleNamespace

from simagent.agent import run_agent
from simagent.library import get
from simagent.proof import Method


def turn(*tool_calls, text=None):
    content = []
    if text:
        content.append(SimpleNamespace(type="text", text=text))
    for i, (name, args) in enumerate(tool_calls):
        content.append(SimpleNamespace(type="tool_use", id=f"tu_{name}_{i}", name=name, input=args))
    return SimpleNamespace(stop_reason="tool_use" if tool_calls else "end_turn", content=content)


class FakeClient:
    def __init__(self, turns):
        self._turns = list(turns)
        self.messages = SimpleNamespace(create=self._create)
        self.requests = []

    def _create(self, **kwargs):
        # snapshot: run_agent mutates the messages list in place across turns
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._turns.pop(0)


def test_agent_hunt_certify_finish(tmp_path):
    client = FakeClient(
        [
            turn(("look", {}), text="Let me see the world."),
            turn(("hunt", {"trials": 300})),
            turn(("certify", {})),
            turn(("finish", {"summary": "Disproved by counterexample."})),
        ]
    )
    result = run_agent(get("circumcenter-in-triangle"), tmp_path, client=client, log=lambda *_: None)
    assert result.turns == 4
    assert result.proof is not None
    assert result.proof.method is Method.COUNTEREXAMPLE
    assert result.proof.verified_by in ("sandbox", "sandbox+lean")
    assert (tmp_path / "looks" / "look_001.png").exists()
    assert (tmp_path / "agent_summary.md").exists()
    assert (tmp_path / "proof.json").exists()
    # the model saw an image in a tool result
    tool_results = client.requests[1]["messages"][-1]["content"]
    kinds = {b["type"] for b in tool_results[0]["content"]}
    assert "image" in kinds and "text" in kinds


def test_agent_manual_counterexample_by_hand(tmp_path):
    # The model drags an obtuse triangle into place by hand, then certifies.
    client = FakeClient(
        [
            turn(("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})),
            turn(("certify", {})),
            turn(("finish", {"summary": "Wide triangle: circumcenter far below."})),
        ]
    )
    result = run_agent(get("circumcenter-in-triangle"), tmp_path, client=client, log=lambda *_: None)
    assert result.proof is not None
    assert result.proof.method is Method.COUNTEREXAMPLE
    assert result.report.notes[0].startswith("found interactively")


def test_agent_exhaustion_path(tmp_path):
    client = FakeClient(
        [
            turn(("exhaust", {})),
            turn(("finish", {"summary": "All 201 cases hold."})),
        ]
    )
    result = run_agent(get("sum-of-odds-square"), tmp_path, client=client, log=lambda *_: None)
    assert result.proof is not None
    assert result.proof.method is Method.EXHAUSTION


def test_agent_survives_tool_errors_and_no_tool_turns(tmp_path):
    client = FakeClient(
        [
            turn(text="thinking out loud, no tools"),
            turn(("exhaust", {})),  # not exhaustible -> is_error result
            turn(("finish", {"summary": "stuck"})),
        ]
    )
    result = run_agent(get("circumcenter-in-triangle"), tmp_path, client=client, log=lambda *_: None)
    assert result.proof is None
    assert result.turns == 3
    lines = [json.loads(l) for l in Path(tmp_path, "transcript.jsonl").read_text().splitlines()]
    assert any(e["error"] for e in lines if e["tool"] == "exhaust")
