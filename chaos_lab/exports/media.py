"""Animated media writers with graceful dependency handling.

* GIF: Pillow only. A single global palette is built from sampled frames so
  colours do not flicker between frames, and unchanged pixels compress well.
* MP4 (H.264) / WebM (VP9): via ``imageio-ffmpeg`` (bundled ffmpeg binary) or a
  system ``ffmpeg``; a clear error explains how to enable them otherwise.
* PNG sequence: Pillow only.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

import numpy as np
from PIL import Image

VIDEO_PRESETS = {
    "youtube": {"width": 1920, "height": 1080, "fps": 60, "label": "YouTube 16:9 (1080p)"},
    "reels": {"width": 1080, "height": 1920, "fps": 30, "label": "TikTok / Reels 9:16"},
    "square": {"width": 1080, "height": 1080, "fps": 30, "label": "Square 1:1"},
    "ultrawide": {"width": 2560, "height": 1080, "fps": 60, "label": "Ultrawide 21:9"},
    "presentation": {"width": 1600, "height": 900, "fps": 30, "label": "Scientific presentation 16:9"},
    "4k": {"width": 3840, "height": 2160, "fps": 30, "label": "4K cinematic"},
    "gif": {"width": 640, "height": 640, "fps": 20, "label": "Optimized GIF"},
}
IMAGE_PRESETS = {
    "1080p": (1920, 1080), "1440p": (2560, 1440), "4k": (3840, 2160), "square": (2048, 2048),
    "ultrawide": (3440, 1440), "phone": (1179, 2556),
}


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - optional dependency
        return shutil.which("ffmpeg")


def available_formats() -> dict:
    ff = ffmpeg_exe() is not None
    return {"gif": True, "png": True, "mp4": ff, "webm": ff}


def save_gif(frames: list[Image.Image], path, fps: float = 20, colors: int = 256, loop: int = 0) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not frames:
        raise ValueError("no frames")
    rgb = [f.convert("RGB") for f in frames]
    # Global palette from up to 9 evenly spaced frames.
    picks = rgb[:: max(1, len(rgb) // 9)][:9]
    w, h = rgb[0].size
    sheet = Image.new("RGB", (w, h * len(picks)))
    for k, f in enumerate(picks):
        sheet.paste(f, (0, k * h))
    colors = min(colors, 255)  # index 255 is reserved for "unchanged" (transparent)
    pal = sheet.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    palette = pal.getpalette()[: 3 * colors]
    palette += [0, 0, 0] * (256 - len(palette) // 3)
    idx = [np.asarray(f.quantize(palette=pal, dither=Image.Dither.NONE)) for f in rgb]
    # Delta encoding: pixels identical to the previous frame become transparent, which LZW
    # compresses to almost nothing; disposal=1 keeps the previous frame underneath.
    out = []
    for k, a in enumerate(idx):
        b = a.copy()
        if k:
            b[a == idx[k - 1]] = 255
        im = Image.fromarray(b.astype(np.uint8), "P")
        im.putpalette(palette)
        out.append(im)
    duration = int(round(1000 / fps))
    out[0].save(path, save_all=True, append_images=out[1:], duration=duration, loop=loop, optimize=False,
                disposal=1, transparency=255)
    return path


def save_video(frames: Iterable[Image.Image], path, fps: float = 30, quality: str = "high",
               size: tuple[int, int] | None = None) -> Path:
    """Write MP4 (H.264) or WebM (VP9) through ffmpeg via stdin."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exe = ffmpeg_exe()
    if exe is None:
        raise RuntimeError("MP4/WebM export needs ffmpeg: `pip install imageio-ffmpeg` or install ffmpeg.")
    frames = iter(frames)
    first = next(frames).convert("RGB")
    w, h = size or first.size
    w -= w % 2
    h -= h % 2
    crf = {"high": 18, "medium": 23, "low": 30}[quality]
    if path.suffix.lower() == ".webm":
        codec = ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf + 12), "-row-mt", "1"]
    else:
        codec = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags",
                 "+faststart"]
    cmd = [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps),
           "-i", "-", *codec, str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for f in [first, *frames]:
            f = f.convert("RGB")
            if f.size != (w, h):
                f = f.resize((w, h), Image.LANCZOS)
            proc.stdin.write(np.asarray(f, dtype=np.uint8).tobytes())
    finally:
        proc.stdin.close()
        err = proc.stderr.read().decode()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.strip()}")
    return path


def save_png_sequence(frames: Iterable[Image.Image], directory, prefix: str = "frame") -> list[Path]:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for k, f in enumerate(frames):
        p = d / f"{prefix}_{k:05d}.png"
        f.save(p)
        out.append(p)
    return out


def save_frames(frames, path, fps: float = 30, **kw) -> Path:
    """Dispatch on extension: .gif, .mp4, .webm, or a directory for PNG sequences."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".gif":
        return save_gif(list(frames), path, fps, **kw)
    if ext in (".mp4", ".webm"):
        return save_video(frames, path, fps, **kw)
    if ext == "":
        save_png_sequence(frames, path)
        return path
    raise ValueError(f"unsupported animation format {ext!r}")
