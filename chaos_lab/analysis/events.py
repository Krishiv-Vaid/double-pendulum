"""Event detection on sampled trajectories.

Definitions
-----------
Flip (complete rotation) of arm i: the arm passes over the top, i.e. its
*unwrapped* angle crosses an odd multiple of pi. The winding index
``k = floor((theta + pi) / (2 pi))`` changes by +-1 at each flip. Crossing
times are refined by linear interpolation between samples, so the sampling
interval must resolve the motion (the default 1/240 s does for typical runs).
"""

from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks

TWO_PI = 2.0 * np.pi


def winding_index(theta):
    return np.floor((np.asarray(theta) + np.pi) / TWO_PI).astype(np.int64)


def flip_events(t, y) -> list[dict]:
    """All over-the-top crossings of either arm: dicts with t, arm (1|2), direction (+1|-1)."""
    t = np.asarray(t)
    y = np.asarray(y)
    events = []
    for arm in (0, 1):
        th = y[:, arm]
        k = winding_index(th)
        idx = np.nonzero(np.diff(k))[0]
        for i in idx:
            step = int(np.sign(k[i + 1] - k[i]))
            # boundary crossed: theta = (2k+1) pi for the lower of the two indices
            kb = min(k[i], k[i + 1])
            target = (2 * kb + 1) * np.pi
            th0, th1 = th[i], th[i + 1]
            frac = 0.5 if th1 == th0 else float(np.clip((target - th0) / (th1 - th0), 0.0, 1.0))
            events.append({"t": float(t[i] + frac * (t[i + 1] - t[i])), "arm": arm + 1, "direction": step})
    events.sort(key=lambda e: e["t"])
    return events


def first_flip_time(t, y, arm: int | None = None) -> float:
    """Time of the first flip (either arm if ``arm`` is None); NaN if none."""
    for e in flip_events(t, y):
        if arm is None or e["arm"] == arm:
            return e["t"]
    return float("nan")


def rotation_counts(y) -> tuple[int, int]:
    """Number of flips of each arm over the whole trajectory."""
    y = np.asarray(y)
    return tuple(int(np.sum(np.abs(np.diff(winding_index(y[:, a]))))) for a in (0, 1))


def peak_events(t, signal, kind: str, top: int = 5, min_separation_s: float = 0.25) -> list[dict]:
    t = np.asarray(t)
    s = np.abs(np.asarray(signal))
    if len(t) < 3:
        return []
    dist = max(1, int(min_separation_s / max(t[1] - t[0], 1e-12)))
    idx, _ = find_peaks(s, distance=dist)
    idx = idx[np.argsort(s[idx])[::-1][:top]]
    return [{"t": float(t[i]), "kind": kind, "value": float(s[i])} for i in sorted(idx)]


def detect_events(result, top: int = 5) -> list[dict]:
    """Bookmarkable events for the replay timeline ("time machine")."""
    t, y = result.t, result.y
    out = []
    for e in flip_events(t, y):
        sign = "+" if e["direction"] > 0 else "-"
        out.append({"t": e["t"], "kind": "flip", "label": f"Arm {e['arm']} flip ({sign})"})
    speed = np.max(np.abs(y[:, 2:4]), axis=1)
    i = int(np.argmax(speed))
    out.append({"t": float(t[i]), "kind": "max_speed", "label": f"Max |omega| = {speed[i]:.2f} rad/s"})
    acc = np.max(np.abs(result.accelerations), axis=1)
    for e in peak_events(t, acc, "acceleration", top=top):
        out.append({"t": e["t"], "kind": "acceleration", "label": f"|alpha| peak {e['value']:.1f} rad/s^2"})
    err = result.relative_energy_error
    for e in peak_events(t, err, "energy_error", top=3):
        out.append({"t": e["t"], "kind": "energy_error", "label": f"Energy error peak {e['value']:.2e}"})
    out.sort(key=lambda e: e["t"])
    return out
