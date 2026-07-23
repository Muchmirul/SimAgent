"""ProblemSpec: the contract between a conjecture, the sandbox, and the search.

A spec carries the same conjecture in four forms:
  - natural language + LaTeX (for humans),
  - executable code strings (for the sandbox and the search),
  - a Lean statement skeleton (for formalization).

Code fields are *strings* so a spec is JSON-serializable end to end — this is
exactly the format the LLM formalizer emits. Strings are compiled with the
sandbox toolbox in scope (numpy + geometry/scene/certify helpers).

Code contract (enforced by validate_spec / the search):
  check(**vars)       -> {"holds": bool, "margin": float | None, "data": dict}
                         margin > 0 iff the property holds for this instance;
                         its magnitude measures robustness (used to guide the
                         annealer). Use None when there is no natural margin.
  build_scene(**vars) -> list of scene primitives (scene.points, ...)
  valid(**vars)       -> bool           (optional sampling constraint)
  certify(**vars)     -> bool           (optional; exact sympy arithmetic —
                         vars arrive as sympy Matrices/Rationals; must return
                         whether the property HOLDS for the instance)
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import numpy as np
import sympy as sp

from .sandbox import certify as certify_mod
from .sandbox import geometry, scene


@dataclass
class VarSpec:
    name: str
    shape: list[int]  # [] for a scalar, [3, 2] for 3 points in R^2, ...
    low: float = -1.0
    high: float = 1.0
    kind: str = "real"  # "real": uniform box | "int": integer grid (enables exhaustion)


@dataclass
class CheckResult:
    holds: bool
    margin: float | None
    data: dict


@dataclass
class ProblemSpec:
    id: str
    title: str
    conjecture: str
    latex: str
    quantifier: str  # "forall": hunt counterexamples | "exists": hunt witnesses
    domain: list[VarSpec]
    check_code: str
    scene_code: str
    constraint_code: str | None = None
    certify_code: str | None = None
    lean_certificate_code: str | None = None  # def lean_certificate(**exact_vars) -> str (Lean source)
    lean_statement: str = ""
    notes: str = ""

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(d: dict) -> "ProblemSpec":
        d = dict(d)
        d["domain"] = [VarSpec(**v) for v in d.get("domain", [])]
        return ProblemSpec(**d)

    def save(self, path) -> None:
        with open(path, "w") as f:
            json.dump(self.to_json(), f, indent=2)

    @staticmethod
    def load(path) -> "ProblemSpec":
        with open(path) as f:
            return ProblemSpec.from_json(json.load(f))

    def compiled(self) -> "CompiledSpec":
        return CompiledSpec(self)


def toolbox() -> dict:
    """Globals available to check/build_scene/valid code."""
    return {
        "np": np,
        "math": math,
        "circumcenter": geometry.circumcenter,
        "barycentric": geometry.barycentric,
        "simplex_volume": geometry.simplex_volume,
        "hull_counts": geometry.hull_counts,
        "hull_mesh": geometry.hull_mesh,
        "scene_points": scene.points,
        "scene_segments": scene.segments,
        "scene_polygon": scene.polygon,
        "scene_mesh": scene.mesh,
        "scene_sphere": scene.sphere,
        "scene_label": scene.label,
    }


def certify_toolbox() -> dict:
    """Globals available to certify / lean_certificate code (exact arithmetic only)."""
    from .sandbox import leangen

    return {
        "sp": sp,
        "exact_circumcenter": certify_mod.exact_circumcenter,
        "exact_barycentric": certify_mod.exact_barycentric,
        "lean_simplex_circumcenter": leangen.lean_simplex_circumcenter,
        "lean_bounded_nat": leangen.lean_bounded_nat,
    }


def sample_vars(rng: np.random.Generator, spec: "ProblemSpec") -> dict[str, np.ndarray]:
    """The one authoritative domain sampler (used by search, play, web, CLI)."""
    out: dict[str, np.ndarray] = {}
    for v in spec.domain:
        if v.kind == "int":
            if int(v.high) < int(v.low):
                raise ValueError(f"{v.name}: integer domain has low ({v.low}) > high ({v.high})")
            out[v.name] = rng.integers(int(v.low), int(v.high) + 1, size=tuple(v.shape)).astype(float)
        else:
            out[v.name] = rng.uniform(v.low, v.high, size=tuple(v.shape))
    return out


def _exec_fn(code: str, fn_name: str, env: dict, where: str) -> Callable:
    ns: dict[str, Any] = dict(env)
    compiled = compile(code, f"<{where}>", "exec")
    exec(compiled, ns)
    if fn_name not in ns:
        raise ValueError(f"{where}: code must define a function named {fn_name!r}")
    return ns[fn_name]


class CompiledSpec:
    """A ProblemSpec with its code fields compiled to callables."""

    def __init__(self, spec: ProblemSpec):
        self.spec = spec
        env = toolbox()
        self._check = _exec_fn(spec.check_code, "check", env, f"{spec.id}/check")
        self._scene = _exec_fn(spec.scene_code, "build_scene", env, f"{spec.id}/scene")
        self._valid = (
            _exec_fn(spec.constraint_code, "valid", env, f"{spec.id}/constraint")
            if spec.constraint_code
            else None
        )
        self._certify = (
            _exec_fn(spec.certify_code, "certify", certify_toolbox(), f"{spec.id}/certify")
            if spec.certify_code
            else None
        )
        self._lean_certificate = (
            _exec_fn(
                spec.lean_certificate_code,
                "lean_certificate",
                certify_toolbox(),
                f"{spec.id}/lean_certificate",
            )
            if spec.lean_certificate_code
            else None
        )

    def check(self, **vars) -> CheckResult:
        out = self._check(**vars)
        margin = out.get("margin")
        return CheckResult(
            holds=bool(out["holds"]),
            margin=None if margin is None else float(margin),
            data=out.get("data", {}),
        )

    def build_scene(self, **vars) -> list[dict]:
        return self._scene(**vars)

    def valid(self, **vars) -> bool:
        if self._valid is None:
            return True
        return bool(self._valid(**vars))

    @property
    def has_certify(self) -> bool:
        return self._certify is not None

    def certify(self, **exact_vars) -> bool:
        """Exact decision: does the property hold for this rational instance?"""
        if self._certify is None:
            raise ValueError(f"{self.spec.id}: no certify_code")
        return bool(self._certify(**exact_vars))

    @property
    def has_lean_certificate(self) -> bool:
        return self._lean_certificate is not None

    def lean_certificate(self, **exact_vars) -> str:
        """Lean source certifying the current verdict (witness-based or bounded)."""
        if self._lean_certificate is None:
            raise ValueError(f"{self.spec.id}: no lean_certificate_code")
        return str(self._lean_certificate(**exact_vars))


def validate_spec(spec: ProblemSpec, samples: int = 8, seed: int = 0) -> list[str]:
    """Smoke-test a spec (used to vet LLM output). Returns a list of problems."""
    errors: list[str] = []
    if spec.quantifier not in ("forall", "exists"):
        errors.append(f"quantifier must be 'forall' or 'exists', got {spec.quantifier!r}")
    if not spec.domain:
        errors.append("domain must declare at least one variable")
    for v in spec.domain:
        if v.kind not in ("real", "int"):
            errors.append(f"{v.name}: kind must be 'real' or 'int', got {v.kind!r}")
        if v.high < v.low:
            errors.append(f"{v.name}: low ({v.low}) must be <= high ({v.high})")
        if v.kind == "int" and (float(v.low) != int(v.low) or float(v.high) != int(v.high)):
            errors.append(f"{v.name}: integer domain needs integer bounds, got [{v.low}, {v.high}]")
    if errors:
        return errors  # a malformed domain would crash sampling below
    try:
        comp = spec.compiled()
    except Exception as e:  # noqa: BLE001 - surface everything to the repair loop
        return errors + [f"compile error: {type(e).__name__}: {e}"]

    rng = np.random.default_rng(seed)
    checked = 0
    for i in range(samples * 25):
        if checked >= samples:
            break
        vars = sample_vars(rng, spec)
        try:
            if not comp.valid(**vars):
                continue
            res = comp.check(**vars)
        except Exception as e:  # noqa: BLE001
            errors.append(f"check raised on sample {i}: {type(e).__name__}: {e}")
            break
        if res.margin is not None and res.holds != (res.margin > 0):
            errors.append(
                f"margin/holds inconsistency on sample {i}: holds={res.holds} margin={res.margin}"
            )
            break
        if checked == 0:
            try:
                sc = comp.build_scene(**vars)
                if not isinstance(sc, list) or not sc:
                    errors.append("build_scene must return a non-empty list of primitives")
            except Exception as e:  # noqa: BLE001
                errors.append(f"build_scene raised: {type(e).__name__}: {e}")
        checked += 1
    if checked == 0:
        errors.append("no valid sample found in the domain (constraint too strict?)")
    if comp.has_certify and checked:
        vars = sample_vars(rng, spec)
        try:
            exact = {k: certify_mod.rationalize_array(v) for k, v in vars.items()}
            comp.certify(**exact)
        except Exception as e:  # noqa: BLE001
            errors.append(f"certify raised: {type(e).__name__}: {e}")
    return errors
