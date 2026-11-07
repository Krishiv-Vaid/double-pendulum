"""Export Studio: animations, artwork stills and scientific figures.

Independent of any UI: the CLI and the web dashboard both call these functions.
Long jobs accept ``progress(fraction)`` and ``cancel() -> bool`` callbacks.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from PIL import Image

from pendulum_sim.analysis import events
from pendulum_sim.core import physics
from pendulum_sim.core.config import SimConfig
from pendulum_sim.core.simulation import simulate
from pendulum_sim.exports import data as data_export
from pendulum_sim.exports import media
from pendulum_sim.rendering import figures, palettes, raster

ARTWORK_DIR = Path.home() / ".pendulum_sim" / "artworks"


class Cancelled(Exception):
    pass


def _result_for(cfg: SimConfig, output_dt: float):
    r = simulate(cfg.with_(**{"numerics.output_dt": output_dt}))
    if not r.success:
        raise RuntimeError(f"simulation failed: {r.message}")
    return r


def scale_style(style: raster.Style, reference: int = 720) -> raster.Style:
    """Scale pixel-sized visual parameters with output resolution (720p reference)."""
    k = min(style.width, style.height) / reference
    if abs(k - 1) < 1e-6:
        return style
    return replace(style, bob_radius=style.bob_radius * k, rod_width=style.rod_width * k,
                   trail_width=style.trail_width * k, glow_radius=style.glow_radius * k,
                   particle_size=style.particle_size * k)


def make_renderer(result, style: raster.Style) -> raster.PendulumRenderer:
    p = result.config.physical
    return raster.PendulumRenderer(result.t, raster.xy_from_result(result), style, raster.world_extent(p.L1, p.L2),
                                   scalars=raster.scalars_for(result),
                                   events=[e["t"] for e in events.flip_events(result.t, result.y)])


def render_animation(cfg: SimConfig, path, style: raster.Style | None = None, preset: str | None = None,
                     fps: float | None = None, speed: float = 1.0, t_start: float = 0.0, t_end: float | None = None,
                     title: str | None = None, show_params: bool = False, show_timecode: bool = True,
                     energy_graph: bool = False, quality: str = "high", progress=None, cancel=None) -> dict:
    """Render a simulation to GIF/MP4/WebM/PNG-sequence. Returns metadata (also written as a .json sidecar)."""
    style = style or raster.Style()
    if preset:
        pr = media.VIDEO_PRESETS[preset]
        style = replace(style, width=pr["width"], height=pr["height"])
        fps = fps or pr["fps"]
    fps = fps or 30
    style = scale_style(style)
    path = Path(path)
    if path.suffix.lower() in (".mp4", ".webm") and not media.available_formats()["mp4"]:
        raise RuntimeError("MP4/WebM export needs ffmpeg (pip install imageio-ffmpeg)")
    # sample densely enough for the playback rate (at least 2 samples per frame)
    out_dt = min(1 / 120, speed / (2 * fps))
    r = _result_for(cfg, out_dt)
    R = make_renderer(r, style)
    t_end = r.t[-1] if t_end is None else min(t_end, r.t[-1])
    times = np.arange(t_start, t_end + 1e-9, speed / fps)
    idx = np.clip(np.searchsorted(r.t, times - 1e-9), 0, len(r.t) - 1)
    # bring long-exposure / full trails up to t_start
    if style.trail == "exposure" and t_start > 0:
        for i in range(0, idx[0], max(1, len(r.t) // 400)):
            R.render(i)
    err = r.relative_energy_error
    E = r.energy["E"]
    sm = max(10, style.height // 45)

    def frames():
        for k, i in enumerate(idx):
            if cancel and cancel():
                raise Cancelled()
            im = R.render(int(i))
            if title:
                raster._text(im, 0.5, 0.04, title, size=int(sm * 1.6), anchor="ma")
            if show_timecode:
                lab = f"t = {r.t[i]:6.2f} s" + (f"   ({speed:g}× speed)" if speed != 1 else "")
                raster._text(im, 0.025, 0.95, lab, size=sm, color=palettes.TOKENS[style.theme]["text_2"], mono=True)
            if show_params:
                p = cfg.physical
                ini = cfg.initial
                txt = (f"m1={p.m1:g} m2={p.m2:g} kg  L1={p.L1:g} L2={p.L2:g} m  g={p.g:g}\n"
                       f"θ1(0)={ini.theta1_deg:g}° θ2(0)={ini.theta2_deg:g}°  {cfg.numerics.method.upper()}")
                raster._text(im, 0.025, 0.025, txt, size=sm, color=palettes.TOKENS[style.theme]["text_2"], mono=True)
            if energy_graph:
                _energy_inset(im, r.t, E, err, int(i), style.theme)
            if progress:
                progress((k + 1) / len(idx))
            yield im

    ext = path.suffix.lower()
    if ext == ".gif":
        media.save_gif(list(frames()), path, fps)
    elif ext in (".mp4", ".webm"):
        media.save_video(frames(), path, fps, quality=quality)
    elif ext == "":
        media.save_png_sequence(frames(), path)
    else:
        raise ValueError(f"unsupported format {ext!r}")
    meta = {
        "output": str(path), "fps": fps, "frames": int(len(idx)), "playback_speed": speed,
        "t_range_s": [float(t_start), float(t_end)], "config": cfg.to_dict(), "style": _style_dict(style),
        "preset": preset, "stamp": data_export.reproducibility_stamp(cfg),
    }
    Path(str(path) + ".json").write_text(json.dumps(meta, indent=2))
    return meta


def _energy_inset(im, t, E, err, i, theme: str = "dark"):
    """Draw a small sparkline of the energy error in the lower-right corner."""
    from PIL import ImageDraw

    d = ImageDraw.Draw(im, "RGBA")
    W, H = im.size
    w, h = int(W * 0.28), int(H * 0.12)
    x0, y0 = W - w - int(W * 0.025), H - h - int(H * 0.025)
    tok = palettes.TOKENS[theme]

    def rgba(h, a=255):
        return tuple(int(255 * c) for c in palettes.hex_to_rgb(h)) + (a,)

    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=6, fill=rgba(tok["panel_2"], 220), outline=rgba(tok["border"]))
    span = max(np.max(np.abs(err)), 1e-16)
    xs = x0 + 6 + (w - 12) * t[: i + 1: max(1, i // 300)] / max(t[-1], 1e-9)
    ys = y0 + h / 2 - (h / 2 - 6) * err[: i + 1: max(1, i // 300)] / span
    if len(xs) > 1:
        d.line(list(zip(xs, ys)), fill=rgba(tok["fg"]), width=max(1, W // 600))
    raster._text(im, (x0 + 6) / W, (y0 + 4) / H, f"ΔE/E0 {err[i]:+.1e}", size=max(9, H // 70), color=tok["text_2"],
                 mono=True)


def _style_dict(style):
    d = asdict(style)
    return d


def render_still(cfg: SimConfig, path, style: raster.Style | None = None, size: str | tuple | None = None,
                 save_to_gallery: bool = False, name: str | None = None) -> dict:
    """High-resolution long-exposure artwork from a whole trajectory (PNG, optionally transparent).

    A sidecar JSON with the exact configuration and style is always written so
    the image can be reproduced; with ``save_to_gallery`` a copy goes to
    ~/.pendulum_sim/artworks/.
    """
    style = style or raster.Style(trail="exposure", glow=0.2, show_pendulum=False)
    if size is not None:
        w, h = media.IMAGE_PRESETS[size] if isinstance(size, str) else size
        style = replace(style, width=int(w), height=int(h))
    if style.trail not in ("exposure", "full"):
        style = replace(style, trail="exposure")
    if style.camera == "static":
        style = replace(style, camera="autofit")  # fill the frame with the artwork
    style = scale_style(style, reference=900)
    r = _result_for(cfg, 1 / 240)
    R = make_renderer(r, style)
    step = max(1, len(r.t) // 600)
    img = None
    for i in range(0, len(r.t), step):
        img = R.render(i)
    img = R.render(len(r.t) - 1)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".svg":
        _svg_path(r, path, style)
    else:
        img.save(path)
    meta = {"output": str(path), "config": cfg.to_dict(), "style": _style_dict(style),
            "stamp": data_export.reproducibility_stamp(cfg)}
    Path(str(path) + ".json").write_text(json.dumps(meta, indent=2))
    if save_to_gallery:
        ARTWORK_DIR.mkdir(parents=True, exist_ok=True)
        stem = name or f"{cfg.digest()}-{style.palette if isinstance(style.palette, str) else 'custom'}"
        (ARTWORK_DIR / f"{stem}.png").write_bytes(path.read_bytes() if path.suffix.lower() == ".png"
                                                  else _png_bytes(img))
        (ARTWORK_DIR / f"{stem}.json").write_text(json.dumps(meta, indent=2))
        meta["gallery"] = str(ARTWORK_DIR / f"{stem}.png")
    return meta


def _png_bytes(img):
    import io

    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def _svg_path(result, path, style):
    """Vector export of the lower-bob path as colour-graded SVG polylines."""
    p = result.config.physical
    _, _, x2, y2 = result.positions
    ext = raster.world_extent(p.L1, p.L2)
    W, H = style.width, style.height
    k = min(W, H) / (2 * ext)
    X = W / 2 + x2 * k
    Y = H / 2 - y2 * k
    n_seg = 240
    edges = np.linspace(0, len(X) - 1, n_seg + 1).astype(int)
    cols = palettes.sample(style.palette, np.linspace(0, 1, n_seg))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
    if not style.transparent:
        parts.append(f'<rect width="100%" height="100%" fill="{style.background}"/>')
    for s in range(n_seg):
        a, b = edges[s], edges[s + 1] + 1
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(X[a:b:2], Y[a:b:2]))
        c = "#" + "".join(f"{int(255 * v):02x}" for v in cols[s])
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="{style.trail_width:.2f}" '
                     f'stroke-linecap="round" stroke-linejoin="round" stroke-opacity="0.85"/>')
    parts.append("</svg>")
    Path(path).write_text("\n".join(parts))


# ------------------------------------------------------------------ scientific figures
PANELS = ("theta1_omega1", "theta2_omega2", "theta1_theta2", "omega1_omega2", "energy", "energy_components",
          "alpha", "speed", "error")


def scientific_figure(result, path=None, panels=PANELS, theme: str = "dark", cols: int = 3, dpi: int = 150,
                      fmt: str | None = None):
    """Publication-style multi-panel figure of one trajectory (PNG/SVG/PDF by extension)."""
    import matplotlib.pyplot as plt

    t = figures.apply_theme(theme)
    rows = (len(panels) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 3.3 * rows))
    axes = np.atleast_1d(axes).ravel()
    y = result.y
    tt = result.t
    th1, th2 = physics.wrap_angle(y[:, 0]), physics.wrap_angle(y[:, 1])
    e = result.energy
    acc = result.accelerations
    _, _, vx2, vy2 = physics.velocities(y, result.p)

    def phase(ax, x, v, xl, yl, wrap=True):
        ax.scatter(x, v, c=tt, s=0.6, cmap=palettes.colormap(theme), lw=0, rasterized=True)  # keep SVG/PDF small
        ax.set_xlabel(xl)
        ax.set_ylabel(yl)

    for ax, name in zip(axes, panels):
        if name == "theta1_omega1":
            phase(ax, th1, y[:, 2], r"$\theta_1$ [rad]", r"$\omega_1$ [rad/s]")
            ax.set_title(r"$\theta_1$–$\omega_1$")
        elif name == "theta2_omega2":
            phase(ax, th2, y[:, 3], r"$\theta_2$ [rad]", r"$\omega_2$ [rad/s]")
            ax.set_title(r"$\theta_2$–$\omega_2$")
        elif name == "theta1_theta2":
            phase(ax, th1, th2, r"$\theta_1$ [rad]", r"$\theta_2$ [rad]")
            ax.set_title("configuration space")
        elif name == "omega1_omega2":
            phase(ax, y[:, 2], y[:, 3], r"$\omega_1$ [rad/s]", r"$\omega_2$ [rad/s]")
            ax.set_title("angular velocities")
        elif name == "energy":
            ax.plot(tt, e["E"], color=t["fg"])
            ax.set_title("total energy")
            ax.set_xlabel("t [s]")
            ax.set_ylabel("E [J]")
            ax.ticklabel_format(axis="y", useOffset=False)
        elif name == "energy_components":
            ax.plot(tt, e["T"], color=t["fg"], lw=0.8, label="T")
            ax.plot(tt, e["V"], color=t["fg_2"], lw=0.8, ls="--", label="V")
            ax.legend()
            ax.set_title("kinetic / potential")
            ax.set_xlabel("t [s]")
            ax.set_ylabel("J")
        elif name == "alpha":
            ax.plot(tt, acc[:, 0], color=t["fg"], lw=0.6, label=r"$\alpha_1$")
            ax.plot(tt, acc[:, 1], color=t["fg_3"], lw=0.6, label=r"$\alpha_2$")
            ax.legend()
            ax.set_title("angular acceleration")
            ax.set_xlabel("t [s]")
            ax.set_ylabel(r"rad/s$^2$")
        elif name == "speed":
            ax.plot(tt, np.hypot(vx2, vy2), color=t["fg"], lw=0.7)
            ax.set_title("lower-bob speed")
            ax.set_xlabel("t [s]")
            ax.set_ylabel("m/s")
        elif name == "error":
            ax.plot(tt, result.relative_energy_error, color=t["fg"], lw=0.7)
            ax.set_title("relative energy error")
            ax.set_xlabel("t [s]")
            ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
        else:
            raise ValueError(f"unknown panel {name!r}")
    for ax in axes[len(panels):]:
        ax.set_visible(False)
    c = result.config
    figures.stamp(fig, f"Double Pendulum Simulator · {c.name} · {c.numerics.method.upper()} · config {c.digest()}",
                  theme)
    fig.tight_layout()
    if path is not None:
        fig.savefig(path, dpi=dpi, format=fmt)
    plt.close(fig)
    return fig


def contact_image(images: list[Image.Image], cols: int = 4) -> Image.Image:
    w, h = images[0].size
    rows = (len(images) + cols - 1) // cols
    out = Image.new("RGB", (w * cols, h * rows))
    for k, im in enumerate(images):
        out.paste(im.convert("RGB"), ((k % cols) * w, (k // cols) * h))
    return out
