import json
from pathlib import Path

from simagent.library import get
from simagent.pipeline import run_problem


def test_pipeline_offline_counterexample(tmp_path: Path):
    result = run_problem(get("circumcenter-in-triangle"), tmp_path / "run", trials=300, seed=0)
    out = Path(result.out_dir)
    for name in ("spec.json", "report.json", "scene.json", "preview.png", "scene_manim.py",
                 "answer.md", "answer.tex", "conjecture.lean"):
        assert (out / name).exists(), name

    report = json.loads((out / "report.json").read_text())
    assert report["report"]["verdict"] == "counterexample"
    assert report["report"]["certified"] is True

    lean = (out / "conjecture.lean").read_text()
    assert "_disproved" in lean and "sorry" in lean

    tex = (out / "answer.tex").read_text()
    assert "DISPROVED" in tex

    # generated manim scene must at least be valid python
    compile((out / "scene_manim.py").read_text(), "scene_manim.py", "exec")


def test_pipeline_offline_evidence(tmp_path: Path):
    result = run_problem(get("euler-characteristic-hull"), tmp_path / "run", trials=80, seed=0)
    report = json.loads((Path(result.out_dir) / "report.json").read_text())
    assert report["report"]["verdict"] == "no_counterexample"
    md = (Path(result.out_dir) / "answer.md").read_text()
    assert "evidence" in md
