"""High-level simulation driver: config in, :class:`Result` with diagnostics out."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

import numpy as np

from pendulum_sim.core import physics
from pendulum_sim.core.config import SimConfig
from pendulum_sim.core.integrators import integrate_adaptive, integrate_rk4_double_pendulum


@dataclass
class Result:
    config: SimConfig
    t: np.ndarray  # physical time of each sample (s)
    y: np.ndarray  # (n, 4) states
    nfev: int
    runtime: float
    success: bool = True
    message: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def p(self):
        return self.config.physical

    @cached_property
    def energy(self) -> dict:
        """Energy components (J) and the work done by non-conservative forces."""
        T = physics.kinetic_energy(self.y, self.p)
        V = physics.potential_energy(self.y, self.p)
        E = T + V
        out = {"T": T, "V": V, "E": E}
        if self.p.has_forcing:
            # Integrate input power by the trapezoid rule on the sample grid.
            p_drive = physics.drive_power(self.t, self.y, self.p) if self.p.drive_amplitude else 0 * E
            p_damp = physics.damping_power(self.y, self.p)
            w_drive = _cumtrapz(p_drive, self.t)
            w_damp = _cumtrapz(p_damp, self.t)
            out.update(P_drive=p_drive, P_damp=p_damp, W_drive=w_drive, W_damp=w_damp)
            # Energy balance: E(t) - E0 = W_drive - W_damp  (up to quadrature error).
            out["balance_error"] = (E - E[0]) - (w_drive - w_damp)
        return out

    @cached_property
    def relative_energy_error(self) -> np.ndarray:
        """Conservative runs: (E - E0)/|E0|, except when |E0| is tiny compared with
        the characteristic energy (e.g. a 90°/90° start at rest has E0 = 0 exactly),
        where dividing by E0 would explode; then the characteristic energy is used.
        Forced runs: energy-balance residual / characteristic energy, because E
        itself legitimately changes."""
        e = self.energy
        if self.p.has_forcing:
            return e["balance_error"] / self.energy_scale
        return (e["E"] - e["E"][0]) / self.energy_reference

    @property
    def energy_reference(self) -> float:
        """Denominator of the relative energy error (J): |E0|, or the characteristic
        energy when |E0| < 1e-3 of it."""
        e0 = abs(float(self.energy["E"][0]))
        return e0 if e0 >= 1e-3 * self.energy_scale else self.energy_scale

    @property
    def energy_scale(self) -> float:
        """Characteristic energy (m1+m2) g L1 + m2 g L2 (J)."""
        p = self.p
        return (p.m1 + p.m2) * p.g * p.L1 + p.m2 * p.g * p.L2

    @cached_property
    def positions(self):
        return physics.positions(self.y, self.p)

    @cached_property
    def accelerations(self):
        return np.stack(physics.accelerations(self.t, self.y, self.p), axis=-1)

    def summary(self) -> dict:
        err = self.relative_energy_error
        return {
            "samples": int(len(self.t)),
            "t_end": float(self.t[-1]),
            "method": self.config.numerics.method,
            "nfev": int(self.nfev),
            "runtime_s": float(self.runtime),
            "E0": float(self.energy["E"][0]),
            "max_abs_rel_energy_error": float(np.max(np.abs(err))),
            "final_rel_energy_error": float(err[-1]),
            "success": self.success,
            "message": self.message,
        }


def _cumtrapz(y, x):
    y = np.broadcast_to(np.asarray(y, dtype=float), np.shape(x))
    out = np.zeros_like(x, dtype=float)
    out[1:] = np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(x))
    return out


def make_field(cfg: SimConfig):
    p = cfg.physical
    return lambda t, y: physics.derivatives(t, y, p)


def simulate(cfg: SimConfig, callback=None, y0=None) -> Result:
    """Integrate ``cfg`` and return samples every ``numerics.output_dt`` seconds.

    For RK4 the output spacing is rounded to a whole number of steps; for the
    adaptive methods samples come from the solver's dense output.
    """
    cfg.validate()
    num = cfg.numerics
    f = make_field(cfg)
    y0 = np.asarray(cfg.initial.state() if y0 is None else y0, dtype=float)
    if num.method == "rk4":
        every = max(1, int(round(num.output_dt / num.dt)))
        out = integrate_rk4_double_pendulum(cfg.physical, y0, num.t_max, num.dt, output_every=every,
                                            callback=callback)
    else:
        n = int(round(num.t_max / num.output_dt))
        t_eval = np.linspace(0.0, n * num.output_dt, n + 1)
        out = integrate_adaptive(f, y0, t_eval[-1], num.method, num.rtol, num.atol, t_eval=t_eval)
    return Result(cfg, out.t, out.y, out.nfev, out.runtime, out.success, out.message)
