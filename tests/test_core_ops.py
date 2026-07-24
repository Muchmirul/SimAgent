"""P2 gate: the recipe model — World/Entity/Op/Derive.

Fork isolation (imagination can never touch the mainline), dependency-driven
recomputation (the depgraph is the sandbox's physics), and the closed op
vocabulary as the only mutation channel.
"""
import numpy as np
import pytest

from simagent.core import Box, World, apply_op, recompute
from simagent.core.op import KERNEL_OPS


def triangle_world() -> World:
    w = World()
    w.add_free("T", Box(shape=(3, 2), low=-1.2, high=1.2))
    apply_op(w, {"op": "replace", "vars": {"T": np.array([[-1, 0], [1, 0], [0, 1]], float)}})
    return w


def test_construct_and_recompute_follow_ancestors():
    w = triangle_world()
    out = apply_op(w, {"op": "construct", "name": "O", "ctor": "circumcenter", "args": ["T"]})
    assert out.recomputed == ["O"]
    assert np.allclose(w.values["O"], [0.0, 0.0])  # right triangle: center at hypotenuse midpoint
    apply_op(w, {"op": "construct", "name": "w", "ctor": "barycentric", "args": ["T", "O"]})
    # move a vertex; both derived entities follow automatically
    out = apply_op(w, {"op": "set", "target": "T", "row": 2, "values": [0.0, 0.2]})
    assert set(out.recomputed) == {"O", "w"}
    assert w.values["O"][1] < -1  # obtuse triangle: circumcenter far below the base
    assert w.values["w"].min() < 0


def test_fork_isolation_for_imagination():
    w = triangle_world()
    apply_op(w, {"op": "construct", "name": "O", "ctor": "circumcenter", "args": ["T"]})
    before = {k: v.copy() for k, v in w.values.items()}
    fork = w.fork()
    apply_op(fork, {"op": "nudge", "target": "T", "row": 0, "delta": [0.3, -0.3]})
    for k, v in before.items():
        assert np.array_equal(w.values[k], v), "fork mutation leaked into mainline"
    assert not np.array_equal(fork.values["T"], w.values["T"])


def test_ops_are_the_only_vocabulary_and_fail_closed():
    w = triangle_world()
    with pytest.raises(KeyError):
        apply_op(w, {"op": "set", "target": "nope", "values": [1, 2]})
    with pytest.raises(ValueError):
        apply_op(w, {"op": "unknown_op"})
    apply_op(w, {"op": "construct", "name": "O", "ctor": "circumcenter", "args": ["T"]})
    with pytest.raises(ValueError):  # derived entities are consequences, not inputs
        apply_op(w, {"op": "set", "target": "O", "values": [0, 0]})
    for kernel_op in KERNEL_OPS:  # truth never runs through world ops
        with pytest.raises(ValueError):
            apply_op(w, {"op": kernel_op})


def test_remove_guards_dependencies():
    w = triangle_world()
    apply_op(w, {"op": "construct", "name": "O", "ctor": "circumcenter", "args": ["T"]})
    apply_op(w, {"op": "construct", "name": "w", "ctor": "barycentric", "args": ["T", "O"]})
    with pytest.raises(ValueError):
        apply_op(w, {"op": "remove", "name": "O"})  # w depends on it
    apply_op(w, {"op": "remove", "name": "w"})
    apply_op(w, {"op": "remove", "name": "O"})
    with pytest.raises(ValueError):
        apply_op(w, {"op": "remove", "name": "T"})  # free = the domain, never removable


def test_degenerate_construction_is_a_state_not_a_crash():
    w = World()
    w.add_free("T", Box(shape=(3, 2)))
    apply_op(w, {"op": "replace", "vars": {"T": np.array([[0, 0], [1, 0], [2, 0]], float)}})
    apply_op(w, {"op": "construct", "name": "O", "ctor": "circumcenter", "args": ["T"]})
    assert "O" not in w.values  # collinear: no circumcenter — value absent, world alive
    recompute(w, {"T"})
    assert "O" not in w.values
