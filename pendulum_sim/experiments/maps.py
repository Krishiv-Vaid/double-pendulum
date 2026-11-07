"""Initial-condition maps ("Fractal Universe").

Each pixel is an initial condition (theta1(0), theta2(0)) with both angular
velocities zero (configurable), integrated with fixed-step RK4 vectorized over
a block of pixels. Observables:

* ``first_flip``  time (s) until either arm first passes over the top
  (unwrapped angle crosses +-pi). NaN if no flip occurs before ``t_max``.
  Pixels whose total energy is below the minimum potential energy of any
  flipped configuration cannot flip and are set to NaN without integrating.
* ``rotations``   total number of over-the-top crossings of both arms in t_max.
* ``max_omega``   maximum of max(|omega1|, |omega2|) over [0, t_max] (rad/s).
* ``sensitivity`` finite-time growth rate (1/s): ln(d(T)/d0)/T between the
  pixel and a twin displaced by d0 in theta1 (wrapped dimensionless norm).
  Saturates once separations become O(1); read it as a sensitivity index.
* ``energy``      total energy of the initial condition (J) — exact, no integration.

Intricate boundaries in these maps are a hallmark of sensitive dependence,
but a picture is not a proof that a set is fractal.
"""

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from pendulum_sim.core import physics
from pendulum_sim.core.config import Physical
from pendulum_sim.core.integrators import rk4_step

OBSERVABLES = ("first_flip", "rotations", "max_omega", "sensitivity", "energy")
CACHE_DIR = Path(os.environ.get("PENDULUM_SIM_CACHE", Path.home() / ".cache" / "pendulum_sim")) / "maps"
MAX_PIXELS = 1_000_000
# Vectorized RK4 amortizes NumPy call overhead over many pixels, so chunks should be large;
# process-pool start-up (~0.5-1 s on spawn platforms) only pays off for big maps (measured,
# see benchmarks/results.md).
PIXELS_PER_CHUNK = 20_000
PARALLEL_MIN_PIXELS = 120_000


@dataclass(frozen=True)
class MapSpec:
    observable: str = "first_flip"
    theta1_range: tuple[float, float] = (-180.0, 180.0)  # degrees
    theta2_range: tuple[float, float] = (-180.0, 180.0)  # degrees
    nx: int = 200
    ny: int = 200
    t_max: float = 10.0
    dt: float = 0.005
    omega1: float = 0.0
    omega2: float = 0.0
    sensitivity_d0: float = 1e-8
    physical: Physical = field(default_factory=Physical)

    def validate(self):
        if self.observable not in OBSERVABLES:
            raise ValueError(f"observable must be one of {OBSERVABLES}")
        if not (1 <= self.nx <= 4000 and 1 <= self.ny <= 4000) or self.nx * self.ny > MAX_PIXELS:
            raise ValueError(f"resolution too large (max {MAX_PIXELS} pixels)")
        if not (0 < self.dt <= 0.05) or not (0 < self.t_max <= 200):
            raise ValueError("need 0 < dt <= 0.05 and 0 < t_max <= 200")
        if self.t_max / self.dt > 200_000:
            raise ValueError("t_max/dt too large for a map (limit 2e5 steps)")
        self.physical.validate()
        return self

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d["physical"] = Physical(**d.get("physical", {}))
        for k in ("theta1_range", "theta2_range"):
            if k in d:
                d[k] = tuple(float(v) for v in d[k])
        for k in ("nx", "ny"):
            if k in d:
                d[k] = int(d[k])
        return cls(**d)

    def digest(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:20]

    def axes(self):
        """Pixel-centre angles in degrees: (theta1 values along x, theta2 values along y)."""
        def centres(lo, hi, n):
            w = (hi - lo) / n
            return lo + w * (np.arange(n) + 0.5)

        return centres(*self.theta1_range, self.nx), centres(*self.theta2_range, self.ny)


def min_flip_energy(p: Physical) -> float:
    """Lowest potential energy of any configuration with one arm vertical-up.
    Below this total energy neither arm can ever pass over the top."""
    up1 = (p.m1 + p.m2) * p.g * p.L1 - p.m2 * p.g * p.L2  # theta1 = pi, theta2 = 0
    up2 = -(p.m1 + p.m2) * p.g * p.L1 + p.m2 * p.g * p.L2  # theta1 = 0, theta2 = pi
    return min(up1, up2)


def compute_rows(spec: MapSpec, row_start: int, row_end: int) -> np.ndarray:
    """Compute map rows [row_start, row_end) — the unit of parallel work."""
    p = spec.physical
    t1, t2 = spec.axes()
    th1, th2 = np.meshgrid(np.radians(t1), np.radians(t2[row_start:row_end]))
    y = np.stack([th1, th2, np.full_like(th1, spec.omega1), np.full_like(th1, spec.omega2)], axis=-1).reshape(-1, 4)
    E = physics.total_energy(y, p)
    if spec.observable == "energy":
        return E.reshape(th1.shape)

    f = lambda t, s: physics.derivatives(t, s, p)  # noqa: E731
    n = int(round(spec.t_max / spec.dt))
    dt = spec.dt
    if spec.observable == "first_flip":
        result = np.full(len(y), np.nan)
        active = np.nonzero(E >= min_flip_energy(p))[0]
        ya = y[active]
        for i in range(1, n + 1):
            if len(active) == 0:
                break
            ya = rk4_step(f, (i - 1) * dt, ya, dt)
            flipped = (np.abs(ya[:, 0]) > np.pi) | (np.abs(ya[:, 1]) > np.pi)
            if np.any(flipped):
                result[active[flipped]] = i * dt
                active, ya = active[~flipped], ya[~flipped]
        return result.reshape(th1.shape)

    if spec.observable == "rotations":
        k_prev = np.floor((y[:, :2] + np.pi) / (2 * np.pi))
        count = np.zeros(len(y))
        for i in range(1, n + 1):
            y = rk4_step(f, (i - 1) * dt, y, dt)
            k = np.floor((y[:, :2] + np.pi) / (2 * np.pi))
            count += np.sum(np.abs(k - k_prev), axis=1)
            k_prev = k
        return count.reshape(th1.shape)

    if spec.observable == "max_omega":
        mx = np.max(np.abs(y[:, 2:]), axis=1)
        for i in range(1, n + 1):
            y = rk4_step(f, (i - 1) * dt, y, dt)
            mx = np.maximum(mx, np.max(np.abs(y[:, 2:]), axis=1))
        return mx.reshape(th1.shape)

    if spec.observable == "sensitivity":
        tau = physics.natural_time_scale(p)
        yb = y.copy()
        yb[:, 0] += spec.sensitivity_d0
        both = np.concatenate([y, yb])
        for i in range(1, n + 1):
            both = rk4_step(f, (i - 1) * dt, both, dt)
        m = len(y)
        d = physics.state_distance(both[:m], both[m:], tau)
        with np.errstate(divide="ignore"):
            return (np.log(np.maximum(d, 1e-300) / spec.sensitivity_d0) / spec.t_max).reshape(th1.shape)

    raise ValueError(spec.observable)


def _job(args):
    spec_d, a, b = args
    return a, b, compute_rows(MapSpec.from_dict(spec_d), a, b)


def compute_map(spec: MapSpec, workers: int | None = None, rows_per_chunk: int | None = None,
                progress=None, cancel=None, use_cache: bool = True) -> np.ndarray:
    """Compute the full (ny, nx) map, in parallel row chunks, with caching.

    ``progress(fraction, partial_map)`` is called after each chunk;
    ``cancel()`` returning True aborts (raises ``InterruptedError``).
    """
    spec.validate()
    path = CACHE_DIR / f"{spec.digest()}.npy"
    if use_cache and path.exists():
        data = np.load(path)
        if progress:
            progress(1.0, data)
        return data
    if rows_per_chunk is None:
        rows_per_chunk = max(1, PIXELS_PER_CHUNK // spec.nx)
    chunks = [(a, min(a + rows_per_chunk, spec.ny)) for a in range(0, spec.ny, rows_per_chunk)]
    if workers is None:
        big = spec.nx * spec.ny >= PARALLEL_MIN_PIXELS and spec.observable != "energy"
        workers = min(max(1, (os.cpu_count() or 2) - 1), len(chunks)) if big else 1
    out = np.full((spec.ny, spec.nx), np.nan)
    done = 0
    spec_d = spec.to_dict()
    if workers == 1 or len(chunks) == 1:
        for a, b in chunks:
            if cancel and cancel():
                raise InterruptedError("map computation cancelled")
            out[a:b] = compute_rows(spec, a, b)
            done += 1
            if progress:
                progress(done / len(chunks), out)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_job, (spec_d, a, b)) for a, b in chunks]
            try:
                for fut in as_completed(futs):
                    a, b, rows = fut.result()
                    out[a:b] = rows
                    done += 1
                    if progress:
                        progress(done / len(chunks), out)
                    if cancel and cancel():
                        raise InterruptedError("map computation cancelled")
            finally:
                for fu in futs:
                    fu.cancel()
    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.save(path, out)
    return out
