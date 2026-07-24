"""Expression — the general arithmetic vocabulary for measures.

One whitelisted AST, three evaluators: float (search), exact sympy Rational
(certification), and a Lean Q-term form (leangen renders it). There is no
`exec` and no `eval` here — the whitelist below IS the language, so a margin
written by an LLM can enter the kernel without arbitrary code entering with
it. That is the point: `min_coord` and friends each serve one problem, while
one expression measure serves every claim expressible as a rational
inequality over the free entities.

Everything stays inside the rationals, which is exactly what makes a margin
written here certifiable in exact arithmetic and checkable by the Lean
kernel. Division is evaluated but never Lean-encoded (a negative divisor
breaks leangen's positive-denominator invariant), so a claim that divides
tops out at the `sandbox` rung — fail closed, never a silent downgrade.
"""
from __future__ import annotations

import ast

import numpy as np
import sympy as sp

MAX_POW = 12  # keeps exact expansion and Lean terms bounded
FUNCS = ("abs", "min", "max", "sum")
_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)


class ExprError(ValueError):
    """Rejected expression: outside the closed arithmetic language."""


# -- parse + whitelist --------------------------------------------------------

_PARSED: dict[str, ast.expr] = {}  # search evaluates one margin thousands of times


def parse(src: str) -> ast.expr:
    """Parse `src` and reject anything outside the language. Raises ExprError."""
    if not isinstance(src, str) or not src.strip():
        raise ExprError("expression must be a non-empty string")
    if src in _PARSED:
        return _PARSED[src]
    try:
        tree = ast.parse(src, mode="eval").body
    except SyntaxError as e:
        raise ExprError(f"cannot parse {src!r}: {e}") from e
    _check(tree)
    _PARSED[src] = tree
    return tree


def _int_literal(node) -> int | None:
    ok = isinstance(node, ast.Constant) and isinstance(node.value, int)
    return node.value if ok and not isinstance(node.value, bool) else None


def _check(node) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExprError(f"only int/float literals are allowed, got {node.value!r}")
    elif isinstance(node, ast.Name):
        return
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise ExprError("only unary + and - are allowed")
        _check(node.operand)
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, _BINOPS):
            raise ExprError(f"operator {type(node.op).__name__} is not allowed")
        if isinstance(node.op, ast.Pow):
            e = _int_literal(node.right)
            if e is None or not (0 <= e <= MAX_POW):
                raise ExprError(f"exponent must be an integer literal in 0..{MAX_POW}")
        _check(node.left)
        _check(node.right)
    elif isinstance(node, ast.Subscript):
        if _int_literal(node.slice) is None:
            raise ExprError("subscripts must be integer literals")
        _check(node.value)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
            raise ExprError(f"only {', '.join(FUNCS)} may be called")
        if node.keywords or not node.args:
            raise ExprError("calls take positional arguments only")
        for a in node.args:
            _check(a)
    else:
        raise ExprError(f"{type(node).__name__} is not part of the expression language")


def names(tree: ast.expr) -> set[str]:
    """Entity names the expression reads (a called helper like `min` is not one)."""
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and id(n) not in called}


# -- evaluation ---------------------------------------------------------------

def _seq(x) -> list:
    if isinstance(x, np.ndarray):
        return list(x.ravel())
    if isinstance(x, (list, tuple)):
        return list(x)
    raise ExprError("expected a vector argument")


def evaluate(tree: ast.expr, env: dict, exact: bool = False):
    """Evaluate against `env` (entity name -> number/vector/matrix).

    `exact=False` uses floats (search); `exact=True` expects an env built by
    `exact_env` and returns a sympy Rational (certification).
    """
    def num(v):
        return sp.Rational(str(v)) if exact else float(v)

    def ev(n):
        if isinstance(n, ast.Constant):
            return num(n.value)
        if isinstance(n, ast.Name):
            if n.id not in env:
                raise ExprError(f"unknown entity {n.id!r}")
            return env[n.id]
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Subscript):
            base = ev(n.value)
            i = n.slice.value
            try:
                return base[i]
            except (IndexError, TypeError, KeyError) as e:
                raise ExprError(f"bad index [{i}] on {ast.unparse(n.value)}") from e
        if isinstance(n, ast.BinOp):
            if isinstance(n.op, ast.Pow):
                return ev(n.left) ** n.right.value
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if b == 0:
                raise ExprError("division by zero")
            return a / b
        fn = n.func.id
        args = [ev(a) for a in n.args]
        if fn == "abs":
            return abs(args[0])
        if fn == "sum":
            return sum(_seq(args[0]))
        pick = min if fn == "min" else max
        return pick(_seq(args[0]) if len(args) == 1 else args)

    return ev(tree)


def symbol_env(shapes: dict) -> dict:
    """Nested lists of sympy Symbols named like the Lean atoms (`P_0`, `T_1_0`).

    Evaluating a margin against this env turns it into a symbolic polynomial,
    which is what a sum-of-squares certificate needs."""
    def build(prefix: str, shape: tuple):
        if not shape:
            return sp.Symbol(prefix)
        return [build(f"{prefix}_{i}", shape[1:]) for i in range(shape[0])]

    return {name: build(name, tuple(shape)) for name, shape in shapes.items()}


def exact_env(exact: dict) -> dict:
    """Normalize rationalized free vars to nested lists of sympy Rationals, so
    `P[0][1]` means the same thing on the float and the exact path."""
    def nest(v):
        if isinstance(v, sp.MatrixBase):
            rows, cols = v.shape
            if rows == 1 or cols == 1:
                return [sp.Rational(x) for x in v]
            return [[sp.Rational(v[i, j]) for j in range(cols)] for i in range(rows)]
        if isinstance(v, (list, tuple, np.ndarray)):
            return [nest(x) for x in v]
        return sp.Rational(v)

    return {k: nest(v) for k, v in exact.items()}


# -- Lean form ----------------------------------------------------------------
# A term is ("lit", Rational) | ("atom", name) | (op, left, right) with
# op in qadd/qsub/qmul. leangen renders it; this module never writes Lean.

def lean_form(tree: ast.expr, env: dict, free: set | None = None) -> tuple[dict, tuple]:
    """Compile to (atoms, term) over an exact env. Raises ExprError for any
    construct the rational Q encoding cannot represent (fail closed).

    `free` restricts which entities may become atoms. A derived entity must
    never be one: emitting its computed value would have Lean check a bare
    number, proving nothing about how that number was derived.
    """
    atoms: dict[str, sp.Rational] = {}

    def atom(path: tuple):
        name = "_".join(str(p) for p in path)
        if name not in atoms:
            if free is not None and path[0] not in free:
                raise ExprError(
                    f"{path[0]!r} is derived; Lean would only see its value, not "
                    "its construction — the sandbox verdict stands"
                )
            v = env.get(path[0])
            if v is None:
                raise ExprError(f"unknown entity {path[0]!r}")
            for i in path[1:]:
                v = v[i]
            if isinstance(v, (list, tuple)):
                raise ExprError(f"{name} is a vector; index it down to a number")
            atoms[name] = sp.Rational(v)
        return ("atom", name)

    def path_of(n) -> tuple:
        if isinstance(n, ast.Name):
            return (n.id,)
        return path_of(n.value) + (n.slice.value,)

    def ev(n) -> tuple:
        if isinstance(n, ast.Constant):
            return ("lit", sp.Rational(str(n.value)))
        if isinstance(n, (ast.Name, ast.Subscript)):
            return atom(path_of(n))
        if isinstance(n, ast.UnaryOp):
            t = ev(n.operand)
            return ("qsub", ("lit", sp.Rational(0)), t) if isinstance(n.op, ast.USub) else t
        if isinstance(n, ast.BinOp):
            if isinstance(n.op, ast.Pow):
                k = n.right.value
                if k == 0:
                    return ("lit", sp.Rational(1))
                base = ev(n.left)
                term = base
                for _ in range(k - 1):
                    term = ("qmul", term, base)
                return term
            if isinstance(n.op, ast.Div):
                raise ExprError(
                    "division cannot be Lean-encoded (a negative divisor breaks the "
                    "positive-denominator invariant); the sandbox verdict stands"
                )
            op = {ast.Add: "qadd", ast.Sub: "qsub", ast.Mult: "qmul"}[type(n.op)]
            return (op, ev(n.left), ev(n.right))
        raise ExprError(f"{ast.unparse(n)} cannot be Lean-encoded; sandbox verdict stands")

    return atoms, ev(tree)
