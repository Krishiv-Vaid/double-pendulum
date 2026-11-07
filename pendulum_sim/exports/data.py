"""Data exports: CSV with units, JSON configs, and reproducible experiment bundles.

Large numerical results never go inside configuration JSON: bundles store the
config (small, human-readable) and the trajectory (``.npz``) as separate files.
"""

from __future__ import annotations

import csv
import io
import json
import platform
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from pendulum_sim import __version__
from pendulum_sim.core import physics

COLUMNS = [
    ("t", "s", "physical time"),
    ("theta1", "rad", "upper rod angle from downward vertical"),
    ("theta2", "rad", "lower rod angle from downward vertical"),
    ("omega1", "rad/s", "upper rod angular velocity"),
    ("omega2", "rad/s", "lower rod angular velocity"),
    ("alpha1", "rad/s^2", "upper rod angular acceleration"),
    ("alpha2", "rad/s^2", "lower rod angular acceleration"),
    ("x1", "m", "upper bob x"),
    ("y1", "m", "upper bob y (up positive)"),
    ("x2", "m", "lower bob x"),
    ("y2", "m", "lower bob y (up positive)"),
    ("T", "J", "kinetic energy"),
    ("V", "J", "potential energy (zero at pivot height)"),
    ("E", "J", "total energy"),
    ("rel_energy_error", "1", "(E-E0)/|E0|, or energy-balance residual / characteristic energy if forced"),
]


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=2,
                             cwd=Path(__file__).resolve().parents[2])
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def reproducibility_stamp(cfg=None, extra: dict | None = None) -> dict:
    import matplotlib
    import scipy

    d = {
        "simulator_version": __version__,
        "git_commit": git_commit(),
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "matplotlib": matplotlib.__version__,
        "platform": platform.platform(),
    }
    if cfg is not None:
        d["config_digest"] = cfg.digest()
    d.update(extra or {})
    return d


def table(result, every: int = 1) -> tuple[list[str], np.ndarray]:
    y = result.y[::every]
    t = result.t[::every]
    acc = physics.accelerations(t, y, result.p)
    x1, y1, x2, y2 = physics.positions(y, result.p)
    T = physics.kinetic_energy(y, result.p)
    V = physics.potential_energy(y, result.p)
    err = result.relative_energy_error[::every]
    data = np.column_stack([t, y, acc[0], acc[1], x1, y1, x2, y2, T, V, T + V, err])
    return [c[0] for c in COLUMNS], data


def to_csv(result, every: int = 1, t_range: tuple[float, float] | None = None) -> str:
    names, data = table(result, every)
    if t_range is not None:
        data = data[(data[:, 0] >= t_range[0]) & (data[:, 0] <= t_range[1])]
    buf = io.StringIO()
    buf.write(f"# Double Pendulum Simulator trajectory export — config {result.config.digest()} "
              f"({result.config.name})\n")
    for name, unit, desc in COLUMNS:
        buf.write(f"# {name} [{unit}]: {desc}\n")
    w = csv.writer(buf)
    w.writerow([f"{n} [{u}]" for n, u, _ in COLUMNS])
    for row in data:
        w.writerow([f"{v:.10g}" for v in row])
    return buf.getvalue()


def bundle(result, path, notes: str = "", media: dict | None = None) -> Path:
    """Zip with config.json, trajectory.npz, trajectory.csv (downsampled), stamp.json and optional media."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    npz = io.BytesIO()
    np.savez_compressed(npz, t=result.t, y=result.y)
    every = max(1, len(result.t) // 20000)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("config.json", result.config.to_json())
        z.writestr("trajectory.npz", npz.getvalue())
        z.writestr("trajectory.csv", to_csv(result, every))
        z.writestr("stamp.json", json.dumps(reproducibility_stamp(result.config, {"summary": result.summary(),
                                                                                 "notes": notes}), indent=2))
        z.writestr("README.txt", "Reproduce with:\n  python -m pendulum_sim simulate --config config.json\n")
        for name, blob in (media or {}).items():
            z.writestr(name, blob)
    return path


def load_bundle(path):
    from pendulum_sim.core.config import SimConfig

    with zipfile.ZipFile(path) as z:
        cfg = SimConfig.from_json(z.read("config.json").decode())
        arr = np.load(io.BytesIO(z.read("trajectory.npz")))
        return cfg, arr["t"], arr["y"]
