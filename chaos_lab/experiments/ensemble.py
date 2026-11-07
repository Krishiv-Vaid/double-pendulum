"""Vectorized ensembles and the Butterfly Effect experiment.

Separation metric
-----------------
For member k against the unperturbed reference (member 0):

    d_k(t) = || (wrap(dtheta1), wrap(dtheta2), tau*domega1, tau*domega2) ||_2

with tau = sqrt(L1/g) (dimensionless). We also report the Cartesian distance
between the lower masses in metres, which is what the eye sees.

Physical sensitivity vs numerical error
---------------------------------------
Perturbing the initial condition by epsilon probes *physical* sensitivity.
To show that the observed divergence is not an integration artefact,
:func:`butterfly` also integrates the reference at dt and dt/2 and reports
their separation ("numerical control"). Physical divergence is only
meaningful while it stays well above that curve.
"""

from __future__ import annotations

import time

import numpy as np

from chaos_lab.core import physics
from chaos_lab.core.config import SimConfig
from chaos_lab.core.integrators import rk4_step

VARIABLES = {"theta1": 0, "theta2": 1, "omega1": 2, "omega2": 3}


def integrate_batch(p, y0, t_max: float, dt: float, output_dt: float, callback=None):
    """Fixed-step RK4 for a batch of states y0 (N, 4). Returns t (T,), Y (T, N, 4)."""
    y = np.array(y0, dtype=float)
    every = max(1, int(round(output_dt / dt)))
    n = int(round(t_max / dt))
    n_out = n // every + 1
    out = np.empty((n_out,) + y.shape)
    out[0] = y
    f = lambda t, s: physics.derivatives(t, s, p)  # noqa: E731
    k = 1
    for i in range(1, n + 1):
        y = rk4_step(f, (i - 1) * dt, y, dt)
        if i % every == 0:
            out[k] = y
            k += 1
            if callback is not None and callback(i / n):
                break
    if not np.all(np.isfinite(out[:k])):
        raise FloatingPointError("non-finite state in ensemble integration")
    return np.arange(k) * dt * every, out[:k]


def perturbations(n: int, epsilon: float, distribution: str = "linear", seed: int = 0) -> np.ndarray:
    """Offsets for n members; member 0 is always exactly 0 (the reference)."""
    if n < 2:
        raise ValueError("need at least 2 members")
    if distribution == "linear":
        return epsilon * np.arange(n) / (n - 1)
    if distribution == "gaussian":
        rng = np.random.default_rng(seed)
        off = rng.normal(0.0, epsilon, n)
        off[0] = 0.0
        return off
    raise ValueError("distribution must be 'linear' or 'gaussian'")


def butterfly(
    cfg: SimConfig,
    n: int = 10,
    epsilon: float = 1e-6,
    variable: str = "theta1",
    distribution: str = "linear",
    seed: int = 0,
    threshold: float = 0.5,
    numerical_control: bool = True,
    max_members: int = 2000,
    callback=None,
) -> dict:
    """Run n nearly identical pendulums. ``epsilon`` is in rad (angles) or rad/s."""
    if not 2 <= n <= max_members:
        raise ValueError(f"n must be between 2 and {max_members}")
    cfg.validate()
    p = cfg.physical
    num = cfg.numerics
    base = np.array(cfg.initial.state())
    y0 = np.tile(base, (n, 1))
    y0[:, VARIABLES[variable]] += perturbations(n, epsilon, distribution, seed)
    t0 = time.perf_counter()
    t, Y = integrate_batch(p, y0, num.t_max, num.dt, num.output_dt, callback)
    runtime = time.perf_counter() - t0
    tau = physics.natural_time_scale(p)
    sep = physics.state_distance(Y, Y[:, :1, :], tau)  # (T, N)
    _, _, x2, y2 = physics.positions(Y, p)
    cart = np.hypot(x2 - x2[:, :1], y2 - y2[:, :1])
    div_t = []
    for k in range(1, n):
        idx = np.nonzero(sep[:, k] > threshold)[0]
        div_t.append(float(t[idx[0]]) if len(idx) else None)
    valid = [d for d in div_t if d is not None]
    out = {
        "t": t,
        "Y": Y,
        "separation": sep,
        "cartesian_separation": cart,
        "divergence_times": div_t,
        "threshold": threshold,
        "time_scale": tau,
        "runtime_s": runtime,
        "steps_per_second": n * num.t_max / num.dt / max(runtime, 1e-9),
        "stats": {
            "members": n,
            "diverged": len(valid),
            "median_divergence_time": float(np.median(valid)) if valid else None,
            "min_divergence_time": float(np.min(valid)) if valid else None,
            "final_spread_m": float(np.std(np.stack([x2[-1], y2[-1]]), axis=1).mean()),
        },
    }
    if numerical_control:
        # dt/2 run sampled at exactly the same physical times (2x the stride in steps)
        every = max(1, int(round(num.output_dt / num.dt)))
        _, Yh = integrate_batch(p, base[None, :], num.t_max, num.dt / 2, every * num.dt)
        m = min(len(Yh), len(Y))
        out["numerical_control"] = physics.state_distance(Yh[:m, 0], Y[:m, 0], tau)
    return out
