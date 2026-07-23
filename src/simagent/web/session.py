"""Server-side sandbox session backing the browser UI.

Holds one live configuration per loaded problem; every mutation returns the
full authoritative state (vars + scene graph + check) so the frontend stays a
dumb renderer.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..search import (
    SearchReport,
    certify_candidate,
    exhaustible,
    refine_candidate,
    run_exhaustive,
    run_search,
)
from ..spec import ProblemSpec, sample_vars


_DECISIVE = frozenset(
    {"counterexample", "witness", "holds_on_domain", "no_witness_on_domain"}
)


def _report_rank(report: SearchReport | None) -> int:
    """Ordering so a later weaker search never shadows an earlier decisive one."""
    if report is None:
        return -1
    if report.verdict in _DECISIVE and report.certified:
        return 3
    if report.verdict in _DECISIVE:
        return 2
    return 1


class SandboxSession:
    def __init__(self, spec: ProblemSpec, out_dir):
        self.spec = spec
        self.comp = spec.compiled()
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        spec.save(self.out / "spec.json")
        self.rng = np.random.default_rng(0)
        self._hunt_seed = 0
        self.vars: dict[str, np.ndarray] = {}
        self.last_report: SearchReport | None = None  # most recent search result
        self.best_report: SearchReport | None = None  # strongest kept so far (never downgrades)
        self.sample()

    def _keep(self, report: SearchReport) -> None:
        self.last_report = report
        if _report_rank(report) > _report_rank(self.best_report):
            self.best_report = report

    # -- state ---------------------------------------------------------------

    def _check(self) -> dict:
        try:
            res = self.comp.check(**self.vars)
            return {"holds": res.holds, "margin": res.margin, "data": res.data}
        except Exception as e:  # noqa: BLE001 - degenerate configs are a UI state
            return {"error": f"{type(e).__name__}: {e}"}

    def scene(self) -> list[dict]:
        try:
            return self.comp.build_scene(**self.vars)
        except Exception:  # noqa: BLE001
            return []

    def state(self) -> dict:
        scene = self.scene()
        (self.out / "scene.json").write_text(json.dumps(scene))
        return {
            "spec": {
                "id": self.spec.id,
                "title": self.spec.title,
                "conjecture": self.spec.conjecture,
                "latex": self.spec.latex,
                "quantifier": self.spec.quantifier,
                "has_certify": self.comp.has_certify,
                "domain": [
                    {"name": v.name, "shape": v.shape, "low": v.low, "high": v.high}
                    for v in self.spec.domain
                ],
            },
            "vars": {k: np.asarray(v).tolist() for k, v in self.vars.items()},
            "scene": scene,
            "check": self._check(),
        }

    # -- mutations -----------------------------------------------------------

    def sample(self, seed: int | None = None) -> None:
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        for _ in range(1000):
            vars = sample_vars(self.rng, self.spec)
            try:
                if self.comp.valid(**vars):
                    self.vars = vars
                    return
            except Exception:  # noqa: BLE001
                continue
        raise RuntimeError("could not draw a valid sample (constraint too strict?)")

    def set_value(self, name: str, row: int | None, values: list[float]) -> None:
        if name not in self.vars:
            raise KeyError(f"unknown variable {name!r}")
        v = self.vars[name]
        arr = np.array(values, dtype=float)
        if row is None:
            if arr.size != v.size:
                raise ValueError(f"{name} needs {v.size} numbers, got {arr.size}")
            self.vars[name] = arr.reshape(v.shape)
        else:
            if not (0 <= row < v.shape[0]):
                raise ValueError(f"{name} has rows 0..{v.shape[0] - 1}")
            if arr.size != np.asarray(v[row]).size:
                raise ValueError(f"{name}[{row}] needs {np.asarray(v[row]).size} numbers")
            v[row] = arr

    def refine(self, steps: int = 300) -> dict:
        vars, res, used = refine_candidate(self.spec, self.vars, steps=steps)
        self.vars = vars
        return {"steps": used, "holds": res.holds, "margin": res.margin}

    def exhaust(self) -> dict:
        """Check EVERY case of a finite integer domain (proof by exhaustion)."""
        if not exhaustible(self.spec):
            raise ValueError(
                "domain is not finite (or too large); exhaustion needs all vars kind='int'"
            )
        report = run_exhaustive(self.spec)
        self._keep(report)
        if report.witness:
            self.vars = {k: np.array(v, dtype=float) for k, v in report.witness.items()}
        return {
            "verdict": report.verdict,
            "certified": report.certified,
            "cases_checked": report.valid_trials,
            "loaded_witness": report.witness is not None,
            "notes": report.notes,
        }

    def hunt(self, trials: int = 800) -> dict:
        self._hunt_seed += 1
        report = run_search(self.spec, trials=trials, seed=self._hunt_seed)
        self._keep(report)
        if report.witness:
            self.vars = {k: np.array(v, dtype=float) for k, v in report.witness.items()}
        return {
            "verdict": report.verdict,
            "certified": report.certified,
            "loaded_witness": report.witness is not None,
            "exact_witness": report.exact_witness,
            "notes": report.notes,
            "trials": report.trials,
            "valid_trials": report.valid_trials,
        }

    def certify(self) -> dict:
        res, certified, exact, notes = certify_candidate(self.spec, self.vars)
        return {
            "holds": res.holds,
            "margin": res.margin,
            "certified": certified,
            "exact": exact,
            "notes": notes,
        }
