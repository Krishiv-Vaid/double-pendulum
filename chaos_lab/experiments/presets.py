"""Preset library. Every qualitative claim in ``expected`` is backed by a
machine-checkable ``checks`` entry that the test suite verifies
(tests/test_presets.py), so the descriptions cannot silently drift from the
physics.

check keys
  max_flips / min_flips  : bounds on the number of over-the-top crossings in ``check_t`` seconds
  both_arms_flip         : both arms complete at least one rotation
  lyapunov_max / _min    : bounds on the finite-time Lyapunov estimate over ``check_t`` (1/s)
  max_angle_deg          : max |theta_i| stays below this
  energy_decreases       : total energy at the end is below E0 by this fraction
"""

from __future__ import annotations

import math

from chaos_lab.core.config import Initial, Numerics, Physical, SimConfig

_S2 = math.sqrt(2.0)


def _cfg(name, t1, t2, w1=0.0, w2=0.0, t_max=30.0, method="rk4", dt=1e-3, **phys):
    return SimConfig(Physical(**phys), Initial(t1, t2, w1, w2), Numerics(method=method, dt=dt, t_max=t_max), name)


def _p(pid, title, desc, cfg, expected, visual=None, mode="playground", checks=None, check_t=30.0, extra=None):
    return {
        "id": pid,
        "title": title,
        "description": desc,
        "config": cfg,
        "visual": {"palette": "white", "trail": "fade", "glow": 0.0, "trail_seconds": 3.0, **(visual or {})},
        "mode": mode,
        "expected": expected,
        "checks": checks or {},
        "check_t": check_t,
        "extra": extra or {},
    }


PRESETS = [
    _p("classic", "Classic Double Pendulum", "Equal masses and rods released from 120°/−10° at rest.",
       _cfg("Classic", 120, -10), "Chaotic swinging; the lower arm flips over the top repeatedly.",
       checks={"min_flips": 3, "lyapunov_min": 0.5}),
    _p("near_equilibrium", "Near Equilibrium", "Released from 10°/10°: tiny oscillations about the hanging state.",
       _cfg("Near Equilibrium", 10, 10), "Regular, nearly linear oscillation; no flips.",
       visual={"palette": "silver"}, checks={"max_flips": 0, "lyapunov_max": 0.1, "max_angle_deg": 20}),
    _p("normal_mode_1", "Small-Angle Normal Mode 1", "In-phase mode: θ2 = +√2 θ1 (equal masses/lengths), 3° amplitude.",
       _cfg("Normal Mode 1", 3.0, 3.0 * _S2), "Both rods swing in phase at ω ≈ 2.40 rad/s, shape preserved.",
       visual={"palette": "silver", "trail": "full"}, checks={"max_flips": 0, "max_angle_deg": 4.5}),
    _p("normal_mode_2", "Small-Angle Normal Mode 2", "Anti-phase mode: θ2 = −√2 θ1, 3° amplitude.",
       _cfg("Normal Mode 2", 3.0, -3.0 * _S2), "Rods swing in opposition at ω ≈ 5.79 rad/s, shape preserved.",
       visual={"palette": "silver", "trail": "full"}, checks={"max_flips": 0, "max_angle_deg": 4.5}),
    _p("near_inverted", "Near-Inverted Start", "Balanced almost straight up at 179°/179°.",
       _cfg("Near-Inverted", 179, 179), "Hesitates near the top, then collapses into violent chaotic motion.",
       visual={"palette": "silver"}, checks={"both_arms_flip": True, "lyapunov_min": 0.5}),
    _p("double_flip", "Double Flip", "Released from 150°/150°: enough energy for both arms to go over the top.",
       _cfg("Double Flip", 150, 150), "Both the upper and the lower arm complete full rotations.",
       visual={"palette": "silver"}, checks={"both_arms_flip": True}),
    _p("butterfly", "Butterfly Effect", "Ten pendulums from 135°/−45°, spread over 1 µrad in θ1.",
       _cfg("Butterfly Effect", 135, -45, t_max=25), "Identical for seconds, then the swarm fans out.",
       mode="butterfly", extra={"n": 10, "epsilon": 1e-6, "variable": "theta1"},
       checks={"lyapunov_min": 0.5}),
    _p("high_energy", "High-Energy Rotation", "Hanging straight down, upper arm kicked at 12 rad/s.",
       _cfg("High-Energy Rotation", 0, 0, 12.0, 0.0), "Rapid continuous rotations of both arms.",
       visual={"palette": "silver"}, checks={"min_flips": 20, "both_arms_flip": True}),
    _p("low_energy", "Low-Energy Oscillation", "Released from 30°/−20°.",
       _cfg("Low Energy", 30, -20), "Bounded, quasi-periodic motion; no flips.",
       visual={"palette": "silver"}, checks={"max_flips": 0, "lyapunov_max": 0.2}),
    _p("unequal_masses", "Unequal Masses", "Heavy upper bob (3 kg), light lower bob (0.5 kg) from 140°/30°.",
       _cfg("Unequal Masses", 140, 30, m1=3.0, m2=0.5), "The light bob whips around a slowly swinging heavy arm.",
       visual={"palette": "silver"}, checks={"min_flips": 1}),
    _p("unequal_lengths", "Unequal Rod Lengths", "Long upper rod (1.2 m), short lower rod (0.6 m) from 130°/80°.",
       _cfg("Unequal Lengths", 130, 80, L1=1.2, L2=0.6), "Tight fast loops of the short arm.",
       visual={"palette": "silver"}, checks={"min_flips": 1}),
    _p("low_gravity", "Low Gravity (Moon)", "Classic start under constant g = 1.62 m/s² (simplified constant-gravity experiment).",
       _cfg("Moon Gravity", 120, -10, g=1.62), "Same geometry as Classic, slowed by sqrt(9.81/1.62) ≈ 2.5×.",
       checks={"min_flips": 1}),
    _p("strong_gravity", "Strong Gravity (Jupiter-like g)", "Classic start under constant g = 24.79 m/s² (simplified).",
       _cfg("Strong Gravity", 120, -10, g=24.79), "Same geometry as Classic, sped up by ≈ 1.6×.",
       checks={"min_flips": 3}),
    _p("long_exposure", "Long Exposure Art", "A minute of motion from 90°/90°, rendered as a light painting.",
       _cfg("Long Exposure", 90, 90, t_max=60), "The lower bob traces a dense web of arcs.",
       visual={"trail": "exposure", "glow": 0.2}, checks={"lyapunov_min": 0.3}, check_t=60),
    _p("gradient_chaos", "Time-Gradient Chaos", "160°/20° with a long trail that brightens with elapsed time.",
       _cfg("Time-Gradient Chaos", 160, 20, t_max=40), "Looping chaos; the trail records its own history.",
       visual={"trail": "time", "trail_seconds": 8.0}, checks={"min_flips": 3}),
    _p("velocity_swirls", "Velocity Swirls", "170°/−90° with a trail whose brightness follows the lower bob's speed.",
       _cfg("Velocity Swirls", 170, -90, t_max=40), "Fast swirls; bright where the bob moves fastest.",
       visual={"trail": "velocity", "particles": "dust"}, checks={"min_flips": 1}),
    _p("swarm", "Pendulum Swarm", "100 pendulums from 150°/150° spread over 1e-4 rad in θ2.",
       _cfg("Pendulum Swarm", 150, 150, t_max=20), "A single rod splits into a fan.",
       mode="butterfly", extra={"n": 100, "epsilon": 1e-4, "variable": "theta2"}, checks={"both_arms_flip": True}),
    _p("phase_space", "Phase-Space Explorer", "60°/40°: regular motion with a clean phase portrait.",
       _cfg("Phase Space", 60, 40, t_max=60), "Closed, nested loops in (θ, ω): quasi-periodic motion.",
       mode="phase", checks={"max_flips": 0, "lyapunov_max": 0.15}, check_t=60),
    _p("poincare", "Poincaré Experiment", "Several trajectories at E = −15 J (hanging energy is −29.4 J).",
       _cfg("Poincaré", 0, 30, t_max=200, method="dop853"), "Regular islands (curves) and chaotic scatter coexist.",
       mode="poincare", extra={"energy": -15.0, "theta2_values": [0.1, 0.4, 0.8, 1.2, 1.6, 2.0]}),
    _p("integrator_challenge", "Integrator Accuracy Challenge", "Near-inverted start integrated with a coarse RK4 step (dt = 0.02 s).",
       _cfg("Integrator Challenge", 178, 180, dt=0.02), "Visible energy error: compare against DOP853 in the Physics Lab.",
       mode="lab", checks={}),
    _p("damped", "Damped Motion", "150°/0° with viscous damping 0.05 N·m·s/rad at both joints.",
       _cfg("Damped", 150, 0, t_max=40, damping1=0.05, damping2=0.05), "Energy drains away and the motion settles.",
       visual={"palette": "silver"}, checks={"energy_decreases": 0.5}, check_t=40),
    _p("driven", "Driven Motion", "From 5°/5°, a 1.5 N·m torque at 2.4 rad/s (near the slow normal mode).",
       _cfg("Driven", 5, 5, t_max=40, drive_amplitude=1.5, drive_frequency=2.4),
       "Near-resonant pumping builds the amplitude up from rest.", visual={"palette": "silver"}),
    _p("lyapunov", "Lyapunov Analysis", "The classic chaotic start, for estimating λ.",
       _cfg("Lyapunov", 120, -10, t_max=60), "Positive finite-time exponent around 1 s⁻¹.",
       mode="lyapunov", checks={"lyapunov_min": 0.5}),
    _p("flip_map", "First-Flip Map", "Map of the time to first flip over all starting angles (ω = 0).",
       _cfg("First-Flip Map", 0, 0), "Calm central region, intricate boundaries outside.", mode="fractal",
       extra={"observable": "first_flip", "nx": 300, "ny": 300, "t_max": 10.0}),
    _p("art_generator", "Chaos Art Generator", "Starting point for the trajectory-art search.",
       _cfg("Chaos Art", 140, 100, t_max=60), "Long-exposure composition; use the generator to explore.",
       mode="studio", visual={"trail": "exposure", "glow": 0.2}),
]

BY_ID = {p["id"]: p for p in PRESETS}


def get(pid: str) -> dict:
    try:
        return BY_ID[pid]
    except KeyError:
        raise KeyError(f"unknown preset {pid!r}; choose from {sorted(BY_ID)}") from None


def to_json(p: dict) -> dict:
    d = {k: v for k, v in p.items() if k != "config"}
    d["config"] = p["config"].to_dict()
    return d
