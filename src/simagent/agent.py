"""Agent mode: an LLM lives in the sandbox.

The model gets eyes and hands: `look` returns the rendered 3D scene as an
image (vision), the other tools move points, run the search machinery, and
submit Lean. The harness stays the authority — the model's narrative is saved
as narrative, but the final verdict is built only from kernel state
(certified reports and kernel-checked Lean), exactly as in pipeline runs.

Two interchangeable backends drive the same AgentRun tool state machine:
  "api"          — a deliberately small manual tool loop over the Anthropic
                   SDK (needs an API key or `ant auth login` profile).
  "claude-code"  — the Claude Agent SDK, which authenticates with the user's
                   existing `claude` login (subscription; no API key). Tools
                   are exposed as an in-process MCP server; `look` images pass
                   through as MCP image content.
"""
from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import answer as answer_mod
from . import proof as proof_mod
from .llm import DEFAULT_MODEL, resolve_backend
from .proof import Method
from .search import SearchReport
from .spec import ProblemSpec
from .trace import TraceRecorder
from .visualize import mpl
from .web.session import SandboxSession

MAX_TOOL_CHARS = 2000

SYSTEM = """You are a mathematician placed inside SimAgent, a 3D math sandbox.
You are embodied: `look` shows you the current configuration as a rendered
image; the other tools move points and run the harness machinery. Use your
eyes — geometry that looks wrong usually is wrong.

Your task: settle the conjecture with one of the ten classical proof methods
(direct, contradiction, contrapositive, induction, cases, construction,
counterexample, exhaustion, combinatorial, infinite descent). That list is
your option menu — pick a line of attack and pursue it in the scene.

Think in the scene, not in prose: form each hypothesis as a configuration you
can look at, then act on it. Every act is traced — thought, move, resulting
picture — and the harness translates each new state into equations for the
record. Equations are the translation of what you see, not the medium of
thought.

Declare your line of attack with `plan` (method + one-line idea) before your
first substantive act, and declare again whenever you switch strategy. The
declaration is recorded as intent — it never becomes the verdict; what you
*establish* is stamped by the kernel alone.

The harness is the authority, and it is strict:
- Only these count as established: a `certify` that returns CERTIFIED (exact
  rational arithmetic), an `exhaust` over the full finite domain, or
  `submit_lean_proof` code that the Lean kernel accepts (Lean 4 CORE only —
  no imports, no Mathlib, no sorry; prefer `decide`-style statements; end
  with `#print axioms <name>`).
- Your prose is recorded but proves nothing. Never claim more than the
  machinery verified.

Work economically: look, form a hypothesis, test it. When the matter is
settled (or you are honestly stuck), call `finish` with a summary."""

TOOLS = [
    {
        "name": "plan",
        "description": "Declare your current line of attack: one of the ten methods plus a one-line idea. Recorded as intent (re-declare when you switch); the verdict is still stamped only by the kernel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": [m.value for m in Method]},
                "idea": {"type": "string"},
            },
            "required": ["method", "idea"],
            "additionalProperties": False,
        },
    },
    {
        "name": "look",
        "description": "Render the current configuration and see it (image + exact holds/margin status).",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "sample",
        "description": "Draw a new random valid configuration.",
        "input_schema": {
            "type": "object",
            "properties": {"seed": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "set_var",
        "description": "Place one row of a variable exactly (row omitted = set the whole array, flattened).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "row": {"type": "integer"},
                "values": {"type": "array", "items": {"type": "number"}},
            },
            "required": ["name", "values"],
            "additionalProperties": False,
        },
    },
    {
        "name": "nudge",
        "description": "Move one row of a variable by a delta.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "row": {"type": "integer"},
                "delta": {"type": "array", "items": {"type": "number"}},
            },
            "required": ["name", "row", "delta"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check",
        "description": "Exact numeric check of the current configuration (holds, margin, data).",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "refine",
        "description": "Anneal the current configuration toward violation (forall) or witness (exists).",
        "input_schema": {
            "type": "object",
            "properties": {"steps": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "hunt",
        "description": "Automated random search; loads the found counterexample/witness into the scene.",
        "input_schema": {
            "type": "object",
            "properties": {"trials": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "exhaust",
        "description": "Check EVERY case of the domain (finite integer domains only) — proof by exhaustion.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "certify",
        "description": "Exact-rational verdict for the current configuration; CERTIFIED results count as proof material.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "submit_lean_proof",
        "description": "Submit a deductive proof: named method, honest argument, and self-contained Lean 4 CORE code the kernel will check.",
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": [m.value for m in Method]},
                "argument": {"type": "string"},
                "lean_code": {"type": "string"},
            },
            "required": ["method", "argument"],
            "additionalProperties": False,
        },
    },
    {
        "name": "finish",
        "description": "End the session with a summary of what was (and was not) established.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
]


@dataclass
class AgentResult:
    spec: ProblemSpec
    out_dir: str
    proof: proof_mod.Proof | None
    report: SearchReport | None
    turns: int
    summary: str
    artifacts: dict[str, str] = field(default_factory=dict)


def _task_prompt(spec: ProblemSpec) -> str:
    return (
        f"Conjecture: {spec.conjecture}\n\nLaTeX: {spec.latex}\n"
        f"Quantifier: {spec.quantifier}. Domain: "
        + ", ".join(
            f"{v.name}{v.shape or '[scalar]'} in [{v.low},{v.high}] ({v.kind})"
            for v in spec.domain
        )
        + "\n\nSettle it. Start by looking at the world."
    )


def _report_from_certify(spec: ProblemSpec, session: SandboxSession, c: dict) -> SearchReport | None:
    """Promote an interactive certified configuration to kernel proof material."""
    if not c.get("certified"):
        return None
    holds = c["holds"]
    if spec.quantifier == "forall" and not holds:
        verdict = "counterexample"
    elif spec.quantifier == "exists" and holds:
        verdict = "witness"
    else:
        return None
    return SearchReport(
        verdict=verdict,
        certified=True,
        trials=0,
        valid_trials=0,
        refine_steps=0,
        seed=0,
        witness={k: np.asarray(v).tolist() for k, v in session.vars.items()},
        witness_check={"holds": holds, "margin": c.get("margin"), "data": {}},
        exact_witness=c.get("exact"),
        margin_min=None,
        margin_max=None,
        notes=["found interactively in an agent session; certified in exact arithmetic"],
    )


class AgentRun:
    """The tool state machine shared by both backends. Cannot stamp verdicts."""

    def __init__(self, spec: ProblemSpec, out_dir):
        self.spec = spec
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "looks").mkdir(exist_ok=True)
        self.session = SandboxSession(spec, self.out)
        self.looks = 0
        self.seq = 0
        self.declared_plans: list[dict] = []  # narrative intent, never the verdict
        self.deductive: proof_mod.Proof | None = None
        self.certify_report: SearchReport | None = None
        self.finished = False
        self.stop_requested = False
        self.summary = ""
        self._transcript = (self.out / "transcript.jsonl").open("w")
        # The mind trace: thought + act + scene + equation per step, replayable
        # in the web UI's Mind panel (narrative only — proof.json stays boss).
        self.trace = TraceRecorder(self.out)
        self.trace.seed(self.session.vars, self.session._check())
        self._step_extra: dict | None = None
        self._step_image: str | None = None

    def note_thought(self, text: str | None, kind: str = "text") -> None:
        """Backends feed the model's narrative/thinking here; it attaches to
        the next tool step in the trace."""
        self.trace.note_thought(text, kind)

    def stop(self) -> None:
        """Cooperative cancel (threads can't be killed): every further tool
        call errors, both backend loops wind down, and finalize still records
        whatever the kernel established before the stop."""
        self.stop_requested = True
        self.finished = True
        self.summary = self.summary or "session stopped by the user"

    # -- tool dispatch -------------------------------------------------------

    def dispatch(self, name: str, args: dict):
        """Returns (content, is_error): content is str or a content-block list."""
        self.seq += 1
        self._step_extra = None
        self._step_image = None
        try:
            if self.stop_requested and name != "finish":
                raise RuntimeError("session stopped by the user; no further actions will run")
            handler = getattr(self, f"_t_{name}", None)
            if handler is None:
                content, is_error = f"unknown tool {name!r}", True
            else:
                content, is_error = handler(**(args or {})), False
        except Exception as e:  # noqa: BLE001 - the model must see and recover from errors
            content, is_error = f"{type(e).__name__}: {e}", True
        result_text = content if isinstance(content, str) else "<image>"
        self._transcript.write(
            json.dumps(
                {
                    "seq": self.seq,
                    "tool": name,
                    "args": args,
                    "result": result_text,
                    "error": is_error,
                }
            )
            + "\n"
        )
        self._transcript.flush()
        self.trace.record(
            tool=name,
            args=args,
            result=result_text,
            error=is_error,
            spec=self.spec,
            vars=self.session.vars,
            check=self.session._check(),
            scene=self.session.scene(),
            extra=self._step_extra,
            image=self._step_image,
        )
        return content, is_error

    def _status(self) -> str:
        check = self.session._check()
        return json.dumps(check, default=str)[:MAX_TOOL_CHARS]

    def _t_plan(self, method: str, idea: str):
        m = Method(method)  # ValueError on junk -> the model sees and recovers
        self.declared_plans.append({"method": m.value, "idea": idea})
        self._step_extra = {"declared_method": m.value, "idea": idea}
        return (
            f"approach recorded: {m.value} — {idea!r}. Intent only; the kernel "
            "stamps what you actually establish."
        )

    def _t_look(self):
        self.looks += 1
        path = self.out / "looks" / f"look_{self.looks:03d}.png"
        scene = self.session.scene()
        if not scene:
            return "scene could not be built (degenerate configuration?)"
        mpl.render_png(scene, path, title=self.spec.title)
        self._step_image = f"looks/{path.name}"  # what the agent saw, for the trace
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
            {"type": "text", "text": f"status: {self._status()}"},
        ]

    def _t_sample(self, seed: int | None = None):
        self.session.sample(seed)
        return f"sampled; status: {self._status()}"

    def _t_set_var(self, name: str, values: list, row: int | None = None):
        self.session.set_value(name, row, values)
        return f"set; status: {self._status()}"

    def _t_nudge(self, name: str, row: int, delta: list):
        cur = np.asarray(self.session.vars[name][row], dtype=float)
        self.session.set_value(name, row, (cur + np.asarray(delta, dtype=float)).tolist())
        return f"nudged; status: {self._status()}"

    def _t_check(self):
        return self._status()

    def _t_refine(self, steps: int = 300):
        r = self.session.refine(steps)
        return json.dumps(r, default=str)

    def _t_hunt(self, trials: int = 1500):
        r = self.session.hunt(trials)
        self._step_extra = {"verdict": r.get("verdict"), "certified": r.get("certified")}
        return json.dumps(r, default=str)[:MAX_TOOL_CHARS]

    def _t_exhaust(self):
        r = self.session.exhaust()
        self._step_extra = {"verdict": r.get("verdict"), "certified": r.get("certified")}
        return json.dumps(r, default=str)[:MAX_TOOL_CHARS]

    def _t_certify(self):
        r = self.session.certify()
        report = _report_from_certify(self.spec, self.session, r)
        if report is not None:
            self.certify_report = report
        self._step_extra = {"certified": r.get("certified"), "exact": r.get("exact")}
        return json.dumps(r, default=str)[:MAX_TOOL_CHARS]

    def _t_submit_lean_proof(self, method: str, argument: str, lean_code: str | None = None):
        attempt = proof_mod.deductive_proof(
            self.spec, method, argument, lean_code, out_dir=self.out
        )
        self._step_extra = {"method": method, "verified_by": attempt.verified_by}
        # Keep-best: never let a later failed attempt clobber a verified one.
        rank = {"lean": 2, "none": 0}
        if self.deductive is None or rank.get(attempt.verified_by, 0) >= rank.get(
            self.deductive.verified_by, 0
        ):
            self.deductive = attempt
        detail = (attempt.lean_report or {}).get("output", "no Lean code given")
        return f"recorded: method={method}, verified_by={attempt.verified_by}. Lean says: {detail[:800]}"

    def _t_finish(self, summary: str):
        self.finished = True
        self.summary = summary
        return "session ended"

    # -- kernel finalization -------------------------------------------------

    def best_report(self) -> SearchReport | None:
        """Prefer the strongest kernel-grade report accumulated in the session.

        Uses the session's kept-best (never-downgraded) report plus any
        certified interactive configuration, and returns the strongest.
        """
        from .web.session import _report_rank

        candidates = [
            r for r in (self.session.best_report, self.certify_report) if r is not None
        ]
        if not candidates:
            return None
        return max(candidates, key=_report_rank)

    def finalize(self) -> tuple[proof_mod.Proof | None, SearchReport | None, dict]:
        self._transcript.close()
        self.trace.close()
        from . import library

        report = self.best_report()
        proof = None
        if report is not None:
            proof = proof_mod.mechanized_proof(
                self.spec, report, out_dir=self.out, spec_trusted=library.is_bundled(self.spec)
            )
        if proof is None and self.deductive is not None:
            proof = self.deductive
        artifacts: dict[str, str] = {}
        if report is not None:
            artifacts.update(answer_mod.write_answers(self.spec, report, self.out, proof=proof))
        if proof is not None:
            artifacts["proof"] = proof_mod.save_proof(proof, self.out)
            if proof.lean_file:
                artifacts["lean"] = proof.lean_file
        (self.out / "agent_summary.md").write_text(
            "# Agent summary (the model's narrative — see proof.json for what is verified)\n\n"
            + self.summary
        )
        artifacts["agent_summary"] = str(self.out / "agent_summary.md")
        artifacts["transcript"] = str(self.out / "transcript.jsonl")
        artifacts["trace"] = str(self.trace.path)
        return proof, report, artifacts


def _block_get(block, key, default=None):
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def run_agent(
    spec: ProblemSpec,
    out_dir,
    client=None,
    model: str | None = None,
    max_turns: int = 40,
    log=print,
    on_run=None,
) -> AgentResult:
    """The "api" backend: a small manual tool loop. `client` is injectable for
    tests; `on_run` receives the AgentRun right after construction (the web
    job runner uses it to expose cooperative stop)."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    model = model or DEFAULT_MODEL
    run = AgentRun(spec, out_dir)
    if on_run is not None:
        on_run(run)
    messages: list[dict] = [{"role": "user", "content": _task_prompt(spec)}]

    turns = 0
    for turns in range(1, max_turns + 1):
        if run.finished:  # e.g. stopped from outside between turns
            break
        resp = client.messages.create(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        if getattr(resp, "stop_reason", None) == "refusal":
            raise RuntimeError("model refused the agent task")
        messages.append({"role": "assistant", "content": resp.content})
        tool_uses = [b for b in resp.content if _block_get(b, "type") == "tool_use"]
        for b in resp.content:  # feed narrative + thinking to the mind trace, in order
            if _block_get(b, "type") == "thinking" and _block_get(b, "thinking"):
                run.note_thought(_block_get(b, "thinking"), kind="thinking")
            elif _block_get(b, "type") == "text" and _block_get(b, "text"):
                run.note_thought(_block_get(b, "text"), kind="text")
                log(f"[agent] {_block_get(b, 'text')[:300]}")

        if not tool_uses:
            messages.append(
                {"role": "user", "content": "Use the tools, or call finish with your summary."}
            )
            continue

        results = []
        for tu in tool_uses:
            # Once finish is called, don't run later tools in the same batch
            # (they could mutate kernel state after the session was declared
            # done). Each tool_use still needs a matching tool_result.
            if run.finished:
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": _block_get(tu, "id"),
                        "content": "skipped: session already finished",
                        "is_error": True,
                    }
                )
                continue
            name = _block_get(tu, "name")
            args = dict(_block_get(tu, "input") or {})
            content, is_error = run.dispatch(name, args)
            log(f"[tool] {name}({json.dumps(args)[:120]}) -> "
                + (content if isinstance(content, str) else "<image+status>")[:160])
            result_block = {
                "type": "tool_result",
                "tool_use_id": _block_get(tu, "id"),
                "content": content,
            }
            if is_error:
                result_block["is_error"] = True
            results.append(result_block)
        messages.append({"role": "user", "content": results})
        if run.finished:
            break

    proof, report, artifacts = run.finalize()
    return AgentResult(
        spec=spec, out_dir=str(run.out), proof=proof, report=report,
        turns=turns, summary=run.summary, artifacts=artifacts,
    )


def run_agent_claude_code(
    spec: ProblemSpec,
    out_dir,
    model: str | None = None,
    max_turns: int = 40,
    log=print,
    on_run=None,
) -> AgentResult:
    """The "claude-code" backend: the Claude Agent SDK on the user's `claude` login.

    Tools are served from an in-process MCP server; `look` images travel as
    MCP image content. Claude Code's own built-in tools are disabled so the
    session stays inside the sandbox.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        create_sdk_mcp_server,
        query,
    )
    from claude_agent_sdk import tool as sdk_tool

    run = AgentRun(spec, out_dir)
    if on_run is not None:
        on_run(run)

    def bridge(t: dict):
        @sdk_tool(t["name"], t["description"], t["input_schema"])
        async def handler(args, _name=t["name"]):
            if run.finished and _name != "finish":
                return {"content": [{"type": "text", "text": "ERROR: session already finished"}]}
            content, is_error = run.dispatch(_name, dict(args or {}))
            if isinstance(content, str):
                blocks = [{"type": "text", "text": ("ERROR: " if is_error else "") + content}]
            else:
                blocks = []
                for b in content:
                    if b["type"] == "image":
                        blocks.append(
                            {
                                "type": "image",
                                "data": b["source"]["data"],
                                "mimeType": b["source"]["media_type"],
                            }
                        )
                    else:
                        blocks.append(b)
            log(f"[tool] {_name} -> " + ("<image+status>" if not isinstance(content, str) else content[:160]))
            return {"content": blocks}

        return handler

    server = create_sdk_mcp_server(name="sim", version="0.1.0", tools=[bridge(t) for t in TOOLS])
    options = ClaudeAgentOptions(
        mcp_servers={"sim": server},
        allowed_tools=[f"mcp__sim__{t['name']}" for t in TOOLS],
        disallowed_tools=[
            "Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "Read", "Glob",
            "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite",
        ],
        system_prompt=SYSTEM,
        permission_mode="bypassPermissions",
        max_turns=max_turns,
        model=model,  # None -> the login's default model
        cwd=str(run.out),
    )

    turns = 0

    async def go():
        nonlocal turns
        async for message in query(prompt=_task_prompt(spec), options=options):
            if run.stop_requested:
                break  # closing the generator tears down the SDK session
            if isinstance(message, AssistantMessage):
                turns += 1
                for block in message.content:
                    thinking = getattr(block, "thinking", None)
                    if thinking:
                        run.note_thought(thinking, kind="thinking")
                    text = getattr(block, "text", None)
                    if text:
                        run.note_thought(text, kind="text")
                        log(f"[agent] {text[:300]}")
            elif isinstance(message, ResultMessage):
                cost = getattr(message, "total_cost_usd", None)
                log(f"[session] done ({turns} assistant turns"
                    + (f", ${cost:.4f}" if cost else "") + ")")

    asyncio.run(go())
    proof, report, artifacts = run.finalize()
    return AgentResult(
        spec=spec, out_dir=str(run.out), proof=proof, report=report,
        turns=turns, summary=run.summary, artifacts=artifacts,
    )


def run(
    spec: ProblemSpec,
    out_dir,
    backend: str | None = None,
    model: str | None = None,
    max_turns: int = 40,
    log=print,
    on_run=None,
) -> AgentResult:
    """Backend dispatcher: 'api', 'claude-code', or None/'auto' to resolve."""
    resolved = resolve_backend(backend)
    log(f"[backend] {resolved}")
    if resolved == "claude-code":
        return run_agent_claude_code(
            spec, out_dir, model=model, max_turns=max_turns, log=log, on_run=on_run
        )
    return run_agent(spec, out_dir, model=model, max_turns=max_turns, log=log, on_run=on_run)
