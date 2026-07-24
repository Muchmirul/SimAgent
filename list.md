# SimAgent: what to do next

Snapshot: 2026-07-25. Baseline: v2 P0-P6 landed, 171 Python tests + 12 pi tests green.

This file is the ranked work list. It is scored against the goal below, not
against what is interesting to build.

---

## The goal

1. SimAgent is the best **harness** for an AI model to solve math by
   *experiencing* it, seeing and doing, with equations as formalization rather
   than the medium of thought. First principles, not answers gathered from
   outside.
2. Human and agent unblock each other: the human helps when the agent is stuck,
   the agent helps when the human is stuck, through a UI where the human can
   comment on any step.

## Three decisions that scope every task below

**1. SimAgent is only a harness. It never does the model's thinking.**

The design test for any proposed feature:

> Does this give the model something it cannot get by thinking?
> If yes, the harness owes it. If no, hands off.

Capability, perception, verification and memory cannot be produced by thinking,
so they are the harness's job. Strategy, insight and choice of proof method are
exactly what thinking produces, so they are the model's. Reporting an
instrument's own limits is information and belongs to the harness; naming which
method to try next is steering and does not. `test_sos.py` pins this.

**2. The math domain is limited to what the architecture actually fits.**

Strip away the words and SimAgent is one machine: a finite-dimensional
configuration space, a scalar margin whose sign decides the claim, a picture of
that space, and exact arithmetic to settle it. That is not a general math tool
and never was.

| In scope | Out of scope, permanently |
|---|---|
| Geometry (points in ℝᵈ) | Calculus, real and complex analysis |
| Algebraic inequalities | Topology |
| Linear algebra | Abstract algebra, set theory, logic |
| Optimization | Cryptography |
| Discrete and extremal geometry | Number theory beyond bounded integer claims |
| Combinatorics and graph theory (needs a new Space type) | |

None of the seven Millennium problems fits, and no amount of building changes
that: they live in analysis, topology, number theory and logic, all of which are
infinite in the way this machine is finite. That is a boundary, not a weakness.

**3. The target is one explicit finite object that settles a real question.**

Euler's sum of powers conjecture stood ~200 years and fell to one line of
numbers. Borsuk's stood 60 years and fell to one finite point set. Hirsch's
stood 53 years and fell to one polytope. That is this machine's shape.

Use olympiad inequalities as the benchmark that earns credibility. Do not
mistake the benchmark for the destination.

---

## The work

| # | Task | Why it blocks the goal | Whose job | Cost |
|---|---|---|---|---|
| 1 | **Print the certificate as mathematics.** Show the actual identity, not `sum_i d_i (v_i . z)^2`. | A sum-of-squares identity is checkable by a human in ten seconds. Lean is machine trust; the identity is human trust. The kernel computes it and then throws it away, so we ship neither readable form. Trust is the product. | Harness | Small |
| 2 | **Run one live session.** A real model on a real conjecture, watched end to end. | 171 tests and zero live runs. We do not know whether the model reasons well from the pictures, or whether human comments actually redirect it. Every item below is a prediction until this happens. | Harness (evaluation) | Small, needs Claude API auth |
| 3 | **Let conditions join the proof.** `sum_of_squares` only proves claims true *everywhere*. | Most real claims are conditional ("for positive x", "for sides of a triangle"). Today the model does everything right and hits a dead end for a harness reason, not a math reason. Worked example below. | Harness | Medium, reuses existing machinery |
| 4 | **Space types for the chosen domains.** Today only `Box` and `IntBox`. | A mathematician's object is a graph, a permutation, a polytope, a lattice. Without these they must ask us to edit the kernel, and no one will wait for that. This is the single biggest barrier to outside use. | Harness | Medium to large |
| 5 | **Instruments for more of the ten methods.** Induction first, then cases. | Four of ten methods have an instrument (counterexample, construction, exhaustion, direct). A model may declare a sound method and find the harness cannot help it execute. | Harness | Medium, one at a time |
| 6 | **Packaging.** `pip install simagent`, Lean optional and degrading honestly, one hosted page. | Today: venv, uv, elan, micromamba, Node, API keys. An outsider closes the tab. | Harness | Medium |
| 7 | **Search that reaches real sizes.** Symmetry reduction, and a bridge to SAT or integer programming for discrete spaces. | Random sampling is fine in ℝ⁴ and useless in ℝ⁵⁰. Real problems are big. The harness supplies the instrument; the model still decides where to point it. | Harness supplies, model aims | Large |
| — | **Find something new.** | Reproducing known counterexamples makes a demo. One new result makes a tool. This is the only measure the community will care about. | Model | Follows 1-7 |

### Order

**1 → 2 → 3 → 4 → 5 → 6 → 7.**

Make it believable, then measure it, then make it capable, then let outsiders
in. Task 2 can move ahead of 1 the moment API auth exists; the two are
independent. Task 7 only when a real problem demands it.

---

## What task 3 looks like, concretely

Claim: **for all x >= 0, x³ + 1 > x.** True (the margin never drops below about
0.615 there), but false at x = -2, so the current tool refuses with "odd total
degree, no sum-of-squares decomposition can exist". Correct and useless at once:
it answered a question nobody asked.

With conditions allowed as ingredients, the certificate is:

    x³ + 1 - x  =  2(x - 1/2)²  +  1/2  +  x · (x - 1)²

Every term on the right is nonnegative on the domain: two squares, a positive
constant, and `x` (given as >= 0) times a square. So the margin is at least 1/2
everywhere on x >= 0. The idea is simply to let the given conditions join the
proof, the way a human uses them.

---

## Done

- **The harness no longer picks the method.** A failure message used to end
  with "hunting for a counterexample would settle that", which chose the next
  method for the model. It now states the limit and stops. Pinned by
  `test_harness_never_picks_the_method_for_the_model`.

## Dropped from the previous version of this file

- **"No Mathlib."** It was ranked low; it is now out of scope entirely. Mathlib
  buys reach into analysis and topology, which decision 2 excludes. Removing it
  is a direct consequence of scoping the domain.
- **"New areas need new vocabulary"**, listed as ongoing upkeep. That was
  mis-sized. The missing piece is not measures (`expr` already covers rational
  arithmetic generally) but **Spaces**, and that is now task 4, near the top.
- Everything else survived: the ranking method, the live-run item, the
  conditional-domains item, and the missing-methods item.
