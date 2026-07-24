"""Measure — atom #5 (observable): perception as calibrated compression.

The agent (and the notebook) should never have to read raw coordinate dumps:
a measure turns kernel state into the compressed, perceptual language a
mathematician uses — "the center is OUTSIDE, beyond the face opposite vertex
2, margin −0.41". Margin convention everywhere: margin > 0 ⇔ property holds.

Measures only *describe* state; they never decide anything — the claim's
distinguished check plus the truth layer (certify/exhaust/Lean) remain the
only verdict path.
"""
from __future__ import annotations

import numpy as np

NEAR_BOUNDARY = 0.05


def qualitative_lines(vars: dict, check: dict) -> list[str]:
    """Human/agent-readable predicates for the current state."""
    lines: list[str] = []
    if check.get("error"):
        return [f"degenerate configuration: {check['error']}"]
    data = check.get("data") or {}
    bary = data.get("barycentric")
    if bary is not None:
        w = np.asarray(bary, dtype=float).ravel()
        k = int(np.argmin(w))
        if float(w.min()) > 0:
            lines.append(
                f"the point is INSIDE the simplex (all {w.size} barycentric "
                f"coordinates positive; smallest is w[{k}] = {w.min():.4g})"
            )
        else:
            lines.append(
                f"the point is OUTSIDE the simplex — beyond the face opposite "
                f"vertex {k} (barycentric w[{k}] = {w.min():.4g} < 0)"
            )
    margin, holds = check.get("margin"), check.get("holds")
    if margin is None:
        lines.append(f"discrete claim at this configuration: holds = {holds}")
    else:
        m = float(margin)
        state = "HOLDS" if holds else "FAILS"
        distance = "close to the boundary" if abs(m) < NEAR_BOUNDARY else "clearly"
        lines.append(f"the property {state} here, {distance} (margin {m:+.4g})")
    for name, val in vars.items():
        arr = np.asarray(val, dtype=float)
        if arr.ndim == 2 and arr.shape[1] > 3:
            lines.append(
                f"{name} lives in ℝ^{arr.shape[1]} — the picture is a projection; "
                "trust the numbers over the image"
            )
    return lines


def measure_state(spec, vars: dict, check: dict) -> dict:
    """The agent-facing measurement of the current configuration."""
    return {
        "holds": None if check.get("error") else check.get("holds"),
        "margin": None if check.get("error") else check.get("margin"),
        "qualitative": qualitative_lines(vars, check),
        "data": check.get("data") if not check.get("error") else None,
        "error": check.get("error"),
    }
