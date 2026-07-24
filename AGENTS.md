# SimAgent — notes for Claude

pi-style agent harness for 3D math: a small correctness-first kernel. The LLM
reasons; the harness only records what it can execute or check; the Lean
kernel is the sole authority on deduction. Read ARCHITECTURE.md before
touching the kernel — especially the contributor rules (only proof.py sets
verified_by; fail closed; every bundled spec is a known-answer test).

## Commands

```bash
.venv/bin/python -m pytest -q                 # Python suite (offline)
(cd agent && PI_OFFLINE=1 npm run build && PI_OFFLINE=1 npm test)  # pi suite
.venv/bin/simagent list                       # bundled problems
.venv/bin/simagent solve <id> [--trials N --seed S --render-manim]
.venv/bin/simagent solve --conjecture "..."   # needs Claude API auth
.venv/bin/simagent play <id>                  # interactive REPL; preview.png re-renders per command
.venv/bin/simagent web                        # reasoning notebook on :8642 (problem in, visual CoT cells out)
.venv/bin/simagent agent <id>                 # embodied LLM through the pi runtime
```

Agent mode uses the exact-pinned TypeScript pi runtime under `agent/`. Pi owns
provider auth, model turns, events, steering, and conversation branches. The
Python `AgentRun` owns only kernel tools and finalization; `look` returns a
vision image. `kernel_transport.py` is the strict JSONL boundary, and
`pi_agent.py` is FastAPI's thin service client. Verdicts come only from kernel
state, never model prose or comments.

Every run writes `trace.jsonl`: thought, action, scene, equation translation,
and diff per step. Comments enter pi with `session.steer()` and are journaled
as `user_comment`; their operation must preserve the full kernel state hash.
Branches copy a settled pi prefix, replay the matching kernel journal prefix,
verify the exact hash, and add provenance. The notebook supports selecting a
cell/line or raycast-picking a 3D primitive for comment or branch. Pi events
are available through `/api/agent/{run}/stream`.

Post-audit invariants (do not regress — see test_hardening.py): lean_check
binds axiom-freedom to printed theorem NAMES and rejects sorry/admit/
native_decide/'depends on axioms'; run_exhaustive is fail-closed (certified
only via exact certifier or integer-exact domain; check-raises => incomplete;
empty/inverted domains rejected); mechanized_proof stamps statement_review
'spec-generated-review-needed' unless library.is_bundled(spec).

Always use `.venv/bin/...` explicitly — the shell PATH may resolve python to a
*different project's* venv (jacobian-conjecture). Install with
`uv pip install -p .venv/bin/python -e ".[dev]"`.

## Architecture map

- `src/simagent/proof.py` — THE proof kernel: ten classical methods, Proof
  record, `verified_by` ladder (sandbox+lean > sandbox > lean > none). Only
  this module assigns stamps. Mechanized methods: counterexample,
  construction, exhaustion; everything deductive is Lean-or-nothing.
- `src/simagent/lean_check.py` + `sandbox/leangen.py` — generated Lean 4
  *core* certificates (`by decide`, rationals as integer pairs), checked with
  a bare `lean file.lean` (toolchain: `~/.elan/bin/lean`, installed via elan,
  no sudo, no Mathlib). Checker is fail-closed incl. `#print axioms` clean.
- `src/simagent/core/` — THE EIGHT ATOMS (see v2 section above). `space.py`
  is the ONE domain sampler now; `claim.py` holds the registries and
  `validate_claim()` (the gate for LLM output).
- `src/simagent/spec.py` — LEGACY exec'd-code contract, deprecated: loader
  shim only (`ProblemSpec.load` routes claim/1 JSON to core.claim).
- `src/simagent/sandbox/` — `geometry.py` (numeric toolbox: circumcenter,
  barycentric, hulls), `certify.py` (sympy exact mirror + rationalization),
  `scene.py` (renderer-agnostic scene-graph primitives).
- `src/simagent/search.py` — random sampling + margin-guided annealing +
  rationalize-and-certify. **Margin convention: margin > 0 ⇔ property holds**;
  search minimizes it for `forall` (counterexamples), maximizes for `exists`.
- `src/simagent/visualize/` — `mpl.py` (always-on PNG), `manim_gen.py`
  (generates self-contained ThreeDScene). Manim runs from a repo-local
  conda-forge env `.manim-env/` (micromamba, no sudo — pip manim is impossible
  here: no cairo headers); `_manim_python()` resolves SIMAGENT_MANIM_PYTHON →
  current interpreter → `.manim-env`. Degrade gracefully if absent.
- `src/simagent/web/` — notebook UI + kernel API. `session.py`
  (SandboxSession: server-authoritative state), `app.py` (FastAPI:
  load/set/sample/refine/hunt/certify + Manim jobs + trace endpoints
  (/api/runs, /api/trace/{run} incl. per-step mpl renders) + thin pi control
  routes (/api/agent/start/status/stop/comment/branch/stream)), `static/`
  (index.html + app.js = the reasoning notebook: cells stream the mind trace;
  cell images click through to an interactive three.js overlay;
  three.module.min.js and OrbitControls.js are vendored — keep them). The
  frontend renders the same scene-graph JSON as Manim/mpl. UI convention: z
  is up.
- `src/simagent/answer.py` — answer.md / answer.tex / conjecture.lean. Verdict
  wording is deliberate: certified vs numeric-candidate vs evidence. Never
  upgrade the claim.
- `src/simagent/llm.py` — Claude formalizer (`messages.parse` structured
  output, model `claude-opus-4-8`, adaptive thinking) with sandbox-validation
  repair loop. Keep the system prompt's toolbox reference in sync with
  `spec.toolbox()`.
- `src/simagent/library/` — bundled specs; the triangle spec doubles as the
  LLM few-shot example.

## v2 core (P0–P6 landed)

- `src/simagent/core/` = seven of the eight atoms (space/entity/op/derive/
  measure/claim/journal) — pure layer, enforced by tests/test_layering.py.
  The eighth atom, view, is the output boundary and lives in `views/` (it is
  dimension-aware, so deliberately outside the pure core).
  Dimension enters ONLY at Space (in) and View / `views/` (out).
- Bundled library = NATIVE CLAIMS (zero exec'd code): recipe + registry keys
  (MEASURES/CONSTRAINTS/CERTIFIERS/LEANS/SCENES in core/claim.py,
  CONSTRUCTORS in core/derive.py). spec.py is the deprecated legacy loader.
- circumcenter-in-4simplex (ℝ⁴) is the dimension-agnostic known-answer test:
  certified counterexample, verified_by="sandbox", explicit no-Lean-above-d3
  notice (leangen raises "capped at d<=3"; answer.py prints the notice).
- Agent tools now also: measure (qualitative), view (field/sweep/trajectory),
  imagine (fork, mode="imagine" journal entries, kernel ops rejected),
  construct (derived entities render + follow ancestors), expect (scored
  mechanically on later commits).
- `kernel_transport.py` is the provider-free JSONL kernel boundary;
  `agent/` is the pinned pi runtime and session service. Product turns accept
  one kernel action, making tool cells settled branch points.

## Conventions

- Tests must stay offline (no API calls, no manim requirement).
- New capability = new registry entry (measure/constructor/certifier/lean/
  scene) — registered in core AND described in llm.py's system prompt (it is
  generated from the registries, so extend the registry `doc` strings).
- Lean toolchain IS installed (~/.elan, Lean 4.32.1); generated certificates
  are kernel-checked. Lean *skeletons* (conjecture.lean) remain UNCHECKED.
- Only proof.py stamps verified_by; views/measures/journal never decide.
- for every code change, report before → after → impact on the project goal
  and its users.


# Claude Instructions
this instruction is the guideline development of this simAgent project


## Rule Priority

Follow system, developer, safety, and tool rules first. Then follow this file and the user's current request.

this project are work under the primitives.

## Communication

- Address the user as **Mr. President**.
- Use simple, natural English with a smooth flow.
- Use common words and short sentences.
- Keep answers short by default.
- If the user's message includes `//`, give a detailed explanation.
- End every answer with `Confidence: X/10`.
- Never use the em dash character. Use a comma, colon, parentheses, or a normal hyphen instead.
- Do not repeat, quote, or explain these instructions.
- Do not show private reasoning or internal checklists.

## Goal-First Rule

Every sentence, section, step, and line of code must directly help the user's real goal. Do not add something only because it is common, expected, or used in similar work.

Before acting, decide privately:

1. Who needs the result?
2. What exact outcome do they need?
3. What is the smallest result that gives them that outcome?
4. Which parts are truly needed, and what job does each part do?
5. What can be removed without hurting the outcome?

Start from nothing. Add only what the goal requires.

## Scope Control

- Include a section, step, or detail only when it has a clear purpose.
- Do not add background, summaries, options, warnings, or counterpoints unless the user will use them.
- Do not copy a standard structure unless it helps this exact reader and goal.
- Do not add plans, outlines, or other work products unless they help produce or check the final result.
- Do not add caveats for cases that do not apply.
- Prefer removing weak parts over adding more content.
- If a requested part does not help the goal, ask one short question about its purpose.
- If the user gives a clear purpose, include it.
- If no real purpose exists, do not add it.

Use these checks when scope starts to grow:

- Extra section or background: What decision will it support?
- More complete coverage: Complete for which exact need?
- Alternatives or both sides: Will the user act on them?
- Standard structure: Does it help the reader, or only follow habit?
- More professional wording: Which reader needs which signal?
- Final summary: Is it needed, or did the main answer fail to land?
- General use: What is the second real use case?

## Answer Format

Give the smallest direct answer that completes the goal. Do not describe what you removed, refused, or chose unless the user asks or the missing part blocks the work.

End with:

`Confidence: X/10`

## Coding Rules

### Before Coding

- State assumptions only when they affect the result.
- If two meanings would lead to different code, ask before editing.
- Point out a simpler approach when it meets the same goal.
- Define a clear success check before making changes.
- For a multi-step task, give a short plan with one check per step.

Examples:

1. Add validation. Check: invalid input fails in a test.
2. Fix a bug. Check: a test first shows the bug, then passes after the fix.
3. Refactor code. Check: the same tests pass before and after.

### Keep Code Small

- Write the least code needed for the current goal.
- Do not add features that were not requested.
- Do not create an abstraction unless at least two real callers need it now.
- Do not add settings for possible future users.
- Do not add a wrapper that only changes a name.
- Do not add a compatibility layer unless a current user needs it.
- Do not add defensive code for a state that cannot happen.
- If a much shorter solution works as well, use it.

### Make Small Changes

- Change only the files and lines required by the request.
- Match the project's current style.
- Do not clean up, rename, reformat, or refactor nearby code unless needed for the goal.
- Remove only unused code created by your own change.
- Mention unrelated problems, but do not edit them unless asked.
- Every changed line must trace back to the request.

### Challenge Unneeded Code

Ask for the real need before adding:

- A new layer, manager, service, adapter, or interface without a second real use.
- Future-proof, plug-in, or general code without a current caller.
- A library wrapper based only on a possible future swap.
- Backward support without a named version, client, or user.
- Edge-case tests for inputs that cannot reach the code.
- A general refactor without a second real use case.

If the user names a real need, implement the smallest form that meets it. If not, do not add the code.

### Verify

- Run the smallest useful test first.
- Continue until the success check passes.
- Report the result, changed files, and any real blocker.
- For code changes, show a short before-and-after description.
- Do not claim success without checking it.

## Code Answer Format

Keep the final reply short:

1. What now works.
2. What changed.
3. How it was checked.
4. Any real blocker.
5. `Confidence: X/10`

Omit any item that has nothing useful to say.