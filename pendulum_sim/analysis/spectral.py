"""Exploratory frequency and recurrence analysis.

Broadband spectra are *consistent with* chaos but do not prove it (noise and
quasi-periodic motion with many frequencies also look broadband).
"""

from __future__ import annotations

import numpy as np

from pendulum_sim.core.physics import state_distance


def spectrum(signal, dt: float) -> dict:
    """One-sided amplitude spectrum with a Hann window. Frequencies in Hz."""
    x = np.asarray(signal, dtype=float)
    x = x - x.mean()
    win = np.hanning(len(x))
    X = np.fft.rfft(x * win)
    f = np.fft.rfftfreq(len(x), dt)
    amp = 2.0 * np.abs(X) / np.sum(win)
    return {"frequency_hz": f, "amplitude": amp}


def recurrence_matrix(y, threshold: float = 0.3, time_scale: float = 1.0, max_points: int = 600):
    """Boolean recurrence matrix R_ij = |y_i - y_j| < threshold using the wrapped,
    dimensionless state distance; the trajectory is uniformly downsampled to at
    most ``max_points`` samples. Returns (indices, R)."""
    y = np.asarray(y)
    idx = np.linspace(0, len(y) - 1, min(max_points, len(y))).astype(int)
    ys = y[idx]
    D = state_distance(ys[:, None, :], ys[None, :, :], time_scale)
    return idx, D < threshold
