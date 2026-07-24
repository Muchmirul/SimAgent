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
    if d > 3:
        # The edge-determinant encoding uses cofactor expansion; beyond 3x3 the
        # term count explodes and `decide` chokes. Honest cap, stated plainly
        # (the LU-witness encoding is the documented post-v2 extension).
        raise ValueError(
            f"Lean certificate capped at d<=3 (got d={d}); "
            "sandbox verdict (exact rational arithmetic) stands"
        )
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


EXPR_TERM_CAP = 4000  # `decide` evaluates the term in-kernel; keep it tractable


def _render_q(term: tuple) -> str:
    kind = term[0]
    if kind == "lit":
        return _q(term[1])
    if kind == "atom":
        return term[1]
    return f"({kind} {_render_q(term[1])} {_render_q(term[2])})"


def _term_size(term: tuple) -> int:
    return 1 if term[0] in ("lit", "atom") else 1 + _term_size(term[1]) + _term_size(term[2])


def lean_expr_sign(
    atoms: dict, term: tuple, theorem: str, title: str, negative: bool
) -> str:
    """Certificate: this rational point makes the claim's margin negative (a
    counterexample) or positive (a witness).

    `atoms`/`term` come from `core.expr.lean_form`, so the Lean term is the
    same expression the sandbox measured — no second encoding to drift.
    Unlike the circumcenter certificate this has no determinant blow-up, so
    it carries no dimension cap.
    """
    size = _term_size(term)
    if size > EXPR_TERM_CAP:
        raise ValueError(
            f"Lean term too large ({size} nodes > {EXPR_TERM_CAP}); "
            "sandbox verdict (exact rational arithmetic) stands"
        )
    lines = [PRELUDE, f"/- {title} -/", ""]
    for name in sorted(atoms):
        lines.append(f"def {name} : Q := {_q(atoms[name])}")
    lines += ["", f"def margin : Q := {_render_q(term)}", ""]

    zero = _q(0)
    conjuncts = [f"qposden {name}" for name in sorted(atoms)]
    conjuncts.append(f"qlt margin {zero}" if negative else f"qlt {zero} margin")
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


SOS_PRELUDE = """\
/- SimAgent sum-of-squares certificate — Lean 4 core only, checked by `decide`.

   Encoding: (p, q) : Int × Int stands for the rational p/q with q > 0; the
   theorem asserts q > 0 for every number it uses, and qadd/qmul multiply
   denominators, so qeqB/qleB (cross-multiplication) coincide with =/<= on ℚ.

   `basis` lists the exponent vectors of the monomial vector z, so z_i is the
   monomial x^(basis i). The checks below verify, by pure computation:
     (1) every d_i >= 0,
     (2) G = sum_i d_i * v_i * v_i^T,
     (3) every monomial of p has coefficient equal to the matching sum of
         G entries, i.e. p = z^T G z,
     (4) every product z_i * z_j is one of p's listed monomials (nothing
         escapes the comparison), and (5) that monomial list has no repeats.
   Together: p = z^T G z = sum_i d_i (v_i . z)^2, a sum of squares with
   nonnegative coefficients, hence p >= 0 at EVERY real point. That closure
   step is the whole trusted modeling argument; all arithmetic is kernel-checked. -/

abbrev Q := Int × Int

def qadd (a b : Q) : Q := (a.1 * b.2 + b.1 * a.2, a.2 * b.2)
def qmul (a b : Q) : Q := (a.1 * b.1, a.2 * b.2)
def qzero : Q := ((0 : Int), 1)

def qeqB (a b : Q) : Bool := a.1 * b.2 == b.1 * a.2
def qleB (a b : Q) : Bool := decide (a.1 * b.2 <= b.1 * a.2)
def qposdenB (a : Q) : Bool := decide (0 < a.2)

def expAdd : List Nat -> List Nat -> List Nat
  | [], b => b
  | a, [] => a
  | x :: xs, y :: ys => (x + y) :: expAdd xs ys

def memb (m : List Nat) : List (List Nat) -> Bool
  | [] => false
  | x :: xs => (x == m) || memb m xs

def noDup : List (List Nat) -> Bool
  | [] => true
  | x :: xs => !(memb x xs) && noDup xs

def sumQ (l : List Q) : Q := l.foldl qadd qzero

def scaleRow (c : Q) (v : List Q) : List Q := v.map (fun x => qmul c x)
def outer (d : Q) (v : List Q) : List (List Q) := v.map (fun vi => scaleRow (qmul d vi) v)
def addMat (A B : List (List Q)) : List (List Q) := List.zipWith (List.zipWith qadd) A B
def matEqB (A B : List (List Q)) : Bool :=
  (List.zip A B).all (fun p => (List.zip p.1 p.2).all (fun q => qeqB q.1 q.2))
"""

SOS_BASIS_CAP = 28  # `decide` walks basis^2 products; keep the kernel honest and quick


def lean_sos(
    basis: list[tuple],
    gram: sp.Matrix,
    squares: list[tuple],
    monomials: list[tuple],
    coefficients: list,
    theorem: str,
    title: str,
) -> str:
    """Certificate: the margin polynomial is a sum of squares, so it is
    nonnegative at every real point — a genuine universal proof, not a sample.

    Inputs come from `sandbox.sos`; this module only renders them.
    """
    n = len(basis)
    if n > SOS_BASIS_CAP:
        raise ValueError(
            f"sum-of-squares Lean certificate capped at {SOS_BASIS_CAP} basis "
            f"monomials (got {n}); the sandbox verdict stands"
        )

    def nat_list(v) -> str:
        return "[" + ", ".join(str(int(x)) for x in v) + "]"

    def q_list(v) -> str:
        return "[" + ", ".join(_q(x) for x in v) + "]"

    lines = [SOS_PRELUDE, f"/- {title} -/", ""]
    lines.append("def basis : List (List Nat) := ["
                 + ", ".join(nat_list(b) for b in basis) + "]")
    lines.append("def mons : List (List Nat) := ["
                 + ", ".join(nat_list(m) for m in monomials) + "]")
    lines.append("def pcoef : List Q := " + q_list(coefficients))
    lines.append("def G : List (List Q) := ["
                 + ", ".join(q_list([gram[i, j] for j in range(n)]) for i in range(n)) + "]")
    lines.append("def ds : List Q := " + q_list([d for d, _ in squares]))
    lines.append("def vs : List (List Q) := ["
                 + ", ".join(q_list(v) for _, v in squares) + "]")
    lines += [
        "",
        "def zeroMat : List (List Q) := List.replicate basis.length "
        "(List.replicate basis.length qzero)",
        "def recon : List (List Q) :=",
        "  (List.zip ds vs).foldl (fun acc p => addMat acc (outer p.1 p.2)) zeroMat",
        "",
        "-- coefficient of monomial m in z^T G z",
        "def gramCoef (m : List Nat) : Q :=",
        "  sumQ ((List.zip basis G).map (fun r =>",
        "    sumQ ((List.zip basis r.2).filterMap (fun p =>",
        "      if expAdd r.1 p.1 = m then some p.2 else none))))",
        "",
        "def dimsOk : Bool :=",
        "  (G.length == basis.length) && G.all (fun r => r.length == basis.length)",
        "  && (ds.length == vs.length) && vs.all (fun v => v.length == basis.length)",
        "  && (pcoef.length == mons.length)",
        "",
        "def checkAll : Bool :=",
        "  dimsOk",
        "  && ds.all (fun d => qposdenB d && qleB qzero d)",
        "  && G.all (fun r => r.all qposdenB) && vs.all (fun v => v.all qposdenB)",
        "  && pcoef.all qposdenB",
        "  && matEqB recon G",
        "  && (List.zip mons pcoef).all (fun p => qeqB (gramCoef p.1) p.2)",
        "  && basis.all (fun a => basis.all (fun b => memb (expAdd a b) mons))",
        "  && noDup mons",
        "",
        f"theorem {theorem} : checkAll = true := by",
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
