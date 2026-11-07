"""Design tokens and colour palettes shared by the renderer, figures and web app."""

from __future__ import annotations

import numpy as np

TOKENS = {
    "dark": {
        "bg": "#070910",
        "panel": "#101522",
        "panel_2": "#161D2E",
        "border": "#232C42",
        "cyan": "#00E5FF",
        "purple": "#A855F7",
        "pink": "#FF3CAC",
        "green": "#39FF88",
        "gold": "#FFD166",
        "text": "#F4F7FF",
        "text_2": "#95A3BA",
        "grid": "#1B2335",
    },
    "light": {
        "bg": "#F6F7FB",
        "panel": "#FFFFFF",
        "panel_2": "#EEF1F7",
        "border": "#D5DBE7",
        "cyan": "#0086A8",
        "purple": "#7C3AED",
        "pink": "#D61F7A",
        "green": "#0E9F5B",
        "gold": "#B7791F",
        "text": "#0E1424",
        "text_2": "#4B5870",
        "grid": "#E3E7F0",
    },
}


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


# Gradient stops (position, hex). Sampled with linear interpolation in RGB.
GRADIENTS = {
    "cyan": [(0, "#003B4D"), (0.6, "#00E5FF"), (1, "#E0FCFF")],
    "magenta": [(0, "#4A0033"), (0.6, "#FF3CAC"), (1, "#FFE0F2")],
    "purple": [(0, "#2A0E4F"), (0.6, "#A855F7"), (1, "#F1E4FF")],
    "rainbow": [(0, "#FF3CAC"), (0.17, "#FF7A45"), (0.33, "#FFD166"), (0.5, "#39FF88"), (0.67, "#00E5FF"),
                (0.83, "#5B7CFF"), (1, "#A855F7")],
    "fire": [(0, "#3D0000"), (0.35, "#C2185B"), (0.6, "#FF6D00"), (0.85, "#FFD166"), (1, "#FFF8E1")],
    "ice": [(0, "#0B1E3F"), (0.4, "#1E64C8"), (0.75, "#00E5FF"), (1, "#F0FDFF")],
    "plasma": [(0, "#0D0887"), (0.25, "#6A00A8"), (0.5, "#B12A90"), (0.75, "#E16462"), (0.9, "#FCA636"),
               (1, "#F0F921")],
    "mono": [(0, "#5A6378"), (1, "#FFFFFF")],
    "gold": [(0, "#4A3000"), (0.6, "#FFD166"), (1, "#FFF6DD")],
    # colour-blind-friendly sequential maps (perceptually uniform)
    "viridis": [(0, "#440154"), (0.25, "#3B528B"), (0.5, "#21918C"), (0.75, "#5EC962"), (1, "#FDE725")],
    "cividis": [(0, "#00224E"), (0.25, "#35456C"), (0.5, "#666970"), (0.75, "#A59C74"), (1, "#FEE838")],
}
COLORBLIND_SAFE = ("viridis", "cividis", "mono")


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


def distinct(n: int, palette: str = "rainbow") -> np.ndarray:
    """n colours spread evenly along a palette (for ensembles)."""
    return sample(palette, np.linspace(0, 1, n) if n > 1 else [0.6])


def tokens_css(theme: str = "dark") -> str:
    return "\n".join(f"  --{k.replace('_', '-')}: {v};" for k, v in TOKENS[theme].items())
