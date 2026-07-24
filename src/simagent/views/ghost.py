"""Ghost view: before/after overlay — the deformed-shape plot of CAE.

The base scene renders desaturated and translucent behind the hypothetical
(or new) scene at full strength. Used by imagination ("what would it look
like if…") and by diff replays.
"""
from __future__ import annotations

from pathlib import Path

from ..visualize import mpl

_GHOST_COLOR = "#5a5f68"


def _ghosted(prims: list[dict]) -> list[dict]:
    out = []
    for prim in prims:
        p = dict(prim)
        if p.get("type") == "label":
            continue  # only the live scene labels
        if "color" in p:
            p["color"] = _GHOST_COLOR
        if "opacity" in p:
            p["opacity"] = max(float(p["opacity"]) * 0.35, 0.04)
        elif p.get("type") in ("points", "segments"):
            p["opacity"] = 0.3
        out.append(p)
    return out


def render_ghost(base_scene: list[dict], scene: list[dict], out_path,
                 title: str | None = None) -> tuple[str, dict]:
    if not scene:
        raise ValueError("hypothetical scene is empty (degenerate configuration?)")
    combined = _ghosted(base_scene or []) + scene
    path = mpl.render_png(combined, Path(out_path), title=title)
    return str(path), {
        "kind": "ghost",
        "base_primitives": len(base_scene or []),
        "primitives": len(scene),
    }
