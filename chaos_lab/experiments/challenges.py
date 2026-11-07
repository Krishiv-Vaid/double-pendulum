"""Chaos Challenges: small experiments with measurable success criteria and
scientific feedback. Each evaluator returns ``{"success", "metrics", "feedback"}``.
No points or leaderboards: the feedback explains *why* a result happened.
"""

from __future__ import annotations

import time

import numpy as np

from chaos_lab.analysis import events, linear, lyapunov
from chaos_lab.core import physics
from chaos_lab.core.config import Initial, Numerics, Physical, SimConfig
from chaos_lab.core.simulation import simulate

CHALLENGES = [
    {"id": "flip", "title": "Make It Flip", "goal": "Choose initial angles (at rest) so that an arm goes over the top within 3 s.",
     "inputs": ["theta1_deg", "theta2_deg"]},
    {"id": "divergence", "title": "Maximum Divergence",
     "goal": "Pick a start and a θ1 offset ≤ 1e-6 rad that is amplified at least 10,000× within 10 s.",
     "inputs": ["theta1_deg", "theta2_deg", "epsilon"]},
    {"id": "energy", "title": "Energy Conservation",
     "goal": "Choose integrator settings that keep |ΔE/E0| below 1e-6 over 30 s from 120°/−10°.",
     "inputs": ["method", "dt", "rtol"]},
    {"id": "predict", "title": "Predict the Motion",
     "goal": "Guess which quadrant (relative to the pivot) the lower bob is in after 2 s.",
     "inputs": ["theta1_deg", "theta2_deg", "quadrant"]},
    {"id": "regular", "title": "Find Regular Motion",
     "goal": "Find a start (at rest) with total energy above −20 J whose finite-time Lyapunov estimate over 40 s is below 0.15 1/s.",
     "inputs": ["theta1_deg", "theta2_deg"]},
    {"id": "artist", "title": "Chaos Artist",
     "goal": "With |θ| ≤ 180° at rest, cover at least 35% of the reachable disc in 30 s.",
     "inputs": ["theta1_deg", "theta2_deg"]},
    {"id": "detective", "title": "Numerical Detective",
     "goal": "Two runs of the same start, RK4 dt = 0.05 s and DOP853 (rtol 1e-10). Which one is under-resolved?",
     "inputs": ["answer"]},
    {"id": "normal_mode", "title": "Normal Mode Explorer",
     "goal": "Excite a single small-angle normal mode: ≥ 95% of the energy in one mode, |θ| ≤ 10°.",
     "inputs": ["theta1_deg", "theta2_deg"]},
]


def _sim(t1, t2, t_max, w1=0.0, w2=0.0, **num):
    cfg = SimConfig(Physical(), Initial(t1, t2, w1, w2), Numerics(t_max=t_max, output_dt=1 / 240, **num))
    return cfg, simulate(cfg)


def evaluate(cid: str, inp: dict) -> dict:
    fn = {
        "flip": _flip, "divergence": _divergence, "energy": _energy, "predict": _predict, "regular": _regular,
        "artist": _artist, "detective": _detective, "normal_mode": _normal_mode,
    }.get(cid)
    if fn is None:
        raise KeyError(f"unknown challenge {cid!r}")
    return fn(inp)


def _flip(inp):
    t1, t2 = float(inp["theta1_deg"]), float(inp["theta2_deg"])
    cfg, r = _sim(t1, t2, 3.0)
    tf = events.first_flip_time(r.t, r.y)
    E = float(r.energy["E"][0])
    from chaos_lab.experiments.maps import min_flip_energy

    emin = min_flip_energy(cfg.physical)
    ok = bool(np.isfinite(tf))
    if ok:
        fb = f"Flip at t = {tf:.2f} s. Your start had E = {E:.2f} J, above the {emin:.2f} J needed for any flip."
    elif E < emin:
        fb = (f"Impossible from here: E = {E:.2f} J is below {emin:.2f} J, the lowest potential energy of any "
              "configuration with an arm pointing straight up. Energy conservation forbids a flip.")
    else:
        fb = (f"Energetically allowed (E = {E:.2f} J ≥ {emin:.2f} J) but no flip within 3 s. "
              "Enough energy is necessary, not sufficient — try larger angles.")
    return {"success": ok, "metrics": {"first_flip_s": None if not ok else tf, "E0": E, "E_min_flip": emin}, "feedback": fb}


def _divergence(inp):
    t1, t2 = float(inp["theta1_deg"]), float(inp["theta2_deg"])
    eps = float(inp.get("epsilon", 1e-6))
    if not 0 < abs(eps) <= 1e-6:
        return {"success": False, "metrics": {}, "feedback": "The offset must satisfy 0 < |ε| ≤ 1e-6 rad."}
    cfg, a = _sim(t1, t2, 10.0)
    b = simulate(cfg, y0=np.array(cfg.initial.state()) + [eps, 0, 0, 0])
    tau = physics.natural_time_scale(cfg.physical)
    d = physics.state_distance(a.y, b.y, tau)
    _, _, x2a, y2a = a.positions
    _, _, x2b, y2b = b.positions
    cart = float(np.hypot(x2a[-1] - x2b[-1], y2a[-1] - y2b[-1]))
    growth = float(d[-1] / abs(eps))
    ok = growth >= 1e4
    fb = (f"Separation grew {growth:.2e}× (state-space distance {d[-1]:.3g}; lower bobs {cart:.3f} m apart). "
          + ("Chaotic regions amplify tiny differences exponentially." if ok
             else "This start is in a calmer region — low-energy motion separates only slowly (roughly linearly)."))
    return {"success": bool(ok), "metrics": {"final_distance": float(d[-1]), "growth_factor": growth, "bob_distance_m": cart},
            "feedback": fb}


def _energy(inp):
    method = str(inp.get("method", "rk4"))
    num = {"method": method}
    if method == "rk4":
        num["dt"] = float(inp.get("dt", 1e-3))
        if num["dt"] < 5e-5:
            return {"success": False, "metrics": {}, "feedback": "Please keep dt ≥ 5e-5 s to bound runtime."}
    else:
        num["rtol"] = num["atol"] = float(inp.get("rtol", 1e-8))
    t0 = time.perf_counter()
    _, r = _sim(120, -10, 30.0, **num)
    err = float(np.max(np.abs(r.relative_energy_error)))
    ok = err < 1e-6
    fb = (f"max |ΔE/E0| = {err:.2e} using {r.nfev} function evaluations in {time.perf_counter() - t0:.2f} s. "
          "Small energy error is necessary for accuracy, but it does not prove the chaotic trajectory is pointwise "
          "correct — errors in phase do not show up in energy.")
    return {"success": ok, "metrics": {"max_rel_energy_error": err, "nfev": r.nfev}, "feedback": fb}


def _predict(inp):
    t1, t2 = float(inp["theta1_deg"]), float(inp["theta2_deg"])
    guess = str(inp["quadrant"]).lower()
    _, r = _sim(t1, t2, 2.0)
    _, _, x2, y2 = r.positions
    q = ("upper" if y2[-1] > 0 else "lower") + "-" + ("right" if x2[-1] > 0 else "left")
    ok = guess == q
    fb = f"After 2 s the bob is at ({x2[-1]:+.2f}, {y2[-1]:+.2f}) m: {q}. " + (
        "Short-term prediction is possible — chaos limits *long-term* prediction." if ok else
        "Even deterministic motion can be hard to predict by intuition; the equations know.")
    return {"success": ok, "metrics": {"x2": float(x2[-1]), "y2": float(y2[-1]), "answer": q}, "feedback": fb}


def _regular(inp):
    t1, t2 = float(inp["theta1_deg"]), float(inp["theta2_deg"])
    cfg = SimConfig(initial=Initial(t1, t2))
    E = float(physics.total_energy(np.array(cfg.initial.state()), cfg.physical))
    lam = lyapunov.double_pendulum_lyapunov(cfg, 40.0, dt=2e-3).lam
    ok = E > -20 and lam < 0.15
    fb = f"E = {E:.2f} J, finite-time λ ≈ {lam:.3f} 1/s. "
    if E <= -20:
        fb += "Too little energy — low-energy motion is almost always regular. Raise the energy."
    elif ok:
        fb += "A regular island at substantial energy: nearby trajectories separate slowly."
    else:
        fb += "Chaotic: small perturbations grow exponentially. Try symmetric or mode-like shapes."
    return {"success": ok, "metrics": {"E0": E, "lyapunov": lam}, "feedback": fb}


def coverage(x, y, R: float, bins: int = 64) -> float:
    """Fraction of grid cells inside the disc of radius R visited by (x, y)."""
    H, _, _ = np.histogram2d(x, y, bins=bins, range=[[-R, R], [-R, R]])
    c = (np.arange(bins) + 0.5) / bins * 2 * R - R
    X, Y = np.meshgrid(c, c)
    disc = (X**2 + Y**2) <= R**2
    return float(np.sum((H > 0) & disc) / np.sum(disc))


def _artist(inp):
    t1, t2 = float(inp["theta1_deg"]), float(inp["theta2_deg"])
    if abs(t1) > 180 or abs(t2) > 180:
        return {"success": False, "metrics": {}, "feedback": "Angles must be within ±180°."}
    cfg, r = _sim(t1, t2, 30.0)
    _, _, x2, y2 = r.positions
    cov = coverage(x2, y2, cfg.physical.L1 + cfg.physical.L2)
    ok = cov >= 0.35
    fb = (f"Coverage {cov:.1%} of the reachable disc (64×64 grid). This is a documented heuristic for "
          "'visual richness', not an objective measure of beauty.")
    return {"success": ok, "metrics": {"coverage": cov}, "feedback": fb}


def detective_runs():
    """The two runs for the Numerical Detective challenge (same start, different integrators)."""
    _, a = _sim(160, 20, 20.0, method="rk4", dt=0.05)
    _, b = _sim(160, 20, 20.0, method="dop853", rtol=1e-10, atol=1e-10)
    return a, b


def _detective(inp):
    a, b = detective_runs()
    ea = float(np.max(np.abs(a.relative_energy_error)))
    eb = float(np.max(np.abs(b.relative_energy_error)))
    ok = str(inp["answer"]).lower() in ("rk4", "a", "rk4 dt=0.05")
    fb = (f"RK4 at dt = 0.05 s drifts in energy by up to {ea:.1e} vs {eb:.1e} for DOP853. A step of 0.05 s is "
          "comparable to the fastest timescales during flips. Diagnostic habits: watch energy, halve the step and "
          "see if the answer changes, and compare short-horizon trajectories — not long chaotic ones, which "
          "diverge even when both runs are accurate.")
    return {"success": ok, "metrics": {"rk4_energy_error": ea, "dop853_energy_error": eb}, "feedback": fb}


def _normal_mode(inp):
    t1, t2 = float(inp["theta1_deg"]), float(inp["theta2_deg"])
    if max(abs(t1), abs(t2)) > 10:
        return {"success": False, "metrics": {}, "feedback": "Keep |θ| ≤ 10° so the small-angle analysis applies."}
    p = Physical()
    M, K = linear.linear_matrices(p)
    phi = np.array(linear.normal_modes(p)["phi"])
    th = np.radians([t1, t2])
    q = phi.T @ M @ th  # modal coordinates (mass-normalized modes)
    w2 = np.array(linear.normal_modes(p)["omega"]) ** 2
    Em = 0.5 * w2 * q**2  # modal potential energy at rest
    frac = Em / max(Em.sum(), 1e-300)
    k = int(np.argmax(frac))
    ok = frac[k] >= 0.95
    ratio = linear.normal_modes(p)["shape_ratio_theta2_over_theta1"]
    fb = (f"Energy split: mode 1 {frac[0]:.1%}, mode 2 {frac[1]:.1%}. Pure modes have θ2/θ1 = {ratio[0]:+.3f} "
          f"(slow, in phase) or {ratio[1]:+.3f} (fast, anti-phase).")
    return {"success": bool(ok), "metrics": {"mode_fractions": frac.tolist()}, "feedback": fb}
