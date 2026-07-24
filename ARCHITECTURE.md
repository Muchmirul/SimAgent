# SimAgent architecture
THIS PROJECT IS ONLY HARNESS, thinking or any thought must come from the model itself, which must not be provided here

SimAgent is an **agent harness for visualization-based math**: a small kernel
with a strict responsibility split, where correctness beats features. Humans
and agents solve math by communicating through visuals — imagine, visualize,
act, and only then formalize (equations are the *translation* of thought,
never the medium). See plan.md for the full v2 design and decision log.

core idea of sim agent is this :
1. simagent is the harness on how to get of the best harness to routed models llm, to solve any math problem by experiencing doing math by viz and equation is just formalization. instead of just using text file. and gathering information from outside. doing it by first principle.
2. as a toll human and ai agent can collaborate on solving, sometimes human get stuck agent help, and sometime human giving idea while agent stuck. this done by seamless ui that human can giving comment on the step that agent do.


## The eight atoms

Everything in the domain — harnessing an LLM to do math through visualization
— composes from eight primitives (`src/simagent/core/`). Dimension-aware code
exists ONLY at the two boundaries: Space (input) and View (output); everything
between is dimension-blind.

| primitive | physical analogy | role |
|---|---|---|
| **Space** | configuration space | input boundary: `sample / valid / perturb / exact / enumerate_cases`. v1: `Box(ℝᵈ)`, `IntBox(ℤᵈ)` |
| **Entity** | particle | named, stable id; *free* (value in a Space) or *derived* (recipe over entities — coordinates are consequences, the CAD lesson) |
| **Op** | force | THE only mutation channel (Blender lesson) = the agent's action vocabulary; a closed registry replaces exec'd code |
| **Derive** | physical law | dependency graph; derived entities recompute when ancestors move |
| **Measure** | observable | perception as calibrated compression: margins + qualitative predicates; never raw coordinate dumps |
| **Claim** | hypothesis under test | quantifier + free Spaces + recipe + a distinguished measure, all from closed registries |
| **Journal** | worldline / lab notebook | dynamics first-class: state = replay(journal) = save format = undo = notebook feed; `imagine` branches = thought experiments; annotations = plan/expect/user_comment |
| **View** | detector | output boundary: identity (d≤3), **field** (margin painted over a config-space slice, fixed diverging colormap centered at 0, zero-contour = the theorem's shape — the Ansys lesson), sweep, ghost, trajectory |

Derivations (features as compositions): sample = Op(Space.sample) · refine =
loop{perturb → Measure → keep} · hunt = sampleⁿ + refine · exhaust =
Space.enumerate_cases × Measure · certify = Space.exact + exact Measure · construct
= Op(add derived) + Derive · diff = Journal[n] − Journal[n−1] · imagine = Ops
on a World fork, journaled `mode:"imagine"`, never merged · expect = journal
annotation scored mechanically on later commits · undo/branch = journal
prefix replay + fork.

## The responsibility split

```
LLM / human   — reasons, conjectures, chooses proof methods, writes Lean
harness      — executes, enumerates, certifies, kernel-checks; keeps state
Lean kernel  — the only authority on deductive truth
```

The harness **never evaluates prose**. An argument becomes a proof only when
machinery checks it. UIs (web, terminal REPL, CLI) are thin shells over the
kernel; they can display state but cannot mint verdicts.

## The three pillars

| pillar | role | trust |
|---|---|---|
| **Python** | computation: sandbox, search, exact rationals (sympy) | trusted for *mechanized* methods only |
| **Lean 4** | formulation + deductive verification (`decide`, core-only certificates) | the kernel is the root of trust |
| **Manim** | visualization: the presentation renderer over the shared scene graph | no trust role — pictures explain, never prove |

## The proof kernel (`proof.py`)

Every answer names one of the ten classical proof methods and carries a
`verified_by` stamp that **only `proof.py` assigns**:

| method | who can verify it here | how |
|---|---|---|
| counterexample | harness (+ Lean) | exact-rational violation of a ∀; Lean pair-arithmetic certificate |
| construction | harness (+ Lean) | exact-rational witness of an ∃; same certificate machinery |
| exhaustion | harness (+ Lean) | every case of a finite integer domain checked; Lean `decide` over the bounded statement |
| direct | Lean only | |
| contradiction | Lean only | |
| contrapositive | Lean only | |
| induction | Lean only | |
| cases | Lean only | |
| combinatorial | Lean only | |
| infinite descent | Lean only | |

`verified_by` values, strongest first:

- `sandbox+lean` — harness check AND a generated certificate accepted by the
  Lean kernel with **no axioms** (`#print axioms` must come back clean).
- `sandbox` — complete mechanical check by the harness (exact rationals or
  full enumeration). Sound, but not independently checked.
- `lean` — a Lean proof (usually LLM-written) the kernel accepted; the
  *statement's* faithfulness to the conjecture still needs human review
  (`statement_review` field).
- `none` — an argument on record. Not a proof. The harness says so.

Sampling evidence ("no counterexample in N trials") is **never** a proof and
`mechanized_proof` returns `None` for it, deliberately.

## Lean certificates (`sandbox/leangen.py`, `lean_check.py`)

Certificates target **Lean 4 core only** — no Mathlib, no Batteries, no lake.
Checking is one `lean file.lean` process; proofs are `by decide`, i.e. pure
kernel computation, which is why the axiom check can demand "does not depend
on any axioms".

Rationals are encoded as integer pairs `(p, q)` with `q > 0` asserted for
every atom; `qadd/qsub/qmul` multiply denominators so positivity is closed
under the operations, and cross-multiplied `qeq/qlt` then coincide with `=`/`<`
on ℚ. That two-line closure argument is the entire trusted modeling step —
everything else is kernel-checked arithmetic on explicit numerals.

The checker is **fail-closed and does not trust the source** (which is
spec-controlled). It rejects unless ALL hold: no `sorry`/`admit`/`sorryAx`/
`native_decide` token (comments stripped first); clean exit with no sorry
warning; the source names ≥1 `#print axioms <thm>` and Lean reports *each named
theorem* axiom-free by name; and no `depends on axioms` line appears anywhere.
Binding axiom-freedom to the printed theorem *names* is what stops a source
from echoing the clean phrase to spoof the check.

**Trust vs. faithfulness.** A `sandbox+lean` stamp means the Lean kernel
accepted the certificate. For a bundled spec that certificate is reviewed, so
`statement_review = bundled-trusted`. For any other spec (disk-loaded, LLM-
authored) the Lean *statement itself* is spec-controlled, so the proof is
stamped `spec-generated-review-needed`: the arithmetic is kernel-checked, but a
human must confirm the Lean theorem actually states the conjecture. Trust is
by object identity with the bundled registry (`library.is_bundled`), never by
id string.

**Exhaustion soundness.** `run_exhaustive` fails closed: a found
counterexample/witness is `certified` only via an exact certifier or the
domain's integer-exactness (all inputs `|x| ≤ 2^40`, keeping float64 integer
arithmetic exact below `2^53`); a case whose `check` raises makes the whole
`∀`/`∃` verdict *incomplete* (not a proof); empty/inverted (`low > high`)
domains are rejected; case counting uses Python ints (no `np.prod` overflow).

## Data flow

```
conjecture ──(llm.formalize, sandbox-validated)──▶ Claim (recipe + registry keys, no exec'd code)
Claim ──▶ search: run_exhaustive (finite int domains: EVERY case)
                        run_search    (continuous: sample + anneal + certify)
report ──▶ proof.mechanized_proof ──▶ Proof {method, claim, verified_by}
                    │                        │
                    └── leangen certificate ─┴─▶ lean_check (kernel, axiom-free)
Proof + report ──▶ answer.md / answer.tex / conjecture.lean / proof.json
scene graph ──▶ matplotlib preview │ Manim still/video │ three.js live view
```

## Agent mode (pi control plane)

The TypeScript package under `agent/` owns provider authentication, model
turns, event streaming, steering, and pi conversation sessions. It starts one
private Python `kernel_transport.py` process per run. The Python process owns
`AgentRun`, `SandboxSession`, exact checks, Lean checks, trace output, and
finalization. Pi transports messages but cannot stamp a verdict.

Product runs expose only the closed SimAgent tools and disable pi's coding
tools and resource discovery. Tool execution is sequential. One kernel action
is accepted per model turn, so each tool cell ends at a settled pi checkpoint.
A branch copies the pi conversation prefix, replays the matching Python
journal prefix, and rejects unless the state hash agrees exactly.

There are two correlated records:

1. The pi session stores conversation, thinking, tool bracketing, steering,
   and the branch tree.
2. `kernel-journal.jsonl` and `trace.jsonl` store the reproducible world,
   pictures, equations, diffs, annotations, and proof candidates.

A targeted comment is written to the trace as `user_comment` and delivered
through `session.steer()` after the current tool batch. The annotation
operation asserts that the complete kernel state hash is unchanged. Branches
add a provenance annotation containing source run, step, journal sequence,
and hash. Neither annotation kind is verdict material.

The reasoning notebook polls the kernel trace and can also consume pi events
through `/api/agent/<run>/stream`. A user can select a cell, thought, action,
or equation line, or raycast-pick a 3D primitive, then comment or branch from
that state. The verdict cell still reads only `proof.json` and `answer.md`.

## Files

```
src/simagent/
  core/          SEVEN OF THE EIGHT ATOMS (View is the 8th, in views/; pure:
                 stdlib+numpy+sympy+sandbox leaves only, enforced by
                 tests/test_layering.py):
                   space.py entity.py op.py derive.py measure.py claim.py
                   journal.py
  views/         the output boundary: identity, field, sweep, ghost, trajectory
                 (one calibrated visual language: diverging colormap centered
                 at margin 0 — blue HOLDS / red FAILS, zero-contour marked)
  search.py      sampled search + annealing (Space.perturb) + exact certify;
                 exhaustive enumeration (Space.enumerate_cases) — fail-closed
  proof.py       the proof kernel (methods, Proof, verified_by) — sole verdict authority
  lean_check.py  run Lean core on generated sources; fail-closed acceptance
  sandbox/       geometry.py (numeric, d-generic simplex math + hull_facets),
                 certify.py (sympy exact, any-ndim rationalization),
                 scene.py (scene graph), leangen.py (Lean certs; d<=3 cap
                 stated explicitly — the LU-witness encoding is the extension)
  answer.py      Markdown / LaTeX / Lean skeleton emitters; states the d>3
                 no-Lean cap explicitly in every verdict it touches
  pipeline.py    one run = claim → search → proof → viz → answers → report.json
  llm.py         formalize (native Claim synthesis from the closed vocabulary,
                 sandbox-vetted) and attempt_proof (Lean-checked, never trusted)
  library/       bundled native Claims — zero exec'd code; known-answer tests
                 incl. circumcenter-in-4simplex (the dimension-agnostic gate)
  visualize/     mpl.py (always-on PNG), manim_gen.py (generated ThreeDScene)
  agent.py       kernel-side tool state over one SandboxSession; no provider loop
  kernel_transport.py  strict JSONL kernel bridge: tools, annotations, stop,
                 hash-verified prefix replay, toolCallId correlation
  pi_agent.py    thin client for the TypeScript pi control service
  spec.py        LEGACY exec'd-code contract (deprecated; loader only)
  trace.py       shim → core.journal
  play.py, web/  shells: terminal REPL and the reasoning-notebook UI over the
                 same kernel (trace replay/live-follow via /api/runs,
                 /api/trace; agent sessions via /api/agent/start)
agent/           TypeScript pi runtime and session service (exact-pinned)
```

## Rules for contributors (human or LLM)

1. Only `proof.py` sets `verified_by`. Never fake a stamp in a shell or spec.
2. New capability = new *mechanized check* or new *Lean certificate shape*,
   not a new claim the harness can't check. Fail closed.
3. Every bundled spec is a known-answer test: its ground truth is documented
   and the test suite asserts the machine reaches it.
4. Certificates must stay core-Lean and `decide`-based unless a stronger,
   equally-checkable scheme replaces them repo-wide.
5. Shells (CLI/REPL/web) may render state; they must not compute verdicts.
