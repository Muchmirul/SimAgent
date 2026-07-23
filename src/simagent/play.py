"""Interactive sandbox: drive a conjecture's world by hand.

The core trick: after every command the current configuration is re-rendered
to <out>/preview.png. Keep that file open in your editor (VS Code reloads
images on change) and the picture updates live while you type.

Human and machine share the same moves — you can `set`/`nudge` points by hand,
or ask the harness to `hunt`/`refine`, then `certify` whatever configuration
is on screen.
"""
from __future__ import annotations

import cmd
import json
import re
from pathlib import Path

import numpy as np

from . import spec as spec_mod
from .search import certify_candidate, refine_candidate, run_search
from .spec import ProblemSpec
from .visualize import mpl
from .visualize.manim_gen import try_render_manim, write_manim_scene

_TARGET_RE = re.compile(r"^([A-Za-z_]\w*)(?:\[(\d+)\])?$")

_HELP = """commands:
  sample [seed]        draw a new random valid configuration
  set VAR[i] x y ...   place a point (row) exactly     e.g.  set T[0] -1 0.6 0.7
  nudge VAR[i] dx ...  move a point by a delta         e.g.  nudge T[2] 0 0 -0.2
  check                full check output (holds / margin / data)
  refine [steps]       anneal the current configuration toward violation/witness
  hunt [trials]        automated search from scratch; loads the witness it finds
  certify              exact-arithmetic verdict for the current configuration
  manim                write (and if possible render) the Manim scene for this state
  save                 write vars.json for the current configuration
  help / quit
"""


class PlayShell(cmd.Cmd):
    prompt = "(sandbox) "

    def __init__(self, spec: ProblemSpec, out_dir, stdout=None):
        super().__init__(stdout=stdout)
        self.spec = spec
        self.comp = spec.compiled()
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.rng = np.random.default_rng(0)
        self._hunt_seed = 0
        self.vars: dict[str, np.ndarray] = {}
        spec.save(self.out / "spec.json")
        self._sample()
        self._sync(announce=False)

    # -- infrastructure ------------------------------------------------------

    def _p(self, msg: str = "") -> None:
        self.stdout.write(msg + "\n")

    def emptyline(self) -> bool:  # don't repeat the last command on Enter
        return False

    def _sample(self, seed: int | None = None) -> None:
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        for _ in range(1000):
            vars = spec_mod.sample_vars(self.rng, self.spec)
            try:
                if self.comp.valid(**vars):
                    self.vars = vars
                    return
            except Exception:  # noqa: BLE001
                continue
        raise RuntimeError("could not draw a valid sample (constraint too strict?)")

    def _check(self):
        try:
            return self.comp.check(**self.vars), None
        except Exception as e:  # noqa: BLE001
            return None, f"{type(e).__name__}: {e}"

    def _sync(self, announce: bool = True) -> None:
        """Re-render the preview and print a one-line status."""
        res, err = self._check()
        try:
            scene = self.comp.build_scene(**self.vars)
            (self.out / "scene.json").write_text(json.dumps(scene, indent=2))
            mpl.render_png(scene, self.out / "preview.png", title=self.spec.title)
        except Exception as e:  # noqa: BLE001
            self._p(f"  (scene render failed: {type(e).__name__}: {e})")
        if not announce:
            return
        if res is None:
            self._p(f"  status: check failed — {err}")
        else:
            margin = "n/a" if res.margin is None else f"{res.margin:+.4f}"
            self._p(f"  status: holds={res.holds}  margin={margin}")

    def _assign(self, arg: str, relative: bool) -> None:
        tokens = arg.replace(",", " ").split()
        if len(tokens) < 2:
            self._p("usage: set|nudge VAR[i] v1 [v2 ...]")
            return
        m = _TARGET_RE.match(tokens[0])
        if not m or m.group(1) not in self.vars:
            self._p(f"unknown target {tokens[0]!r}; variables: {', '.join(self.vars)}")
            return
        name, idx = m.group(1), m.group(2)
        try:
            values = np.array([float(t) for t in tokens[1:]], dtype=float)
        except ValueError:
            self._p("values must be numbers")
            return
        v = self.vars[name]
        if idx is None:
            if values.size != v.size:
                self._p(f"{name} has {v.size} entries; got {values.size}")
                return
            new = values.reshape(v.shape)
            self.vars[name] = v + new if relative else new
        else:
            i = int(idx)
            if i >= v.shape[0]:
                self._p(f"{name} has rows 0..{v.shape[0] - 1}")
                return
            if values.size != np.asarray(v[i]).size:
                self._p(f"{name}[{i}] needs {np.asarray(v[i]).size} numbers; got {values.size}")
                return
            v[i] = v[i] + values if relative else values
        self._sync()

    # -- commands ------------------------------------------------------------

    def do_sample(self, arg: str) -> None:
        """sample [seed] — draw a new random valid configuration."""
        seed = int(arg) if arg.strip() else None
        self._sample(seed)
        self._sync()

    def do_set(self, arg: str) -> None:
        """set VAR[i] x y ... — place a point exactly."""
        self._assign(arg, relative=False)

    def do_nudge(self, arg: str) -> None:
        """nudge VAR[i] dx dy ... — move a point by a delta."""
        self._assign(arg, relative=True)

    def do_check(self, arg: str) -> None:
        """check — full check output for the current configuration."""
        res, err = self._check()
        if res is None:
            self._p(f"check failed — {err}")
            return
        self._p(f"holds  = {res.holds}")
        self._p(f"margin = {res.margin}")
        self._p(f"data   = {json.dumps(res.data, default=str)}")
        for name, v in self.vars.items():
            self._p(f"{name} =")
            for row in np.atleast_2d(np.asarray(v)):
                self._p("  (" + ", ".join(f"{x:+.4f}" for x in np.atleast_1d(row)) + ")")

    def do_refine(self, arg: str) -> None:
        """refine [steps] — anneal toward a counterexample (forall) / witness (exists)."""
        steps = int(arg) if arg.strip() else 300
        try:
            vars, res, used = refine_candidate(self.spec, self.vars, steps=steps)
        except ValueError as e:
            self._p(str(e))
            return
        self.vars = vars
        self._p(f"  refined for {used} steps (stays inside the declared domain)")
        self._sync()

    def do_hunt(self, arg: str) -> None:
        """hunt [trials] — automated search; loads the witness it finds."""
        trials = int(arg) if arg.strip() else 800
        self._hunt_seed += 1
        report = run_search(self.spec, trials=trials, seed=self._hunt_seed)
        self._p(f"  verdict: {report.verdict}" + (f" (certified={report.certified})" if report.certified is not None else ""))
        if report.witness:
            self.vars = {k: np.array(v, dtype=float) for k, v in report.witness.items()}
            self._p("  witness loaded into the current configuration")
            self._sync()
        else:
            self._p("  nothing decisive found; configuration unchanged")

    def do_certify(self, arg: str) -> None:
        """certify — exact-arithmetic verdict for the current configuration."""
        try:
            res, certified, exact, notes = certify_candidate(self.spec, self.vars)
        except ValueError as e:
            self._p(str(e))
            return
        self._p(f"numeric: holds={res.holds}")
        if certified is None:
            self._p("no exact certifier on this spec — numeric only")
        elif certified:
            what = "property FAILS" if not res.holds else "property HOLDS"
            self._p(f"CERTIFIED in exact rationals: {what} for this configuration")
            for name, mat in (exact or {}).items():
                self._p(f"  {name} =")
                rows = mat if isinstance(mat, list) else [[mat]]
                for row in np.atleast_1d(rows):
                    self._p("    (" + ", ".join(str(x) for x in np.atleast_1d(row)) + ")")
        else:
            self._p("certification failed (rational snap crossed the boundary)")
        for n in notes:
            self._p(f"  note: {n}")

    def do_manim(self, arg: str) -> None:
        """manim — write (and if possible render) the Manim scene for this state."""
        scene = self.comp.build_scene(**self.vars)
        path = write_manim_scene(scene, self.spec.title, self.spec.id, self.out / "scene_manim.py")
        self._p(f"scene written: {path}")
        ok, msg, files = try_render_manim(path, still=True, quality="h")
        self._p(msg)
        for f in files:
            self._p(f"  {f}")

    def do_save(self, arg: str) -> None:
        """save — write vars.json for the current configuration."""
        path = self.out / "vars.json"
        path.write_text(json.dumps({k: np.asarray(v).tolist() for k, v in self.vars.items()}, indent=2))
        self._p(f"saved: {path}")

    def do_help(self, arg: str) -> None:  # noqa: A003
        self._p(_HELP)

    def do_quit(self, arg: str) -> bool:
        return True

    do_exit = do_quit
    do_EOF = do_quit


def launch(spec: ProblemSpec, out_dir) -> None:
    shell = PlayShell(spec, out_dir)
    print(f"== {spec.title} ==")
    print(spec.conjecture)
    print()
    print(f"Live view: keep {shell.out / 'preview.png'} open in your editor —")
    print("it re-renders after every command.")
    print()
    print(_HELP)
    shell._sync()
    shell.cmdloop()
