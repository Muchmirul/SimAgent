"""FastAPI backend for the SimAgent reasoning notebook.

Single-user local tool. The frontend is a notebook: a math problem goes in as
text (or a bundled problem id), an embodied agent session runs in a background
thread, and the UI streams the mind trace — thought + act + rendered scene +
equation translation + diff per step — as notebook cells. The server stays
the kernel authority: it also exposes the sandbox session API (load/set/
sample/refine/hunt/certify) and Manim render jobs; the UI cannot mint
verdicts, it only displays kernel state.
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..library import all_specs, get
from ..spec import ProblemSpec
from ..core.journal import TRACE_FILE, read_trace
from ..visualize import mpl
from ..visualize.manim_gen import manim_available, try_render_manim, write_manim_scene
from .session import SandboxSession

_STATIC = Path(__file__).parent / "static"


class LoadBody(BaseModel):
    problem_id: str | None = None
    spec_path: str | None = None


class SetBody(BaseModel):
    name: str
    row: int | None = None
    values: list[float]


class SampleBody(BaseModel):
    seed: int | None = None


class RefineBody(BaseModel):
    steps: int = 300


class HuntBody(BaseModel):
    trials: int = 800


class ManimBody(BaseModel):
    video: bool = False


class AgentStartBody(BaseModel):
    problem_id: str | None = None
    conjecture: str | None = None
    backend: str | None = None  # None/auto -> resolve_backend
    max_turns: int = 40


def create_app(
    out_root: str = "runs/web",
    runs_root: str | None = None,
    agent_runner=None,
) -> FastAPI:
    app = FastAPI(title="SimAgent sandbox")
    sessions: dict[str, SandboxSession] = {}
    jobs: dict[str, dict] = {}
    lock = threading.Lock()
    # Where agent runs live (each with a trace.jsonl mind trace). Default: the
    # parent of out_root, i.e. `runs/` when serving from `runs/web`.
    traces_root = Path(runs_root) if runs_root else Path(out_root).parent

    def run_dir(run: str) -> Path:
        d = (traces_root / run).resolve()
        if (
            run in ("", ".", "..")
            or "/" in run
            or "\\" in run
            or not d.is_relative_to(traces_root.resolve())
            or not (d / TRACE_FILE).exists()
        ):
            raise HTTPException(404, f"no trace for run {run!r}")
        return d

    def session() -> SandboxSession:
        s = sessions.get("current")
        if s is None:
            raise HTTPException(409, "no problem loaded; POST /api/load first")
        return s

    @app.get("/api/problems")
    def problems() -> list[dict]:
        return [
            {
                "id": s.id,
                "title": s.title,
                "quantifier": s.quantifier,
                "conjecture": s.conjecture,
            }
            for s in all_specs()
        ]

    @app.post("/api/load")
    def load(body: LoadBody) -> dict:
        if body.spec_path:
            spec = ProblemSpec.load(body.spec_path)
        elif body.problem_id:
            try:
                spec = get(body.problem_id)
            except KeyError as e:
                raise HTTPException(404, str(e)) from e
        else:
            raise HTTPException(422, "problem_id or spec_path required")
        sessions["current"] = SandboxSession(spec, Path(out_root) / spec.id)
        return sessions["current"].state()

    @app.get("/api/state")
    def state() -> dict:
        return session().state()

    @app.post("/api/set")
    def set_value(body: SetBody) -> dict:
        s = session()
        try:
            s.set_value(body.name, body.row, body.values)
        except (KeyError, ValueError) as e:
            raise HTTPException(422, str(e)) from e
        return s.state()

    @app.post("/api/sample")
    def sample(body: SampleBody) -> dict:
        s = session()
        s.sample(body.seed)
        return s.state()

    @app.post("/api/refine")
    def refine(body: RefineBody) -> dict:
        s = session()
        try:
            result = s.refine(body.steps)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"result": result, "state": s.state()}

    @app.post("/api/hunt")
    def hunt(body: HuntBody) -> dict:
        s = session()
        result = s.hunt(body.trials)
        return {"result": result, "state": s.state()}

    @app.post("/api/certify")
    def certify() -> dict:
        s = session()
        try:
            return s.certify()
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.post("/api/manim")
    def manim_render(body: ManimBody) -> dict:
        s = session()
        if not manim_available():
            return {
                "job": None,
                "available": False,
                "message": "Manim is not available on this machine (see README: .manim-env).",
            }
        job_id = uuid.uuid4().hex[:8]
        scene = s.scene()
        scene_py = write_manim_scene(scene, s.spec.title, s.spec.id, s.out / "scene_manim.py")
        with lock:
            jobs[job_id] = {"status": "running", "message": "rendering...", "file": None}

        def work() -> None:
            ok, msg, files = try_render_manim(
                scene_py, still=not body.video, quality="h" if not body.video else "l"
            )
            with lock:
                jobs[job_id] = {
                    "status": "done" if ok else "failed",
                    "message": msg,
                    "file": files[-1] if files else None,
                }

        threading.Thread(target=work, daemon=True).start()
        return {"job": job_id, "available": True, "video": body.video}

    @app.get("/api/manim/{job_id}")
    def manim_status(job_id: str) -> dict:
        with lock:
            job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown job")
        return {**job, "url": f"/api/manim/{job_id}/file" if job["file"] else None}

    @app.get("/api/manim/{job_id}/file")
    def manim_file(job_id: str):
        with lock:
            job = jobs.get(job_id)
        if job is None or not job["file"]:
            raise HTTPException(404, "no file for this job")
        return FileResponse(job["file"])

    # -- mind traces: replay/watch an agent's chain of thought ---------------

    @app.get("/api/runs")
    def runs() -> list[dict]:
        """Agent runs under the runs root that recorded a mind trace."""
        found = []
        if traces_root.is_dir():
            for d in traces_root.iterdir():
                tf = d / TRACE_FILE
                if not tf.is_file():
                    continue
                title = None
                spec_file = d / "spec.json"
                if spec_file.is_file():
                    try:
                        title = json.loads(spec_file.read_text()).get("title")
                    except (OSError, ValueError):
                        pass
                found.append({"run": d.name, "title": title, "mtime": tf.stat().st_mtime})
        return sorted(found, key=lambda r: r["mtime"], reverse=True)

    @app.get("/api/trace/{run}")
    def trace(run: str, after: int = 0) -> dict:
        """Steps of a run's mind trace; `after` returns only steps > it, so a
        viewer can poll and follow a live agent."""
        d = run_dir(run)
        out = read_trace(d, after=after)
        spec_meta = None
        spec_file = d / "spec.json"
        if spec_file.is_file():
            try:
                s = json.loads(spec_file.read_text())
                spec_meta = {
                    k: s.get(k) for k in ("id", "title", "conjecture", "latex", "quantifier")
                }
            except (OSError, ValueError):
                pass
        # Kernel outcome, straight from the artifacts on disk (never computed here).
        proof_meta, verdict = None, None
        proof_file = d / "proof.json"
        if proof_file.is_file():
            try:
                p = json.loads(proof_file.read_text())
                proof_meta = {
                    k: p.get(k) for k in ("method", "verified_by", "claim", "statement_review")
                }
            except (OSError, ValueError):
                pass
        answer_file = d / "answer.md"
        if answer_file.is_file():
            try:
                for line in answer_file.read_text().splitlines():
                    if line.startswith("## Verdict:"):
                        verdict = line.removeprefix("## Verdict:").strip()
                        break
            except OSError:
                pass
        return {"run": run, "spec": spec_meta, "proof": proof_meta, "verdict": verdict, **out}

    @app.get("/api/trace/{run}/render/{step}")
    def trace_render(run: str, step: int):
        """Server-side PNG of one step's scene graph (matplotlib, cached).
        Steps are append-only, so the cache never goes stale."""
        d = run_dir(run)
        cache = d / "trace_renders" / f"step_{step:03d}.png"
        if not cache.is_file():
            entry = next((s for s in read_trace(d)["steps"] if s.get("step") == step), None)
            if entry is None:
                raise HTTPException(404, f"no step {step} in this trace")
            scene = entry.get("scene") or []
            if not scene:
                raise HTTPException(404, "this step has no renderable scene")
            title = None
            spec_file = d / "spec.json"
            if spec_file.is_file():
                try:
                    title = json.loads(spec_file.read_text()).get("title")
                except (OSError, ValueError):
                    pass
            cache.parent.mkdir(exist_ok=True)
            mpl.render_png(scene, cache, title=title)
        return FileResponse(cache)

    @app.get("/api/trace/{run}/file/{path:path}")
    def trace_file(run: str, path: str):
        """Serve a file from inside one run dir only (e.g. looks/look_001.png)."""
        d = run_dir(run)
        f = (d / path).resolve()
        if not f.is_relative_to(d) or not f.is_file():
            raise HTTPException(404, "no such file in this run")
        return FileResponse(f)

    # -- agent sessions: the notebook's "Run" button -------------------------
    # One background thread runs formalize (for free-text conjectures) and the
    # embodied agent loop; the notebook streams the growing trace. One session
    # at a time — this is a single-user local tool.

    agent_jobs: dict[str, dict] = {}
    agent_active: dict[str, str | None] = {"run": None}

    def _default_runner(spec, out_dir, backend=None, max_turns=40, log=print, on_run=None):
        from .. import agent as agent_mod

        return agent_mod.run(
            spec, out_dir, backend=backend, max_turns=max_turns, log=log, on_run=on_run
        )

    runner = agent_runner or _default_runner

    @app.post("/api/agent/start")
    def agent_start(body: AgentStartBody) -> dict:
        if bool(body.problem_id) == bool(body.conjecture is not None and body.conjecture.strip()):
            raise HTTPException(422, "give exactly one of problem_id or conjecture")
        spec = None
        if body.problem_id:
            try:
                spec = get(body.problem_id)
            except KeyError as e:
                raise HTTPException(404, str(e)) from e
        max_turns = max(1, min(body.max_turns, 200))
        with lock:
            active = agent_active["run"]
            if active and agent_jobs.get(active, {}).get("status") in ("formalizing", "running"):
                raise HTTPException(409, f"an agent session is already running ({active})")
            base = f"agent-{spec.id if spec else 'conjecture'}"
            run, n = base, 1
            while (traces_root / run).exists() or run in agent_jobs:
                n += 1
                run = f"{base}-{n}"
            agent_jobs[run] = {
                "status": "formalizing" if spec is None else "running",
                "title": spec.title if spec else None,
                "log": [],
                "error": None,
                "proof": None,
                "cancel": False,      # stop requested (works even before the loop exists)
                "agent_run": None,    # live AgentRun handle, for cooperative stop
            }
            agent_active["run"] = run

        def job_log(msg) -> None:
            with lock:
                tail = agent_jobs[run]["log"]
                tail.append(str(msg)[:300])
                del tail[:-30]

        def register_run(agent_run) -> None:
            # Close the stop-vs-registration race: if stop arrived before the
            # loop existed, apply it the moment the handle appears.
            with lock:
                agent_jobs[run]["agent_run"] = agent_run
                cancelled = agent_jobs[run]["cancel"]
            if cancelled:
                agent_run.stop()

        def work() -> None:
            try:
                the_spec = spec
                if the_spec is None:
                    from ..llm import formalize

                    the_spec = formalize(body.conjecture, log=job_log)
                    with lock:
                        if agent_jobs[run]["cancel"]:
                            agent_jobs[run]["status"] = "stopped"
                            return
                        agent_jobs[run]["status"] = "running"
                        agent_jobs[run]["title"] = the_spec.title
                result = runner(
                    the_spec,
                    traces_root / run,
                    backend=body.backend,
                    max_turns=max_turns,
                    log=job_log,
                    on_run=register_run,
                )
                proof = getattr(result, "proof", None)
                with lock:
                    agent_jobs[run]["status"] = "stopped" if agent_jobs[run]["cancel"] else "done"
                    if proof is not None:
                        agent_jobs[run]["proof"] = {
                            "method": proof.method.value,
                            "verified_by": proof.verified_by,
                        }
            except Exception as e:  # noqa: BLE001 - job errors surface via status
                with lock:
                    agent_jobs[run]["status"] = "failed"
                    agent_jobs[run]["error"] = f"{type(e).__name__}: {e}"
            finally:
                with lock:
                    if agent_active["run"] == run:
                        agent_active["run"] = None

        threading.Thread(target=work, daemon=True).start()
        return {"run": run}

    @app.post("/api/agent/{run}/stop")
    def agent_stop(run: str) -> dict:
        """Cooperative stop: the loop winds down and finalize still records
        what the kernel established. Only sessions this server started can be
        stopped (CLI runs belong to their own process)."""
        with lock:
            job = agent_jobs.get(run)
            if job is None:
                raise HTTPException(404, "unknown agent job")
            if job["status"] not in ("formalizing", "running"):
                raise HTTPException(409, f"session is not running (status: {job['status']})")
            job["cancel"] = True
            job["status"] = "stopping"
            agent_run = job["agent_run"]
        if agent_run is not None:
            agent_run.stop()
        return {"run": run, "status": "stopping"}

    _STATUS_KEYS = ("status", "title", "log", "error", "proof")

    @app.get("/api/agent/{run}/status")
    def agent_status(run: str) -> dict:
        with lock:
            job = agent_jobs.get(run)
            if job is None:
                raise HTTPException(404, "unknown agent job")
            return {
                "run": run,
                **{k: (list(job[k]) if isinstance(job[k], list) else job[k]) for k in _STATUS_KEYS},
            }

    @app.get("/")
    def index():
        return FileResponse(_STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
    return app
