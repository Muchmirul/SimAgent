"""The proof kernel: what this harness is willing to call a proof.

Responsibility split: the LLM (or the human) reasons; the harness only records
what it can *execute or check*. Every answer names one of the ten
classical proof methods, and carries a `verified_by` stamp that only this
module assigns:

  "sandbox"        complete mechanical check by the harness itself
                   (exact rational arithmetic, or full enumeration)
  "sandbox+lean"   sandbox check AND a generated Lean certificate accepted by
                   the Lean kernel with no axioms
  "lean"           a Lean proof (e.g. LLM-written) accepted by the Lean
                   kernel; the *statement's* faithfulness to the conjecture
                   still needs human review
  "none"           an argument on record, nothing verified

Method taxonomy (the mechanized set is exactly what a simulation harness can
soundly establish on its own; every deductive method requires a proof
assistant, so those are Lean-or-nothing here):

  mechanized: counterexample, construction, exhaustion
  deductive:  direct, contradiction, contrapositive, induction, cases,
              combinatorial, infinite_descent
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

import sympy as sp

from . import lean_check
from .sandbox import certify as certify_mod
from .search import SearchReport
from .spec import ProblemSpec


class Method(str, Enum):
    DIRECT = "direct"
    CONTRADICTION = "contradiction"
    CONTRAPOSITIVE = "contrapositive"
    INDUCTION = "induction"
    CASES = "cases"
    CONSTRUCTION = "construction"
    COUNTEREXAMPLE = "counterexample"
    EXHAUSTION = "exhaustion"
    COMBINATORIAL = "combinatorial"
    INFINITE_DESCENT = "infinite_descent"


MECHANIZED: frozenset[Method] = frozenset(
    {Method.COUNTEREXAMPLE, Method.CONSTRUCTION, Method.EXHAUSTION}
)
DEDUCTIVE: frozenset[Method] = frozenset(Method) - MECHANIZED


@dataclass
class Proof:
    method: Method
    claim: str  # exactly what is proved (may be the negation, or a bounded form)
    verified_by: str  # "sandbox" | "sandbox+lean" | "lean" | "none"
    argument: str  # human-readable core of the argument
    witness: dict | None = None  # exact 'p/q' witness values, when witness-based
    lean_file: str | None = None
    lean_report: dict | None = None
    statement_review: str = "bundled-trusted"  # or "llm-generated-review-needed"

    def to_json(self) -> dict:
        d = asdict(self)
        d["method"] = self.method.value
        return d


def _exact_from_repr(rep) -> sp.Matrix | sp.Rational:
    """Parse the report's exact witness ('p/q' strings) back into sympy."""
    if isinstance(rep, str):
        return sp.Rational(rep)
    return sp.Matrix([[sp.Rational(x) for x in row] for row in rep])


def _attach_lean(proof: Proof, spec: ProblemSpec, report: SearchReport, out_dir) -> None:
    """Generate + kernel-check a Lean certificate, if the spec provides one.

    Only a clean, axiom-free `lean` run upgrades verified_by. Any failure
    leaves the sandbox verdict intact and records why.
    """
    comp = spec.compiled()
    if not comp.has_lean_certificate:
        return
    try:
        if report.exact_witness:
            exact = {k: _exact_from_repr(v) for k, v in report.exact_witness.items()}
            source = comp.lean_certificate(**exact)
        else:  # exhaustion-style certificate, no witness needed
            source = comp.lean_certificate()
    except Exception as e:  # noqa: BLE001 - generation failure must not hide the sandbox result
        proof.lean_report = {"available": None, "ok": False, "error": f"{type(e).__name__}: {e}"}
        return
    path = None
    if out_dir is not None:
        path = Path(out_dir) / "certificate.lean"
        path.write_text(source)
        proof.lean_file = str(path)
    result = lean_check.check_source(source, workdir=out_dir)
    proof.lean_report = result
    if result["ok"] and result["axiom_clean"]:
        proof.verified_by = "sandbox+lean"


def mechanized_proof(
    spec: ProblemSpec, report: SearchReport, out_dir=None, spec_trusted: bool = False
) -> Proof | None:
    """Build a Proof from a search/enumeration report — or refuse.

    Returns None whenever the report does not meet the kernel's bar
    (uncertified numeric findings and sampling evidence are not proofs).
    `spec_trusted` marks a bundled/reviewed spec; otherwise the Lean
    statement is spec-controlled and flagged for human review.
    """
    review = "bundled-trusted" if spec_trusted else "spec-generated-review-needed"
    proof: Proof | None = None
    if report.verdict == "counterexample" and report.certified:
        proof = Proof(
            method=Method.COUNTEREXAMPLE,
            claim=f"NOT[ {spec.latex} ]",
            verified_by="sandbox",
            argument=(
                "A single explicit instance violates the universally quantified "
                "statement. The instance was found by sandbox search, snapped to "
                "rational coordinates, and the violation re-decided in exact "
                "arithmetic."
            ),
            witness=report.exact_witness,
            statement_review=review,
        )
    elif report.verdict == "witness" and report.certified:
        proof = Proof(
            method=Method.CONSTRUCTION,
            claim=spec.latex,
            verified_by="sandbox",
            argument=(
                "The existential statement is proved by exhibiting an explicit "
                "rational instance and re-deciding the property in exact arithmetic."
            ),
            witness=report.exact_witness,
            statement_review=review,
        )
    elif report.verdict in ("holds_on_domain", "no_witness_on_domain") and report.certified:
        polarity = "holds" if report.verdict == "holds_on_domain" else "has no witness"
        proof = Proof(
            method=Method.EXHAUSTION,
            claim=f"{spec.latex}  (over the declared finite domain)",
            verified_by="sandbox",
            argument=(
                f"Every one of the {report.valid_trials} cases in the declared "
                f"finite domain was checked individually; the property {polarity} "
                "in all of them. This proves exactly the bounded statement — "
                "nothing beyond the domain."
            ),
            statement_review=review,
        )
    if proof is not None:
        _attach_lean(proof, spec, report, out_dir)
    return proof


def deductive_proof(
    spec: ProblemSpec,
    method: Method | str,
    argument: str,
    lean_code: str | None,
    out_dir=None,
    statement_review: str = "llm-generated-review-needed",
) -> Proof:
    """Record a deductive proof attempt; verified only if Lean accepts it.

    The harness never evaluates prose. Without Lean code — or with Lean code
    the kernel rejects — the attempt is stored with verified_by="none".
    """
    method = Method(method)
    proof = Proof(
        method=method,
        claim=spec.latex,
        verified_by="none",
        argument=argument,
        statement_review=statement_review,
    )
    if lean_code:
        path = None
        if out_dir is not None:
            path = Path(out_dir) / "proof_attempt.lean"
            path.write_text(lean_code)
            proof.lean_file = str(path)
        result = lean_check.check_source(lean_code, workdir=out_dir)
        proof.lean_report = result
        if result["ok"] and result["axiom_clean"]:
            proof.verified_by = "lean"
    return proof


def save_proof(proof: Proof, out_dir) -> str:
    path = Path(out_dir) / "proof.json"
    path.write_text(json.dumps(proof.to_json(), indent=2))
    return str(path)
