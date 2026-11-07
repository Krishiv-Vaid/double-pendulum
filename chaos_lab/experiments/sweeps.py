"""Parameter sweeps (1D and 2D) with vectorized integration.

Physical parameters and initial conditions are broadcast as arrays through
the vectorized equations of motion, so a whole sweep is one batched RK4 run.
Numerical-setting sweeps (e.g. tolerance vs runtime) necessarily run one
simulation per value.
"""

from __future__ import annotations

import time
from dataclasses import replace

import numpy as np

from chaos_lab.core import physics
from chaos_lab.core.config import SimConfig
from chaos_lab.core.integrators import rk4_step
from chaos_lab.core.simulation import simulate

PHYSICAL_KEYS = ("m1", "m2", "L1", "L2", "g", "damping1", "damping2", "drive_amplitude", "drive_frequency")
INITIAL_KEYS = ("theta1_deg", "theta2_deg", "omega1", "omega2")
DERIVED_KEYS = ("mass_ratio", "length_ratio")  # m1/m2 at fixed m2; L1/L2 at fixed L2
OBSERVABLES = ("rotations", "first_flip", "max_omega", "max_speed", "final_energy")
MAX_POINTS = 250_000


def _apply(cfg: SimConfig, key: str, values: np.ndarray):
    """Return (Physical with array fields, initial-state array) for a sweep key."""
    phys = cfg.physical
    init = np.array(cfg.initial.state(), dtype=float)
    shape = values.shape
    state = np.broadcast_to(init, shape + (4,)).copy()
    if key in PHYSICAL_KEYS:
        phys = replace(phys, **{key: values})
    elif key == "mass_ratio":
        phys = replace(phys, m1=values * phys.m2)
    elif key == "length_ratio":
        phys = replace(phys, L1=values * phys.L2)
    elif key in INITIAL_KEYS:
        i = INITIAL_KEYS.index(key)
        state[..., i] = np.radians(values) if i < 2 else values
    else:
        raise ValueError(f"unknown sweep key {key!r}")
    return phys, state


def _run(phys, state, t_max, dt, observable):
    f = lambda t, s: physics.derivatives(t, s, phys)  # noqa: E731
    n = int(round(t_max / dt))
    y = state
    k_prev = np.floor((y[..., :2] + np.pi) / (2 * np.pi))
    rot = np.zeros(y.shape[:-1])
    first = np.full(y.shape[:-1], np.nan)
    mx = np.max(np.abs(y[..., 2:]), axis=-1)
    mxs = np.zeros(y.shape[:-1])
    for i in range(1, n + 1):
        y = rk4_step(f, (i - 1) * dt, y, dt)
        k = np.floor((y[..., :2] + np.pi) / (2 * np.pi))
        changed = np.sum(np.abs(k - k_prev), axis=-1)
        rot += changed
        first = np.where(np.isnan(first) & (changed > 0), i * dt, first)
        k_prev = k
        mx = np.maximum(mx, np.max(np.abs(y[..., 2:]), axis=-1))
        if observable == "max_speed":
            _, _, vx2, vy2 = physics.velocities(y, phys)
            mxs = np.maximum(mxs, np.hypot(vx2, vy2))
    return {
        "rotations": rot,
        "first_flip": first,
        "max_omega": mx,
        "max_speed": mxs,
        "final_energy": physics.total_energy(y, phys),
    }[observable]


def sweep(cfg: SimConfig, x_key: str, x_values, y_key: str | None = None, y_values=None,
          observable: str = "rotations", t_max: float | None = None, dt: float | None = None) -> dict:
    """1D sweep (y_key None) or 2D sweep returning observable values (ny, nx)."""
    if observable not in OBSERVABLES:
        raise ValueError(f"observable must be one of {OBSERVABLES}")
    t_max = t_max or cfg.numerics.t_max
    dt = dt or max(cfg.numerics.dt, 2e-3)
    xv = np.asarray(x_values, dtype=float)
    t0 = time.perf_counter()
    if y_key is None:
        phys, state = _apply(cfg, x_key, xv)
        vals = _run(phys, state, t_max, dt, observable)
    else:
        yv = np.asarray(y_values, dtype=float)
        if xv.size * yv.size > MAX_POINTS:
            raise ValueError(f"sweep too large (max {MAX_POINTS} points)")
        X, Y = np.meshgrid(xv, yv)
        phys, state = _apply(cfg, x_key, X)
        # apply the second key on top of the first
        if y_key in PHYSICAL_KEYS:
            phys = replace(phys, **{y_key: Y})
        elif y_key == "mass_ratio":
            phys = replace(phys, m1=Y * cfg.physical.m2)
        elif y_key == "length_ratio":
            phys = replace(phys, L1=Y * cfg.physical.L2)
        elif y_key in INITIAL_KEYS:
            i = INITIAL_KEYS.index(y_key)
            state[..., i] = np.radians(Y) if i < 2 else Y
        else:
            raise ValueError(f"unknown sweep key {y_key!r}")
        vals = _run(phys, state, t_max, dt, observable)
    return {"x_key": x_key, "x": xv, "y_key": y_key, "y": None if y_key is None else np.asarray(y_values, float),
            "observable": observable, "values": vals, "runtime_s": time.perf_counter() - t0, "t_max": t_max, "dt": dt}


def tolerance_sweep(cfg: SimConfig, method: str = "dop853", tolerances=(1e-4, 1e-6, 1e-8, 1e-10, 1e-12)) -> list[dict]:
    """Runtime, function evaluations and energy error versus solver tolerance."""
    rows = []
    for tol in tolerances:
        r = simulate(cfg.with_(**{"numerics.method": method, "numerics.rtol": tol, "numerics.atol": tol}))
        s = r.summary()
        rows.append({"tolerance": tol, "runtime_s": s["runtime_s"], "nfev": s["nfev"],
                     "max_abs_rel_energy_error": s["max_abs_rel_energy_error"]})
    return rows
