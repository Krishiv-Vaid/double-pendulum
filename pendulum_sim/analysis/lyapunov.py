"""Finite-time largest Lyapunov exponent (Benettin et al. 1980).

Two estimators share one interface:

* ``tangent`` (default): integrates the variational equations
  dv/dt = J(y) v alongside the trajectory, using complex-step Jacobian-vector
  products (exact to rounding), and renormalizes v every ``renorm_interval``.
  No finite-perturbation saturation.
* ``two_trajectory``: integrates a reference and a perturbed copy separated by
  ``d0`` and rescales the separation back to ``d0`` every interval. Angular
  differences are wrapped to [-pi, pi).

Norm: Euclidean in (theta1, theta2, tau*omega1, tau*omega2) with
tau = sqrt(L1/g) by default, i.e. a dimensionless state space. The asymptotic
exponent is norm-independent; finite-time estimates are not, which is one of
the reasons a finite-time value must be read as an estimate, not a constant
of nature.

lambda_T = (1/T) sum_k ln(d_k / d0)   [1/s]
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np

from pendulum_sim.core.integrators import rk4_step


@dataclass
class LyapunovResult:
    t: np.ndarray  # renormalization times (s)
    running: np.ndarray  # running estimate lambda(t) (1/s)
    local: np.ndarray  # local stretching rates ln(d_k/d0)/interval (1/s)
    lam: float  # final estimate (1/s)
    method: str
    dt: float
    renorm_interval: float
    d0: float

    def predictability_horizon(self, delta0: float, delta_max: float) -> float:
        """Time for an initial uncertainty delta0 to grow to delta_max assuming
        exponential growth at rate lambda: T = ln(delta_max/delta0)/lambda.
        Infinite for lambda <= 0. Same norm as the estimator."""
        if self.lam <= 0:
            return float("inf")
        return float(np.log(delta_max / delta0) / self.lam)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("t", "running", "local"):
            d[k] = d[k].tolist()
        return d


def complex_step_jvp(f: Callable, t, y, v, h: float = 1e-30):
    return np.imag(f(t, np.asarray(y, dtype=complex) + 1j * h * np.asarray(v))) / h


def largest_lyapunov(
    f: Callable,
    y0,
    t_max: float,
    dt: float = 1e-3,
    renorm_interval: float = 0.1,
    d0: float = 1e-8,
    method: str = "tangent",
    weights=None,
    wrap: tuple[int, ...] = (),
    transient: float = 0.0,
    seed: int = 0,
    callback: Callable[[float], bool] | None = None,
) -> LyapunovResult:
    """Estimate the largest Lyapunov exponent of dy/dt = f(t, y).

    ``weights`` scales each state component in the norm; ``wrap`` lists
    components that are angles (differences wrapped, two-trajectory only).
    ``transient`` seconds are integrated first and excluded from the average.
    """
    y = np.array(y0, dtype=float)
    dim = y.size
    w = np.ones(dim) if weights is None else np.asarray(weights, dtype=float)
    steps_per = max(1, int(round(renorm_interval / dt)))
    interval = steps_per * dt
    n_int = int(t_max / interval)
    if n_int < 1:
        raise ValueError("t_max must exceed one renormalization interval")

    t = 0.0
    n_tr = int(round(transient / dt))
    for _ in range(n_tr):
        y = rk4_step(f, t, y, dt)
        t += dt

    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim)
    v /= np.linalg.norm(v * w)

    def wnorm(d):
        return float(np.linalg.norm(d * w))

    def diff(a, b):
        d = a - b
        for i in wrap:
            d[i] = (d[i] + np.pi) % (2 * np.pi) - np.pi
        return d

    if method == "tangent":
        def aug(tt, z):
            yy, vv = z[:dim], z[dim:]
            return np.concatenate([f(tt, yy), complex_step_jvp(f, tt, yy, vv)])

        z = np.concatenate([y, v])
    elif method == "two_trajectory":
        yb = y + d0 * v
    else:
        raise ValueError("method must be 'tangent' or 'two_trajectory'")

    logs = np.empty(n_int)
    times = np.empty(n_int)
    for k in range(n_int):
        for _ in range(steps_per):
            if method == "tangent":
                z = rk4_step(aug, t, z, dt)
            else:
                y_new = rk4_step(f, t, y, dt)
                yb = rk4_step(f, t, yb, dt)
                y = y_new
            t += dt
        if method == "tangent":
            g = wnorm(z[dim:])
            z[dim:] /= g
            logs[k] = np.log(g)
        else:
            d = diff(yb, y)
            g = wnorm(d)
            logs[k] = np.log(g / d0)
            yb = y + d * (d0 / g)
        times[k] = t
        if not np.isfinite(logs[k]):
            raise FloatingPointError(f"non-finite separation at t={t:.4g}s")
        if callback is not None and callback(k / n_int):
            logs, times = logs[: k + 1], times[: k + 1]
            break

    elapsed = times - (n_tr * dt)
    running = np.cumsum(logs) / elapsed
    return LyapunovResult(times, running, logs / interval, float(running[-1]), method, dt, interval, d0)


def double_pendulum_lyapunov(cfg, t_max: float | None = None, **kw) -> LyapunovResult:
    """Convenience wrapper using the double pendulum vector field and the
    dimensionless norm (theta, theta, tau omega, tau omega)."""
    from pendulum_sim.core import physics

    p = cfg.physical
    tau = physics.natural_time_scale(p)
    kw.setdefault("dt", min(cfg.numerics.dt, 2e-3))
    return largest_lyapunov(
        lambda t, y: physics.derivatives(t, y, p),
        cfg.initial.state(),
        t_max if t_max is not None else cfg.numerics.t_max,
        weights=(1.0, 1.0, tau, tau),
        wrap=(0, 1),
        **kw,
    )


def sensitivity_scan(cfg, t_max: float, d0s=(1e-10, 1e-8, 1e-6), intervals=(0.05, 0.1, 0.5), dt=2e-3):
    """Estimate lambda across estimator settings (two-trajectory d0 and
    renormalization interval) plus the tangent method, to expose how much the
    finite-time value depends on choices that should not matter asymptotically."""
    rows = []
    for d0 in d0s:
        for iv in intervals:
            r = double_pendulum_lyapunov(cfg, t_max, dt=dt, renorm_interval=iv, d0=d0, method="two_trajectory")
            rows.append({"method": "two_trajectory", "d0": d0, "renorm_interval": r.renorm_interval, "lambda": r.lam})
    for iv in intervals:
        r = double_pendulum_lyapunov(cfg, t_max, dt=dt, renorm_interval=iv, method="tangent")
        rows.append({"method": "tangent", "d0": None, "renorm_interval": r.renorm_interval, "lambda": r.lam})
    lams = np.array([r["lambda"] for r in rows])
    return {"rows": rows, "mean": float(lams.mean()), "std": float(lams.std(ddof=1)), "min": float(lams.min()),
            "max": float(lams.max())}


def lorenz(t, y, sigma=10.0, rho=28.0, beta=8.0 / 3.0):
    """Lorenz-63 vector field (validation system; lambda_max ~ 0.9056)."""
    x, yy, z = y[..., 0], y[..., 1], y[..., 2]
    return np.stack([sigma * (yy - x), x * (rho - z) - yy, x * yy - beta * z], axis=-1)
