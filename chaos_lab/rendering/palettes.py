"""Monochrome design system shared by the renderer, figures and web app.

Chaos Lab uses a strictly black-and-white visual language: two themes
(``dark`` = white on black, ``light`` = black on white) and greyscale ramps.
Series are distinguished by tone and line style, never by hue, which also
makes every figure colour-blind safe and print friendly.
"""

from __future__ import annotations

import numpy as np

TOKENS = {
    "dark": {
        "bg": "#000000",
        "panel": "#000000",
        "panel_2": "#0E0E0E",
        "border": "#262626",
        "grid": "#161616",
        "text": "#F2F2F2",
        "text_2": "#8A8A8A",
        "fg": "#FFFFFF",  # primary marks
        "fg_2": "#B0B0B0",  # secondary series
        "fg_3": "#6B6B6B",  # tertiary series
        "fg_4": "#2E2E2E",  # backdrop curves
    },
    "light": {
        "bg": "#FFFFFF",
        "panel": "#FFFFFF",
        "panel_2": "#F4F4F4",
        "border": "#DADADA",
        "grid": "#EFEFEF",
        "text": "#0A0A0A",
        "text_2": "#6E6E6E",
        "fg": "#000000",
        "fg_2": "#4A4A4A",
        "fg_3": "#8F8F8F",
        "fg_4": "#D6D6D6",
    },
}

LINESTYLES = ("-", "--", ":", "-.")


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


# Greyscale ramps (position, hex), sampled with linear interpolation.
GRADIENTS = {
    "white": [(0, "#3C3C3C"), (1, "#FFFFFF")],  # trails on black: dim -> bright
    "silver": [(0, "#262626"), (1, "#C8C8C8")],  # softer trails on black
    "black": [(0, "#BDBDBD"), (1, "#000000")],  # trails on white: light -> ink
    "gray": [(0, "#000000"), (1, "#FFFFFF")],  # full ramp, for maps and data
}
THEME_TRAIL = {"dark": "white", "light": "black"}


def custom_gradient(hex_colors: list[str]) -> list[tuple[float, str]]:
    if len(hex_colors) < 2:
        raise ValueError("custom palette needs at least two colours")
    n = len(hex_colors) - 1
    return [(i / n, c) for i, c in enumerate(hex_colors)]


def sample(palette, values) -> np.ndarray:
    """Map values in [0, 1] to RGB floats (..., 3). ``palette`` is a name or stop list."""
    stops = GRADIENTS[palette] if isinstance(palette, str) else palette
    pos = np.array([s[0] for s in stops], dtype=float)
    cols = np.array([hex_to_rgb(s[1]) for s in stops])
    v = np.clip(np.asarray(values, dtype=float), 0.0, 1.0)
    return np.stack([np.interp(v, pos, cols[:, c]) for c in range(3)], axis=-1)


def distinct(n: int, theme: str = "dark") -> np.ndarray:
    """n tones for ensembles: from full contrast down to a mid grey."""
    lo, hi = (0.35, 1.0) if theme == "dark" else (0.0, 0.65)
    v = np.linspace(hi, lo, n) if theme == "dark" else np.linspace(lo, hi, n)
    return np.repeat(v[:, None], 3, axis=1) if n > 1 else np.array([[hi] * 3 if theme == "dark" else [lo] * 3])


def colormap(theme: str = "dark", name: str = "chaos_lab_mono"):
    """Matplotlib greyscale colormap whose low end blends into the background."""
    from matplotlib.colors import LinearSegmentedColormap

    stops = ["#111111", "#FFFFFF"] if theme == "dark" else ["#EEEEEE", "#000000"]
    return LinearSegmentedColormap.from_list(name, stops)


def tokens_css(theme: str = "dark") -> str:
    return "\n".join(f"  --{k.replace('_', '-')}: {v};" for k, v in TOKENS[theme].items())
