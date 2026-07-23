# SimAgent — notes for Claude

pi-style agent harness for 3D math: a small correctness-first kernel. The LLM
reasons; the harness only records what it can execute or check; the Lean
kernel is the sole authority on deduction. Read ARCHITECTURE.md before
touching the kernel — especially the contributor rules (only proof.py sets
verified_by; fail closed; every bundled spec is a known-answer test).

## Commands

```bash
.venv/bin/python -m pytest -q                 # test suite (offline, ~5 s)
.venv/bin/simagent list                       # bundled problems
.venv/bin/simagent solve <id> [--trials N --seed S --render-manim]
.venv/bin/simagent solve --conjecture "..."   # needs Claude API auth
.venv/bin/simagent play <id>                  # interactive REPL; preview.png re-renders per command
.venv/bin/simagent web                        # browser sandbox on :8642 (drag points, Manim panel)
.venv/bin/simagent agent <id>                 # embodied LLM; --backend claude-code uses `claude` login
```

Agent mode has two backends (src/simagent/agent.py): `api` (Anthropic SDK) and
`claude-code` (Claude Agent SDK on the `claude` login, no API key — needs
`pip install -e ".[login]"` + the `claude` CLI). Both drive the same AgentRun
tool state machine; `look` returns the scene as a vision image. Verdicts come
only from kernel state (best_report + certify), never the model's prose.

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
- `src/simagent/spec.py` — ProblemSpec contract. Code fields are strings
  (JSON-serializable, LLM-emittable) exec'd with the sandbox toolbox in scope.
  `validate_spec()` is the gate for LLM output. `sample_vars()` is the ONE
  domain sampler (kind="int" grids enable exhaustion; keep it single-sourced).
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
- `src/simagent/web/` — browser sandbox. `session.py` (SandboxSession: server-
  authoritative state), `app.py` (FastAPI: load/set/sample/refine/hunt/certify
  + Manim job queue), `static/` (index.html + app.js three.js frontend;
  three.module.min.js and OrbitControls.js are vendored — keep them). The
  frontend renders the same scene-graph JSON as Manim/mpl; drags stream
  throttled /api/set calls. UI convention: z is up.
- `src/simagent/answer.py` — answer.md / answer.tex / conjecture.lean. Verdict
  wording is deliberate: certified vs numeric-candidate vs evidence. Never
  upgrade the claim.
- `src/simagent/llm.py` — Claude formalizer (`messages.parse` structured
  output, model `claude-opus-4-8`, adaptive thinking) with sandbox-validation
  repair loop. Keep the system prompt's toolbox reference in sync with
  `spec.toolbox()`.
- `src/simagent/library/` — bundled specs; the triangle spec doubles as the
  LLM few-shot example.

## Conventions

- Tests must stay offline (no API calls, no manim requirement).
- New sandbox helpers: add to `spec.toolbox()` / `certify_toolbox()` AND to the
  system prompt in `llm.py`, or the LLM can't use them.
- Lean output is a skeleton; always flagged UNCHECKED unless a toolchain
  verified it. No Lean toolchain is installed here.
