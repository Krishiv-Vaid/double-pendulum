import numpy as np
import pytest

from pendulum_sim import Initial, Numerics, Physical, SimConfig, simulate
from pendulum_sim.analysis import events, lyapunov
from pendulum_sim.core import physics
from pendulum_sim.experiments import art, challenges, ensemble, integrator_lab, maps, presets, sweeps


# ---------------------------------------------------------------- butterfly
def test_butterfly_reference_and_growth():
    cfg = SimConfig(initial=Initial(135, -45), numerics=Numerics(t_max=15, output_dt=0.05, dt=2e-3))
    b = ensemble.butterfly(cfg, n=5, epsilon=1e-6)
    assert np.all(b["separation"][:, 0] == 0)
    s = b["separation"][:, -1]
    assert s[0] < 1e-5 and s[-1] > 0.5  # grows from ~1e-6 to O(1)
    # physical divergence dominates the dt vs dt/2 numerical control early on
    k = len(b["t"]) // 2
    assert b["separation"][k, -1] > 100 * b["numerical_control"][k]
    assert b["stats"]["diverged"] >= 1


def test_perturbations():
    assert np.allclose(ensemble.perturbations(3, 1.0), [0, 0.5, 1.0])
    g1 = ensemble.perturbations(5, 1e-3, "gaussian", seed=4)
    assert g1[0] == 0 and np.array_equal(g1, ensemble.perturbations(5, 1e-3, "gaussian", seed=4))
    with pytest.raises(ValueError):
        ensemble.perturbations(1, 1.0)


def test_ensemble_matches_single_simulation():
    cfg = SimConfig(numerics=Numerics(t_max=2, output_dt=0.01))
    t, Y = ensemble.integrate_batch(cfg.physical, np.array([cfg.initial.state()] * 3), 2, 1e-3, 0.01)
    r = simulate(cfg)
    assert np.allclose(Y[:, 1], r.y)


# ---------------------------------------------------------------- maps
def test_map_reproducible_parallel_equals_serial():
    spec = maps.MapSpec(nx=12, ny=10, t_max=4.0, dt=0.01)
    a = maps.compute_map(spec, workers=1, use_cache=False)
    b = maps.compute_map(spec, workers=2, rows_per_chunk=3, use_cache=False)
    assert np.array_equal(a, b, equal_nan=True)


def test_first_flip_map_matches_single_trajectory_and_energy_bound():
    spec = maps.MapSpec(nx=8, ny=8, t_max=5.0, dt=0.005)
    m = maps.compute_map(spec, workers=1, use_cache=False)
    t1, t2 = spec.axes()
    j, i = 1, 6
    cfg = SimConfig(initial=Initial(t1[i], t2[j]), numerics=Numerics(t_max=5.0, dt=0.005, output_dt=0.005))
    r = simulate(cfg)
    tf = events.first_flip_time(r.t, r.y)
    if np.isnan(tf):
        assert np.isnan(m[j, i])
    else:
        assert abs(m[j, i] - tf) <= 0.005 + 1e-9
    E = maps.compute_map(maps.MapSpec(observable="energy", nx=8, ny=8), workers=1, use_cache=False)
    assert np.all(np.isnan(m[E < maps.min_flip_energy(Physical())]))


@pytest.mark.parametrize("obs", ["rotations", "max_omega", "sensitivity", "energy"])
def test_map_observables(obs):
    m = maps.compute_map(maps.MapSpec(observable=obs, nx=6, ny=5, t_max=3.0, dt=0.01), workers=1, use_cache=False)
    assert m.shape == (5, 6) and np.all(np.isfinite(m))


def test_map_cache_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(maps, "CACHE_DIR", tmp_path)
    spec = maps.MapSpec(nx=4, ny=4, t_max=1.0, dt=0.01)
    a = maps.compute_map(spec, workers=1)
    assert (tmp_path / f"{spec.digest()}.npy").exists()
    assert np.array_equal(a, maps.compute_map(spec, workers=1), equal_nan=True)
    with pytest.raises(InterruptedError):
        maps.compute_map(maps.MapSpec(nx=4, ny=4, t_max=1.1), workers=1, use_cache=False, cancel=lambda: True)


def test_map_spec_validation_and_round_trip():
    with pytest.raises(ValueError):
        maps.MapSpec(nx=5000, ny=5000).validate()
    s = maps.MapSpec(nx=10, ny=20, physical=Physical(g=1.62))
    assert maps.MapSpec.from_dict(s.to_dict()) == s


# ---------------------------------------------------------------- sweeps
def test_sweep_1d_matches_direct_run():
    cfg = SimConfig(initial=Initial(150, 150), numerics=Numerics(t_max=5))
    sw = sweeps.sweep(cfg, "g", [1.62, 9.81], observable="rotations", dt=2e-3)
    r = simulate(cfg.with_(**{"physical.g": 9.81, "numerics.dt": 2e-3, "numerics.output_dt": 2e-3}))
    assert sw["values"][1] == sum(events.rotation_counts(r.y))


def test_sweep_2d_shape():
    sw = sweeps.sweep(SimConfig(), "theta1_deg", np.linspace(-90, 90, 5), "mass_ratio", [0.5, 1, 2],
                      observable="max_omega", t_max=2.0)
    assert sw["values"].shape == (3, 5)


# ---------------------------------------------------------------- integrators
def test_integrator_lab_and_convergence():
    cmp = integrator_lab.compare(SimConfig(numerics=Numerics(t_max=5)))
    rows = {r["label"]: r for r in cmp["rows"]}
    assert rows["RK4 dt=0.001"]["max_abs_rel_energy_error"] < rows["RK4 dt=0.01"]["max_abs_rel_energy_error"]
    assert rows["DOP853 rtol=1e-12"]["final_state_difference"] < 1e-6
    conv = integrator_lab.rk4_convergence(SimConfig(), dts=(0.004, 0.002, 0.001), t_max=3.0)
    assert 3.3 < conv["observed_order"] < 4.7


# ---------------------------------------------------------------- challenges / art
def test_challenges_feedback():
    assert challenges.evaluate("flip", {"theta1_deg": 170, "theta2_deg": 170})["success"]
    low = challenges.evaluate("flip", {"theta1_deg": 20, "theta2_deg": 20})
    assert not low["success"] and "Impossible" in low["feedback"]
    assert challenges.evaluate("energy", {"method": "dop853", "rtol": 1e-11})["success"]
    assert not challenges.evaluate("energy", {"method": "rk4", "dt": 0.05})["success"]
    assert challenges.evaluate("normal_mode", {"theta1_deg": 3, "theta2_deg": 3 * np.sqrt(2)})["success"]
    assert challenges.evaluate("detective", {"answer": "rk4"})["success"]
    assert challenges.evaluate("divergence", {"theta1_deg": 135, "theta2_deg": -45, "epsilon": 1e-6})["success"]
    pred = challenges.evaluate("predict", {"theta1_deg": 90, "theta2_deg": 0, "quadrant": "lower-left"})
    assert "answer" in pred["metrics"]
    assert challenges.evaluate("artist", {"theta1_deg": 170, "theta2_deg": 100})["metrics"]["coverage"] > 0
    assert "lyapunov" in challenges.evaluate("regular", {"theta1_deg": 60, "theta2_deg": 40})["metrics"]


def test_art_search_sorted_and_deterministic():
    a = art.search("complexity", n_candidates=12, top=4, seed=3, t_max=5)
    b = art.search("complexity", n_candidates=12, top=4, seed=3, t_max=5)
    assert [r["score"] for r in a] == sorted([r["score"] for r in a], reverse=True)
    assert [r["config"] for r in a] == [r["config"] for r in b]


def test_lyapunov_sensitivity_scan():
    res = lyapunov.sensitivity_scan(SimConfig(), 15.0, d0s=(1e-9, 1e-7), intervals=(0.1, 0.5), dt=5e-3)
    assert len(res["rows"]) == 6 and res["min"] > 0.3


def test_presets_shape():
    assert len(presets.PRESETS) >= 25
    for p in presets.PRESETS:
        assert {"id", "title", "description", "config", "visual", "expected"} <= set(p)
        p["config"].validate()
        presets.to_json(p)


def test_preset_state_space_helpers():
    p = Physical()
    assert physics.natural_time_scale(p) > 0
