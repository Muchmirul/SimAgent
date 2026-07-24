"""Derive — atom #4 (physical law): derived entities recompute when their
ancestors move.

The constructor registry is the closed vocabulary of things an agent (or a
Claim) may build — the sketching hand. Every constructor is dimension-generic
where the underlying geometry is (circumcenter/barycentric/volume work for a
k-simplex in ℝᵈ for any d). Insertion order of the entity table is already
topological (arguments must exist before their dependents), so recomputation
is a single ordered sweep.
"""
from __future__ import annotations

import numpy as np

from ..sandbox import geometry
from .entity import World


def _midpoint(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (np.asarray(a, dtype=float) + np.asarray(b, dtype=float)) / 2.0


def _centroid(pts: np.ndarray) -> np.ndarray:
    return np.asarray(pts, dtype=float).mean(axis=0)


def _segment(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.stack([np.asarray(a, dtype=float), np.asarray(b, dtype=float)])


def _row(pts: np.ndarray, index: float) -> np.ndarray:
    return np.asarray(pts, dtype=float)[int(index)]


CONSTRUCTORS: dict[str, dict] = {
    # name -> {fn, arity, doc}
    "circumcenter": {
        "fn": lambda pts: np.asarray(geometry.circumcenter(np.asarray(pts, dtype=float))),
        "arity": 1,
        "doc": "circumcenter of a (k+1, d) simplex — any dimension",
    },
    "barycentric": {
        "fn": lambda pts, x: np.asarray(
            geometry.barycentric(np.asarray(pts, dtype=float), np.asarray(x, dtype=float))
        ),
        "arity": 2,
        "doc": "barycentric coordinates of a point w.r.t. a simplex",
    },
    "centroid": {"fn": _centroid, "arity": 1, "doc": "mean of a point set"},
    "midpoint": {"fn": _midpoint, "arity": 2, "doc": "midpoint of two points"},
    "segment": {"fn": _segment, "arity": 2, "doc": "the segment between two points"},
    "simplex_volume": {
        "fn": lambda pts: np.asarray(geometry.simplex_volume(np.asarray(pts, dtype=float))),
        "arity": 1,
        "doc": "signed-volume magnitude of a simplex",
    },
    "vertex": {"fn": _row, "arity": 2, "doc": "one row of a point set (second arg = index entity/scalar)"},
}


def compute(world: World, name: str) -> np.ndarray:
    """Compute one derived entity from its argument values (which must exist)."""
    ent = world.entities[name]
    spec = CONSTRUCTORS.get(ent.ctor)
    if spec is None:
        raise KeyError(f"unknown constructor {ent.ctor!r}")
    args = []
    for a in ent.args:
        if a not in world.values:
            raise ValueError(f"{name!r}: argument {a!r} has no value yet")
        args.append(world.values[a])
    if len(args) != spec["arity"]:
        raise ValueError(f"{ent.ctor!r} takes {spec['arity']} args, got {len(args)}")
    return np.asarray(spec["fn"](*args), dtype=float)


def recompute(world: World, changed: set[str] | None = None) -> list[str]:
    """Recompute derived entities affected by `changed` (None = all), in the
    entity table's (topological) order. Returns the names recomputed.
    A constructor error clears that entity's value (degenerate state) rather
    than crashing the loop — measures report it as degenerate."""
    dirty = set(world.entities) if changed is None else set(changed)
    updated: list[str] = []
    for ent in world.entities.values():
        if ent.kind != "derived":
            continue
        if ent.name not in dirty and not (set(ent.args) & dirty):
            continue
        try:
            world.values[ent.name] = compute(world, ent.name)
            updated.append(ent.name)
        except Exception:  # noqa: BLE001 - degenerate geometry is a state, not a crash
            world.values.pop(ent.name, None)
            updated.append(ent.name)
        dirty.add(ent.name)
    return updated
