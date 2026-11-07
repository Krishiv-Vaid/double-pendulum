"""Build docs/gallery.md from the sidecar JSON files written by generate_gallery.py.

    python scripts/build_gallery_docs.py

Every parameter shown in the gallery is read from the configuration that
actually produced the asset, so the documentation cannot drift from the media.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG_DIR = ROOT / "assets" / "gifs" / "configs"

SECTIONS = {
    "Cinematic Art": [
        ("hero-chaos", "Hero Chaos", "A single chaotic double pendulum with a fading white trail. The faint bloom is a rendering effect "
                                     "added to the light layer; the trajectory itself is untouched."),
        ("long-exposure", "Long Exposure", "The lower bob paints its path over 45 s of simulated time (4× playback). "
                                           "Each pixel keeps the brightest value it has seen."),
        ("parameter-morph", "Parameter Morph", "Eleven *independent* simulations with the lower rod length stepped "
                                               "from 0.4 m to 1.4 m. The cross-fades are visual transitions between "
                                               "separate runs, not physical evolution."),
        ("cinematic-showcase", "Cinematic Showcase", "Montage of independent verified simulations."),
    ],
    "Butterfly Effect": [
        ("butterfly-effect", "Butterfly Effect", "Eight pendulums whose initial θ1 values span 1e-4 rad. The "
                                                 "right panel shows each member's state-space separation from the "
                                                 "reference on a log scale; the dotted curve is the numerical "
                                                 "control (same start, dt vs dt/2), which stays orders of magnitude "
                                                 "below the physical divergence."),
        ("pendulum-swarm", "100 Pendulums", "One hundred pendulums spread over 1e-4 rad in θ2: a single rod splits "
                                            "into a fan."),
        ("lyapunov-growth", "Lyapunov Growth", "Separation of two trajectories started 1e-8 apart (no "
                                               "renormalization) against d0·e^(λt), and the running finite-time "
                                               "Lyapunov estimate from the tangent-space method."),
    ],
    "Physics Experiments": [
        ("energy-conservation", "Energy Conservation", "Kinetic, potential and total energy on the same clock as the "
                                                       "motion, with the relative energy error of RK4 at dt = 1 ms."),
        ("double-flip", "Double Flip", "Both arms complete full rotations (verified by flip-event detection; the "
                                       "counter shows the detected events). Particle bursts fire at flips."),
        ("slow-motion", "Slow Motion", "The fastest moment of a chaotic run, replayed at 0.2× from DOP853 samples "
                                       "taken every 1 ms."),
        ("gravity-comparison", "Gravity Playground", "Identical starts under Moon, Earth and Jupiter-like constant "
                                                     "gravity, all on the same physical clock (simplified constant-"
                                                     "gravity experiments)."),
        ("mass-ratio", "Mass Ratio", "m2/m1 = 0.25, 1 and 4 from the same start."),
        ("damped-pendulum", "Damped Motion", "Viscous joint damping drains energy; the dashed curve is the energy "
                                             "balance E0 + W_drive − W_damp, which closes to quadrature accuracy."),
        ("driven-pendulum", "Driven Motion", "A sinusoidal pivot torque near the slow normal-mode frequency pumps "
                                             "energy in; the work done by the drive is integrated alongside."),
    ],
    "Chaos Maps": [
        ("chaos-map", "Chaos Heatmap", "A first-flip map computed row by row: time until either arm passes over "
                                       "the top, for every starting angle pair (released from rest)."),
        ("fractal-zoom", "Fractal Zoom", "A zoom into a boundary region of the first-flip map. Every level is "
                                         "recomputed from initial conditions — nothing is upscaled. Intricate "
                                         "boundaries are a hallmark of sensitivity, not a proof of fractality."),
    ],
    "Scientific Analysis": [
        ("phase-space", "Phase Space", "Pendulum motion beside its θ–ω projections (2D projections of the 4D state "
                                       "space; angles wrapped)."),
        ("poincare-section", "Poincaré Section", "Root-found crossings of θ1 = 0 with ω1 > 0 appear as the live "
                                                 "trajectory crosses; faint points are other trajectories at the "
                                                 "same energy."),
        ("regular-vs-chaotic", "Regular vs Chaotic", "A regular and a chaotic start side by side, labelled with their "
                                                     "finite-time Lyapunov estimates."),
    ],
    "Integrator Comparisons": [
        ("integrator-comparison", "Integrator Showdown", "RK4 (dt = 0.01 s), RK45 (rtol 1e-6) and DOP853 (rtol 1e-10) "
                                                         "from a near-inverted start, with their energy errors. The "
                                                         "trajectories separate after a few seconds even though all "
                                                         "three conserve energy well: divergence of chaotic runs is "
                                                         "not, by itself, evidence of a wrong integrator."),
    ],
}


def describe_config(c: dict) -> str:
    p, i, n = c["physical"], c["initial"], c["numerics"]
    parts = [f"θ1(0) = {i['theta1_deg']:g}°, θ2(0) = {i['theta2_deg']:g}°"]
    if i["omega1"] or i["omega2"]:
        parts.append(f"ω1(0) = {i['omega1']:g}, ω2(0) = {i['omega2']:g} rad/s")
    parts.append(f"m1 = {p['m1']:g}, m2 = {p['m2']:g} kg; L1 = {p['L1']:g}, L2 = {p['L2']:g} m; g = {p['g']:g} m/s²")
    if p["damping1"] or p["damping2"]:
        parts.append(f"damping b1 = {p['damping1']:g}, b2 = {p['damping2']:g} N·m·s/rad")
    if p["drive_amplitude"]:
        parts.append(f"drive {p['drive_amplitude']:g} cos({p['drive_frequency']:g} t) N·m")
    meth = n["method"].upper()
    parts.append(f"{meth} " + (f"dt = {n['dt']:g} s" if n["method"] == "rk4" else f"rtol = {n['rtol']:g}"))
    return "; ".join(parts)


def main():
    out = ["# Double Pendulum Simulator — Demo Gallery", "",
           "Every animation here is rendered from an actual simulation. Exact parameters below are read from the "
           "sidecar file that produced each asset (`assets/gifs/configs/<name>.json`). Physical time labels show "
           "simulated seconds; playback speed is stated when it is not 1×.", "",
           "Regenerate everything with `python scripts/generate_gallery.py` (≈ 4 minutes on an Apple M4), or a "
           "single asset with `--only <name>`.", ""]
    for section, items in SECTIONS.items():
        out += [f"## {section}", ""]
        for name, title, desc in items:
            side = json.loads((CFG_DIR / f"{name}.json").read_text())
            out += [f"### {title}", "", f"![{title}](../assets/gifs/{name}.gif)", "", desc, ""]
            if "config" in side:
                out.append(f"- **Parameters:** {describe_config(side['config'])}")
            elif "configs" in side:
                for lab, c in zip(side.get("labels", [None] * len(side["configs"])), side["configs"]):
                    out.append(f"- **{lab or c.get('name')}:** {describe_config(c)}")
            for key, labl in (("playback_speed", "Playback speed"), ("n", "Pendulums"), ("epsilon_rad", "Spread (rad)"),
                              ("energy_J", "Energy (J)"), ("lambda_finite_time", "Finite-time λ (1/s)"),
                              ("max_abs_rel_energy_error", "max |ΔE/E0|"), ("surface", "Section"),
                              ("center_deg", "Zoom centre (deg)")):
                if key in side:
                    v = side[key]
                    v = f"{v:.3g}" if isinstance(v, float) else v
                    out.append(f"- **{labl}:** {v}")
            if "map_spec" in side:
                ms = side["map_spec"]
                out.append(f"- **Map:** {ms['nx']}×{ms['ny']} pixels, θ ranges {ms['theta1_range']}°, t_max "
                           f"{ms['t_max']:g} s, RK4 dt {ms['dt']:g} s")
            out.append(f"- **Frames:** {side['frames']} at {side['fps']:g} fps")
            out.append(f"- **Reproduce:** `python scripts/generate_gallery.py --only {name}`")
            out.append(f"- **Saved configuration:** [`configs/{name}.json`](../assets/gifs/configs/{name}.json)")
            out.append("")
    out += ["## Video", "", "[`assets/videos/hero-chaos-720p.mp4`](../assets/videos/hero-chaos-720p.mp4) — 20 s, "
            "1280×720, 30 fps, with parameter overlay. Reproduce: "
            "`python scripts/generate_gallery.py --only video-hero`.", ""]
    (ROOT / "docs" / "gallery.md").write_text("\n".join(out))
    print("wrote docs/gallery.md")


if __name__ == "__main__":
    main()
