import json
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from chaos_lab import Initial, Numerics, SimConfig, simulate
from chaos_lab.exports import data, media, studio
from chaos_lab.rendering import palettes, raster

ROOT = Path(__file__).resolve().parents[1]
CFG = SimConfig(initial=Initial(150, 20), numerics=Numerics(t_max=1.0))


def _result():
    return simulate(CFG.with_(**{"numerics.output_dt": 1 / 120}))


def test_palette_sampling_and_tokens():
    c = palettes.sample("white", [0, 0.5, 1])
    assert c.shape == (3, 3) and np.all((0 <= c) & (c <= 1))
    assert np.allclose(palettes.sample("gray", [0, 1]), [[0, 0, 0], [1, 1, 1]])
    # strictly monochrome: every token and every gradient stop is a grey (r == g == b)
    for theme in palettes.TOKENS.values():
        for h in theme.values():
            r, g, b = palettes.hex_to_rgb(h)
            assert r == g == b, h
    for stops in palettes.GRADIENTS.values():
        for _, h in stops:
            r, g, b = palettes.hex_to_rgb(h)
            assert r == g == b, h
    assert np.allclose(palettes.distinct(5)[:, 0], palettes.distinct(5)[:, 2])
    custom = palettes.custom_gradient(["#000000", "#FFFFFF"])
    assert np.allclose(palettes.sample(custom, 0.5), [0.5, 0.5, 0.5], atol=0.01)
    assert "--bg: #000000;" in palettes.tokens_css("dark")
    with pytest.raises(ValueError):
        palettes.custom_gradient(["#000000"])


@pytest.mark.parametrize("trail", raster.TRAIL_MODES)
def test_every_trail_mode_renders(trail):
    r = _result()
    st = raster.Style(width=96, height=96, trail=trail, particles="sparks" if trail == "particles" else "none")
    R = studio.make_renderer(r, st)
    for i in (0, 30, 60, 119):
        im = R.render(i)
    assert im.size == (96, 96)
    assert np.asarray(im).max() > 60  # something visible was drawn


@pytest.mark.parametrize("kind", raster.PARTICLE_KINDS)
def test_particles_are_visual_only_and_deterministic(kind):
    r = _result()
    y_before = r.y.copy()
    imgs = []
    for _ in range(2):
        R = studio.make_renderer(r, raster.Style(width=64, height=64, particles=kind, seed=3))
        imgs.append([np.asarray(R.render(i)) for i in range(0, 120, 20)])
    assert np.array_equal(r.y, y_before)
    assert all(np.array_equal(a, b) for a, b in zip(*imgs))


@pytest.mark.parametrize("camera", raster.CAMERA_MODES)
def test_camera_keeps_uniform_scale(camera):
    st = raster.Style(width=200, height=100, camera=camera)
    cam = raster.Camera(st, 2.0, bounds=(-1, 1, -2, 0.5))
    cam.update(np.array([0.5, -1.0]))
    x0, y0 = cam.to_px(0.0, 0.0, 200, 100)
    x1, _ = cam.to_px(1.0, 0.0, 200, 100)
    _, y1 = cam.to_px(0.0, 1.0, 200, 100)
    assert np.isclose(abs(x1 - x0), abs(y1 - y0))  # no aspect distortion


def test_transparent_render_has_alpha():
    r = _result()
    R = studio.make_renderer(r, raster.Style(width=64, height=64, transparent=True, show_pendulum=False,
                                              trail="exposure"))
    for i in range(0, 120, 10):
        im = R.render(i)
    a = np.asarray(im)
    assert im.mode == "RGBA" and a[..., 3].min() == 0 and a[..., 3].max() > 0


def test_gif_writer_round_trip(tmp_path):
    frames = [Image.new("RGB", (32, 32), (k * 20, 0, 255 - k * 20)) for k in range(8)]
    p = media.save_gif(frames, tmp_path / "x.gif", fps=10)
    g = Image.open(p)
    assert g.n_frames == 8
    for k in (0, 5, 7):
        g.seek(k)
        assert np.allclose(np.asarray(g.convert("RGB"))[16, 16], (k * 20, 0, 255 - k * 20), atol=12)


@pytest.mark.skipif(not media.available_formats()["mp4"], reason="ffmpeg not available")
@pytest.mark.parametrize("ext", [".mp4", ".webm"])
def test_video_export(tmp_path, ext):
    meta = studio.render_animation(CFG, tmp_path / f"v{ext}", raster.Style(width=64, height=64), fps=10,
                                   show_params=True, energy_graph=True, title="t")
    assert (tmp_path / f"v{ext}").stat().st_size > 1000
    side = json.loads((tmp_path / f"v{ext}.json").read_text())
    assert side["frames"] == meta["frames"] == 11
    assert SimConfig.from_dict(side["config"]) == CFG


def test_png_sequence_and_cancel(tmp_path):
    studio.render_animation(CFG, tmp_path / "seq", raster.Style(width=32, height=32), fps=5)
    assert len(list((tmp_path / "seq").glob("*.png"))) == 6
    with pytest.raises(studio.Cancelled):
        studio.render_animation(CFG, tmp_path / "c.gif", raster.Style(width=32, height=32), fps=5,
                                cancel=lambda: True)


def test_still_png_svg_and_gallery(tmp_path, monkeypatch):
    monkeypatch.setattr(studio, "ARTWORK_DIR", tmp_path / "gallery")
    m = studio.render_still(CFG, tmp_path / "a.png", size=(120, 80), save_to_gallery=True, name="x")
    assert Image.open(tmp_path / "a.png").size == (120, 80)
    assert (tmp_path / "gallery" / "x.json").exists()
    assert SimConfig.from_dict(json.loads((tmp_path / "gallery" / "x.json").read_text())["config"]) == CFG
    studio.render_still(CFG, tmp_path / "a.svg", size=(120, 80))
    assert (tmp_path / "a.svg").read_text().startswith("<svg")
    assert m["stamp"]["config_digest"] == CFG.digest()


def test_scientific_figure(tmp_path):
    studio.scientific_figure(_result(), tmp_path / "f.png")
    studio.scientific_figure(_result(), tmp_path / "f.svg", panels=("energy", "error"), theme="light", cols=2)
    assert (tmp_path / "f.png").stat().st_size > 10_000 and (tmp_path / "f.svg").exists()


def test_csv_units_and_bundle(tmp_path):
    r = _result()
    txt = data.to_csv(r)
    assert "theta1 [rad]" in txt and "E [J]" in txt
    rows = [ln for ln in txt.splitlines() if not ln.startswith("#")]
    assert len(rows) == len(r.t) + 1
    sub = data.to_csv(r, t_range=(0.5, 0.6))
    assert len([ln for ln in sub.splitlines() if not ln.startswith("#")]) < 20
    p = data.bundle(r, tmp_path / "b.zip")
    names = zipfile.ZipFile(p).namelist()
    assert {"config.json", "trajectory.npz", "trajectory.csv", "stamp.json"} <= set(names)
    cfg, t, y = data.load_bundle(p)
    assert cfg == r.config and np.array_equal(y, r.y)


def _cli(*args):
    return subprocess.run([sys.executable, "-m", "chaos_lab", *args], capture_output=True, text=True, cwd=ROOT,
                          env={"MPLBACKEND": "Agg", "PATH": "/usr/bin:/bin"}, timeout=300)


def test_cli_commands(tmp_path):
    assert "classic" in _cli("presets").stdout
    out = _cli("simulate", "--preset", "classic", "--t-max", "2")
    assert out.returncode == 0 and json.loads(out.stdout)["samples"] > 0
    assert "mode 1" in _cli("modes").stdout
    out = _cli("render", "--t-max", "0.5", "--width", "48", "--height", "48", "-o", str(tmp_path / "a.gif"))
    assert out.returncode == 0
    bad = _cli("simulate", "--m1", "-1")
    assert bad.returncode == 2 and "m1" in bad.stderr


def test_original_cli_output_unchanged():
    out = subprocess.run([sys.executable, "double_pendulum.py", "--no-show", "--dt", "0.004"], capture_output=True,
                         text=True, cwd=ROOT, env={"MPLBACKEND": "Agg", "PATH": "/usr/bin:/bin"}, timeout=300)
    assert "Steps: 7500, dt = 0.004" in out.stdout
    assert "E0 = 0.1490359430 J" in out.stdout
    assert "Max |ΔE/E0| = 8.844e-05" in out.stdout


def test_light_theme_draws_ink_on_white():
    r = _result()
    R = studio.make_renderer(r, raster.Style(width=96, height=96, theme="light"))
    for i in range(0, 120, 10):
        im = R.render(i)
    a = np.asarray(im)
    assert a[0, 0].tolist() == [255, 255, 255]  # white background
    assert a.min() < 60  # dark marks drawn
    assert np.all(a[..., 0] == a[..., 2])  # no hue
