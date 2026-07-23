"""Mind trace: the agent's visual chain of thought, step by step.

Philosophy (why this module exists): the sandbox is the agent's mind. The
model thinks by acting on the 3D scene — look, move a point, refine — the way
a coding agent thinks in diffs. Equations are the *translation* of each
mental picture into symbols, produced by the harness from the actual state,
not the medium of thought. The trace records, for every tool step:

  thought   — the model's narrative/thinking that preceded the act
  act       — tool + args
  scene     — the full 3D scene graph after the act (replayable in the UI)
  check     — holds/margin from the kernel-side numeric check
  equation  — the harness's symbolic translation of the new state
  diff      — what changed vs the previous step (vars moved, margin delta)

Honesty: everything here is narrative plus reproducible state. Verdict-ish
fields are copied verbatim from tool results; nothing in a trace upgrades a
claim — proof.json remains the sole authority (see proof.py).

File format: ``trace.jsonl`` in the run dir — one JSON object per step, plus
a final ``{"event": "end", ...}`` marker so viewers know the run completed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

MAX_RESULT_CHARS = 2000
MAX_THOUGHT_CHARS = 20000

TRACE_FILE = "trace.jsonl"


# -- formatting: state -> equations ------------------------------------------


def _num(x) -> str:
    """Compact numeric literal: integers stay integers, floats trim to 4 sig figs."""
    f = float(x)
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return f"{f:.4g}"


def _tuple(row) -> str:
    return "(" + ", ".join(_num(v) for v in np.asarray(row, dtype=float).ravel()) + ")"


def _fmt_value(v, depth: int = 0) -> str:
    """Generic formatter for check-data values (numbers, vectors, nested lists)."""
    if depth > 3:
        return "…"
    if isinstance(v, (bool, np.bool_)):
        return str(bool(v))
    if isinstance(v, (int, float, np.integer, np.floating)):
        return _num(v)
    arr = np.asarray(v)
    if arr.dtype.kind in "if":
        if arr.ndim == 0:
            return _num(arr)
        if arr.ndim == 1:
            return _tuple(arr)
    if isinstance(v, (list, tuple, np.ndarray)):
        return "(" + ", ".join(_fmt_value(x, depth + 1) for x in np.atleast_1d(arr)[:8]) + ")"
    return str(v)[:80]


def _latex_matrix(arr: np.ndarray) -> str:
    rows = [" & ".join(_num(v) for v in np.atleast_1d(r)) for r in np.atleast_2d(arr)]
    return r"\begin{pmatrix} " + r" \\ ".join(rows) + r" \end{pmatrix}"


def equation_of_state(spec, vars: dict, check: dict) -> dict:
    """Translate the current sandbox state into equations (text + LaTeX).

    This is the "equation as translation" layer: the model thinks in the
    scene; the harness writes down what the scene *says* in symbols. Margin
    convention (see search.py): margin > 0 ⇔ the property holds here.
    """
    text: list[str] = []
    latex: list[str] = []
    for name, val in vars.items():
        arr = np.asarray(val, dtype=float)
        if arr.ndim == 2:
            text.append(f"{name} = " + ", ".join(_tuple(r) for r in arr))
        elif arr.ndim == 1:
            text.append(f"{name} = {_tuple(arr)}")
        else:
            text.append(f"{name} = {_num(arr)}")
        latex.append(f"{name} = {_latex_matrix(arr) if arr.ndim else _num(arr)}")
    if check.get("error"):
        text.append(f"degenerate configuration: {check['error']}")
        latex.append(r"\text{degenerate configuration}")
        return {"text": text, "latex": latex}
    for key, val in (check.get("data") or {}).items():
        text.append(f"{key} = {_fmt_value(val)}")
        latex.append(rf"\mathrm{{{key}}} = {_fmt_value(val)}")
    margin, holds = check.get("margin"), check.get("holds")
    if margin is None:
        text.append(f"holds = {holds} (discrete check, no margin)")
        latex.append(rf"\text{{holds}} = \text{{{holds}}}")
    else:
        state = "HOLDS" if holds else "FAILS"
        text.append(f"margin = {_num(margin)}  →  property {state} here (margin > 0 ⇔ holds)")
        rel = ">" if float(margin) > 0 else r"\le"
        latex.append(
            rf"\mu = {_num(margin)} {rel} 0 \;\Rightarrow\; \text{{{state.lower()} here}}"
        )
    return {"text": text, "latex": latex}


# -- diffs: step N-1 -> step N ------------------------------------------------


def diff_vars(prev: dict | None, cur: dict) -> list[dict]:
    """Row-level var changes, formatted like a diff hunk for the UI."""
    if prev is None:
        return []
    changes: list[dict] = []
    for name, val in cur.items():
        a = np.asarray(prev.get(name), dtype=float) if name in prev else None
        b = np.asarray(val, dtype=float)
        if a is not None and a.shape == b.shape and np.allclose(a, b, atol=1e-12):
            continue
        if a is not None and a.shape == b.shape and b.ndim == 2:
            for i, (ra, rb) in enumerate(zip(a, b)):
                if not np.allclose(ra, rb, atol=1e-12):
                    changes.append(
                        {"var": name, "row": i, "before": _tuple(ra), "after": _tuple(rb)}
                    )
        else:
            changes.append(
                {
                    "var": name,
                    "row": None,
                    "before": None if a is None else _fmt_value(a),
                    "after": _fmt_value(b),
                }
            )
    return changes


# -- the recorder --------------------------------------------------------------


class TraceRecorder:
    """Appends one JSON line per agent step; safe to tail while the run is live."""

    def __init__(self, out_dir):
        self.path = Path(out_dir) / TRACE_FILE
        self._fh = self.path.open("w")
        self.steps = 0
        self._pending: list[dict] = []  # thoughts waiting for their act
        self._prev_vars: dict | None = None
        self._prev_margin = None

    def seed(self, vars: dict, check: dict) -> None:
        """Set the pre-step baseline (the world as first sampled), so step 1's
        diff shows what the agent's first act actually changed."""
        self._prev_vars = {k: np.asarray(v).copy() for k, v in vars.items()}
        self._prev_margin = None if check.get("error") else check.get("margin")

    def note_thought(self, text: str | None, kind: str = "text") -> None:
        """Buffer model narrative ('text') or raw thinking ('thinking');
        it attaches to the next recorded act."""
        if text and text.strip():
            self._pending.append({"kind": kind, "text": text[:MAX_THOUGHT_CHARS]})

    def record(
        self,
        *,
        tool: str,
        args: dict,
        result: str,
        error: bool,
        spec,
        vars: dict,
        check: dict,
        scene: list[dict],
        extra: dict | None = None,
        image: str | None = None,
    ) -> dict:
        self.steps += 1
        margin = None if check.get("error") else check.get("margin")
        entry = {
            "step": self.steps,
            "ts": time.time(),
            "thought": self._pending or None,
            "tool": tool,
            "args": args,
            "error": error,
            "result": result[:MAX_RESULT_CHARS],
            "check": check,
            "vars": {k: np.asarray(v).tolist() for k, v in vars.items()},
            "scene": scene,
            "equation": equation_of_state(spec, vars, check),
            "diff": {
                "changed": diff_vars(self._prev_vars, vars),
                "margin": {"before": self._prev_margin, "after": margin},
            },
            "extra": extra or None,
            "image": image,
        }
        self._pending = []
        self._prev_vars = {k: np.asarray(v).copy() for k, v in vars.items()}
        self._prev_margin = margin
        self._fh.write(json.dumps(entry, default=str) + "\n")
        self._fh.flush()
        return entry

    def close(self) -> None:
        if self._fh.closed:
            return
        if self._pending:  # trailing narrative with no act after it
            self.steps += 1
            self._fh.write(
                json.dumps(
                    {"step": self.steps, "ts": time.time(), "thought": self._pending,
                     "tool": None, "args": None, "error": False}
                )
                + "\n"
            )
            self._pending = []
        self._fh.write(json.dumps({"event": "end", "steps": self.steps}) + "\n")
        self._fh.close()


# -- reading (used by the web viewer) -----------------------------------------


def read_trace(run_dir, after: int = 0) -> dict:
    """Parse trace.jsonl -> {steps, total, done}. `after` skips steps <= it
    (live polling). Malformed trailing lines (mid-write) are ignored."""
    path = Path(run_dir) / TRACE_FILE
    steps: list[dict] = []
    total, done = 0, False
    for line in path.read_text().splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("event") == "end":
            done = True
            continue
        total = max(total, obj.get("step", 0))
        if obj.get("step", 0) > after:
            steps.append(obj)
    return {"steps": steps, "total": total, "done": done}
