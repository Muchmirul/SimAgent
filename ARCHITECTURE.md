# SimAgent architecture

SimAgent is an **agent harness for 3D math**: a small kernel with a strict
responsibility split, where correctness beats features.

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
conjecture ──(llm.formalize, sandbox-validated)──▶ ProblemSpec (JSON + code)
ProblemSpec ──▶ search: run_exhaustive (finite int domains: EVERY case)
                        run_search    (continuous: sample + anneal + certify)
report ──▶ proof.mechanized_proof ──▶ Proof {method, claim, verified_by}
                    │                        │
                    └── leangen certificate ─┴─▶ lean_check (kernel, axiom-free)
Proof + report ──▶ answer.md / answer.tex / conjecture.lean / proof.json
scene graph ──▶ matplotlib preview │ Manim still/video │ three.js live view
```

## Agent mode (`agent.py`)

The embodiment layer: an LLM runs a tool loop against one `SandboxSession` —
`look` (rendered scene as an image), movement tools, the search machinery,
`certify`, `exhaust`, and `submit_lean_proof`. Three rules keep it honest:

1. The loop is manual and small; every tool result is transcribed
   (`transcript.jsonl`) and every look is saved (`looks/`).
2. Tool handlers only call kernel functions; they cannot stamp verdicts.
   Session state is kept-best (a later weaker search or failed Lean attempt
   never downgrades an earlier decisive one), and no tool runs after `finish`.
3. `finalize()` builds the outcome from kernel state (certified reports,
   kernel-checked Lean). The model's `finish` summary is stored as narrative,
   clearly labeled, and never merged into the verdict.

Two interchangeable backends drive the same `AgentRun` state machine:

- **`api`** — a manual tool loop over the Anthropic SDK (API key or
  `ant auth login` profile).
- **`claude-code`** — the Claude Agent SDK on the user's `claude` login (a
  subscription; no API key). Tools are exposed as an in-process MCP server;
  `look` images travel as MCP image content. Claude Code's built-in tools are
  disabled so the session stays inside the sandbox. `resolve_backend()` picks
  `api` when a key is present, else `claude-code`.

## Files

```
src/simagent/
  spec.py        ProblemSpec contract; THE domain sampler; code exec with toolbox
  search.py      sampled search + annealing + exact certify; exhaustive enumeration
  proof.py       the proof kernel (methods, Proof, verified_by) — sole verdict authority
  lean_check.py  run Lean core on generated sources; fail-closed acceptance
  sandbox/       geometry.py (numeric), certify.py (sympy exact), scene.py
                 (renderer-agnostic scene graph), leangen.py (Lean certificates)
  answer.py      Markdown / LaTeX / Lean skeleton emitters (method-aware)
  pipeline.py    one run = spec → search → proof → viz → answers → report.json
  llm.py         formalize (spec synthesis, sandbox-vetted) and attempt_proof
                 (deductive attempts; Lean-checked, never trusted)
  library/       bundled specs; known-answer tests for the whole machine
  visualize/     mpl.py (always-on PNG), manim_gen.py (generated ThreeDScene)
  agent.py       embodied LLM loop (vision + tools) over one SandboxSession
  play.py, web/  shells: terminal REPL and browser UI over the same kernel
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
