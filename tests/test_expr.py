"""The general expression vocabulary: the closed arithmetic language, its
three evaluators, and the known-answer claim built on it.

The language is where LLM-written text enters the kernel, so the rejection
tests matter as much as the arithmetic ones: anything outside rational
arithmetic must be refused, not evaluated.
"""
import numpy as np
import pytest

from simagent import lean_check
from simagent.core import expr
from simagent.core.claim import Claim, validate_claim
from simagent.core.space import Box
from simagent.library import get
from simagent.sandbox import certify as certify_mod
from simagent.search import run_search

lean = pytest.mark.skipif(not lean_check.lean_available(), reason="no Lean toolchain")

MARGIN = "P[0]**2 + P[1]**2 + 1 - 2*P[0] - 2*P[1]"


@pytest.mark.parametrize(
    "src",
    [
        "__import__('os').system('echo hi')",  # the attack the closed vocabulary exists to stop
        "P.__class__",                          # attribute access
        "open('/etc/passwd')",                  # a call outside the whitelist
        "P[0] > 1",                             # comparison: a margin is a number
        "lambda: 1",
        "[1, 2][0]",                            # list display
        "P[0] if P[1] else 0",
        "P[0] % 2",                             # operator outside + - * / **
        "P[0] ** 99",                           # exponent past MAX_POW
        "P[0] ** P[1]",                         # non-literal exponent
        "P[P[0]]",                              # non-literal subscript
        "",
    ],
)
def test_language_rejects_everything_outside_rational_arithmetic(src):
    with pytest.raises(expr.ExprError):
        expr.parse(src)


def test_float_and_exact_evaluators_agree():
    tree = expr.parse(MARGIN)
    P = np.array([1.5, 0.25])
    numeric = expr.evaluate(tree, {"P": P})
    exact = expr.evaluate(
        tree, expr.exact_env({"P": certify_mod.rationalize_array(P)}), exact=True
    )
    assert exact.is_rational
    assert numeric == pytest.approx(float(exact))
    assert float(exact) == pytest.approx(1.5**2 + 0.25**2 + 1 - 3.0 - 0.5)


def test_helpers_and_indexing_evaluate():
    env = {"M": np.array([[1.0, 2.0], [3.0, 4.0]]), "s": np.float64(2.0)}
    assert expr.evaluate(expr.parse("M[1][0] - M[0][1]"), env) == 1.0
    assert expr.evaluate(expr.parse("sum(M[0]) * s"), env) == 6.0
    assert expr.evaluate(expr.parse("max(M[0][0], M[1][1]) - min(M[0])"), env) == 3.0
    assert expr.evaluate(expr.parse("abs(0 - M[1][1])"), env) == 4.0


def test_unknown_entity_and_division_by_zero_fail_closed():
    with pytest.raises(expr.ExprError):
        expr.evaluate(expr.parse("Q[0]"), {"P": np.array([1.0])})
    with pytest.raises(expr.ExprError):
        expr.evaluate(expr.parse("1 / (P[0] - P[0])"), {"P": np.array([1.0])})


def test_lean_form_refuses_division_rather_than_downgrading_silently():
    env = expr.exact_env({"P": certify_mod.rationalize_array(np.array([1.0, 2.0]))})
    atoms, term = expr.lean_form(expr.parse("P[0]*P[0] - P[1]"), env)
    assert set(atoms) == {"P_0", "P_1"}
    with pytest.raises(expr.ExprError):
        expr.lean_form(expr.parse("P[0] / P[1]"), env)


def _claim(**over) -> Claim:
    base = dict(
        id="t", title="t", conjecture="t", latex="t", quantifier="forall",
        spaces={"P": Box(shape=(2,), low=-2.0, high=2.0)}, recipe=[],
        measure={"kind": "expr", "margin": MARGIN},
        scene={"kind": "point", "of": "P"},
    )
    base.update(over)
    return Claim(**base)


def test_validate_rejects_a_certifier_that_names_a_different_expression():
    ok = _claim(certify={"kind": "expr", "margin": MARGIN})
    assert validate_claim(ok) == []
    # certifying a different expression would prove nothing about this claim
    bad = _claim(certify={"kind": "expr", "margin": "P[0] - P[0] + 1"})
    assert any("verbatim" in e for e in validate_claim(bad))
    bad_lean = _claim(lean={"kind": "expr", "margin": "0 - 1",
                            "theorem": "t", "title": "t"})
    assert any("verbatim" in e for e in validate_claim(bad_lean))


def test_validate_rejects_a_margin_reading_an_unknown_entity():
    errors = validate_claim(_claim(measure={"kind": "expr", "margin": "Z[0] - 1"}))
    assert any("unknown entities" in e for e in errors)


def test_bundled_expression_claim_is_a_known_answer():
    claim = get("sum-of-squares-vs-linear")
    assert validate_claim(claim) == []
    # ground truth: margin = (x-1)^2 + (y-1)^2 - 1, so (1,1) fails by exactly -1
    res = claim.compiled().check(P=np.array([1.0, 1.0]))
    assert res.holds is False and res.margin == pytest.approx(-1.0)
    # and every point outside the closed unit disc around (1,1) satisfies it
    assert claim.compiled().check(P=np.array([-1.0, -1.0])).holds is True

    report = run_search(claim, trials=400, seed=3)
    assert report.verdict == "counterexample"
    assert report.certified is True
    assert report.exact_witness is not None


def test_field_view_paints_the_claims_true_boundary(tmp_path):
    """Perception must match the algebra: completing the square says the
    failure region is the open unit disc at (1,1), so the painted field's
    zero-contour is that circle and the failure area is pi/16 of the box."""
    from simagent.views import render_field

    claim = get("sum-of-squares-vs-linear")
    _path, meta = render_field(claim, claim.compiled(), {"P": np.array([1.0, 1.0])},
                               tmp_path / "field.png", resolution=96)
    assert meta["zero_contour"] is True
    assert meta["min_margin"] == pytest.approx(-1.0, abs=1e-3)
    assert meta["min_at"] == pytest.approx([1.0, 1.0], abs=0.02)
    # disc area pi / box area 16
    assert meta["fail_fraction"] == pytest.approx(np.pi / 16, abs=0.01)


@lean
def test_expression_certificate_is_kernel_checked_and_axiom_free(tmp_path):
    from simagent.pipeline import run_problem

    out = run_problem(get("sum-of-squares-vs-linear"), tmp_path, trials=400,
                      seed=3, render_manim=False)
    proof = out.proof
    assert proof.method == "counterexample"
    # the whole point: a general algebraic claim reaches the top rung, and
    # unlike the circumcenter encoding this carries no d<=3 cap
    assert proof.verified_by == "sandbox+lean"
    assert proof.lean_report["ok"] is True
    assert proof.lean_report["axiom_clean"] is True
