"""P0 tests for the standalone Python kernel JSONL transport."""
import io
import json

from simagent.kernel_transport import KernelTransport, read_journal, serve
from simagent.library import get


def test_kernel_journal_replays_prefix_exactly(tmp_path):
    source = KernelTransport(get("circumcenter-in-triangle"), tmp_path / "source")
    source.call_tool(
        "pi-call-set",
        "set_var",
        {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]},
    )
    source.call_tool("pi-call-check", "check", {})
    expected = source.snapshot()

    branch = KernelTransport(
        get("circumcenter-in-triangle"),
        tmp_path / "branch",
        replay_journal=source.path,
        replay_through=2,
    )
    try:
        actual = branch.snapshot()
        assert actual["state"] == expected["state"]
        assert actual["stateHash"] == expected["stateHash"]
        _header, calls = read_journal(branch.path)
        assert [entry["toolCallId"] for entry in calls] == ["pi-call-set", "pi-call-check"]
        # Replay restores hidden continuation state too (not just coordinates):
        # the next unseeded sample must agree in both processes.
        source_next = source.call_tool("source-next-sample", "sample", {})
        branch_next = branch.call_tool("branch-next-sample", "sample", {})
        assert branch_next["stateHash"] == source_next["stateHash"]
    finally:
        branch.finalize()
        source.finalize()


def test_finish_rejects_later_calls_and_journals_their_ids(tmp_path):
    transport = KernelTransport(get("circumcenter-in-triangle"), tmp_path)
    before = transport.snapshot()["state"]["vars"]
    done = transport.call_tool("pi-finish", "finish", {"summary": "done"})
    rejected = transport.call_tool(
        "pi-after-finish",
        "set_var",
        {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]},
    )
    try:
        assert done["finished"] is True
        assert rejected["isError"] is True
        assert transport.snapshot()["state"]["vars"] == before
        _header, calls = read_journal(transport.path)
        assert [entry["toolCallId"] for entry in calls] == ["pi-finish", "pi-after-finish"]
        assert calls[-1]["isError"] is True
        transcript = [json.loads(line) for line in (tmp_path / "transcript.jsonl").read_text().splitlines()]
        assert [entry["toolCallId"] for entry in transcript] == ["pi-finish", "pi-after-finish"]
    finally:
        transport.finalize()


def test_jsonl_server_returns_one_correlated_response_per_request(tmp_path):
    transport = KernelTransport(get("circumcenter-in-triangle"), tmp_path)
    requests = "\n".join(
        json.dumps(request)
        for request in (
            {"id": "describe-id", "op": "describe"},
            {
                "id": "call-id",
                "op": "call",
                "toolCallId": "pi-tool-id",
                "name": "check",
                "args": {},
            },
            {"id": "final-id", "op": "finalize"},
        )
    ) + "\n"
    output = io.StringIO()
    serve(transport, io.StringIO(requests), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [response["id"] for response in responses] == ["describe-id", "call-id", "final-id"]
    assert all(response["ok"] for response in responses)
    assert responses[1]["result"]["toolCallId"] == "pi-tool-id"
