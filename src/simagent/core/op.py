"""Op — atom #3 (force): THE only mutation channel.

A closed registry of typed operations replaces free-form mutation (and,
after P5, LLM-emitted exec'd code). Every op returns an OpOutcome describing
exactly what changed; derived entities recompute automatically. This is the
whole action vocabulary — for the agent, for the UI, and for imagination
(which applies the same ops to a forked World).

Op dicts (JSON-able, journal-ready):
    {"op": "set",       "target": name, "row": int|None, "values": [...]}
    {"op": "nudge",     "target": name, "row": int,      "delta":  [...]}
    {"op": "replace",   "vars": {name: array, ...}}          # sample/hunt load
    {"op": "construct", "name": name, "ctor": str, "args": [names...]}
    {"op": "remove",    "name": name}
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import derive
from .entity import World

MUTATING_OPS = ("set", "nudge", "replace", "construct", "remove")
# Ops that reach the truth layer; imagination must never run these.
KERNEL_OPS = ("certify", "exhaust", "hunt", "submit_lean_proof", "refine")


@dataclass
class OpOutcome:
    op: dict
    changed: list[str] = field(default_factory=list)   # free entities touched
    recomputed: list[str] = field(default_factory=list)  # derived entities updated


def _set(world: World, target: str, values, row=None) -> list[str]:
    if target not in world.entities:
        raise KeyError(f"unknown variable {target!r}")
    if world.entities[target].kind != "free":
        raise ValueError(f"{target!r} is derived — move its ancestors instead")
    v = world.values[target]
    arr = np.array(values, dtype=float)
    if row is None:
        if arr.size != v.size:
            raise ValueError(f"{target} needs {v.size} numbers, got {arr.size}")
        world.values[target] = arr.reshape(v.shape)
    else:
        if not (0 <= row < v.shape[0]):
            raise ValueError(f"{target} has rows 0..{v.shape[0] - 1}")
        if arr.size != np.asarray(v[row]).size:
            raise ValueError(f"{target}[{row}] needs {np.asarray(v[row]).size} numbers")
        v[row] = arr
    return [target]


def apply_op(world: World, op: dict) -> OpOutcome:
    """Apply one op; recompute affected derived entities; report what moved."""
    kind = op.get("op")
    changed: list[str] = []
    if kind == "set":
        changed = _set(world, op["target"], op["values"], op.get("row"))
    elif kind == "nudge":
        target, row = op["target"], op["row"]
        if target not in world.values:
            raise KeyError(f"unknown variable {target!r}")
        cur = np.asarray(world.values[target][row], dtype=float)
        delta = np.asarray(op["delta"], dtype=float)
        changed = _set(world, target, (cur + delta).tolist(), row)
    elif kind == "replace":
        world.replace_free(op["vars"])
        changed = list(op["vars"].keys())
    elif kind == "construct":
        world.add_derived(op["name"], op["ctor"], tuple(op.get("args") or ()))
        changed = [op["name"]]
    elif kind == "remove":
        world.remove(op["name"])
        return OpOutcome(op=op, changed=[op["name"]], recomputed=[])
    elif kind in KERNEL_OPS:
        raise ValueError(f"{kind!r} is kernel-grade and not a world op")
    else:
        raise ValueError(f"unknown op {kind!r}")
    recomputed = derive.recompute(world, set(changed))
    return OpOutcome(op=op, changed=changed, recomputed=recomputed)
