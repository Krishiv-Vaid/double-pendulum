"""Numerical integrators.

* :func:`rk4_step` / :func:`integrate_rk4` — classical fixed-step 4th-order
  Runge–Kutta, vectorized over any leading batch shape. Used for animation,
  ensembles and chaos maps.
* :func:`integrate_adaptive` — SciPy's embedded Runge–Kutta pairs RK45
  (Dormand–Prince 5(4)) and DOP853 (8(5,3)) with dense output and event
  location. Used for high-accuracy references and Poincaré sections.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp

Field = Callable[[float, np.ndarray], np.ndarray]


def rk4_step(f: Field, t: float, y: np.ndarray, dt: float) -> np.ndarray:
    k1 = f(t, y)
    k2 = f(t + 0.5 * dt, y + 0.5 * dt * k1)
    k3 = f(t + 0.5 * dt, y + 0.5 * dt * k2)
    k4 = f(t + dt, y + dt * k3)
    return y + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


@dataclass
class IntegrationOutput:
    t: np.ndarray
    y: np.ndarray  # shape (n_samples, ..., dim)
    nfev: int
    runtime: float
    success: bool = True
    message: str = ""
    t_events: list | None = None
    y_events: list | None = None


def integrate_rk4(
    f: Field,
    y0,
    t_max: float,
    dt: float,
    output_every: int = 1,
    callback: Callable[[int, int], bool] | None = None,
) -> IntegrationOutput:
    """Fixed-step RK4 from t=0 to t_max, storing every ``output_every`` steps.

    ``callback(step, n_steps)`` may return True to cancel (checked every 1000 steps).
    Non-finite states stop the integration and are reported, never hidden.
    """
    y = np.array(y0, dtype=float)
    n = int(round(t_max / dt))
    if n < 1:
        raise ValueError("t_max must be at least one step")
    n_out = n // output_every + 1
    out = np.empty((n_out,) + y.shape)
    out[0] = y
    t0 = time.perf_counter()
    k = 1
    success, message = True, "completed"
    for i in range(1, n + 1):
        y = rk4_step(f, (i - 1) * dt, y, dt)
        if i % output_every == 0:
            out[k] = y
            k += 1
        if i % 1000 == 0:
            if not np.all(np.isfinite(y)):
                success, message = False, f"non-finite state at t={i * dt:.6g}s"
                break
            if callback is not None and callback(i, n):
                success, message = False, "cancelled"
                break
    if not np.all(np.isfinite(y)):
        success, message = False, "non-finite state"
    out = out[:k]
    t = np.arange(k) * dt * output_every
    return IntegrationOutput(t, out, nfev=4 * (k - 1) * output_every, runtime=time.perf_counter() - t0,
                             success=success, message=message)


def integrate_adaptive(
    f: Field,
    y0,
    t_max: float,
    method: str = "DOP853",
    rtol: float = 1e-10,
    atol: float = 1e-10,
    t_eval=None,
    events=None,
    max_step: float = np.inf,
) -> IntegrationOutput:
    """Adaptive embedded Runge–Kutta integration via ``scipy.integrate.solve_ivp``."""
    method = {"rk45": "RK45", "dop853": "DOP853"}.get(method.lower(), method)
    t0 = time.perf_counter()
    sol = solve_ivp(
        f,
        (0.0, t_max),
        np.asarray(y0, dtype=float),
        method=method,
        t_eval=t_eval,
        rtol=rtol,
        atol=atol,
        events=events,
        max_step=max_step,
    )
    ys = np.asarray(sol.y, dtype=float)
    ys = ys.T if ys.size else np.empty((0, np.size(y0)))
    return IntegrationOutput(
        t=np.asarray(sol.t, dtype=float),
        y=ys,
        nfev=int(sol.nfev),
        runtime=time.perf_counter() - t0,
        success=bool(sol.success),
        message=str(sol.message),
        t_events=sol.t_events,
        y_events=sol.y_events,
    )


def integrate_rk4_double_pendulum(p, y0, t_max: float, dt: float, output_every: int = 1,
                                  callback=None) -> IntegrationOutput:
    """Fast path: RK4 for a *single* double pendulum using Python floats.

    On a 4-element state NumPy's per-call overhead dominates, so plain float
    arithmetic is ~20x faster (measured: see benchmarks/results.md). The equations are the same as
    :func:`chaos_lab.core.physics.derivatives` (the test suite pins the two
    implementations to agree to ~1e-12).
    """
    m1, m2, L1, L2, g = float(p.m1), float(p.m2), float(p.L1), float(p.L2), float(p.g)
    b1, b2 = float(p.damping1), float(p.damping2)
    A, Om, ph = float(p.drive_amplitude), float(p.drive_frequency), float(p.drive_phase)
    M = m1 + m2
    sin, cos = math.sin, math.cos

    def f(t, a, b, w1, w2):
        d = a - b
        c, s = cos(d), sin(d)
        rel = w2 - w1
        q1 = -b1 * w1 + b2 * rel + (A * cos(Om * t + ph) if A else 0.0)
        q2 = -b2 * rel
        r1 = -m2 * L2 * w2 * w2 * s - M * g * sin(a) + q1 / L1
        r2 = L1 * w1 * w1 * s - g * sin(b) + q2 / (m2 * L2)
        bb = m2 * L2 * c
        cc = L1 * c
        aa = M * L1
        det = aa * L2 - bb * cc
        return w1, w2, (r1 * L2 - bb * r2) / det, (aa * r2 - cc * r1) / det

    n = int(round(t_max / dt))
    if n < 1:
        raise ValueError("t_max must be at least one step")
    th1, th2, w1, w2 = (float(v) for v in y0)
    n_out = n // output_every + 1
    out = np.empty((n_out, 4))
    out[0] = (th1, th2, w1, w2)
    h2, h6 = 0.5 * dt, dt / 6.0
    k = 1
    success, message = True, "completed"
    t0 = time.perf_counter()
    for i in range(1, n + 1):
        t = (i - 1) * dt
        a1, a2, a3, a4 = f(t, th1, th2, w1, w2)
        b1_, b2_, b3_, b4_ = f(t + h2, th1 + h2 * a1, th2 + h2 * a2, w1 + h2 * a3, w2 + h2 * a4)
        c1, c2, c3, c4 = f(t + h2, th1 + h2 * b1_, th2 + h2 * b2_, w1 + h2 * b3_, w2 + h2 * b4_)
        d1, d2, d3, d4 = f(t + dt, th1 + dt * c1, th2 + dt * c2, w1 + dt * c3, w2 + dt * c4)
        th1 += h6 * (a1 + 2 * b1_ + 2 * c1 + d1)
        th2 += h6 * (a2 + 2 * b2_ + 2 * c2 + d2)
        w1 += h6 * (a3 + 2 * b3_ + 2 * c3 + d3)
        w2 += h6 * (a4 + 2 * b4_ + 2 * c4 + d4)
        if i % output_every == 0:
            out[k] = (th1, th2, w1, w2)
            k += 1
        if i % 1000 == 0:
            if not (math.isfinite(th1) and math.isfinite(th2) and math.isfinite(w1) and math.isfinite(w2)):
                success, message = False, f"non-finite state at t={i * dt:.6g}s"
                break
            if callback is not None and callback(i, n):
                success, message = False, "cancelled"
                break
    out = out[:k]
    return IntegrationOutput(np.arange(k) * dt * output_every, out, nfev=4 * (k - 1) * output_every,
                             runtime=time.perf_counter() - t0, success=success, message=message)
