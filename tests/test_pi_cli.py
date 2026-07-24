"""P6 CLI cutover: `simagent agent` launches the TypeScript pi runtime."""
from types import SimpleNamespace

from simagent.cli import _cmd_agent


def test_agent_cli_launches_pi_with_bundled_identity(tmp_path, monkeypatch):
    pi_cli = tmp_path / "cli.js"
    pi_cli.write_text("// test placeholder")
    monkeypatch.setenv("SIMAGENT_PI_CLI", str(pi_cli))
    monkeypatch.setenv("SIMAGENT_PI_NODE", "/test/node")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr("simagent.cli.subprocess.run", fake_run)
    args = SimpleNamespace(
        problem="circumcenter-in-triangle",
        spec=None,
        conjecture=None,
        out=str(tmp_path / "run"),
        provider="openai-codex",
        model="gpt-5.4",
        thinking="medium",
        max_turns=12,
    )
    assert _cmd_agent(args) == 7
    command = captured["command"]
    assert command[:3] == ["/test/node", str(pi_cli), "run"]
    assert command[command.index("--problem-id") + 1] == "circumcenter-in-triangle"
    assert "--spec" not in command, "bundled identity must survive into the proof trust check"
    assert command[command.index("--provider") + 1 : command.index("--provider") + 4] == [
        "openai-codex",
        "--model",
        "gpt-5.4",
    ]
