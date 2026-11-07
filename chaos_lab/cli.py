"""Chaos Lab command line: ``python -m chaos_lab <command>`` (or ``chaos-lab``)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def _cfg_from_args(a):
    from chaos_lab.core.config import SimConfig
    from chaos_lab.experiments import presets

    if getattr(a, "config", None):
        cfg = SimConfig.from_json(Path(a.config).read_text())
    elif getattr(a, "preset", None):
        cfg = presets.get(a.preset)["config"]
    else:
        cfg = SimConfig()
    changes = {}
    for key, path in (("theta1", "initial.theta1_deg"), ("theta2", "initial.theta2_deg"), ("omega1", "initial.omega1"),
                      ("omega2", "initial.omega2"), ("m1", "physical.m1"), ("m2", "physical.m2"),
                      ("L1", "physical.L1"), ("L2", "physical.L2"), ("g", "physical.g"),
                      ("damping", "physical.damping1"), ("t_max", "numerics.t_max"), ("dt", "numerics.dt"),
                      ("method", "numerics.method"), ("rtol", "numerics.rtol")):
        v = getattr(a, key, None)
        if v is not None:
            changes[path] = v
            if key == "damping":
                changes["physical.damping2"] = v
            if key == "rtol":
                changes["numerics.atol"] = v
    return cfg.with_(**changes).validate() if changes else cfg.validate()


def _add_cfg_args(p):
    g = p.add_argument_group("simulation")
    g.add_argument("--preset", help="preset id (see `presets`)")
    g.add_argument("--config", help="SimConfig JSON file")
    for k in ("theta1", "theta2"):
        g.add_argument(f"--{k}", type=float, help=f"initial {k} [deg]")
    for k in ("omega1", "omega2"):
        g.add_argument(f"--{k}", type=float, help=f"initial {k} [rad/s]")
    for k in ("m1", "m2", "L1", "L2", "g"):
        g.add_argument(f"--{k}", type=float)
    g.add_argument("--damping", type=float, help="viscous damping at both joints [N m s/rad]")
    g.add_argument("--t-max", dest="t_max", type=float, help="simulated time [s]")
    g.add_argument("--dt", type=float, help="RK4 step [s]")
    g.add_argument("--method", choices=["rk4", "rk45", "dop853"])
    g.add_argument("--rtol", type=float, help="adaptive tolerance (rtol = atol)")


def _style_from_args(a, **defaults):
    from chaos_lab.rendering import raster

    kw = dict(defaults)
    for k in ("palette", "trail", "glow", "particles", "camera", "background", "trail_seconds", "zoom", "seed",
              "motion_blur"):
        v = getattr(a, k, None)
        if v is not None:
            kw[k] = v
    if getattr(a, "custom_palette", None):
        from chaos_lab.rendering.palettes import custom_gradient

        kw["palette"] = custom_gradient(a.custom_palette.split(","))
    if getattr(a, "transparent", False):
        kw["transparent"] = True
    if getattr(a, "no_pendulum", False):
        kw["show_pendulum"] = False
    if getattr(a, "width", None):
        kw["width"] = a.width
    if getattr(a, "height", None):
        kw["height"] = a.height
    return raster.Style(**kw)


def _add_style_args(p):
    from chaos_lab.rendering import palettes, raster

    g = p.add_argument_group("style (visual only)")
    g.add_argument("--palette", choices=sorted(palettes.GRADIENTS))
    g.add_argument("--custom-palette", help="comma-separated hex colours, e.g. '#00E5FF,#FF3CAC'")
    g.add_argument("--trail", choices=raster.TRAIL_MODES)
    g.add_argument("--trail-seconds", dest="trail_seconds", type=float)
    g.add_argument("--glow", type=float)
    g.add_argument("--particles", choices=raster.PARTICLE_KINDS)
    g.add_argument("--camera", choices=raster.CAMERA_MODES)
    g.add_argument("--zoom", type=float)
    g.add_argument("--motion-blur", dest="motion_blur", type=int)
    g.add_argument("--background", help="hex colour")
    g.add_argument("--transparent", action="store_true")
    g.add_argument("--no-pendulum", action="store_true", help="draw only the trail")
    g.add_argument("--width", type=int)
    g.add_argument("--height", type=int)
    g.add_argument("--seed", type=int, help="particle seed")


# ---------------------------------------------------------------- commands
def cmd_simulate(a):
    from chaos_lab.analysis import events
    from chaos_lab.core.simulation import simulate
    from chaos_lab.exports import data

    cfg = _cfg_from_args(a)
    r = simulate(cfg)
    s = r.summary()
    s["rotations"] = events.rotation_counts(r.y)
    s["first_flip_s"] = events.first_flip_time(r.t, r.y)
    print(json.dumps(s, indent=2, default=float))
    if a.csv:
        Path(a.csv).write_text(data.to_csv(r))
        print(f"wrote {a.csv}")
    if a.bundle:
        data.bundle(r, a.bundle)
        print(f"wrote {a.bundle}")
    if a.save_config:
        Path(a.save_config).write_text(cfg.to_json())
        print(f"wrote {a.save_config}")


def cmd_render(a):
    from chaos_lab.exports import studio

    cfg = _cfg_from_args(a)
    style = _style_from_args(a)
    last = [-1]

    def prog(f):
        pct = int(f * 100)
        if pct // 10 != last[0]:
            last[0] = pct // 10
            print(f"  {pct:3d}%", flush=True)

    meta = studio.render_animation(cfg, a.output, style, preset=a.video_preset, fps=a.fps, speed=a.speed,
                                   t_start=a.t_start, t_end=a.t_end, title=a.title, show_params=a.params,
                                   show_timecode=not a.no_timecode, energy_graph=a.energy_graph, progress=prog)
    print(f"wrote {meta['output']} ({meta['frames']} frames) + sidecar JSON")


def cmd_art(a):
    from chaos_lab.exports import studio

    cfg = _cfg_from_args(a)
    style = _style_from_args(a, trail="exposure", palette="plasma", glow=0.9, show_pendulum=False)
    meta = studio.render_still(cfg, a.output, style, size=a.size, save_to_gallery=a.gallery)
    print(f"wrote {meta['output']} + sidecar JSON" + (f"; gallery copy {meta['gallery']}" if a.gallery else ""))


def cmd_figure(a):
    from chaos_lab.core.simulation import simulate
    from chaos_lab.exports import studio

    cfg = _cfg_from_args(a)
    r = simulate(cfg)
    panels = a.panels.split(",") if a.panels else studio.PANELS
    studio.scientific_figure(r, a.output, panels=panels, theme=a.theme)
    print(f"wrote {a.output}")


def cmd_map(a):
    import time

    from chaos_lab.core.config import Physical
    from chaos_lab.experiments import maps

    spec = maps.MapSpec(observable=a.observable, theta1_range=(a.t1[0], a.t1[1]), theta2_range=(a.t2[0], a.t2[1]),
                        nx=a.res, ny=a.res, t_max=a.t_max or 10.0, dt=a.dt or 0.005,
                        physical=Physical(g=a.g or 9.81))
    t0 = time.perf_counter()
    arr = maps.compute_map(spec, workers=a.workers, progress=lambda f, _: print(f"  {f:4.0%}", end="\r", flush=True))
    print(f"\ncomputed {spec.nx}x{spec.ny} {spec.observable} map in {time.perf_counter() - t0:.2f} s")
    np.save(Path(a.output).with_suffix(".npy"), arr)
    _save_map_png(arr, spec, a.output)
    Path(a.output + ".json").write_text(json.dumps(spec.to_dict(), indent=2))
    print(f"wrote {a.output} (+ .npy data, .json spec)")


def _save_map_png(arr, spec, path):
    import matplotlib.pyplot as plt

    from chaos_lab.rendering import figures

    figures.apply_theme("dark")
    fig, ax = plt.subplots(figsize=(7, 6))
    data = np.log10(np.maximum(arr, 1e-3)) if spec.observable == "first_flip" else arr
    im = ax.imshow(data, origin="lower", cmap="plasma", extent=[*spec.theta1_range, *spec.theta2_range],
                   interpolation="nearest", aspect="auto")
    cb = fig.colorbar(im, ax=ax)
    cb.set_label("log10 first-flip time [s]" if spec.observable == "first_flip" else spec.observable)
    ax.set_xlabel(r"$\theta_1(0)$ [deg]")
    ax.set_ylabel(r"$\theta_2(0)$ [deg]")
    ax.set_title(f"{spec.observable} · t_max {spec.t_max:g} s · RK4 dt {spec.dt:g} s")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def cmd_lyapunov(a):
    from chaos_lab.analysis import lyapunov

    cfg = _cfg_from_args(a)
    T = a.t_max or 60.0
    r = lyapunov.double_pendulum_lyapunov(cfg, T, dt=a.dt or 1e-3, renorm_interval=a.interval, d0=a.d0,
                                          method=a.estimator)
    print(f"finite-time largest Lyapunov exponent over {T:g} s: {r.lam:.4f} 1/s  ({r.method})")
    print(f"predictability horizon for 1e-6 -> 1e-1: {r.predictability_horizon(1e-6, 1e-1):.2f} s "
          "(assumes exponential growth at this rate)")
    if a.scan:
        s = lyapunov.sensitivity_scan(cfg, min(T, 30.0))
        print(f"estimator sensitivity: mean {s['mean']:.3f}, std {s['std']:.3f}, "
              f"range [{s['min']:.3f}, {s['max']:.3f}]")
    if a.csv:
        np.savetxt(a.csv, np.column_stack([r.t, r.running, r.local]), delimiter=",",
                   header="t [s],running_lambda [1/s],local_rate [1/s]", comments="")
        print(f"wrote {a.csv}")


def cmd_poincare(a):
    import matplotlib.pyplot as plt

    from chaos_lab.analysis import poincare
    from chaos_lab.core.config import Physical
    from chaos_lab.rendering import figures, palettes

    p = Physical()
    ics = poincare.fixed_energy_initials(p, a.energy, np.linspace(a.theta2_min, a.theta2_max, a.n))
    secs = poincare.multi_section(p, ics, t_max=a.t_max or 300.0)
    figures.apply_theme("dark")
    fig, ax = plt.subplots(figsize=(7, 6))
    for k, s in enumerate(secs):
        ax.scatter(s["theta2"], s["omega2"], s=1.5, color=palettes.distinct(len(secs))[k], lw=0)
    ax.set_xlabel(r"$\theta_2$ [rad]")
    ax.set_ylabel(r"$\omega_2$ [rad/s]")
    ax.set_title(rf"Poincaré section $\theta_1=0,\ \omega_1>0$, E = {a.energy:g} J")
    fig.tight_layout()
    fig.savefig(a.output, dpi=150)
    print(f"{len(ics)} trajectories, {sum(len(s['t']) for s in secs)} crossings -> {a.output}")


def cmd_butterfly(a):
    from chaos_lab.experiments import ensemble

    cfg = _cfg_from_args(a)
    b = ensemble.butterfly(cfg, n=a.n, epsilon=a.epsilon, variable=a.variable, distribution=a.distribution,
                           seed=a.seed_perturb, threshold=a.threshold)
    print(json.dumps(b["stats"], indent=2))
    print(f"integration: {b['runtime_s']:.2f} s, {b['steps_per_second']:.3g} pendulum-steps/s")


def cmd_modes(a):
    from chaos_lab.analysis import linear

    cfg = _cfg_from_args(a)
    nm = linear.normal_modes(cfg.physical)
    for k in range(2):
        print(f"mode {k + 1}: omega = {nm['omega'][k]:.4f} rad/s, period = {nm['period_s'][k]:.4f} s, "
              f"theta2/theta1 = {nm['shape_ratio_theta2_over_theta1'][k]:+.4f}")
    for e in linear.equilibria(cfg.physical):
        print(f"{e['name']:>9}: V = {e['potential_energy']:+8.3f} J  {e['classification']}")


def cmd_integrators(a):
    from chaos_lab.experiments import integrator_lab

    cfg = _cfg_from_args(a)
    res = integrator_lab.compare(cfg)
    print(f"{'setting':<22}{'runtime [s]':>12}{'nfev':>10}{'max|dE/E0|':>13}{'final diff':>12}")
    for r in res["rows"]:
        print(f"{r['label']:<22}{r['runtime_s']:>12.3f}{r['nfev']:>10}{r['max_abs_rel_energy_error']:>13.2e}"
              f"{r['final_state_difference']:>12.2e}")
    print("final diff = wrapped state-space distance to a DOP853 rtol=1e-13 reference at t_max")


def cmd_presets(a):
    from chaos_lab.experiments import presets

    if a.show:
        print(json.dumps(presets.to_json(presets.get(a.show)), indent=2))
        return
    for p in presets.PRESETS:
        print(f"{p['id']:<22} {p['title']:<34} {p['mode']}")


def cmd_challenge(a):
    from chaos_lab.experiments import challenges

    if not a.id:
        for c in challenges.CHALLENGES:
            print(f"{c['id']:<12} {c['title']:<24} {c['goal']}")
        return
    inp = dict(kv.split("=", 1) for kv in a.inputs)
    r = challenges.evaluate(a.id, inp)
    print(("SUCCESS: " if r["success"] else "NOT YET: ") + r["feedback"])


def cmd_art_search(a):
    from chaos_lab.experiments import art

    res = art.search(a.objective, n_candidates=a.n, top=a.top, seed=a.seed_search, t_max=a.t_max or 30.0)
    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for k, r in enumerate(res):
        (out / f"candidate_{k:02d}.json").write_text(r["config"].to_json())
        m = r["metrics"]
        print(f"#{k}: score {r['score']:.3f}  coverage {m['coverage']:.2f}  symmetry {m['symmetry']:.2f}  "
              f"loops {m['loops']:.0f}  -> {out / f'candidate_{k:02d}.json'}")
    print("render one with: python -m chaos_lab art --config <file> -o art.png --size 4k")


def cmd_bench(a):
    from chaos_lab import benchmarks

    benchmarks.main((["--quick"] if a.quick else []) + (["--output", a.output] if a.output else []))


def cmd_serve(a):
    try:
        from chaos_lab.app.server import main as serve_main
    except ImportError as e:
        sys.exit(f"The interactive dashboard is not installed in this checkout ({e}).")
    serve_main(a.rest)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["serve"]:
        # argparse.REMAINDER does not capture options such as "--port" inside a
        # subparser, so hand everything after "serve" to the dashboard directly.
        return cmd_serve(argparse.Namespace(rest=argv[1:]))
    ap = argparse.ArgumentParser(prog="chaos-lab", description="Chaos Lab Ultra — double pendulum chaos laboratory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("simulate", help="run a simulation and print diagnostics")
    _add_cfg_args(p)
    p.add_argument("--csv")
    p.add_argument("--bundle", help="write a reproducible .zip bundle")
    p.add_argument("--save-config")
    p.set_defaults(fn=cmd_simulate)

    p = sub.add_parser("render", help="render an animation (gif/mp4/webm or a directory for PNGs)")
    _add_cfg_args(p)
    _add_style_args(p)
    p.add_argument("-o", "--output", required=True)
    from chaos_lab.exports.media import IMAGE_PRESETS, VIDEO_PRESETS

    p.add_argument("--video-preset", choices=sorted(VIDEO_PRESETS))
    p.add_argument("--fps", type=float)
    p.add_argument("--speed", type=float, default=1.0, help="physical seconds per playback second")
    p.add_argument("--t-start", type=float, default=0.0)
    p.add_argument("--t-end", type=float)
    p.add_argument("--title")
    p.add_argument("--params", action="store_true", help="overlay parameters")
    p.add_argument("--no-timecode", action="store_true")
    p.add_argument("--energy-graph", action="store_true")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("art", help="high-resolution long-exposure artwork (png/svg)")
    _add_cfg_args(p)
    _add_style_args(p)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--size", choices=sorted(IMAGE_PRESETS))
    p.add_argument("--gallery", action="store_true", help="also save to ~/.chaos_lab/artworks")
    p.set_defaults(fn=cmd_art)

    p = sub.add_parser("figure", help="multi-panel scientific figure (png/svg/pdf)")
    _add_cfg_args(p)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--panels", help="comma-separated: " + ",".join(__import__("chaos_lab.exports.studio",
                                                                            fromlist=["PANELS"]).PANELS))
    p.add_argument("--theme", choices=["dark", "light"], default="dark")
    p.set_defaults(fn=cmd_figure)

    p = sub.add_parser("map", help="initial-condition (fractal) map")
    p.add_argument("--observable", default="first_flip",
                   choices=["first_flip", "rotations", "max_omega", "sensitivity", "energy"])
    p.add_argument("--res", type=int, default=300)
    p.add_argument("--t1", type=float, nargs=2, default=(-180, 180), metavar=("MIN", "MAX"))
    p.add_argument("--t2", type=float, nargs=2, default=(-180, 180), metavar=("MIN", "MAX"))
    p.add_argument("--t-max", dest="t_max", type=float)
    p.add_argument("--dt", type=float)
    p.add_argument("--g", type=float)
    p.add_argument("--workers", type=int)
    p.add_argument("-o", "--output", default="map.png")
    p.set_defaults(fn=cmd_map)

    p = sub.add_parser("lyapunov", help="finite-time largest Lyapunov exponent")
    _add_cfg_args(p)
    p.add_argument("--estimator", choices=["tangent", "two_trajectory"], default="tangent")
    p.add_argument("--interval", type=float, default=0.1, help="renormalization interval [s]")
    p.add_argument("--d0", type=float, default=1e-8)
    p.add_argument("--scan", action="store_true", help="estimator-settings sensitivity analysis")
    p.add_argument("--csv")
    p.set_defaults(fn=cmd_lyapunov)

    p = sub.add_parser("poincare", help="Poincaré section at fixed energy")
    p.add_argument("--energy", type=float, default=-15.0)
    p.add_argument("--n", type=int, default=8)
    p.add_argument("--theta2-min", type=float, default=0.1)
    p.add_argument("--theta2-max", type=float, default=2.2)
    p.add_argument("--t-max", dest="t_max", type=float)
    p.add_argument("-o", "--output", default="poincare.png")
    p.set_defaults(fn=cmd_poincare)

    p = sub.add_parser("butterfly", help="ensemble divergence statistics")
    _add_cfg_args(p)
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--epsilon", type=float, default=1e-6)
    p.add_argument("--variable", choices=["theta1", "theta2", "omega1", "omega2"], default="theta1")
    p.add_argument("--distribution", choices=["linear", "gaussian"], default="linear")
    p.add_argument("--seed-perturb", type=int, default=0)
    p.add_argument("--threshold", type=float, default=0.5)
    p.set_defaults(fn=cmd_butterfly)

    p = sub.add_parser("modes", help="normal modes and equilibrium stability")
    _add_cfg_args(p)
    p.set_defaults(fn=cmd_modes)

    p = sub.add_parser("integrators", help="compare RK4 / RK45 / DOP853")
    _add_cfg_args(p)
    p.set_defaults(fn=cmd_integrators)

    p = sub.add_parser("presets", help="list presets")
    p.add_argument("--show")
    p.set_defaults(fn=cmd_presets)

    p = sub.add_parser("challenge", help="list or evaluate chaos challenges")
    p.add_argument("id", nargs="?")
    p.add_argument("inputs", nargs="*", help="key=value pairs")
    p.set_defaults(fn=cmd_challenge)

    p = sub.add_parser("art-search", help="search for visually interesting trajectories")
    p.add_argument("--objective", default="complexity",
                   choices=["coverage", "symmetry", "dense", "loops", "complexity", "sparse", "exposure"])
    p.add_argument("--n", type=int, default=128)
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--seed-search", type=int, default=0)
    p.add_argument("--t-max", dest="t_max", type=float)
    p.add_argument("--output-dir", default="art_candidates")
    p.set_defaults(fn=cmd_art_search)

    p = sub.add_parser("bench", help="run the benchmark suite")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--output")
    p.set_defaults(fn=cmd_bench)

    p = sub.add_parser("serve", help="launch the interactive dashboard")
    p.add_argument("rest", nargs=argparse.REMAINDER, help="options passed to the dashboard server")
    p.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except (ValueError, KeyError) as e:
        ap.exit(2, f"error: {e}\n")


if __name__ == "__main__":
    main()
