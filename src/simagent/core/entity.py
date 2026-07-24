"""Entity + World — atoms #2 (particle) and the table that holds them.

An Entity is a named thing with stable identity: *free* (its value is a point
of a Space) or *derived* (a recipe — constructor + argument entities; its
coordinates are consequences, never inputs — the CAD lesson). The World is
the single authoritative state table: entity definitions plus current values.

Mutation discipline (the Blender lesson): nothing outside core.op mutates a
World; every change flows through `apply_op`, and derived entities are
recomputed by core.derive. `fork()` gives an isolated copy for imagination —
thought experiments never touch the mainline.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .space import Space


@dataclass(frozen=True)
class Entity:
    name: str
    kind: str  # "free" | "derived"
    space: Space | None = None          # free entities only
    ctor: str | None = None             # derived entities only
    args: tuple[str, ...] = ()          # derived entities only

    def __post_init__(self):
        if self.kind == "free" and self.space is None:
            raise ValueError(f"free entity {self.name!r} needs a Space")
        if self.kind == "derived" and not self.ctor:
            raise ValueError(f"derived entity {self.name!r} needs a constructor")
        if self.kind not in ("free", "derived"):
            raise ValueError(f"unknown entity kind {self.kind!r}")


@dataclass
class World:
    """Entity table + current values. Insertion order is topological by
    construction (a derived entity's args must already exist)."""

    entities: dict[str, Entity] = field(default_factory=dict)
    values: dict[str, np.ndarray] = field(default_factory=dict)

    # -- definition ----------------------------------------------------------

    def add_free(self, name: str, space: Space, value=None) -> None:
        if name in self.entities:
            raise ValueError(f"entity {name!r} already exists")
        self.entities[name] = Entity(name=name, kind="free", space=space)
        if value is not None:
            self.values[name] = np.asarray(value, dtype=float)

    def add_derived(self, name: str, ctor: str, args: tuple[str, ...]) -> None:
        if name in self.entities:
            raise ValueError(f"entity {name!r} already exists")
        for a in args:
            if a not in self.entities:
                raise ValueError(f"derived entity {name!r}: unknown argument {a!r}")
        self.entities[name] = Entity(name=name, kind="derived", ctor=ctor, args=args)

    def remove(self, name: str) -> None:
        ent = self.entities.get(name)
        if ent is None:
            raise KeyError(f"unknown entity {name!r}")
        dependents = [e.name for e in self.entities.values() if name in e.args]
        if dependents:
            raise ValueError(f"cannot remove {name!r}: {dependents} depend on it")
        if ent.kind == "free":
            raise ValueError(f"cannot remove free entity {name!r} (it is the domain)")
        del self.entities[name]
        self.values.pop(name, None)

    # -- access --------------------------------------------------------------

    def free_names(self) -> list[str]:
        return [e.name for e in self.entities.values() if e.kind == "free"]

    def derived_names(self) -> list[str]:
        return [e.name for e in self.entities.values() if e.kind == "derived"]

    def free_values(self) -> dict[str, np.ndarray]:
        """The historical `vars` dict: free entities only, insertion order."""
        return {n: self.values[n] for n in self.free_names() if n in self.values}

    # -- state ---------------------------------------------------------------

    def replace_free(self, vars: dict[str, np.ndarray]) -> None:
        """Wholesale replacement of the free configuration (sample/hunt load)."""
        for name, value in vars.items():
            if name not in self.entities or self.entities[name].kind != "free":
                raise KeyError(f"unknown free entity {name!r}")
            self.values[name] = np.asarray(value, dtype=float)

    def fork(self) -> "World":
        """Isolated copy for imagination: shared frozen entity defs, copied
        values — mutating the fork can never touch the mainline."""
        clone = World(entities=dict(self.entities))
        clone.values = {k: np.array(v, dtype=float, copy=True) for k, v in self.values.items()}
        return clone
