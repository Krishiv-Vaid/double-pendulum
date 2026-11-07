"""Poincaré sections of the double pendulum.

Surface of section: theta1 = 0 (mod 2 pi) crossed with omega1 > 0, i.e. the
upper rod swinging through the downward vertical counter-clockwise. Recorded
coordinates: (theta2 wrapped to [-pi, pi), omega2).

Crossings are located by root finding on the solver's dense output
(``solve_ivp`` events, DOP853 by default) on g(y) = sin(theta1) with positive
direction; crossings at theta1 = pi (where sin also increases if omega1 < 0)
are rejected by requiring cos(theta1) > 0. For conservative dynamics all
points of one trajectory lie on its energy surface, so sections are most
meaningful when trajectories share the same total energy (see
:func:`fixed_energy_initials`).
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import numpy as np

from chaos_lab.core import physics
from chaos_lab.core.config import Physical
from chaos_lab.core.integrators import integrate_adaptive


def _event(t, y):
    return np.sin(y[0])


_event.direction = 1.0


def section(p: Physical, y0, t_max: float = 200.0, method: str = "dop853", rtol: float = 1e-10,
            atol: float = 1e-10, max_points: int | None = None) -> dict:
    out = integrate_adaptive(lambda t, y: physics.derivatives(t, y, p), y0, t_max, method, rtol, atol,
                             t_eval=[], events=[_event])
    ye = np.asarray(out.y_events[0]).reshape(-1, 4)
    te = np.asarray(out.t_events[0])
    keep = np.cos(ye[:, 0]) > 0
    ye, te = ye[keep], te[keep]
    if max_points is not None:
        ye, te = ye[:max_points], te[:max_points]
    E = physics.total_energy(np.asarray(y0, dtype=float), p)
    return {
        "t": te.tolist(),
        "theta2": physics.wrap_angle(ye[:, 1]).tolist(),
        "omega2": ye[:, 3].tolist(),
        "energy": float(E),
        "energy_drift": float(np.max(np.abs(physics.total_energy(ye, p) - E))) if len(ye) else 0.0,
        "nfev": out.nfev,
        "runtime_s": out.runtime,
        "success": out.success,
    }


def fixed_energy_initials(p: Physical, energy: float, theta2_values, omega2_values=None) -> list[list[float]]:
    """Initial states on the section (theta1 = 0, omega1 > 0) at a fixed total energy.

    For each (theta2, omega2) pair omega1 is solved from E = T + V; pairs for
    which the energy is unreachable are skipped."""
    th2 = np.asarray(theta2_values, dtype=float)
    om2 = np.zeros_like(th2) if omega2_values is None else np.asarray(omega2_values, dtype=float)
    w1 = physics.energy_for_omega1(0.0 * th2, th2, om2, energy, p)
    return [[0.0, float(a), float(w), float(b)] for a, b, w in zip(th2, om2, w1) if np.isfinite(w) and w > 0]


def _section_job(args):
    p, y0, t_max, kw = args
    return section(p, y0, t_max, **kw)


def multi_section(p: Physical, initials, t_max: float = 200.0, workers: int | None = None, **kw) -> list[dict]:
    """Sections for several initial conditions, computed in parallel processes."""
    jobs = [(p, y0, t_max, kw) for y0 in initials]
    if len(jobs) <= 1 or workers == 1:
        return [_section_job(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(_section_job, jobs))
