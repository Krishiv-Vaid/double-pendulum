"""Integrator laboratory: RK4 vs RK45 vs DOP853.

Accuracy is measured two ways:
* energy drift (conservative runs) — a necessary, not sufficient, check;
* final-state difference from a tight DOP853 reference (rtol = atol = 1e-13).

For chaotic trajectories even tiny differences eventually grow exponentially,
so a large final-state difference after a long time is expected and does not by
itself mean an integrator is wrong; compare over horizons shorter than the
predictability time, and look at convergence as settings are refined.
"""

from __future__ import annotations

import numpy as np

from chaos_lab.core import physics
from chaos_lab.core.config import SimConfig
from chaos_lab.core.simulation import simulate

DEFAULT_SETTINGS = (
    {"method": "rk4", "dt": 0.01},
    {"method": "rk4", "dt": 0.001},
    {"method": "rk45", "rtol": 1e-6, "atol": 1e-9},
    {"method": "rk45", "rtol": 1e-10, "atol": 1e-10},
    {"method": "dop853", "rtol": 1e-8, "atol": 1e-10},
    {"method": "dop853", "rtol": 1e-12, "atol": 1e-12},
)


def reference(cfg: SimConfig):
    return simulate(cfg.with_(**{"numerics.method": "dop853", "numerics.rtol": 1e-13, "numerics.atol": 1e-13}))


def compare(cfg: SimConfig, settings=DEFAULT_SETTINGS, keep_trajectories: bool = False) -> dict:
    ref = reference(cfg)
    tau = physics.natural_time_scale(cfg.physical)
    rows = []
    trajectories = {}
    for s in settings:
        changes = {f"numerics.{k}": v for k, v in s.items()}
        r = simulate(cfg.with_(**changes))
        m = min(len(r.t), len(ref.t))
        dist = physics.state_distance(r.y[:m], ref.y[:m], tau)
        label = s["method"].upper() + (f" dt={s['dt']:g}" if s["method"] == "rk4" else f" rtol={s['rtol']:g}")
        rows.append({
            "label": label,
            **s,
            "runtime_s": r.runtime,
            "nfev": r.nfev,
            "max_abs_rel_energy_error": float(np.max(np.abs(r.relative_energy_error))),
            "final_state_difference": float(dist[-1]),
            "max_state_difference": float(np.max(dist)),
            "success": r.success,
        })
        if keep_trajectories:
            trajectories[label] = {"t": r.t, "y": r.y, "energy_error": r.relative_energy_error, "distance": dist}
    return {"rows": rows, "reference_nfev": ref.nfev, "trajectories": trajectories, "reference": ref}


def rk4_convergence(cfg: SimConfig, dts=(0.008, 0.004, 0.002, 0.001), t_max: float = 5.0) -> dict:
    """Observed order of accuracy of RK4 from the final-state error vs a DOP853 reference.

    The horizon is kept short so trajectory divergence does not mask the
    truncation error. Expected slope ~ 4."""
    base = cfg.with_(**{"numerics.t_max": t_max, "numerics.output_dt": max(dts)})
    ref = reference(base)
    errs = []
    for dt in dts:
        r = simulate(base.with_(**{"numerics.method": "rk4", "numerics.dt": dt}))
        errs.append(float(np.linalg.norm(r.y[-1] - ref.y[-1])))
    slope = np.polyfit(np.log(dts), np.log(errs), 1)[0]
    return {"dt": list(dts), "error": errs, "observed_order": float(slope)}
