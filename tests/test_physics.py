import json

import numpy as np
import pytest

from pendulum_sim import Initial, Numerics, Physical, SimConfig, simulate
from pendulum_sim.core import nlink, physics, pivot
from pendulum_sim.core.integrators import integrate_adaptive

P = Physical()


# --------------------------------------------------------------------------
# Independent check: Euler–Lagrange residual from a Cartesian Lagrangian.
# Uses only x(q, t) and numerical differentiation — none of the derived EOM.
# --------------------------------------------------------------------------
def cartesian_lagrangian(q, qd, t, p, pivot_pos=None):
    def pos(qq, tt):
        xp, yp = (0.0, 0.0) if pivot_pos is None else pivot_pos(tt)
        x1 = xp + p.L1 * np.sin(qq[0])
        y1 = yp - p.L1 * np.cos(qq[0])
        return np.array([x1, y1, x1 + p.L2 * np.sin(qq[1]), y1 - p.L2 * np.cos(qq[1])])

    h = 1e-5
    # velocity = (dX/dq) qd + dX/dt by central differences
    v = (pos(q, t + h) - pos(q, t - h)) / (2 * h)
    for i in range(2):
        e = np.zeros(2)
        e[i] = h
        v += (pos(q + e, t) - pos(q - e, t)) / (2 * h) * qd[i]
    X = pos(q, t)
    T = 0.5 * p.m1 * (v[0] ** 2 + v[1] ** 2) + 0.5 * p.m2 * (v[2] ** 2 + v[3] ** 2)
    V = p.g * (p.m1 * X[1] + p.m2 * X[3])
    return T - V


def el_residual(t, Y, p, pivot_pos=None, idx=range(200, 1800, 97)):
    """Max |d/dt dL/dqd - dL/dq| / scale along a sampled trajectory."""
    h = 1e-3  # L is quadratic in qd, so central differences in qd are exact up to rounding
    dt = t[1] - t[0]

    def dL_dqd(k):
        out = np.zeros(2)
        for i in range(2):
            e = np.zeros(2)
            e[i] = h
            q, qd = Y[k, :2], Y[k, 2:]
            out[i] = (cartesian_lagrangian(q, qd + e, t[k], p, pivot_pos)
                      - cartesian_lagrangian(q, qd - e, t[k], p, pivot_pos)) / (2 * h)
        return out

    res = []
    for k in idx:
        ddt = (dL_dqd(k + 1) - dL_dqd(k - 1)) / (2 * dt)
        dq = np.zeros(2)
        for i in range(2):
            e = np.zeros(2)
            e[i] = h
            q, qd = Y[k, :2], Y[k, 2:]
            dq[i] = (cartesian_lagrangian(q + e, qd, t[k], p, pivot_pos)
                     - cartesian_lagrangian(q - e, qd, t[k], p, pivot_pos)) / (2 * h)
        res.append(np.abs(ddt - dq))
    scale = (p.m1 + p.m2) * p.g * p.L1
    return float(np.max(res) / scale)


@pytest.mark.parametrize("p", [Physical(), Physical(m1=2.0, m2=0.7, L1=1.3, L2=0.6, g=3.7)])
def test_equations_satisfy_euler_lagrange(p):
    """The residual must converge to zero as O(dt^2) (the test's own time differencing)."""
    res = []
    for n in (2001, 4001):
        t = np.linspace(0, 2, n)
        out = integrate_adaptive(lambda tt, y: physics.derivatives(tt, y, p), [2.0, -0.5, 0.3, 1.0], 2.0,
                                 rtol=1e-12, atol=1e-12, t_eval=t)
        res.append(el_residual(out.t, out.y, p, idx=range(n // 10, 9 * n // 10, n // 20)))
    assert res[1] < 1e-4
    assert 3.0 < res[0] / res[1] < 5.0


def test_euler_lagrange_check_detects_wrong_model():
    """Negative control: a model with a deliberately wrong coupling term must fail the residual test."""
    p = Physical()

    def wrong(t, y):
        d = physics.derivatives(t, y, p)
        d[..., 2] += 0.1 * np.sin(y[..., 1])
        return d

    t = np.linspace(0, 2, 2001)
    out = integrate_adaptive(wrong, [2.0, -0.5, 0.3, 1.0], 2.0, rtol=1e-12, atol=1e-12, t_eval=t)
    assert el_residual(out.t, out.y, p) > 1e-3


def test_moving_pivot_satisfies_euler_lagrange():
    mot = pivot.PivotMotion(amp_x=0.03, amp_y=0.05, omega=12.0)
    t = np.linspace(0, 2, 4001)
    out = integrate_adaptive(lambda tt, y: pivot.derivatives(tt, y, P, mot), [1.0, 0.5, 0.0, 0.0], 2.0,
                             rtol=1e-12, atol=1e-12, t_eval=t)
    assert el_residual(out.t, out.y, P, pivot_pos=mot.position, idx=range(400, 3600, 200)) < 1e-4


def test_moving_pivot_with_no_motion_matches_fixed():
    y = np.array([0.4, -1.2, 0.3, 2.0])
    still = pivot.PivotMotion(0.0, 0.0, 5.0)
    assert np.allclose(pivot.derivatives(0.3, y, P, still), physics.derivatives(0.3, y, P))


def test_matrix_form_matches_readme_equation():
    """The README's normalized 2x2 system, solved with numpy, equals our Cramer solution."""
    p = Physical(m1=1.3, m2=0.8, L1=0.9, L2=1.1, g=9.81)
    th1, th2, w1, w2 = 0.7, -2.1, 1.4, -0.6
    D = th1 - th2
    M = np.array([[(p.m1 + p.m2) * p.L1, p.m2 * p.L2 * np.cos(D)], [p.L1 * np.cos(D), p.L2]])
    b = np.array([-p.m2 * p.L2 * w2**2 * np.sin(D) - (p.m1 + p.m2) * p.g * np.sin(th1),
                  p.L1 * w1**2 * np.sin(D) - p.g * np.sin(th2)])
    assert np.allclose(np.linalg.solve(M, b), physics.derivatives(0, [th1, th2, w1, w2], p)[2:])


def test_positions_velocities_energy_by_hand():
    y = np.array([np.pi / 2, 0.0, 1.0, 2.0])
    x1, y1, x2, y2 = physics.positions(y, P)
    assert np.allclose([x1, y1, x2, y2], [1, 0, 1, -1])
    vx1, vy1, vx2, vy2 = physics.velocities(y, P)
    assert np.allclose([vx1, vy1, vx2, vy2], [0, 1, 2, 1])
    T = 0.5 * 1 * (0 + 1) + 0.5 * 1 * (4 + 1)
    V = 9.81 * (0 + 1 * -1)
    assert np.isclose(physics.kinetic_energy(y, P), T)
    assert np.isclose(physics.potential_energy(y, P), V)
    assert np.isclose(physics.total_energy(y, P), T + V)


def test_vectorized_matches_scalar():
    rng = np.random.default_rng(1)
    Y = rng.normal(size=(7, 4))
    batch = physics.derivatives(0, Y, P)
    for k in range(7):
        assert np.allclose(batch[k], physics.derivatives(0, Y[k], P))


def test_angular_momentum_rate_equals_gravity_torque():
    t = np.linspace(0, 1, 1001)
    out = integrate_adaptive(lambda tt, y: physics.derivatives(tt, y, P), [2.0, 1.0, 0, 0], 1.0,
                             rtol=1e-12, atol=1e-12, t_eval=t)
    Lz = physics.angular_momentum(out.y, P)
    x1, _, x2, _ = physics.positions(out.y, P)
    torque = -P.g * (P.m1 * x1 + P.m2 * x2)
    dL = np.gradient(Lz, t)
    assert np.max(np.abs(dL[5:-5] - torque[5:-5])) < 1e-3
    assert np.ptp(Lz) > 1.0  # clearly not conserved


def test_cartesian_acceleration_matches_numerical_derivative():
    t = np.linspace(0, 1, 2001)
    out = integrate_adaptive(lambda tt, y: physics.derivatives(tt, y, P), [2.0, 1.0, 0.5, 0], 1.0,
                             rtol=1e-12, atol=1e-12, t_eval=t)
    _, _, vx2, vy2 = physics.velocities(out.y, P)
    _, _, ax2, ay2 = physics.cartesian_accelerations(out.t, out.y, P)
    scale = np.max(np.hypot(ax2, ay2))
    assert np.max(np.abs(np.gradient(vx2, t)[5:-5] - ax2[5:-5])) < 1e-4 * scale
    assert np.max(np.abs(np.gradient(vy2, t)[5:-5] - ay2[5:-5])) < 1e-4 * scale


def test_jacobian_complex_step_vs_finite_difference():
    for y in ([0.3, -1.0, 0.5, 2.0], [3.0, 2.0, -4.0, 1.0]):
        assert np.allclose(physics.jacobian(0, y, P), physics.jacobian_fd(0, y, P), atol=1e-6)
    pf = Physical(damping1=0.2, damping2=0.1, drive_amplitude=1.0, drive_frequency=2.0)
    assert np.allclose(physics.jacobian(0.7, [1, 2, 3, 4], pf), physics.jacobian_fd(0.7, [1, 2, 3, 4], pf), atol=1e-6)


def test_wrap_angle_and_distance():
    assert np.isclose(physics.wrap_angle(3 * np.pi / 2), -np.pi / 2)
    assert np.isclose(physics.wrap_angle(-3 * np.pi / 2), np.pi / 2)
    a = np.array([np.pi - 0.01, 0, 0, 0])
    b = np.array([-np.pi + 0.01, 0, 0, 0])
    assert np.isclose(physics.state_distance(a, b), 0.02)


def test_energy_for_omega1_round_trip():
    w1 = physics.energy_for_omega1(0.0, 0.8, 0.3, -12.0, P)
    assert np.isclose(physics.total_energy(np.array([0.0, 0.8, w1, 0.3]), P), -12.0)
    assert np.isnan(physics.energy_for_omega1(0.0, 0.0, 0.0, -100.0, P))


# --------------------------------------------------------------------------
# Integration accuracy
# --------------------------------------------------------------------------
def test_rk4_energy_error_converges_fourth_order():
    errs = []
    for dt in (0.004, 0.002):
        r = simulate(SimConfig(numerics=Numerics(dt=dt, t_max=10.0)))
        errs.append(np.max(np.abs(r.relative_energy_error)))
    assert 10 < errs[0] / errs[1] < 40  # ~16 for 4th order


def test_adaptive_energy_error_improves_with_tolerance():
    for m in ("rk45", "dop853"):
        loose = simulate(SimConfig(numerics=Numerics(method=m, rtol=1e-6, atol=1e-8, t_max=10.0)))
        tight = simulate(SimConfig(numerics=Numerics(method=m, rtol=1e-11, atol=1e-11, t_max=10.0)))
        assert np.max(np.abs(tight.relative_energy_error)) < 0.05 * np.max(np.abs(loose.relative_energy_error))


def test_methods_agree_over_short_horizon():
    base = SimConfig(numerics=Numerics(t_max=3.0, output_dt=0.01))
    ref = simulate(base.with_(**{"numerics.method": "dop853", "numerics.rtol": 1e-12, "numerics.atol": 1e-12}))
    for m in ("rk4", "rk45"):
        r = simulate(base.with_(**{"numerics.method": m}))
        assert np.max(np.abs(r.y - ref.y)) < 1e-5


def test_determinism():
    a = simulate(SimConfig(numerics=Numerics(t_max=5)))
    b = simulate(SimConfig(numerics=Numerics(t_max=5)))
    assert np.array_equal(a.y, b.y)


def test_output_sampling_is_physical_time():
    r = simulate(SimConfig(numerics=Numerics(t_max=2.0, dt=1e-3, output_dt=0.01)))
    assert np.allclose(np.diff(r.t), 0.01)
    assert np.isclose(r.t[-1], 2.0)


# --------------------------------------------------------------------------
# Forcing: damping and driving
# --------------------------------------------------------------------------
def test_damping_dissipates_and_balances():
    cfg = SimConfig(Physical(damping1=0.1, damping2=0.05), Initial(150, 0),
                    Numerics(method="dop853", t_max=20, output_dt=1e-3))
    r = simulate(cfg)
    E = r.energy["E"]
    assert E[-1] < E[0] - 10
    assert np.all(np.diff(E) < 1e-9)  # monotone decrease (no driving)
    assert np.max(np.abs(r.relative_energy_error)) < 1e-5  # energy balance closes


def test_driving_energy_balance():
    cfg = SimConfig(Physical(drive_amplitude=1.5, drive_frequency=2.4), Initial(5, 5),
                    Numerics(method="dop853", t_max=20, output_dt=1e-3))
    r = simulate(cfg)
    assert r.energy["W_drive"][-1] != 0
    assert np.max(np.abs(r.relative_energy_error)) < 1e-5


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    {"physical": {"m1": -1}}, {"physical": {"L2": 0}}, {"physical": {"g": float("nan")}},
    {"physical": {"damping1": -0.1}}, {"numerics": {"method": "euler"}}, {"numerics": {"dt": 0}},
    {"numerics": {"t_max": -1}}, {"initial": {"omega1": float("inf")}},
])
def test_invalid_parameters_rejected(bad):
    with pytest.raises(ValueError):
        SimConfig.from_dict(bad).validate()


def test_unknown_field_rejected():
    with pytest.raises(ValueError):
        SimConfig.from_dict({"physical": {"mass": 1}})


def test_config_json_round_trip_and_digest():
    cfg = SimConfig(Physical(m1=2.0, damping2=0.1), Initial(10, 20, 0.5, -0.5), Numerics(method="dop853"), "x")
    back = SimConfig.from_json(cfg.to_json())
    assert back == cfg
    assert back.digest() == cfg.digest()
    assert cfg.with_(name="other").digest() == cfg.digest()
    assert cfg.with_(**{"physical.g": 1.62}).digest() != cfg.digest()
    json.loads(cfg.to_json())


# --------------------------------------------------------------------------
# N-link (triple pendulum)
# --------------------------------------------------------------------------
def test_nlink_two_links_matches_double_pendulum():
    p = Physical(m1=1.4, m2=0.6, L1=0.8, L2=1.2, g=9.0)
    q = nlink.NLinkParams((1.4, 0.6), (0.8, 1.2), 9.0)
    rng = np.random.default_rng(0)
    for _ in range(5):
        y = rng.normal(size=4) * 2
        assert np.allclose(nlink.derivatives(0, y, q), physics.derivatives(0, y, p))
        assert np.isclose(nlink.total_energy(y, q), physics.total_energy(y, p))


def test_triple_pendulum_conserves_energy():
    q = nlink.NLinkParams()
    y0 = np.array([2.0, 1.0, -1.0, 0, 0, 0])
    out = integrate_adaptive(lambda t, y: nlink.derivatives(t, y, q), y0, 10.0, rtol=1e-11, atol=1e-11,
                             t_eval=np.linspace(0, 10, 501))
    E = nlink.total_energy(out.y, q)
    assert np.max(np.abs(E - E[0])) < 1e-6


@pytest.mark.parametrize("p", [Physical(), Physical(m1=2, m2=0.5, L1=0.7, L2=1.3, g=3.0, damping1=0.1, damping2=0.2,
                                                    drive_amplitude=0.8, drive_frequency=2.0, drive_phase=0.3)])
def test_scalar_fast_path_matches_vectorized_rk4(p):
    from pendulum_sim.core.integrators import integrate_rk4, integrate_rk4_double_pendulum

    y0 = [2.0, -0.4, 0.3, 1.1]
    a = integrate_rk4_double_pendulum(p, y0, 3.0, 1e-3, output_every=10)
    b = integrate_rk4(lambda t, y: physics.derivatives(t, y, p), y0, 3.0, 1e-3, output_every=10)
    assert np.allclose(a.y, b.y, rtol=0, atol=1e-11)
    assert np.array_equal(a.t, b.t)


def test_relative_energy_error_safe_when_e0_is_zero():
    """90°/90° at rest has E0 = 0 (up to rounding); the error must be referenced to the
    characteristic energy rather than exploding (regression: ~1e3 reported before)."""
    r = simulate(SimConfig(initial=Initial(90, 90), numerics=Numerics(t_max=10)))
    assert abs(r.energy["E"][0]) < 1e-9
    assert r.energy_reference == pytest.approx(r.energy_scale)
    assert np.max(np.abs(r.relative_energy_error)) < 1e-5
    classic = simulate(SimConfig(numerics=Numerics(t_max=2)))
    assert classic.energy_reference == pytest.approx(abs(classic.energy["E"][0]))
