import io

import numpy as np

from simagent.library import get
from simagent.play import PlayShell


def _shell(tmp_path, problem="circumcenter-in-triangle"):
    return PlayShell(get(problem), tmp_path, stdout=io.StringIO())


def test_play_starts_with_valid_sample_and_preview(tmp_path):
    shell = _shell(tmp_path)
    assert shell.vars["T"].shape == (3, 2)
    assert (tmp_path / "preview.png").exists()
    assert (tmp_path / "scene.json").exists()


def test_play_set_and_nudge(tmp_path):
    shell = _shell(tmp_path)
    shell.onecmd("set T[0] 2 2")
    assert np.allclose(shell.vars["T"][0], [2.0, 2.0])
    shell.onecmd("nudge T[0] -1 0")
    assert np.allclose(shell.vars["T"][0], [1.0, 2.0])
    shell.onecmd("set T[0] 9 9 9")  # wrong arity: rejected, value unchanged
    assert np.allclose(shell.vars["T"][0], [1.0, 2.0])


def test_play_hunt_loads_violating_witness_and_certifies(tmp_path):
    shell = _shell(tmp_path)
    shell.onecmd("hunt 300")
    res = shell.comp.check(**shell.vars)
    assert res.holds is False
    shell.onecmd("certify")
    out = shell.stdout.getvalue()
    assert "CERTIFIED" in out and "FAILS" in out


def test_play_refine_unavailable_for_discrete_specs(tmp_path):
    shell = _shell(tmp_path, problem="euler-characteristic-hull")
    shell.onecmd("refine 10")
    assert "discrete" in shell.stdout.getvalue()
