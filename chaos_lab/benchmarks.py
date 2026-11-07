"""Reproducible benchmark suite.

    python -m chaos_lab bench            # full suite -> benchmarks/results.json + .md
    python -m chaos_lab bench --quick    # smaller sizes

Every number is measured on the machine running it; the report records the
hardware, OS, Python and dependency versions and all benchmark settings.
Integration throughput (pendulum-steps per second) is reported separately
from rendering throughput (frames per second).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import tempfile
import time
import tracemalloc
from pathlib import Path

import numpy as np

from chaos_lab.core.config import Initial, Numerics, Physical, SimConfig
from chaos_lab.core.simulation import simulate
from chaos_lab.exports.data import reproducibility_stamp


def hardware() -> dict:
    info = {"machine": platform.machine(), "processor": platform.processor(), "cpu_count": os.cpu_count()}
    try:
        if platform.system() == "Darwin":
            info["cpu"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                         text=True).stdout.strip()
            info["memory_gb"] = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                                   text=True).stdout) / 2**30
        elif Path("/proc/cpuinfo").exists():
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
    except Exception:  # noqa: BLE001
        pass
    return info


def timed(fn, repeat=3):
    best = np.inf
    out = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = fn()
        best = min(best, time.perf_counter() - t0)
    return best, out


def peak_memory(fn):
    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 2**20


def run(quick: bool = False) -> dict:
    from chaos_lab.experiments import ensemble, integrator_lab, maps
    from chaos_lab.exports import media, studio
    from chaos_lab.rendering import raster

    res = {"settings": {"quick": quick}, "results": []}

    def add(name, value, unit, **settings):
        res["results"].append({"name": name, "value": float(value), "unit": unit, "settings": settings})
        print(f"  {name:<44} {value:>12.4g} {unit}")

    T = 10.0 if quick else 30.0
    cfg = SimConfig(Physical(), Initial(120, -10), Numerics(t_max=T, dt=1e-3, output_dt=1 / 60))

    # single-trajectory integration
    t, r = timed(lambda: simulate(cfg), 3)
    add("RK4 single trajectory", T / 1e-3 / t, "steps/s", t_max=T, dt=1e-3)
    add("RK4 single trajectory wall time", t, "s", t_max=T, dt=1e-3)
    for m, tol in (("rk45", 1e-10), ("dop853", 1e-10)):
        c = cfg.with_(**{"numerics.method": m, "numerics.rtol": tol, "numerics.atol": tol})
        t, r = timed(lambda c=c: simulate(c), 3)
        add(f"{m.upper()} wall time (rtol=atol={tol:g})", t, "s", t_max=T, nfev=r.nfev)
        add(f"{m.upper()} max |dE/E0|", np.max(np.abs(r.relative_energy_error)), "1", rtol=tol)

    # energy drift and convergence
    for dt in (4e-3, 2e-3, 1e-3):
        r = simulate(cfg.with_(**{"numerics.dt": dt}))
        add(f"RK4 max |dE/E0| (dt={dt:g})", np.max(np.abs(r.relative_energy_error)), "1", t_max=T)
    conv = integrator_lab.rk4_convergence(cfg, dts=(0.004, 0.002, 0.001), t_max=3.0)
    add("RK4 observed order (final-state error)", conv["observed_order"], "", dts=conv["dt"], t_max=3.0)

    # ensembles
    sizes = (10, 100) if quick else (10, 100, 1000)
    for n in sizes:
        Te = 5.0 if n >= 1000 else 10.0
        ce = cfg.with_(**{"numerics.t_max": Te, "numerics.dt": 2e-3})
        y0 = np.tile(ce.initial.state(), (n, 1)) + np.linspace(0, 1e-6, n)[:, None] * [1, 0, 0, 0]
        t, _ = timed(lambda y0=y0, ce=ce, Te=Te: ensemble.integrate_batch(ce.physical, y0, Te, 2e-3, 1 / 60), 1)
        add(f"{n}-pendulum ensemble RK4", n * Te / 2e-3 / t, "pendulum-steps/s", t_max=Te, dt=2e-3, wall_s=t)

    # chaos map
    res_px = 100 if quick else 200
    spec = maps.MapSpec(nx=res_px, ny=res_px, t_max=10.0, dt=0.005)
    t, _ = timed(lambda: maps.compute_map(spec, use_cache=False), 1)
    add(f"first-flip map {res_px}x{res_px} (parallel)", t, "s", workers=max(1, (os.cpu_count() or 2) - 1),
        t_max=10.0, dt=0.005)
    t1, _ = timed(lambda: maps.compute_map(spec, workers=1, use_cache=False), 1)
    add(f"first-flip map {res_px}x{res_px} (1 process)", t1, "s")
    add("map parallel speed-up", t1 / t, "x")

    # rendering and export
    r = simulate(cfg.with_(**{"numerics.t_max": 5.0, "numerics.output_dt": 1 / 120}))
    st = raster.Style(width=640, height=640)
    R = studio.make_renderer(r, st)
    n_frames = 60
    t0 = time.perf_counter()
    for i in np.linspace(0, len(r.t) - 1, n_frames).astype(int):
        R.render(int(i))
    add("raster render 640x640 (fade trail + glow)", n_frames / (time.perf_counter() - t0), "frames/s")
    with tempfile.TemporaryDirectory() as d:
        c5 = cfg.with_(**{"numerics.t_max": 5.0})
        t, _ = timed(lambda: studio.render_animation(c5, Path(d) / "b.gif", raster.Style(width=480, height=480),
                                                     fps=20), 1)
        add("GIF export 5 s @ 20 fps, 480x480", t, "s", frames=100)
        if media.available_formats()["mp4"]:
            t, _ = timed(lambda: studio.render_animation(c5, Path(d) / "b.mp4", raster.Style(width=1280,
                                                                                               height=720), fps=30), 1)
            add("MP4 export 5 s @ 30 fps, 1280x720", t, "s", frames=150)

    # memory
    add("peak traced memory: 30 s RK4 run (1/240 s output)",
        peak_memory(lambda: simulate(cfg.with_(**{"numerics.output_dt": 1 / 240}))), "MiB")
    add("peak traced memory: 100-pendulum ensemble 10 s",
        peak_memory(lambda: ensemble.integrate_batch(cfg.physical, np.tile(cfg.initial.state(), (100, 1)), 10.0,
                                                     2e-3, 1 / 60)), "MiB")
    res["environment"] = {"hardware": hardware(), **reproducibility_stamp()}
    return res


def to_markdown(res: dict) -> str:
    env = res["environment"]
    hw = env["hardware"]
    lines = [
        "| Benchmark | Value | Unit |",
        "|---|---:|---|",
    ]
    for r in res["results"]:
        v = r["value"]
        txt = f"{v:.3g}" if (abs(v) < 1e-2 or abs(v) >= 1e5) else f"{v:,.3f}".rstrip("0").rstrip(".")
        lines.append(f"| {r['name']} | {txt} | {r['unit']} |")
    lines += ["", f"Measured on {hw.get('cpu', hw.get('machine'))} ({hw.get('cpu_count')} logical CPUs"
              + (f", {hw['memory_gb']:.0f} GB RAM" if "memory_gb" in hw else "") + f"), {env['platform']}; "
              f"Python {env['python']}, NumPy {env['numpy']}, SciPy {env['scipy']}, Matplotlib {env['matplotlib']}; "
              f"chaos_lab {env['chaos_lab_version']} (commit {env['git_commit']}), {env['created_utc']}."]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--output", default="benchmarks/results")
    a = ap.parse_args(argv)
    print("Chaos Lab benchmarks" + (" (quick)" if a.quick else ""))
    res = run(a.quick)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(res, indent=2))
    out.with_suffix(".md").write_text(to_markdown(res) + "\n")
    print(f"wrote {out.with_suffix('.json')} and {out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
