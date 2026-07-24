"""View — atom #8 (detector): the output boundary.

The only layer that knows what "d dimensions" means on the way out. Views
render kernel state for perception — the agent's and the human's — and every
view returns (png_path, metadata) where the metadata carries the numbers the
picture summarizes (calibrated compression: the image is gestalt, the numbers
are truth). Pictures explain, never prove.

Kinds:
  identity   — the scene as-is (d<=3; the historical render)
  field      — margin painted over a 2D slice of configuration space
               (the Ansys lesson: the claim's landscape, zero-contour = the
               theorem's shape)
  sweep      — margin along ONE coordinate; zero crossings marked
  ghost      — before/after overlay (thought experiments, diffs)
  trajectory — margin vs journal step (the search's convergence plot)
"""
from __future__ import annotations

from .field import render_field
from .ghost import render_ghost
from .identity import render_identity
from .sweep import render_sweep
from .trajectory import render_trajectory

VIEW_KINDS = ("identity", "field", "sweep", "ghost", "trajectory")

__all__ = [
    "VIEW_KINDS", "render_identity", "render_field", "render_sweep",
    "render_ghost", "render_trajectory",
]
