"""Regenerate every demo asset in assets/gifs/ from actual simulations.

    python scripts/generate_gallery.py              # all
    python scripts/generate_gallery.py --list
    python scripts/generate_gallery.py --only hero-chaos,butterfly-effect

Each GIF is written with a sidecar JSON (assets/gifs/configs/<name>.json)
holding the exact simulation configuration, numerical settings, playback
speed and a reproducibility stamp. Physical time labels always show simulated
seconds; playback speed is stated whenever it is not 1x.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chaos_lab import Initial, Numerics, Physical, SimConfig, simulate  # noqa: E402
from chaos_lab.analysis import events, lyapunov, poincare  # noqa: E402
from chaos_lab.core import physics  # noqa: E402
from chaos_lab.experiments import ensemble, maps, presets  # noqa: E402
from chaos_lab.exports import data as data_export  # noqa: E402
from chaos_lab.exports.media import save_gif  # noqa: E402
from chaos_lab.rendering import figures, palettes, raster  # noqa: E402

OUT = ROOT / "assets" / "gifs"
CFG_DIR = OUT / "configs"
TOK = palettes.TOKENS["dark"]
GENERATORS = {}


def gen(name):
    def deco(fn):
        GENERATORS[name] = fn
        return fn
    return deco


# ---------------------------------------------------------------------------- helpers
def run(cfg: SimConfig, output_dt: float):
    r = simulate(cfg.with_(**{"numerics.output_dt": output_dt}))
    if not r.success:
        raise RuntimeError(r.message)
    return r


def frame_indices(t, fps, speed=1.0, t0=0.0, t1=None):
    """Sample indices so that playback advances `speed` physical seconds per real second."""
    t1 = t[-1] if t1 is None else t1
    times = np.arange(t0, t1 + 1e-9, speed / fps)
    return np.clip(np.searchsorted(t, times - 1e-9), 0, len(t) - 1)


def fade(frames, n_in=6, n_out=10, bg=TOK["bg"]):
    """Fade from/to the background so the loop restarts cleanly (no false periodicity)."""
    bgc = Image.new("RGB", frames[0].size, bg)
    out = list(frames)
    for k in range(min(n_in, len(out))):
        out[k] = Image.blend(bgc, out[k].convert("RGB"), (k + 1) / (n_in + 1))
    for k in range(min(n_out, len(out))):
        j = len(out) - 1 - k
        out[j] = Image.blend(bgc, out[j].convert("RGB"), (k + 1) / (n_out + 1))
    return out


def label(img, text, xy=(0.035, 0.035), size=15, color=TOK["text"], mono=True, anchor="la"):
    raster._text(img, xy[0], xy[1], text, size=size, color=color, mono=mono, anchor=anchor)
    return img


def tag(img, text, size=13):
    """Small rounded caption chip, bottom-left."""
    d = ImageDraw.Draw(img, "RGBA")
    f = raster.font(size)
    w = d.textlength(text, font=f)
    x, y = 14, img.height - size - 22
    d.rounded_rectangle([x - 8, y - 6, x + w + 8, y + size + 8], radius=8, fill=(16, 21, 34, 210),
                        outline=(35, 44, 66, 255))
    d.text((x, y), text, font=f, fill=TOK["text_2"])
    return img


def hstack(*imgs):
    w = sum(i.width for i in imgs)
    h = max(i.height for i in imgs)
    out = Image.new("RGB", (w, h), TOK["bg"])
    x = 0
    for i in imgs:
        out.paste(i.convert("RGB"), (x, 0))
        x += i.width
    return out


def grid(imgs, cols):
    rows = (len(imgs) + cols - 1) // cols
    w, h = imgs[0].size
    out = Image.new("RGB", (w * cols, h * rows), TOK["bg"])
    for k, im in enumerate(imgs):
        out.paste(im.convert("RGB"), ((k % cols) * w, (k // cols) * h))
    return out


class Plot:
    """A matplotlib panel redrawn per frame and returned as a PIL image."""

    def __init__(self, w, h, nrows=1, ncols=1, **kw):
        figures.apply_theme("dark")
        self.fig, axes = plt.subplots(nrows, ncols, figsize=(w / 100, h / 100), dpi=100, **kw)
        self.axes = np.atleast_1d(axes).ravel()

    def image(self):
        return figures.fig_to_image(self.fig)

    def close(self):
        plt.close(self.fig)


def pend_renderer(result, size, **style):
    st = raster.Style(width=size[0], height=size[1], **style)
    p = result.config.physical
    return raster.PendulumRenderer(result.t, raster.xy_from_result(result), st, raster.world_extent(p.L1, p.L2),
                                   scalars=raster.scalars_for(result),
                                   events=[e["t"] for e in events.flip_events(result.t, result.y)])


def write(name, frames, fps, meta, colors=112, max_width=720, max_fps=12):
    """Save a GIF within a size budget: frames are decimated (preserving physical timing) to at
    most ``max_fps`` and downscaled to ``max_width`` pixels."""
    step = max(1, int(round(fps / max_fps)))
    if step > 1:
        frames, fps = frames[::step], fps / step
    if frames[0].width > max_width:
        h = int(frames[0].height * max_width / frames[0].width)
        frames = [f.convert("RGB").resize((max_width, h), Image.LANCZOS) for f in frames]
    path = OUT / f"{name}.gif"
    save_gif(frames, path, fps=fps, colors=colors)
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    meta = {"asset": f"assets/gifs/{name}.gif", "fps": fps, "frames": len(frames), **meta,
            "stamp": data_export.reproducibility_stamp()}
    (CFG_DIR / f"{name}.json").write_text(json.dumps(meta, indent=2, default=_json_default))
    print(f"  {name}.gif  {len(frames)} frames  {path.stat().st_size / 1e6:.2f} MB")
    return path


def _json_default(o):
    if isinstance(o, SimConfig):
        return o.to_dict()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def ensemble_xy(b, p):
    return np.stack(physics.positions(b["Y"], p), axis=-1)


# ---------------------------------------------------------------------------- 01 hero
@gen("hero-chaos")
def hero():
    cfg = SimConfig(Physical(), Initial(160, 20), Numerics(t_max=9), "Hero Chaos")
    r = run(cfg, 1 / 120)
    R = pend_renderer(r, (520, 520), palette="rainbow", trail="fade", trail_seconds=4.0, glow=1.0,
                      trail_width=2.6, bob_radius=10)
    fps = 18
    frames = []
    for i in frame_indices(r.t, fps):
        im = R.render(i)
        label(im, f"t = {r.t[i]:5.2f} s", size=13, color=TOK["text_2"])
        frames.append(im)
    return write("hero-chaos", fade(frames), fps, {"config": cfg, "playback_speed": 1.0,
                                                   "notes": "Rainbow trail; glow is a rendering effect."},
                 colors=128, max_fps=18)


# ---------------------------------------------------------------------------- 02 butterfly
@gen("butterfly-effect")
def butterfly():
    cfg = SimConfig(Physical(), Initial(135, -45), Numerics(t_max=13, dt=1e-3, output_dt=1 / 60), "Butterfly")
    n, eps = 8, 1e-4
    b = ensemble.butterfly(cfg, n=n, epsilon=eps, variable="theta1", threshold=0.5)
    p = cfg.physical
    cols = palettes.distinct(n, "rainbow")
    R = raster.PendulumRenderer(b["t"], ensemble_xy(b, p), raster.Style(width=400, height=400, trail="fade",
                                trail_seconds=1.0, glow=0.6, rod_width=2.2), raster.world_extent(1, 1), colors=cols)
    P = Plot(440, 400)
    ax = P.axes[0]
    t = b["t"]
    sep = b["separation"]
    for k in range(1, n):
        ax.semilogy(t, np.maximum(sep[:, k], 1e-12), color="#2A3348", lw=1)
    ax.semilogy(t, np.maximum(b["numerical_control"], 1e-16), color=TOK["text_2"], lw=1, ls=":",
                label="numerical control (dt vs dt/2)")
    ax.axhline(b["threshold"], color=TOK["gold"], lw=1, ls="--", label="divergence threshold")
    lines = [ax.semilogy([], [], color=cols[k], lw=1.6)[0] for k in range(1, n)]
    head = ax.axvline(0, color=TOK["text_2"], lw=0.8, alpha=0.6)
    ax.set_ylim(1e-9, 20)
    ax.set_xlim(0, t[-1])
    ax.set_xlabel("time [s]")
    ax.set_ylabel("state-space separation (dimensionless)")
    ax.set_title(f"{n} pendulums, θ1 spread over {eps:g} rad")
    ax.legend(loc="lower right")
    P.fig.tight_layout()
    fps = 12
    frames = []
    for i in frame_indices(t, fps):
        for k, ln in enumerate(lines, start=1):
            ln.set_data(t[: i + 1], np.maximum(sep[: i + 1, k], 1e-12))
        head.set_xdata([t[i], t[i]])
        left = R.render(i)
        label(left, f"t = {t[i]:5.2f} s", size=13, color=TOK["text_2"])
        frames.append(hstack(left, P.image()))
    P.close()
    return write("butterfly-effect", fade(frames), fps,
                 {"config": cfg, "n": n, "epsilon_rad": eps, "variable": "theta1", "playback_speed": 1.0,
                  "separation_metric": "||(wrap dθ1, wrap dθ2, τ dω1, τ dω2)||, τ = sqrt(L1/g)",
                  "divergence_times": b["divergence_times"]})


# ---------------------------------------------------------------------------- 03 swarm
@gen("pendulum-swarm")
def swarm():
    cfg = SimConfig(Physical(), Initial(150, 150), Numerics(t_max=16, dt=2e-3, output_dt=1 / 60), "Swarm")
    n, eps = 100, 1e-4
    b = ensemble.butterfly(cfg, n=n, epsilon=eps, variable="theta2", numerical_control=False)
    R = raster.PendulumRenderer(b["t"], ensemble_xy(b, cfg.physical), raster.Style(width=360, height=360,
                                trail="fade", trail_seconds=0.35, glow=0.45, trail_width=1.2),
                                raster.world_extent(1, 1), colors=palettes.distinct(n, "rainbow"))
    fps = 10
    frames = []
    for i in frame_indices(b["t"], fps):
        im = R.render(i)
        label(im, f"t = {b['t'][i]:5.2f} s", size=13, color=TOK["text_2"])
        tag(im, f"100 pendulums · θ2 spread over {eps:g} rad")
        frames.append(im)
    return write("pendulum-swarm", fade(frames), fps, {"config": cfg, "n": n, "epsilon_rad": eps,
                                                       "variable": "theta2", "playback_speed": 1.0}, colors=64)


# ---------------------------------------------------------------------------- 04 long exposure
@gen("long-exposure")
def long_exposure():
    cfg = presets.get("long_exposure")["config"].with_(**{"numerics.t_max": 45})
    r = run(cfg, 1 / 240)
    speed, fps = 4.0, 20
    R = pend_renderer(r, (500, 500), palette="plasma", trail="exposure", glow=0.9, trail_width=1.6)
    frames = []
    for i in frame_indices(r.t, fps, speed):
        im = R.render(i)
        label(im, f"t = {r.t[i]:5.1f} s", size=13, color=TOK["text_2"])
        tag(im, f"long exposure · {speed:g}× speed")
        frames.append(im)
    frames += [frames[-1]] * 20
    return write("long-exposure", fade(frames, n_out=12), fps, {"config": cfg, "playback_speed": speed})


# ---------------------------------------------------------------------------- 05 energy
@gen("energy-conservation")
def energy():
    cfg = SimConfig(Physical(), Initial(120, -10), Numerics(t_max=12, dt=1e-3), "Energy Conservation")
    r = run(cfg, 1 / 240)
    e = r.energy
    err = r.relative_energy_error
    R = pend_renderer(r, (440, 440), palette="cyan", trail="fade", trail_seconds=2.0, glow=0.7)
    P = Plot(500, 440, 2, 1, sharex=True)
    a1, a2 = P.axes
    t = r.t
    for arr in (e["T"], e["V"], e["E"]):  # full-run backdrop curves
        a1.plot(t, arr, color="#222B40", lw=1)
    lT, = a1.plot([], [], color=TOK["cyan"], lw=1.5, label="kinetic T")
    lV, = a1.plot([], [], color=TOK["pink"], lw=1.5, label="potential V")
    lE, = a1.plot([], [], color=TOK["green"], lw=1.8, label="total E")
    a1.set_ylabel("energy [J]")
    a1.legend(loc="upper right", ncol=3)
    a1.set_title("Energy (RK4, dt = 1 ms)")
    a2.plot(t, err, color="#222B40", lw=1)
    lErr, = a2.plot([], [], color=TOK["gold"], lw=1.4)
    a2.set_ylabel(r"$(E-E_0)/|E_0|$")
    a2.set_xlabel("time [s]")
    a2.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
    a2.set_xlim(0, t[-1])
    heads = [a.axvline(0, color=TOK["text_2"], lw=0.8, alpha=0.5) for a in (a1, a2)]
    P.fig.tight_layout()
    fps = 15
    frames = []
    for i in frame_indices(t, fps):
        for ln, arr in ((lT, e["T"]), (lV, e["V"]), (lE, e["E"]), (lErr, err)):
            ln.set_data(t[: i + 1], arr[: i + 1])
        for h in heads:
            h.set_xdata([t[i], t[i]])
        left = R.render(i)
        label(left, f"t = {t[i]:5.2f} s", size=13, color=TOK["text_2"])
        frames.append(hstack(left, P.image()))
    P.close()
    return write("energy-conservation", fade(frames), fps,
                 {"config": cfg, "playback_speed": 1.0, "max_abs_rel_energy_error": float(np.max(np.abs(err)))})


# ---------------------------------------------------------------------------- 06 phase space
@gen("phase-space")
def phase_space():
    cfg = SimConfig(Physical(), Initial(100, 60), Numerics(t_max=24), "Phase Space")
    r = run(cfg, 1 / 120)
    speed, fps = 2.0, 15
    R = pend_renderer(r, (420, 420), palette="purple", trail="fade", trail_seconds=2.0, glow=0.7)
    P = Plot(560, 420, 1, 2)
    t = r.t
    th1, th2 = physics.wrap_angle(r.y[:, 0]), physics.wrap_angle(r.y[:, 1])
    w1, w2 = r.y[:, 2], r.y[:, 3]
    arts = []
    for ax, th, w, c, name in ((P.axes[0], th1, w1, TOK["cyan"], "1"), (P.axes[1], th2, w2, TOK["pink"], "2")):
        ax.set_xlim(-np.pi, np.pi)
        ax.set_ylim(w.min() * 1.1, w.max() * 1.1)
        ax.set_xlabel(rf"$\theta_{name}$ [rad] (wrapped)")
        ax.set_ylabel(rf"$\omega_{name}$ [rad/s]")
        ax.set_title(rf"$\theta_{name}$ vs $\omega_{name}$")
        sc = ax.scatter([], [], s=1.2, c=[], cmap="plasma", vmin=0, vmax=t[-1])
        hd, = ax.plot([], [], "o", color=c, ms=6)
        arts.append((sc, hd, th, w))
    P.fig.tight_layout()
    frames = []
    for i in frame_indices(t, fps, speed):
        for sc, hd, th, w in arts:
            sc.set_offsets(np.column_stack([th[: i + 1:2], w[: i + 1:2]]))
            sc.set_array(t[: i + 1:2])
            hd.set_data([th[i]], [w[i]])
        left = R.render(i)
        label(left, f"t = {t[i]:5.2f} s", size=13, color=TOK["text_2"])
        tag(left, f"{speed:g}× speed · colour = time")
        frames.append(hstack(left, P.image()))
    P.close()
    return write("phase-space", fade(frames), fps,
                 {"config": cfg, "playback_speed": speed,
                  "note": "2D projections of the 4D state space; angles wrapped to [-π, π)."})


# ---------------------------------------------------------------------------- 07 poincaré
@gen("poincare-section")
def poincare_gif():
    p = Physical()
    E = -15.0
    ics = poincare.fixed_energy_initials(p, E, [0.1, 0.4, 0.8, 1.2, 1.6, 2.0, 2.3])
    T = 300.0
    secs = poincare.multi_section(p, ics, t_max=T, workers=4)
    focus = 4  # trajectory shown live
    y0 = ics[focus]
    cfg = SimConfig(p, Initial(np.degrees(y0[0]), np.degrees(y0[1]), y0[2], y0[3]),
                    Numerics(method="dop853", t_max=12, rtol=1e-10, atol=1e-10), "Poincaré focus")
    r = run(cfg, 1 / 120)
    R = pend_renderer(r, (420, 420), palette="gold", trail="fade", trail_seconds=1.5, glow=0.7)
    P = Plot(480, 420)
    ax = P.axes[0]
    cols = palettes.distinct(len(ics), "rainbow")
    for k, s in enumerate(secs):
        if k != focus:
            ax.scatter(s["theta2"], s["omega2"], s=2.5, color=cols[k], alpha=0.5, lw=0)
    ax.set_xlabel(r"$\theta_2$ [rad]")
    ax.set_ylabel(r"$\omega_2$ [rad/s]")
    ax.set_title(r"Section $\theta_1 = 0,\ \omega_1 > 0$  (E = −15 J)")
    allx = np.concatenate([s["theta2"] for s in secs])
    ally = np.concatenate([s["omega2"] for s in secs])
    ax.set_xlim(allx.min() - 0.1, allx.max() + 0.1)
    ax.set_ylim(ally.min() - 0.5, ally.max() + 0.5)
    fs = secs[focus]
    ft = np.array(fs["t"])
    live = ax.scatter([], [], s=9, color=cols[focus], edgecolor="white", lw=0.3, zorder=5)
    flash = ax.scatter([], [], s=80, facecolor="none", edgecolor="white", lw=1.2, zorder=6)
    P.fig.tight_layout()
    fps = 15
    frames = []
    for i in frame_indices(r.t, fps):  # phase A: real time
        n = int(np.searchsorted(ft, r.t[i], side="right"))
        live.set_offsets(np.column_stack([fs["theta2"][:n], fs["omega2"][:n]]) if n else np.empty((0, 2)))
        recent = n and r.t[i] - ft[n - 1] < 0.4
        flash.set_offsets([[fs["theta2"][n - 1], fs["omega2"][n - 1]]] if recent else np.empty((0, 2)))
        left = R.render(i)
        label(left, f"t = {r.t[i]:5.2f} s", size=13, color=TOK["text_2"])
        tag(left, "crossings θ1 = 0, ω1 > 0 (root-found)")
        frames.append(hstack(left, P.image()))
    flash.set_offsets(np.empty((0, 2)))
    last_left = Image.new("RGB", (420, 420), TOK["bg"])
    for tt in np.linspace(12, T, 70):  # phase B: fast-forward the same trajectory
        n = int(np.searchsorted(ft, tt, side="right"))
        live.set_offsets(np.column_stack([fs["theta2"][:n], fs["omega2"][:n]]))
        left = last_left.copy()
        label(left, f"t = {tt:5.0f} s", size=13, color=TOK["text_2"])
        label(left, "fast-forward", (0.5, 0.45), size=22, mono=False, anchor="mm")
        label(left, f"{n} crossings", (0.5, 0.55), size=15, color=TOK["text_2"], mono=False, anchor="mm")
        frames.append(hstack(left, P.image()))
    frames += [frames[-1]] * 15
    P.close()
    return write("poincare-section", fade(frames), fps,
                 {"physical": p, "energy_J": E, "initials": ics, "t_max": T, "focus": focus, "method": "DOP853 1e-10",
                  "surface": "theta1 = 0 mod 2pi, omega1 > 0"})


# ---------------------------------------------------------------------------- 08 chaos map
def map_image(arr, spec, title, vmax=None, size=(520, 520), progress=None):
    P = Plot(*size)
    ax = P.axes[0]
    finite = arr[np.isfinite(arr)]
    vmax = vmax or (np.nanmax(finite) if finite.size else 1)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("cl", palettes.sample("plasma", np.linspace(0, 1, 256)))
    cmap.set_bad(TOK["panel"])
    with np.errstate(invalid="ignore"):
        shown = np.log10(np.maximum(arr, 1e-3))
    ax.imshow(shown, origin="lower", cmap=cmap, vmin=np.log10(0.3), vmax=np.log10(vmax), interpolation="nearest",
              extent=[*spec.theta1_range, *spec.theta2_range], aspect="auto")
    ax.set_xlabel(r"$\theta_1(0)$ [deg]")
    ax.set_ylabel(r"$\theta_2(0)$ [deg]")
    ax.set_title(title)
    if progress is not None:
        ax.text(0.02, 0.97, progress, transform=ax.transAxes, va="top", fontsize=9, color=TOK["text_2"],
                bbox=dict(boxstyle="round", fc=TOK["panel_2"], ec=TOK["border"]))
    P.fig.tight_layout()
    im = P.image()
    P.close()
    return im


@gen("chaos-map")
def chaos_map():
    spec = maps.MapSpec(nx=260, ny=260, t_max=10.0, dt=0.005)
    rows = 10
    arr = np.full((spec.ny, spec.nx), np.nan)
    frames = []
    t0 = time.perf_counter()
    for a in range(0, spec.ny, rows):
        b = min(a + rows, spec.ny)
        arr[a:b] = maps.compute_rows(spec, a, b)
        frames.append(map_image(arr, spec, "Time to first flip (log colour; dark = no flip in 10 s)", 10.0,
                                progress=f"computing rows {b}/{spec.ny}"))
    elapsed = time.perf_counter() - t0
    final = map_image(arr, spec, "Time to first flip (log colour; dark = no flip in 10 s)", 10.0)
    frames += [final] * 25
    return write("chaos-map", fade(frames, n_in=2), 12,
                 {"map_spec": spec.to_dict(), "serial_compute_s": elapsed,
                  "observable": "first_flip: time until either arm passes over the top"})


# ---------------------------------------------------------------------------- 09 fractal zoom
@gen("fractal-zoom")
def fractal_zoom():
    # Zoom target: a boundary point picked from a coarse map (largest local contrast near (-110°, 60°)).
    coarse = maps.MapSpec(nx=120, ny=120, t_max=10.0, dt=0.005)
    m = maps.compute_map(coarse, workers=8)
    t1, t2 = coarse.axes()
    lm = np.log10(np.nan_to_num(m, nan=20.0))
    gy, gx = np.gradient(lm)
    score = np.hypot(gx, gy)
    T1, T2 = np.meshgrid(t1, t2)
    score[(np.abs(T1 + 110) > 40) | (np.abs(T2 - 60) > 40)] = 0
    j, i = np.unravel_index(np.argmax(score), score.shape)
    c1, c2 = float(t1[i]), float(t2[j])
    levels = 26
    spans = 360.0 * 0.84 ** np.arange(levels)
    frames = []
    t0 = time.perf_counter()
    for k, span in enumerate(spans):
        spec = maps.MapSpec(nx=200, ny=200, t_max=10.0, dt=0.005, theta1_range=(c1 - span / 2, c1 + span / 2),
                            theta2_range=(c2 - span / 2, c2 + span / 2))
        arr = maps.compute_map(spec, workers=8)
        img = map_image(arr, spec, f"First-flip map · zoom ×{360 / span:,.0f} (recomputed)", 10.0,
                        progress=f"level {k + 1}/{levels}  span {span:.2f}°")
        frames += [img] * 2
    frames += [frames[-1]] * 14
    return write("fractal-zoom", fade(frames, n_in=2), 10,
                 {"center_deg": [c1, c2], "spans_deg": spans.tolist(), "resolution": [200, 200], "t_max": 10.0,
                  "dt": 0.005, "compute_s": time.perf_counter() - t0,
                  "note": "Every level is recomputed from initial conditions, not upscaled. Fine detail is limited "
                          "by the RK4 step and the 10 s horizon; intricate boundaries are not a proof of fractality."})


# ---------------------------------------------------------------------------- 10 integrators
@gen("integrator-comparison")
def integrators():
    base = SimConfig(Physical(), Initial(178, 180), Numerics(t_max=12), "Integrator Showdown")
    settings = [("RK4 dt=0.01", {"numerics.method": "rk4", "numerics.dt": 0.01}, TOK["pink"]),
                ("RK45 rtol=1e-6", {"numerics.method": "rk45", "numerics.rtol": 1e-6, "numerics.atol": 1e-9},
                 TOK["gold"]),
                ("DOP853 rtol=1e-10", {"numerics.method": "dop853", "numerics.rtol": 1e-10, "numerics.atol": 1e-10},
                 TOK["cyan"])]
    runs = [(lab, run(base.with_(**ch), 0.01), c) for lab, ch, c in settings]
    t = runs[0][1].t
    xy = np.stack([np.stack(r.positions, axis=-1) for _, r, _ in runs], axis=1)
    cols = np.array([palettes.hex_to_rgb(c) for *_, c in runs])
    R = raster.PendulumRenderer(t, xy, raster.Style(width=420, height=420, trail="fade", trail_seconds=1.5,
                                glow=0.6), raster.world_extent(1, 1), colors=cols)
    P = Plot(500, 420)
    ax = P.axes[0]
    lines = []
    for lab, r, c in runs:
        err = np.maximum(np.abs(r.relative_energy_error), 1e-16)
        ax.semilogy(t, err, color="#222B40", lw=1)
        lines.append((ax.semilogy([], [], color=c, lw=1.5, label=f"{lab}  (nfev {r.nfev})")[0], err))
    ax.set_ylim(1e-14, 1)
    ax.set_xlim(0, t[-1])
    ax.set_xlabel("time [s]")
    ax.set_ylabel(r"$|E-E_0|/|E_0|$")
    ax.set_title("Energy error by integrator")
    ax.legend(loc="lower right")
    ax.text(0.02, 0.97, "Chaotic trajectories separate even when all\nruns are accurate: divergence alone does\n"
            "not prove an integrator wrong.", transform=ax.transAxes, va="top", fontsize=7.5, color=TOK["text_2"])
    head = ax.axvline(0, color=TOK["text_2"], lw=0.8, alpha=0.5)
    P.fig.tight_layout()
    fps = 15
    frames = []
    for i in frame_indices(t, fps):
        for ln, err in lines:
            ln.set_data(t[: i + 1], err[: i + 1])
        head.set_xdata([t[i], t[i]])
        left = R.render(i)
        label(left, f"t = {t[i]:5.2f} s", size=13, color=TOK["text_2"])
        frames.append(hstack(left, P.image()))
    P.close()
    return write("integrator-comparison", fade(frames), fps,
                 {"config": base, "settings": [s[:2] for s in settings],
                  "max_energy_error": {lab: float(np.max(np.abs(r.relative_energy_error))) for lab, r, _ in runs}})


# ---------------------------------------------------------------------------- 11 double flip
@gen("double-flip")
def double_flip():
    cfg = presets.get("double_flip")["config"].with_(**{"numerics.t_max": 10})
    r = run(cfg, 1 / 120)
    ev = events.flip_events(r.t, r.y)
    R = pend_renderer(r, (500, 500), palette="fire", trail="dual", trail_seconds=2.0, glow=1.0, particles="burst",
                      particle_count=300)
    fps = 20
    frames = []
    for i in frame_indices(r.t, fps):
        n1 = sum(1 for e in ev if e["arm"] == 1 and e["t"] <= r.t[i])
        n2 = sum(1 for e in ev if e["arm"] == 2 and e["t"] <= r.t[i])
        im = R.render(i)
        label(im, f"t = {r.t[i]:5.2f} s", size=13, color=TOK["text_2"])
        label(im, f"upper flips {n1}   lower flips {n2}", (0.965, 0.035), size=13, color=TOK["gold"], anchor="ra")
        frames.append(im)
    return write("double-flip", fade(frames), fps, {"config": cfg, "flip_events": ev, "playback_speed": 1.0})


# ---------------------------------------------------------------------------- 12 slow motion
@gen("slow-motion")
def slow_motion():
    cfg = SimConfig(Physical(), Initial(120, -10), Numerics(method="dop853", t_max=10, rtol=1e-11, atol=1e-11),
                    "Slow Motion")
    r = run(cfg, 1 / 1000)
    i_peak = int(np.argmax(np.max(np.abs(r.y[:, 2:]), axis=1)))
    tp = r.t[i_peak]
    speed, fps = 0.2, 20
    R = pend_renderer(r, (500, 500), palette="ice", trail="velocity", trail_seconds=0.8, glow=1.0, motion_blur=3)
    frames = []
    for i in frame_indices(r.t, fps, speed, max(0, tp - 0.6), min(r.t[-1], tp + 0.6)):
        im = R.render(i)
        w = np.max(np.abs(r.y[i, 2:]))
        label(im, f"t = {r.t[i]:6.3f} s", size=13, color=TOK["text_2"])
        label(im, f"max|ω| = {w:5.1f} rad/s", (0.965, 0.035), size=13, color=TOK["cyan"], anchor="ra")
        tag(im, f"{speed:g}× slow motion · DOP853 samples every 1 ms")
        frames.append(im)
    return write("slow-motion", fade(frames), fps, {"config": cfg, "playback_speed": speed, "peak_time_s": tp,
                                                    "peak_omega": float(np.max(np.abs(r.y[i_peak, 2:])))})


# ---------------------------------------------------------------------------- multi-panel helper
def panels(cfgs, labels, name, t_max, meta, fps=15, size=340, palette_list=None, speed=1.0, trail="fade"):
    runs = [run(c.with_(**{"numerics.t_max": t_max}), 1 / 120) for c in cfgs]
    pals = palette_list or ["cyan", "magenta", "gold", "plasma"]
    Rs = [pend_renderer(r, (size, size), palette=pals[k % len(pals)], trail=trail, trail_seconds=2.0, glow=0.75,
                        bob_radius=7, rod_width=2.4) for k, r in enumerate(runs)]
    frames = []
    for i in frame_indices(runs[0].t, fps, speed):
        ims = []
        for R, lab, r in zip(Rs, labels, runs):
            im = R.render(min(i, len(r.t) - 1))
            label(im, lab, (0.5, 0.04), size=13, mono=False, anchor="ma")
            label(im, f"t = {r.t[min(i, len(r.t) - 1)]:5.2f} s", (0.5, 0.94), size=11, color=TOK["text_2"],
                  anchor="ma")
            ims.append(im)
        frames.append(hstack(*ims))
    return write(name, fade(frames), fps, {"configs": cfgs, "labels": labels, "playback_speed": speed, **meta})


@gen("regular-vs-chaotic")
def regular_vs_chaotic():
    a = SimConfig(Physical(), Initial(60, 40), Numerics(t_max=40), "Regular")
    b = SimConfig(Physical(), Initial(135, -45), Numerics(t_max=40), "Chaotic")
    la = lyapunov.double_pendulum_lyapunov(a, 40.0).lam
    lb = lyapunov.double_pendulum_lyapunov(b, 40.0).lam
    return panels([a, b], [f"regular · λ ≈ {la:.2f} s⁻¹", f"chaotic · λ ≈ {lb:.2f} s⁻¹"], "regular-vs-chaotic", 14,
                  {"lyapunov_40s": [la, lb], "note": "Finite-time Lyapunov estimates over 40 s (tangent method)."},
                  size=380, palette_list=["ice", "fire"], trail="time")


@gen("gravity-comparison")
def gravity():
    gs = [("Moon", 1.62), ("Earth", 9.81), ("Jupiter-like", 24.79)]
    cfgs = [SimConfig(Physical(g=g), Initial(120, -10), Numerics(t_max=10), n) for n, g in gs]
    return panels(cfgs, [f"{n}  g = {g} m/s²" for n, g in gs], "gravity-comparison", 10,
                  {"note": "Simplified constant-gravity experiments; same physical clock in every panel."})


@gen("mass-ratio")
def mass_ratio():
    ratios = [0.25, 1.0, 4.0]
    cfgs = [SimConfig(Physical(m1=1.0, m2=q), Initial(140, 30), Numerics(t_max=10), f"m2/m1={q}") for q in ratios]
    return panels(cfgs, [f"m2/m1 = {q:g}" for q in ratios], "mass-ratio", 10, {"ratios": ratios},
                  palette_list=["magenta", "purple", "cyan"])


# ---------------------------------------------------------------------------- 16/17 forced
def forced_gif(name, cfg, title, t_max, show_drive):
    r = run(cfg.with_(**{"numerics.t_max": t_max, "numerics.method": "dop853", "numerics.rtol": 1e-10,
                         "numerics.atol": 1e-10}), 1 / 120)
    e = r.energy
    R = pend_renderer(r, (420, 420), palette="fire" if show_drive else "ice", trail="fade", trail_seconds=2.5,
                      glow=0.8)
    P = Plot(500, 420)
    ax = P.axes[0]
    t = r.t
    series = [(e["E"], TOK["green"], "total energy E")]
    if show_drive:
        series.append((e["E"][0] + e["W_drive"], TOK["gold"], "E0 + work by drive"))
    series.append((e["E"][0] - e["W_damp"] + (e["W_drive"] if show_drive else 0), TOK["text_2"],
                   "E0 + W_drive − W_damp (balance)"))
    lines = []
    for arr, c, lab in series:
        ax.plot(t, arr, color="#222B40", lw=1)
        lines.append((ax.plot([], [], color=c, lw=1.6 if "balance" not in lab else 1.0,
                              ls="-" if "balance" not in lab else "--", label=lab)[0], arr))
    ax.set_xlim(0, t[-1])
    ax.set_xlabel("time [s]")
    ax.set_ylabel("energy [J]")
    ax.set_title(title)
    ax.legend(loc="best")
    head = ax.axvline(0, color=TOK["text_2"], lw=0.8, alpha=0.5)
    P.fig.tight_layout()
    speed, fps = 2.0, 15
    frames = []
    for i in frame_indices(t, fps, speed):
        for ln, arr in lines:
            ln.set_data(t[: i + 1], arr[: i + 1])
        head.set_xdata([t[i], t[i]])
        left = R.render(i)
        label(left, f"t = {t[i]:5.2f} s", size=13, color=TOK["text_2"])
        tag(left, f"{speed:g}× speed")
        frames.append(hstack(left, P.image()))
    P.close()
    return write(name, fade(frames), fps, {"config": r.config, "playback_speed": speed,
                                           "max_balance_residual": float(np.max(np.abs(r.relative_energy_error)))})


@gen("damped-pendulum")
def damped():
    return forced_gif("damped-pendulum", presets.get("damped")["config"],
                      "Viscous joint damping: energy drains away", 30, False)


@gen("driven-pendulum")
def driven():
    return forced_gif("driven-pendulum", presets.get("driven")["config"],
                      "Pivot torque 1.5 cos(2.4 t) N·m: energy balance", 30, True)


# ---------------------------------------------------------------------------- 18 lyapunov
@gen("lyapunov-growth")
def lyapunov_growth():
    cfg = SimConfig(Physical(), Initial(120, -10), Numerics(t_max=20, dt=1e-3), "Lyapunov")
    d0 = 1e-8
    r = run(cfg, 1 / 120)
    rb = simulate(cfg.with_(**{"numerics.output_dt": 1 / 120}), y0=np.array(cfg.initial.state()) + [d0, 0, 0, 0])
    tau = physics.natural_time_scale(cfg.physical)
    sep = np.maximum(physics.state_distance(r.y, rb.y, tau), 1e-16)
    L = lyapunov.double_pendulum_lyapunov(cfg, 20.0, dt=1e-3, renorm_interval=0.1)
    t = r.t
    xy = np.stack([np.stack(r.positions, -1), np.stack(rb.positions, -1)], axis=1)
    R = raster.PendulumRenderer(t, xy, raster.Style(width=420, height=420, trail="fade", trail_seconds=1.5,
                                glow=0.7), raster.world_extent(1, 1),
                                colors=np.array([palettes.hex_to_rgb(TOK["cyan"]), palettes.hex_to_rgb(TOK["pink"])]))
    P = Plot(500, 420, 2, 1, sharex=True)
    a1, a2 = P.axes
    a1.semilogy(t, sep, color="#222B40")
    a1.semilogy(t, d0 * np.exp(L.lam * t), color=TOK["gold"], ls="--", lw=1,
                label=rf"$d_0 e^{{\lambda t}}$, λ={L.lam:.2f}/s")
    ls, = a1.semilogy([], [], color=TOK["pink"], lw=1.5, label="separation (no renormalization)")
    a1.set_ylabel("separation")
    a1.set_ylim(1e-9, 20)
    a1.legend(loc="lower right")
    a1.set_title(rf"Perturbation growth, $d_0$ = {d0:g}")
    a2.plot(L.t, L.running, color="#222B40")
    lr, = a2.plot([], [], color=TOK["green"], lw=1.5)
    a2.set_ylabel(r"running $\lambda$ [1/s]")
    a2.set_xlabel("time [s]")
    a2.set_ylim(0, max(2.0, float(np.max(L.running[5:])) * 1.1))
    a2.set_xlim(0, t[-1])
    P.fig.tight_layout()
    fps = 15
    frames = []
    for i in frame_indices(t, fps):
        ls.set_data(t[: i + 1], sep[: i + 1])
        k = int(np.searchsorted(L.t, t[i]))
        lr.set_data(L.t[:k], L.running[:k])
        left = R.render(i)
        label(left, f"t = {t[i]:5.2f} s", size=13, color=TOK["text_2"])
        frames.append(hstack(left, P.image()))
    P.close()
    return write("lyapunov-growth", fade(frames), fps,
                 {"config": cfg, "d0": d0, "lambda_finite_time": L.lam, "estimator": "tangent, renorm 0.1 s",
                  "note": "Finite-time estimate; not a universal constant."})


# ---------------------------------------------------------------------------- 19 parameter morph
@gen("parameter-morph")
def parameter_morph():
    values = np.linspace(0.4, 1.4, 11)
    stills = []
    cfgs = []
    for k, L2 in enumerate(values):
        cfg = SimConfig(Physical(L2=float(L2)), Initial(140, 100), Numerics(t_max=25), f"L2={L2:.2f}")
        cfgs.append(cfg)
        r = run(cfg, 1 / 120)
        R = raster.PendulumRenderer(r.t, raster.xy_from_result(r), raster.Style(
            width=460, height=460, trail="exposure", palette="plasma", glow=0.9, trail_width=1.4,
            show_pendulum=False), raster.world_extent(1.0, 1.4))
        for i in range(0, len(r.t), 60):
            img = R.render(i)
        img = R.render(len(r.t) - 1)
        label(img, f"L2 = {L2:.2f} m", (0.5, 0.04), size=16, mono=False, anchor="ma")
        tag(img, f"independent simulation {k + 1}/{len(values)} · 25 s each")
        stills.append(img)
    frames = []
    for a, b in zip(stills, stills[1:] + stills[:1]):
        frames += [a] * 8
        frames += [Image.blend(a, b, w) for w in np.linspace(0.15, 0.85, 5)]
    return write("parameter-morph", frames, 10,
                 {"configs": cfgs, "note": "Each frame group is a separate simulation; the crossfade is a visual "
                                           "transition, not physical evolution."})


# ---------------------------------------------------------------------------- 20 showcase
@gen("cinematic-showcase")
def showcase():
    size, fps = 480, 20
    clips = []

    def title(text, sub):
        im = Image.new("RGB", (size, size), TOK["bg"])
        label(im, text, (0.5, 0.45), size=26, mono=False, anchor="mm")
        label(im, sub, (0.5, 0.55), size=14, color=TOK["text_2"], mono=False, anchor="mm")
        return [im] * 18

    clips += title("CHAOS LAB ULTRA", "Two pendulums. Infinite possibilities.")
    r = run(SimConfig(initial=Initial(160, 20), numerics=Numerics(t_max=5)), 1 / 120)
    R = pend_renderer(r, (size, size), palette="rainbow", trail="time", trail_seconds=4, glow=1.0)
    clips += [R.render(i) for i in frame_indices(r.t, fps)]
    clips += title("Butterfly effect", "100 pendulums, 0.0001 rad apart")
    cfg = SimConfig(Physical(), Initial(150, 150), Numerics(t_max=9, dt=2e-3, output_dt=1 / 60))
    b = ensemble.butterfly(cfg, n=100, epsilon=1e-4, variable="theta2", numerical_control=False)
    R = raster.PendulumRenderer(b["t"], ensemble_xy(b, cfg.physical), raster.Style(width=size, height=size,
                                trail="fade", trail_seconds=0.7, glow=0.55, trail_width=1.3),
                                raster.world_extent(1, 1), colors=palettes.distinct(100))
    clips += [R.render(i) for i in frame_indices(b["t"], fps, 1.0, 3.0)]
    clips += title("Light painting", "40 seconds of motion, 8× speed")
    r = run(SimConfig(initial=Initial(90, 90), numerics=Numerics(t_max=40)), 1 / 120)
    R = pend_renderer(r, (size, size), palette="plasma", trail="exposure", glow=0.9, trail_width=1.5)
    clips += [R.render(i) for i in frame_indices(r.t, fps, 8.0)]
    clips += title("Explore the mathematics of chaos", "python -m chaos_lab")
    return write("cinematic-showcase", fade(clips), fps, {"note": "Montage of independent verified simulations."})


# ---------------------------------------------------------------------------- MP4
@gen("video-hero")
def video_hero():
    """Longer, higher-quality MP4 (assets/videos/) — too large to be a GIF."""
    from chaos_lab.exports import studio

    cfg = SimConfig(Physical(), Initial(160, 20), Numerics(t_max=20), "Hero video")
    out = ROOT / "assets" / "videos" / "hero-chaos-720p.mp4"
    meta = studio.render_animation(cfg, out, raster.Style(width=1280, height=720, palette="rainbow", trail="fade",
                                                          trail_seconds=5.0, glow=1.0), fps=30, quality="medium",
                                   title="Chaos Lab Ultra", show_params=True)
    print(f"  {out.name}  {meta['frames']} frames  {out.stat().st_size / 1e6:.2f} MB")


# ---------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated names")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        print("\n".join(GENERATORS))
        return
    names = [n for n in a.only.split(",") if n] or list(GENERATORS)
    for n in names:
        if n not in GENERATORS:
            raise SystemExit(f"unknown asset {n!r}; use --list")
    total = time.perf_counter()
    for n in names:
        t0 = time.perf_counter()
        print(f"[{n}]")
        GENERATORS[n]()
        print(f"  done in {time.perf_counter() - t0:.1f} s")
    print(f"all done in {time.perf_counter() - total:.1f} s")


if __name__ == "__main__":
    main()
