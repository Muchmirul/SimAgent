"""LLM formalizer: natural-language conjecture -> validated ProblemSpec.

The model writes *against the sandbox*: its check/scene/certify code is
compiled and smoke-tested locally (spec.validate_spec); failures are fed back
for repair. Structured output keeps the spec schema-exact.

Auth: the anthropic client resolves ANTHROPIC_API_KEY or an `ant auth login`
profile automatically — no key handling here.
"""
from __future__ import annotations

import importlib.util
import json
import os
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from .spec import ProblemSpec, validate_spec

DEFAULT_MODEL = os.environ.get("SIMAGENT_MODEL", "claude-opus-4-8")


def resolve_backend(backend: str | None = None) -> str:
    """Pick the agent backend: 'api' (Anthropic SDK key/profile) or
    'claude-code' (Claude Agent SDK on the user's `claude` login).

    Order: explicit arg > SIMAGENT_BACKEND env > auto. Auto prefers the API
    when a key/profile is present, else claude-code if the SDK + `claude` CLI
    are available.
    """
    import shutil

    choice = (backend or os.environ.get("SIMAGENT_BACKEND") or "auto").lower()
    if choice in ("api", "claude-code"):
        return choice
    have_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    have_cc = (
        importlib.util.find_spec("claude_agent_sdk") is not None and shutil.which("claude") is not None
    )
    if have_key:
        return "api"
    if have_cc:
        return "claude-code"
    return "api"  # let the API backend surface a clear auth error


class VarModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    shape: list[int]
    low: float = -1.0
    high: float = 1.0
    kind: Literal["real", "int"] = "real"


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    conjecture: str
    latex: str
    quantifier: Literal["forall", "exists"]
    domain: list[VarModel]
    check_code: str
    scene_code: str
    constraint_code: Optional[str] = None
    certify_code: Optional[str] = None
    lean_statement: str = ""
    notes: str = ""


def _example_spec_json() -> str:
    from .library import get

    return json.dumps(get("circumcenter-in-triangle").to_json(), indent=2)


def build_system_prompt() -> str:
    return f"""You are the formalization stage of SimAgent, a sandbox harness for
exploring math conjectures. Convert the user's conjecture into a ProblemSpec:
an executable, searchable, visualizable form of the statement.

## Code contract (Python, exec'd with a fixed toolbox in scope)

check(**vars) -> {{"holds": bool, "margin": float | None, "data": dict}}
  - vars are numpy arrays shaped per the domain you declare.
  - margin > 0 MUST be equivalent to holds == True; magnitude = robustness.
    Provide a continuous margin whenever possible (it powers annealing);
    use None only for genuinely discrete checks.
build_scene(**vars) -> list of scene primitives (see below); make the
  interesting object visually obvious (color the violating element red).
valid(**vars) -> bool   (optional constraint_code; reject degenerate samples)
certify(**vars) -> bool (optional certify_code; EXACT arithmetic only —
  vars arrive as sympy Matrices/Rationals; return whether the property HOLDS.
  Provide it whenever the property is decidable in rational arithmetic; it is
  what upgrades a numeric finding into a mathematical certificate.)

## Toolbox in scope for check/build_scene/valid
np, math,
circumcenter(pts), barycentric(pts, x), simplex_volume(pts)   # (n+1, n) simplex
hull_counts(points3d) -> (V, E, F), hull_mesh(points3d) -> (vertices, faces)
scene_points(coords, color=..., radius=..., name=...), scene_segments(pairs, ...),
scene_polygon(coords, ...), scene_mesh(vertices, faces, ...),
scene_sphere(center, radius, ...), scene_label(text)

## Toolbox in scope for certify
sp (sympy), exact_circumcenter(M), exact_barycentric(M, x)  # sympy Matrices

## Domain
Declare each variable with name, shape (e.g. [3, 2] = 3 points in R^2, [] =
scalar), bounds, and kind. kind="real" is a uniform box (sampled search);
kind="int" is an integer grid — if EVERY variable is an int grid with a small
total case count, the harness checks every case (proof by exhaustion), which
is the strongest thing it can do, so prefer finite integer domains whenever
the conjecture allows a faithful bounded form. Keep coordinates O(1).
quantifier: "forall" means the harness hunts counterexamples; "exists" means
it hunts witnesses.

## Honesty
latex must faithfully state the conjecture. lean_statement is a Lean 4 /
Mathlib statement of the *positive* conjecture (the harness negates it if
disproved); if no clean Mathlib formulation exists, say so in a Lean comment.
Use notes for caveats (e.g. discrete check = evidence only).

## Example spec (this exact JSON shape)
{_example_spec_json()}
"""


class FormalizeError(RuntimeError):
    pass


def _request_spec(client, model: str, messages: list[dict]) -> dict:
    """One structured-output request; parse() with a raw-schema fallback."""
    try:
        resp = client.messages.parse(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=build_system_prompt(),
            messages=messages,
            output_format=SpecModel,
        )
        if resp.stop_reason == "refusal":
            raise FormalizeError("model refused the formalization request")
        if resp.parsed_output is None:
            raise FormalizeError(f"no parsed output (stop_reason={resp.stop_reason})")
        return resp.parsed_output.model_dump()
    except (AttributeError, TypeError):
        schema = SpecModel.model_json_schema()
        resp = client.messages.create(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=build_system_prompt(),
            messages=messages,
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if resp.stop_reason == "refusal":
            raise FormalizeError("model refused the formalization request")
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)


def formalize(
    conjecture_text: str,
    model: str | None = None,
    max_repairs: int = 2,
    log=print,
) -> ProblemSpec:
    """Conjecture text -> validated ProblemSpec (with a repair loop)."""
    import anthropic

    client = anthropic.Anthropic()
    model = model or DEFAULT_MODEL
    messages: list[dict] = [
        {
            "role": "user",
            "content": f"Formalize this conjecture into a ProblemSpec:\n\n{conjecture_text}",
        }
    ]
    errors: list[str] = []
    for attempt in range(max_repairs + 1):
        log(f"[llm] formalize attempt {attempt + 1} (model={model})")
        spec_dict = _request_spec(client, model, messages)
        spec = ProblemSpec.from_json(spec_dict)
        errors = validate_spec(spec)
        if not errors:
            log(f"[llm] spec '{spec.id}' validated against the sandbox")
            return spec
        log(f"[llm] spec failed validation: {errors}")
        messages.append({"role": "assistant", "content": json.dumps(spec_dict)})
        messages.append(
            {
                "role": "user",
                "content": (
                    "That spec failed sandbox validation:\n- "
                    + "\n- ".join(errors)
                    + "\nReturn a corrected, complete spec (all fields)."
                ),
            }
        )
    raise FormalizeError(f"spec failed validation after {max_repairs + 1} attempts: {errors}")


class ProofAttemptModel(BaseModel):
    """A deductive proof attempt. The harness checks the Lean; it never trusts prose."""

    model_config = ConfigDict(extra="forbid")
    method: Literal[
        "direct",
        "contradiction",
        "contrapositive",
        "induction",
        "cases",
        "construction",
        "counterexample",
        "exhaustion",
        "combinatorial",
        "infinite_descent",
    ]
    argument: str
    lean_code: Optional[str] = None


PROOF_SYSTEM = """You are the proof stage of SimAgent. Given a ProblemSpec and
the sandbox search report, produce ONE proof attempt.

Rules (the harness enforces them; do not fight them):
- Pick exactly one classical method and name it in `method`. The sandbox has
  already exhausted the mechanized methods (counterexample / construction /
  exhaustion) — you are called because a deductive method is needed, so
  usually: direct, contradiction, contrapositive, induction, cases,
  combinatorial, or infinite_descent.
- `argument` is the honest human core of the proof — every step justified,
  no more certainty than the evidence supports.
- `lean_code`, if you can produce it, must be a SELF-CONTAINED Lean 4 CORE
  file: no imports, no Mathlib, no Batteries, no sorry. Prefer statements
  decidable by `decide` over Nat/Int (bounded quantifiers via `∀ n, n < N →`,
  explicit numerals, small recursive defs), and end with
  `#print axioms <theorem_name>` — the harness accepts the proof only if Lean
  exits cleanly and reports no axioms. If the theorem genuinely cannot be
  stated in core Lean, omit lean_code; your attempt will be recorded as
  unverified, which is the honest outcome."""


def attempt_proof(spec: ProblemSpec, report_json: dict, model: str | None = None) -> dict:
    """One structured deductive proof attempt: {method, argument, lean_code}."""
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.parse(
        model=model or DEFAULT_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=PROOF_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    "ProblemSpec:\n```json\n"
                    + json.dumps(spec.to_json(), indent=2)
                    + "\n```\n\nSearch report:\n```json\n"
                    + json.dumps(report_json, indent=2)
                    + "\n```"
                ),
            }
        ],
        output_format=ProofAttemptModel,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise FormalizeError(f"no proof attempt (stop_reason={resp.stop_reason})")
    return resp.parsed_output.model_dump()
