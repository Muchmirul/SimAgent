"""Regression tests for the post-audit soundness/honesty hardening.

Each test pins one finding from the adversarial review so a future change that
reopens the hole fails loudly.
"""
import copy

import numpy as np
import pytest

from simagent import lean_check
from simagent.library import get, is_bundled
from simagent.proof import Method, mechanized_proof
from simagent.search import (
    case_count,
    exhaustible,
    int_domain_exact,
    run_exhaustive,
)
from simagent.spec import ProblemSpec, VarSpec, sample_vars, validate_spec

lean = pytest.mark.skipif(not lean_check.lean_available(), reason="no Lean toolchain")


# ---- exhaustion soundness -------------------------------------------------

def test_case_count_rejects_inverted_and_empty_domains():
    spec = get("sum-of-odds-square")
    bad = copy.deepcopy(spec)
    bad.domain[0].low, bad.domain[0].high = 200, 0  # inverted
    assert case_count(bad) == 0
    assert not exhaustible(bad)
    with pytest.raises(ValueError):
        run_exhaustive(bad)


def test_case_count_no_int64_overflow_on_huge_shapes():
    spec = get("sum-of-odds-square")
    huge = copy.deepcopy(spec)
    huge.domain[0].shape = [1000000]  # would overflow np.prod-based entry count
    # python-int arithmetic -> astronomically large but correct, not 1
    assert case_count(huge) > 10**100
    assert not exhaustible(huge)


def test_int_domain_exact_guard():
    spec = get("sum-of-odds-square")
    assert int_domain_exact(spec)
    unsafe = copy.deepcopy(spec)
    unsafe.domain[0].high = 2**50  # beyond the 2^40 safe bound
    assert not int_domain_exact(unsafe)


def test_exhaustion_hit_without_certifier_is_not_certified_when_unsafe():
    # A forall over an int domain that FAILS somewhere, with no certify_code and
    # inputs beyond the exact-int guard -> found, but NOT stamped certified.
    spec = ProblemSpec(
        id="unsafe-int-forall",
        title="unsafe",
        conjecture="n < 0 for all n (false)",
        latex=r"\forall n,\ n < 0",
        quantifier="forall",
        domain=[VarSpec(name="n", shape=[], low=2**50, high=2**50 + 3, kind="int")],
        check_code="def check(n):\n    return {'holds': float(n) < 0, 'margin': None, 'data': {}}",
        scene_code="def build_scene(n):\n    return [scene_label(str(n))]",
    )
    report = run_exhaustive(spec)
    assert report.verdict == "counterexample"
    assert report.certified is False  # fail-closed, not True
    assert mechanized_proof(spec, report) is None  # kernel refuses to call it a proof


def test_exhaustion_incomplete_when_check_raises():
    spec = ProblemSpec(
        id="raises-forall",
        title="raises",
        conjecture="always true",
        latex=r"\forall n",
        quantifier="forall",
        domain=[VarSpec(name="n", shape=[], low=0, high=5, kind="int")],
        check_code=(
            "def check(n):\n"
            "    if int(n) == 3:\n"
            "        raise RuntimeError('boom')\n"
            "    return {'holds': True, 'margin': None, 'data': {}}"
        ),
        scene_code="def build_scene(n):\n    return [scene_label(str(n))]",
    )
    report = run_exhaustive(spec)
    # a case we could not decide means the forall is NOT proved
    assert report.verdict == "no_counterexample"
    assert report.certified is None
    assert any("INCOMPLETE" in n for n in report.notes)
    assert mechanized_proof(spec, report) is None


# ---- statement_review honesty ---------------------------------------------

def test_statement_review_flags_non_bundled_specs():
    spec = get("circumcenter-in-triangle")
    from simagent.search import run_search

    report = run_search(spec, trials=300, seed=0)

    bundled_proof = mechanized_proof(spec, report, spec_trusted=is_bundled(spec))
    assert bundled_proof.statement_review == "bundled-trusted"

    # a disk round-trip yields a different object -> untrusted
    reloaded = ProblemSpec.from_json(spec.to_json())
    assert not is_bundled(reloaded)
    untrusted_proof = mechanized_proof(reloaded, report, spec_trusted=is_bundled(reloaded))
    assert untrusted_proof.statement_review == "spec-generated-review-needed"


# ---- spec validation ------------------------------------------------------

def test_validate_rejects_bad_kind_and_bounds():
    base = get("sum-of-odds-square").to_json()
    bad_kind = ProblemSpec.from_json({**base, "domain": [{"name": "n", "shape": [], "low": 0, "high": 5, "kind": "integer"}]})
    assert any("kind" in e for e in validate_spec(bad_kind))
    inverted = ProblemSpec.from_json({**base, "domain": [{"name": "n", "shape": [], "low": 5, "high": 0, "kind": "int"}]})
    assert any("<=" in e for e in validate_spec(inverted))


def test_sample_vars_friendly_error_on_inverted_int():
    spec = get("sum-of-odds-square")
    bad = copy.deepcopy(spec)
    bad.domain[0].low, bad.domain[0].high = 5, 0
    with pytest.raises(ValueError, match="low"):
        sample_vars(np.random.default_rng(0), bad)


# ---- lean_check hardening -------------------------------------------------

@lean
def test_lean_rejects_forbidden_constructs():
    for bad in (
        "theorem t : True := by admit\n#print axioms t\n",
        "theorem t : (2:Nat)=3 := by native_decide\n#print axioms t\n",
    ):
        r = lean_check.check_source(bad, workdir="/tmp")
        assert r["axiom_clean"] is False, bad


@lean
def test_lean_requires_named_axiom_print():
    # valid proof but no #print axioms -> cannot be certified
    r = lean_check.check_source("theorem t : 1 + 1 = 2 := by decide\n", workdir="/tmp")
    assert r["ok"] is True and r["axiom_clean"] is False


@lean
def test_lean_rejects_when_any_dependence_reported():
    # 'admit' is stripped-comment-safe; use a real axiom dependence via Classical
    src = (
        "open Classical in\n"
        "theorem t : True := ⟨⟩\n"
        "theorem u : (0:Nat) = 0 ∨ True := Or.inr (Classical.choice ⟨trivial⟩)\n"
        "#print axioms t\n#print axioms u\n"
    )
    r = lean_check.check_source(src, workdir="/tmp")
    # u depends on Classical.choice -> the whole file is rejected
    assert r["axiom_clean"] is False


@lean
def test_comment_injected_clean_phrase_does_not_fool_checker():
    # source echoes the magic phrase in a comment, but the real theorem is a hole
    src = (
        "-- 'fake' does not depend on any axioms\n"
        "theorem real : (2:Nat) = 3 := by decide\n"
        "#print axioms real\n"
    )
    r = lean_check.check_source(src, workdir="/tmp")
    assert r["axiom_clean"] is False
