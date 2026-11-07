"""Verify every machine-checkable claim made in the preset descriptions."""

import numpy as np
import pytest

from chaos_lab import simulate
from chaos_lab.analysis import events, lyapunov
from chaos_lab.experiments import presets

CHECKED = [p for p in presets.PRESETS if p["checks"]]


@pytest.mark.parametrize("preset", CHECKED, ids=[p["id"] for p in CHECKED])
def test_preset_claims(preset):
    c = preset["checks"]
    T = preset["check_t"]
    cfg = preset["config"].with_(**{"numerics.t_max": T, "numerics.method": "dop853"})
    r = simulate(cfg)
    fl = events.flip_events(r.t, r.y)
    if "max_flips" in c:
        assert len(fl) <= c["max_flips"]
    if "min_flips" in c:
        assert len(fl) >= c["min_flips"]
    if c.get("both_arms_flip"):
        assert {e["arm"] for e in fl} == {1, 2}
    if "max_angle_deg" in c:
        assert np.degrees(np.max(np.abs(r.y[:, :2]))) < c["max_angle_deg"]
    if "energy_decreases" in c:
        E = r.energy["E"]
        assert E[-1] < E[0] - c["energy_decreases"] * abs(E[0])
    if "lyapunov_max" in c or "lyapunov_min" in c:
        lam = lyapunov.double_pendulum_lyapunov(preset["config"], min(T, 40.0), dt=2e-3).lam
        assert lam <= c.get("lyapunov_max", np.inf)
        assert lam >= c.get("lyapunov_min", -np.inf)


def test_driven_preset_gains_energy():
    p = presets.get("driven")
    r = simulate(p["config"].with_(**{"numerics.method": "dop853"}))
    E = r.energy["E"]
    assert E.max() > E[0] + 2.0
