# SimAgent — simple guide

## 1. Start it

```bash
cd /mnt/Tforce/dev/SimAgent
.venv/bin/simagent web
```

Your browser opens at **http://127.0.0.1:8642**. (If the port is busy:
`--port 8700`.)

## 2. What you are looking at

- **Left**: the 3D world of one conjecture (a math claim).
- **Right top**: dropdown to pick a different conjecture.
- **Colored box**: the current verdict for the shape on screen.
  - green **PROPERTY HOLDS** — the claim is true for *this* shape
  - red **PROPERTY FAILS** — the claim is false for *this* shape
  - **margin** — how strongly (further from 0 = more clearly)

The bundled claims all say "for **every** shape ...". So the game is:
**try to find one shape that makes it FAIL.** One failing shape kills a
"for every" claim.

## 3. Play by hand

- **Drag a white dot** with the left mouse button. Everything that depends on
  it (the sphere, the red center point, the verdict) follows your mouse.
- Rotate the camera: drag empty space. Zoom: scroll wheel.

## 4. Let the machine play

| Button | What it does |
|---|---|
| **Sample** | throw a new random shape on screen |
| **Hunt** | machine tries ~1500 random shapes, looks for a failing one, and shows it |
| **Refine** | machine pushes the current shape to make the failure stronger |
| **Certify** | re-checks the current shape with **exact fractions** (no rounding errors). "CERTIFIED ... FAILS" = a real mathematical disproof, and the log shows the exact coordinates |

## 5. Make a Manim picture or movie

In the **Manim** panel:

- **Render still** — a picture, ~10 seconds.
- **Render video** — a rotating 3D movie, ~1–2 minutes.

The result appears right below the buttons. It renders exactly the shape you
have on screen. Files are also saved under `runs/web/<problem>/media/`.

## 6. A good 2-minute first session

1. Pick "Circumcenter lies inside every tetrahedron".
2. Press **Sample** a few times — sometimes green, sometimes red.
3. Press **Hunt** — it finds a red (failing) shape.
4. Press **Certify** — read the exact fractions in the log. That claim is now
   *disproved*, for real.
5. Press **Render video** — get the movie of your counterexample.

## 7. Without the browser

```bash
.venv/bin/simagent list                              # see the problems
.venv/bin/simagent solve circumcenter-in-tetrahedron # full automatic run
.venv/bin/simagent play circumcenter-in-triangle     # terminal version of play
```

`solve` writes a folder under `runs/` with: the picture, `answer.md`,
`answer.tex` (LaTeX), `conjecture.lean` (Lean skeleton), and `report.json`.

## 8. Your own conjecture (needs a Claude API key)

```bash
export ANTHROPIC_API_KEY=...   # or: ant auth login
.venv/bin/simagent formalize "the incenter of every triangle lies inside it"
.venv/bin/simagent solve --spec incenter-in-triangle.spec.json
```

`formalize` asks Claude to turn your sentence into a playable spec, and tests
the generated code against the sandbox before accepting it.

## 9. Reading the verdicts honestly

- **CERTIFIED counterexample** — proved false. Done.
- **numeric candidate** — looks false, but exact check didn't confirm. Not proof.
- **no counterexample found** — evidence it may be true. **Never** a proof —
  proving still needs math/Lean (that's the roadmap).
