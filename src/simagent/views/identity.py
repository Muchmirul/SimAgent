"""Identity view: the scene graph rendered as-is (d<=3)."""
from __future__ import annotations

from pathlib import Path

from ..visualize import mpl


def render_identity(scene: list[dict], out_path, title: str | None = None) -> tuple[str, dict]:
    if not scene:
        raise ValueError("scene is empty (degenerate configuration?)")
    path = mpl.render_png(scene, Path(out_path), title=title)
    return str(path), {"kind": "identity", "primitives": len(scene)}
