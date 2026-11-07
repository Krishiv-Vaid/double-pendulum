"""Matplotlib scientific figures in the Double Pendulum Simulator visual identity."""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg", force=False)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from pendulum_sim.rendering.palettes import TOKENS  # noqa: E402


def apply_theme(theme: str = "dark") -> dict:
    t = TOKENS[theme]
    plt.rcParams.update({
        "figure.facecolor": t["bg"],
        "axes.facecolor": t["panel"],
        "savefig.facecolor": t["bg"],
        "axes.edgecolor": t["border"],
        "axes.labelcolor": t["text_2"],
        "axes.titlecolor": t["text"],
        "axes.titlesize": 10.5,
        "axes.titleweight": "normal",
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.labelsize": 9,
        "axes.grid": True,
        "grid.color": t["grid"],
        "grid.linewidth": 0.5,
        "lines.linewidth": 1.2,
        "image.cmap": "gray",
        "xtick.color": t["text_2"],
        "ytick.color": t["text_2"],
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "text.color": t["text"],
        "legend.facecolor": t["panel_2"],
        "legend.edgecolor": t["border"],
        "legend.fontsize": 8,
        "font.family": "DejaVu Sans",
        # monochrome: series differ by tone (and explicit dashes where meaningful), never by hue
        "axes.prop_cycle": matplotlib.cycler(color=[t["fg"], t["fg_2"], t["fg_3"]]),
    })
    return t


def fig_to_image(fig, dpi: int = 100) -> Image.Image:
    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())
    return Image.fromarray(buf[..., :3].copy())


def fig_to_bytes(fig, fmt: str = "png", dpi: int = 150) -> bytes:
    b = io.BytesIO()
    fig.savefig(b, format=fmt, dpi=dpi, bbox_inches="tight")
    return b.getvalue()


def stamp(fig, text: str, theme: str = "dark"):
    """Small reproducibility stamp in the figure corner."""
    fig.text(0.995, 0.005, text, ha="right", va="bottom", fontsize=6, color=TOKENS[theme]["text_2"], alpha=0.8)
