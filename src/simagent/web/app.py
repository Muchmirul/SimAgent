"""FastAPI backend for the browser sandbox.

Single-user local tool: one live SandboxSession, mutated by the endpoints, all
of which return the full authoritative state. Manim renders run as background
jobs (they take seconds to minutes) and are polled by the frontend.
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..library import all_specs, get
from ..spec import ProblemSpec
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


def create_app(out_root: str = "runs/web") -> FastAPI:
    app = FastAPI(title="SimAgent sandbox")
    sessions: dict[str, SandboxSession] = {}
    jobs: dict[str, dict] = {}
    lock = threading.Lock()

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

    @app.get("/")
    def index():
        return FileResponse(_STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
    return app
