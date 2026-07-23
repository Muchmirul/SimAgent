from simagent.library import get
from simagent.search import run_search
from simagent.spec import validate_spec


def test_bundled_specs_validate():
    for pid in ("circumcenter-in-triangle", "circumcenter-in-tetrahedron", "euler-characteristic-hull"):
        assert validate_spec(get(pid)) == []


def test_triangle_counterexample_certified():
    report = run_search(get("circumcenter-in-triangle"), trials=300, seed=0)
    assert report.verdict == "counterexample"
    assert report.certified is True
    assert report.exact_witness is not None
    assert report.witness_check["holds"] is False
    assert report.witness_check["margin"] < 0


def test_tetrahedron_counterexample_certified():
    report = run_search(get("circumcenter-in-tetrahedron"), trials=600, seed=1)
    assert report.verdict == "counterexample"
    assert report.certified is True


def test_euler_no_counterexample():
    report = run_search(get("euler-characteristic-hull"), trials=150, seed=0)
    assert report.verdict == "no_counterexample"
    assert report.valid_trials > 100
