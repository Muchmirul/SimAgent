"""Bundled ProblemSpecs — runnable offline, and few-shot examples for the LLM.

Two deliberately false classics (the machine disproves them with certified
rational counterexamples) and one true invariant (the evidence path).
"""
from __future__ import annotations

from ..spec import ProblemSpec
from . import circumcenter_tetrahedron, circumcenter_triangle, euler_polyhedron, sum_of_odds

_MODULES = [circumcenter_triangle, circumcenter_tetrahedron, euler_polyhedron, sum_of_odds]

REGISTRY: dict[str, ProblemSpec] = {m.SPEC.id: m.SPEC for m in _MODULES}


def get(problem_id: str) -> ProblemSpec:
    if problem_id not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown problem {problem_id!r}; bundled problems: {known}")
    return REGISTRY[problem_id]


def all_specs() -> list[ProblemSpec]:
    return list(REGISTRY.values())


def is_bundled(spec: ProblemSpec) -> bool:
    """True only for the in-process bundled spec objects (reviewed, trusted).

    Identity, not id-string: a disk-loaded spec carrying a bundled id is a
    different object and is correctly treated as untrusted.
    """
    return REGISTRY.get(spec.id) is spec
