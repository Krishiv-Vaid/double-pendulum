import numpy as np
import pytest

from pendulum_sim import Initial, Numerics, Physical, SimConfig, simulate
from pendulum_sim.analysis import events, linear, lyapunov, poincare, spectral
from pendulum_sim.core import physics

P = Physical()


# ---------------------------------------------------------------- Lyapunov
def test_lyapunov_lorenz_validation():
    r = lyapunov.largest_lyapunov(lyapunov.lorenz, [1.0, 1.0, 1.0], 400.0, dt=0.01, renorm_interval=0.1, transient=20)
    assert abs(r.lam - 0.9056) < 0.06


def test_lyapunov_linear_oscillator_is_zero():
    f = lambda t, y: np.stack([y[..., 1], -4.0 * y[..., 0]], axis=-1)
    r = lyapunov.largest_lyapunov(f, [1.0, 0.0], 200.0, dt=0.01)
    assert abs(r.lam) < 0.02


def test_lyapunov_regular_vs_chaotic_and_methods_agree():
    reg = lyapunov.double_pendulum_lyapunov(SimConfig(initial=Initial(10, 10)), 40.0)
    cha_t = lyapunov.double_pendulum_lyapunov(SimConfig(initial=Initial(120, -10)), 40.0)
    cha_2 = lyapunov.double_pendulum_lyapunov(SimConfig(initial=Initial(120, -10)), 40.0, method="two_trajectory")
    assert reg.lam < 0.1
    assert cha_t.lam > 0.5
    assert abs(cha_t.lam - cha_2.lam) < 0.1 * cha_t.lam


def test_predictability_horizon():
    r = lyapunov.LyapunovResult(np.array([1.0]), np.array([1.0]), np.array([1.0]), 2.0, "tangent", 0.01, 0.1, 1e-8)
    assert np.isclose(r.predictability_horizon(1e-6, 1e-2), np.log(1e4) / 2)
    r.lam = -0.1
    assert r.predictability_horizon(1e-6, 1e-2) == float("inf")


# ---------------------------------------------------------------- Poincaré
def test_poincare_crossings_lie_on_section():
    s = poincare.section(P, [0.0, 0.5, 3.0, 0.0], t_max=60)
    assert len(s["t"]) > 5
    # re-integrate to each crossing time and check theta1 = 0 mod 2pi, omega1 > 0
    from pendulum_sim.core.integrators import integrate_adaptive
    out = integrate_adaptive(lambda t, y: physics.derivatives(t, y, P), [0.0, 0.5, 3.0, 0.0], s["t"][-1],
                             rtol=1e-11, atol=1e-11, t_eval=s["t"])
    assert np.max(np.abs(physics.wrap_angle(out.y[:, 0]))) < 1e-6
    assert np.all(out.y[:, 2] > 0)
    assert np.allclose(physics.wrap_angle(out.y[:, 1]), s["theta2"], atol=1e-5)
    assert s["energy_drift"] < 1e-6


def test_fixed_energy_initials():
    ics = poincare.fixed_energy_initials(P, -15.0, [0.1, 0.5, 3.0])
    for y in ics:
        assert np.isclose(physics.total_energy(np.array(y), P), -15.0)
        assert y[0] == 0 and y[2] > 0


# ---------------------------------------------------------------- linear
def test_normal_modes_equal_parameters_analytic():
    nm = linear.normal_modes(P)
    w = np.sqrt(np.array([2 - np.sqrt(2), 2 + np.sqrt(2)]) * 9.81)
    assert np.allclose(nm["omega"], w)
    assert np.allclose(nm["shape_ratio_theta2_over_theta1"], [np.sqrt(2), -np.sqrt(2)])


def test_linear_solution_matches_nonlinear_at_small_amplitude():
    cfg = SimConfig(initial=Initial(0.5, -0.3), numerics=Numerics(method="dop853", t_max=10, output_dt=0.01))
    r = simulate(cfg)
    lin = linear.linear_solution(P, cfg.initial.state(), r.t)
    amp = np.radians(0.6)
    assert np.max(np.abs(lin[:, :2] - r.y[:, :2])) < 0.02 * amp


def test_single_mode_stays_in_shape_and_spectrum_peaks():
    y0 = linear.mode_initial_state(P, 1, amplitude_deg=1.0)
    r = simulate(SimConfig(initial=Initial(np.degrees(y0[0]), np.degrees(y0[1])),
                           numerics=Numerics(method="dop853", t_max=40, output_dt=0.01)))
    big = np.abs(r.y[:, 0]) > 0.5 * np.radians(1.0)
    ratio = r.y[big, 1] / r.y[big, 0]
    assert np.allclose(ratio, -np.sqrt(2), atol=0.02)
    sp = spectral.spectrum(r.y[:, 0], 0.01)
    f_peak = sp["frequency_hz"][np.argmax(sp["amplitude"])]
    assert abs(f_peak - linear.normal_modes(P)["frequency_hz"][1]) < 0.03


def test_equilibria_classification():
    eq = {e["name"]: e["classification"] for e in linear.equilibria(P)}
    assert eq["down-down"].startswith("linearly stable")
    assert "1 unstable" in eq["down-up"] and "1 unstable" in eq["up-down"]
    assert "2 unstable" in eq["up-up"]
    damped = {e["name"]: e["classification"] for e in linear.equilibria(Physical(damping1=0.2, damping2=0.2))}
    assert damped["down-down"] == "asymptotically stable"


# ---------------------------------------------------------------- events
def test_flip_detection_synthetic():
    t = np.linspace(0, 20, 2001)
    y = np.zeros((len(t), 4))
    y[:, 1] = 0.7 * t  # arm 2 rotates steadily: crosses pi at t=pi/0.7, 3pi at 3pi/0.7, ...
    ev = events.flip_events(t, y)
    times = [e["t"] for e in ev]
    assert np.allclose(times, [np.pi / 0.7, 3 * np.pi / 0.7], atol=1e-3)
    assert all(e["arm"] == 2 and e["direction"] == 1 for e in ev)
    assert events.rotation_counts(y) == (0, 2)
    assert np.isclose(events.first_flip_time(t, y), np.pi / 0.7, atol=1e-3)
    assert np.isnan(events.first_flip_time(t, y, arm=1))


def test_flip_back_and_forth_counts_each_crossing():
    t = np.linspace(0, 4, 4001)
    y = np.zeros((len(t), 4))
    y[:, 0] = 4.0 * np.sin(np.pi * t / 2)  # exceeds pi, returns, goes below -pi
    assert events.rotation_counts(y)[0] == 4


def test_detect_events_for_timeline():
    r = simulate(SimConfig(numerics=Numerics(t_max=10)))
    ev = events.detect_events(r)
    kinds = {e["kind"] for e in ev}
    assert {"flip", "max_speed", "acceleration"} <= kinds
    assert all(0 <= e["t"] <= 10 for e in ev)


# ---------------------------------------------------------------- spectral
def test_recurrence_matrix_symmetric():
    r = simulate(SimConfig(numerics=Numerics(t_max=5)))
    idx, R = spectral.recurrence_matrix(r.y, 0.3, max_points=100)
    assert R.shape == (100, 100) and np.array_equal(R, R.T) and R.diagonal().all()


@pytest.mark.parametrize("bad", ["foo"])
def test_lyapunov_bad_method(bad):
    with pytest.raises(ValueError):
        lyapunov.largest_lyapunov(lyapunov.lorenz, [1, 1, 1], 1.0, method=bad)
