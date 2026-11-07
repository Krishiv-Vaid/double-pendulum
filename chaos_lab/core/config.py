"""Simulation configuration: physical parameters, initial state, numerics.

Configurations are plain dataclasses that round-trip through JSON so every
experiment, export and gallery asset can be reproduced exactly. Angles are
stored in degrees in configs (human-friendly) and converted to radians for the
integrator; angular velocities are in rad/s.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, fields, replace

import numpy as np

METHODS = ("rk4", "rk45", "dop853")


def _coerce_floats(obj, skip=()):
    """Store Python ints/bools as floats so JSON round-trips and digests are stable.
    Arrays (used by vectorized sweeps) are left untouched."""
    for f in fields(obj):
        v = getattr(obj, f.name)
        if f.name not in skip and isinstance(v, (int, float)) and not isinstance(v, np.ndarray):
            object.__setattr__(obj, f.name, float(v))


@dataclass(frozen=True)
class Physical:
    m1: float = 1.0  # kg
    m2: float = 1.0  # kg
    L1: float = 1.0  # m
    L2: float = 1.0  # m
    g: float = 9.81  # m/s^2
    damping1: float = 0.0  # N m s/rad, viscous torque at the pivot
    damping2: float = 0.0  # N m s/rad, viscous torque at the elbow (relative)
    drive_amplitude: float = 0.0  # N m, torque applied at the pivot
    drive_frequency: float = 0.0  # rad/s
    drive_phase: float = 0.0  # rad

    def __post_init__(self):
        _coerce_floats(self)

    @property
    def has_forcing(self) -> bool:
        # np.any so that vectorized parameter sweeps (array-valued fields) work
        return bool(np.any(np.asarray(self.damping1) != 0) or np.any(np.asarray(self.damping2) != 0)
                    or np.any(np.asarray(self.drive_amplitude) != 0))

    @property
    def is_conservative(self) -> bool:
        return not self.has_forcing

    def validate(self) -> None:
        for name in ("m1", "m2", "L1", "L2"):
            v = getattr(self, name)
            if not (math.isfinite(v) and v > 0):
                raise ValueError(f"{name} must be a positive finite number, got {v!r}")
        if not (math.isfinite(self.g) and self.g > 0):
            raise ValueError(f"g must be a positive finite number, got {self.g!r}")
        for name in ("damping1", "damping2"):
            v = getattr(self, name)
            if not (math.isfinite(v) and v >= 0):
                raise ValueError(f"{name} must be >= 0, got {v!r}")
        for name in ("drive_amplitude", "drive_frequency", "drive_phase"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")


@dataclass(frozen=True)
class Initial:
    theta1_deg: float = 120.0
    theta2_deg: float = -10.0
    omega1: float = 0.0  # rad/s
    omega2: float = 0.0  # rad/s

    def __post_init__(self):
        _coerce_floats(self)

    def state(self):
        return [
            math.radians(self.theta1_deg),
            math.radians(self.theta2_deg),
            float(self.omega1),
            float(self.omega2),
        ]

    def validate(self) -> None:
        for f in fields(self):
            if not math.isfinite(getattr(self, f.name)):
                raise ValueError(f"initial {f.name} must be finite")


@dataclass(frozen=True)
class Numerics:
    method: str = "rk4"  # rk4 | rk45 | dop853
    dt: float = 1e-3  # s, RK4 step (ignored by adaptive methods)
    rtol: float = 1e-10  # adaptive methods
    atol: float = 1e-10  # adaptive methods
    t_max: float = 30.0  # s, simulated (physical) time
    output_dt: float = 1.0 / 240.0  # s, spacing of stored samples (physical time)

    def __post_init__(self):
        _coerce_floats(self, skip=("method",))

    def validate(self) -> None:
        if self.method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}, got {self.method!r}")
        if not (self.dt > 0 and math.isfinite(self.dt)):
            raise ValueError("dt must be positive")
        if not (self.t_max > 0 and math.isfinite(self.t_max)):
            raise ValueError("t_max must be positive")
        if not (self.output_dt > 0 and math.isfinite(self.output_dt)):
            raise ValueError("output_dt must be positive")
        if self.output_dt > self.t_max:
            raise ValueError("output_dt must not exceed t_max")
        if not (0 < self.rtol < 1 and 0 < self.atol < 1):
            raise ValueError("rtol and atol must be in (0, 1)")
        n_steps = self.t_max / self.dt
        if self.method == "rk4" and n_steps > 5e7:
            raise ValueError(f"t_max/dt = {n_steps:.3g} RK4 steps exceeds the 5e7 safety limit")
        if self.t_max / self.output_dt > 2e6:
            raise ValueError("too many output samples (t_max/output_dt > 2e6)")


@dataclass(frozen=True)
class SimConfig:
    physical: Physical = field(default_factory=Physical)
    initial: Initial = field(default_factory=Initial)
    numerics: Numerics = field(default_factory=Numerics)
    name: str = "Untitled"

    def validate(self) -> SimConfig:
        self.physical.validate()
        self.initial.validate()
        self.numerics.validate()
        return self

    # -- serialization -----------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, **kw) -> str:
        return json.dumps(self.to_dict(), indent=kw.pop("indent", 2), **kw)

    @classmethod
    def from_dict(cls, d: dict) -> SimConfig:
        d = dict(d or {})

        def build(klass, sub):
            sub = dict(sub or {})
            known = {f.name for f in fields(klass)}
            unknown = set(sub) - known
            if unknown:
                raise ValueError(f"unknown {klass.__name__} field(s): {sorted(unknown)}")
            return klass(**{k: (str(v) if k == "method" else float(v)) for k, v in sub.items()})

        return cls(
            physical=build(Physical, d.get("physical")),
            initial=build(Initial, d.get("initial")),
            numerics=build(Numerics, d.get("numerics")),
            name=str(d.get("name", "Untitled")),
        )

    @classmethod
    def from_json(cls, s: str) -> SimConfig:
        return cls.from_dict(json.loads(s))

    def digest(self) -> str:
        """Stable short hash of the physics + numerics (name excluded)."""
        d = self.to_dict()
        d.pop("name", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]

    def with_(self, **changes) -> SimConfig:
        """Return a copy with dotted-path overrides, e.g. ``with_(**{"physical.g": 1.62})``."""
        phys, init, num = self.physical, self.initial, self.numerics
        name = self.name
        for key, val in changes.items():
            section, _, attr = key.partition(".")
            if section == "physical":
                phys = replace(phys, **{attr: float(val)})
            elif section == "initial":
                init = replace(init, **{attr: float(val)})
            elif section == "numerics":
                num = replace(num, **{attr: (val if attr == "method" else float(val))})
            elif section == "name":
                name = str(val)
            else:
                raise KeyError(key)
        return SimConfig(phys, init, num, name)
