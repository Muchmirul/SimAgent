"""Generate Lean 4 *core* certificates for mechanized proofs.

No Mathlib, no Batteries, no build system — a certificate is one file the
Lean kernel checks by pure computation (`decide`), so verification is
axiom-free and needs only the bare toolchain.

Encoding: a rational p/q is the pair (p, q) : Int × Int with q > 0. The
generated theorem asserts q > 0 for every atom; qadd/qsub/qmul multiply
denominators, so positivity is preserved on every derived pair, and under
that invariant qeq/qlt (cross-multiplication) coincide with =/< on ℚ.
This two-line closure argument is the entire trusted modeling step; all the
arithmetic itself is kernel-checked.
"""
from __future__ import annotations

import sympy as sp

from .certify import exact_barycentric, exact_circumcenter

PRELUDE = """\
/- SimAgent certificate — Lean 4 core only; checked by `decide` (no axioms).

   Encoding: (p, q) : Int × Int stands for the rational p/q with q > 0.
   The theorem asserts q > 0 for every atom; qadd/qsub/qmul multiply
   denominators, so every derived pair keeps q > 0, and then
     qeq a b ↔ a = b   and   qlt a b ↔ a < b   as rationals. -/

abbrev Q := Int × Int

def qadd (a b : Q) : Q := (a.1 * b.2 + b.1 * a.2, a.2 * b.2)
def qsub (a b : Q) : Q := (a.1 * b.2 - b.1 * a.2, a.2 * b.2)
def qmul (a b : Q) : Q := (a.1 * b.1, a.2 * b.2)

abbrev qeq (a b : Q) : Prop := a.1 * b.2 = b.1 * a.2
abbrev qlt (a b : Q) : Prop := a.1 * b.2 < b.1 * a.2
abbrev qposden (a : Q) : Prop := 0 < a.2
"""


def _q(x) -> str:
    x = sp.Rational(x)
    assert x.q > 0
    return f"(({x.p} : Int), {x.q})"


def _fold(op: str, terms: list[str]) -> str:
    expr = terms[0]
    for t in terms[1:]:
        expr = f"({op} {expr} {t})"
    return expr


def _det(rows: list[list[str]]) -> str:
    """Cofactor-expansion determinant over Q-expression strings (n <= 3)."""
    n = len(rows)
    if n == 1:
        return rows[0][0]
    if n == 2:
        return f"(qsub (qmul {rows[0][0]} {rows[1][1]}) (qmul {rows[0][1]} {rows[1][0]}))"
    terms = []
    for j in range(n):
        minor = [[row[k] for k in range(n) if k != j] for row in rows[1:]]
        term = f"(qmul {rows[0][j]} {_det(minor)})"
        terms.append(term if j % 2 == 0 else f"(qsub {_q(0)} {term})")
    return _fold("qadd", terms)


def lean_simplex_circumcenter(T: sp.Matrix, theorem: str, title: str) -> str:
    """Certificate: this rational simplex's circumcenter lies OUTSIDE it.

    States, over explicit numerals: the exhibited point c is equidistant from
    all vertices (it IS the circumcenter), the exhibited weights w are its
    barycentric coordinates (affine combination = c, sum = 1), the simplex is
    nondegenerate (edge determinant nonzero, so c and w are unique), and some
    w_k < 0 — which is the definition of "outside". Raises if the instance is
    not actually violating.
    """
    m, d = T.shape
    assert m == d + 1, "expected an (n+1) x n simplex"
    c = exact_circumcenter(T)
    w = exact_barycentric(T, c)
    k = min(range(m), key=lambda i: w[i])
    if not w[k] < 0:
        raise ValueError("instance is not a counterexample: all barycentric coords >= 0")

    lines = [PRELUDE, f"/- {title} -/", ""]
    atoms: list[str] = []

    def atom(name: str, value) -> str:
        lines.append(f"def {name} : Q := {_q(value)}")
        atoms.append(name)
        return name

    t = [[atom(f"t{i}{j}", T[i, j]) for j in range(d)] for i in range(m)]
    cs = [atom(f"c{j}", c[j]) for j in range(d)]
    ws = [atom(f"w{i}", w[i]) for i in range(m)]
    lines.append("")

    # squared distance from c to each vertex
    for i in range(m):
        sq = _fold(
            "qadd",
            [f"(qmul (qsub {cs[j]} {t[i][j]}) (qsub {cs[j]} {t[i][j]}))" for j in range(d)],
        )
        lines.append(f"def dist{i} : Q := {sq}")
    # barycentric combination, per coordinate
    for j in range(d):
        combo = _fold("qadd", [f"(qmul {ws[i]} {t[i][j]})" for i in range(m)])
        lines.append(f"def combo{j} : Q := {combo}")
    lines.append(f"def wsum : Q := {_fold('qadd', ws)}")
    edges = [[f"(qsub {t[i][j]} {t[0][j]})" for j in range(d)] for i in range(1, m)]
    lines.append(f"def edgeDet : Q := {_det(edges)}")
    lines.append("")

    conjuncts = [f"qposden {a}" for a in atoms]
    conjuncts += [f"qeq dist0 dist{i}" for i in range(1, m)]
    conjuncts += [f"qeq combo{j} c{j}" for j in range(d)]
    conjuncts += [f"qeq wsum {_q(1)}", f"¬ qeq edgeDet {_q(0)}", f"qlt w{k} {_q(0)}"]

    body = " ∧\n    ".join(conjuncts)
    lines += [
        f"theorem {theorem} :",
        f"    {body} := by",
        "  decide",
        "",
        f"#print axioms {theorem}",
        "",
    ]
    return "\n".join(lines)


def lean_bounded_nat(theorem: str, title: str, defs: str, statement: str) -> str:
    """Certificate for a `decide`-able bounded statement over Nat/Int.

    `defs` is verbatim Lean (helper definitions); `statement` is the Prop.
    Kept free-form because bounded claims vary by problem; the checker still
    enforces sorry-freedom and axiom-freedom.
    """
    return "\n".join(
        [
            "/- SimAgent certificate — Lean 4 core only; checked by `decide` (no axioms).",
            f"   {title} -/",
            "",
            "set_option maxRecDepth 8000",
            "",
            defs.strip(),
            "",
            f"theorem {theorem} :",
            f"    {statement.strip()} := by",
            "  decide",
            "",
            f"#print axioms {theorem}",
            "",
        ]
    )
