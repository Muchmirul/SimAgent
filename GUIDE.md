# SimAgent — simple guide

## 1. Start it

```bash
cd /mnt/Tforce/dev/SimAgent
.venv/bin/simagent web
```

Your browser opens the **reasoning notebook** at **http://127.0.0.1:8642**.
(If the port is busy: `--port 8700`.)

## 2. The idea

A coding agent shows its work as diffs. SimAgent shows a *math* agent's work
as a **visual chain of thought**: the agent lives in a 3D sandbox (its
"mind"), and the notebook streams that mind step by step. Equations appear in
every cell, but as *translations* of what the agent is looking at — the
thinking happens in the scene; the symbols are the record.

## 3. Run an agent on a bundled problem

1. In the **In [ ]:** cell, pick a problem (e.g. *Circumcenter lies inside
   every tetrahedron*).
2. Press **Run agent**. (**■ stop** ends the running session — kernel results
   established so far are kept and the verdict cell still appears; **⟳ restart**
   stops it and re-runs the same problem in a fresh notebook.)
3. Cells stream in, one per step of the agent's mind:
   - **approach** (amber box) — the agent's declared line of attack: one of
     the ten proof methods plus its idea, re-declared when it switches
     strategy. This is intent; the end verdict shows *declared vs established*.
   - **thinking** (dim italic) and **says** — the model's narrative before the act
   - **act** — the tool it chose: `look()`, `set_var(…)`, `hunt(…)`, `certify()` …
   - the **picture** — for `look` steps, the exact image the agent saw;
     otherwise the scene after the act. **Click any picture** to open it as an
     interactive 3D view (drag to orbit, scroll to zoom, Esc to close).
   - the **equations** the harness wrote down for that state (amber box)
   - a **diff** — which points moved (`- before` / `+ after`) and the margin change
   - a **HOLDS / FAILS** badge with the margin (margin > 0 ⇔ the property holds)
4. The final **verdict cell** comes only from the kernel (`proof.json`):
   *method — verified by sandbox+lean* means exact arithmetic plus a Lean
   kernel certificate. If nothing was certified, it says so — the agent's
   prose never upgrades a claim.

Backends: **auto** uses your Claude API key if one is set, else your `claude`
login (claude-code). Bundled problems work on either.

## 4. Type your own problem

Write it in the text box in plain words, e.g.

> the incenter of every triangle lies inside the triangle

and press **Run agent**. The server first *formalizes* it (Claude turns the
sentence into a spec, validated against the sandbox — this step needs Claude
API auth), then the agent session starts and the cells stream in as above.

## 5. Replay past runs

The header dropdown lists every recorded run (web-started and CLI-started
alike). Pick one to re-read the whole notebook; if the run is still going,
the page follows it live. Deep-link with `?run=<name>`.

## 6. Without the browser

```bash
.venv/bin/simagent list                              # see the problems
.venv/bin/simagent solve circumcenter-in-tetrahedron # full automatic run
.venv/bin/simagent agent circumcenter-in-triangle    # embodied agent in the terminal
.venv/bin/simagent play circumcenter-in-triangle     # hands-on REPL sandbox
```

`solve` writes a folder under `runs/` with the picture, `answer.md`,
`answer.tex`, `conjecture.lean`, and `report.json`. `agent` additionally
writes `trace.jsonl` — the mind trace the notebook replays. Manim stills and
videos render via `simagent solve --render-manim` (see README for the no-sudo
Manim env).

## 7. Reading the verdicts honestly

- **CERTIFIED counterexample** — proved false. Done.
- **numeric candidate** — looks false, but exact check didn't confirm. Not proof.
- **no counterexample found** — evidence it may be true. **Never** a proof —
  proving still needs math/Lean (that's the roadmap).
