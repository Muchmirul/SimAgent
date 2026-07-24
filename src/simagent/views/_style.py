"""Shared view styling: ONE calibrated visual language for every margin plot.

The colormap contract (fixed repo-wide, the Ansys legend discipline):
diverging, centered at margin = 0 — red = FAILS (margin < 0), blue = HOLDS
(margin > 0). Every field/sweep view uses these constants so the agent's
vision channel is a calibrated instrument, not decoration.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # offline; never require a display
import matplotlib.pyplot as plt  # noqa: E402

BG = "#101014"
FG = "#e8eaed"
DIM = "#9aa0a6"
CMAP = "RdBu"  # with symmetric vmin/vmax: negative margin = red, positive = blue
ZERO_CONTOUR = "#f2c14e"
MARKER_CURRENT = "#2ecc71"
MARKER_MIN = "#e74c3c"


def dark_figure(figsize=(6.4, 5.2)):
    fig, ax = plt.subplots(figsize=figsize, facecolor=BG)
    ax.set_facecolor(BG)
    ax.tick_params(colors=DIM, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#26262e")
    return fig, ax


def finish(fig, out_path, title=None):
    if title:
        fig.suptitle(title, color=FG, fontsize=11)
    fig.savefig(out_path, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)
