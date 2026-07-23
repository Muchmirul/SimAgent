"""Scene graph: the shared visual language between the sandbox and renderers.

A scene is a list of primitive dicts. Spec `build_scene` code creates them via
the constructors below; both the matplotlib renderer and the generated Manim
scene consume the same JSON, so a witness found by the search renders
identically everywhere. 2D inputs are lifted to z = 0.
"""
from __future__ import annotations


def _pt3(p) -> list[float]:
    p = [float(x) for x in p]
    while len(p) < 3:
        p.append(0.0)
    return p[:3]


def _pts3(coords) -> list[list[float]]:
    return [_pt3(p) for p in coords]


def points(coords, color: str = "#ffffff", radius: float = 0.05, name: str | None = None) -> dict:
    return {"type": "points", "coords": _pts3(coords), "color": color, "radius": radius, "name": name}


def segments(pairs, color: str = "#9aa0a6", width: float = 2.0) -> dict:
    return {"type": "segments", "pairs": [[_pt3(a), _pt3(b)] for a, b in pairs], "color": color, "width": width}


def polygon(coords, color: str = "#4a90d9", opacity: float = 0.35) -> dict:
    return {"type": "polygon", "coords": _pts3(coords), "color": color, "opacity": opacity}


def mesh(vertices, faces, color: str = "#4a90d9", opacity: float = 0.3) -> dict:
    return {
        "type": "mesh",
        "vertices": _pts3(vertices),
        "faces": [[int(i) for i in f] for f in faces],
        "color": color,
        "opacity": opacity,
    }


def sphere(center, radius: float, color: str = "#f2c14e", opacity: float = 0.12) -> dict:
    return {"type": "sphere", "center": _pt3(center), "radius": float(radius), "color": color, "opacity": opacity}


def label(text: str) -> dict:
    return {"type": "label", "text": str(text)}


def bounds(scene: list[dict]) -> tuple[float, float]:
    """(lo, hi) cube bounds covering all geometry in the scene."""
    xs: list[float] = []
    for prim in scene:
        if prim["type"] == "points":
            for p in prim["coords"]:
                xs.extend(p)
        elif prim["type"] == "segments":
            for a, b in prim["pairs"]:
                xs.extend(a)
                xs.extend(b)
        elif prim["type"] == "polygon":
            for p in prim["coords"]:
                xs.extend(p)
        elif prim["type"] == "mesh":
            for p in prim["vertices"]:
                xs.extend(p)
        elif prim["type"] == "sphere":
            c, r = prim["center"], prim["radius"]
            xs.extend([v - r for v in c])
            xs.extend([v + r for v in c])
    if not xs:
        return -1.0, 1.0
    lo, hi = min(xs), max(xs)
    pad = 0.1 * max(hi - lo, 1e-6)
    return lo - pad, hi + pad
