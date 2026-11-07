"""Supersampled raster renderer for cinematic pendulum art.

Pipeline per frame (all at ``ssaa`` x the output resolution):
  1. draw trails / particles onto a black "light" layer (colours pre-multiplied
     by opacity, so the layer is additive light);
  2. optional long-exposure accumulation of the light layer across frames;
  3. glow = Gaussian blur of the light layer (computed at reduced resolution);
  4. composite light + glow over the background, draw rods and bobs (with
     their own glow), then downsample with a Lanczos filter for antialiasing.

World -> pixel mapping always uses one uniform scale, so the pendulum geometry
is never distorted by the camera.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from chaos_lab.rendering import palettes

TRAIL_MODES = ("full", "fade", "exposure", "velocity", "acceleration", "energy", "time", "dashed", "dual",
               "lineart", "ghost", "particles")
CAMERA_MODES = ("static", "autofit", "follow", "smooth", "pivot")
PARTICLE_KINDS = ("none", "sparks", "dust", "comet", "burst", "confetti", "starfield", "smoke")


@dataclass
class Style:
    width: int = 720
    height: int = 720
    ssaa: int = 2
    theme: str = "dark"  # "dark" = white on black, "light" = black on white
    background: str | None = None  # None -> theme background
    transparent: bool = False
    palette: str | list | None = None  # None -> theme trail ramp
    trail: str = "fade"
    trail_seconds: float = 3.0
    trail_width: float = 1.6  # output pixels
    glow: float = 0.0  # 0 disables; small values give a soft bloom
    glow_radius: float = 5.0  # output pixels
    exposure_decay: float = 1.0  # 1.0 = never fades (long exposure)
    rod_color: str | None = None  # None -> theme foreground
    rod_width: float = 2.2
    bob_colors: tuple[str, str] | None = None
    bob_radius: float = 7.0
    show_pendulum: bool = True
    show_pivot: bool = True
    particles: str = "none"
    particle_count: int = 400
    particle_lifetime: float = 1.2  # s of playback
    particle_size: float = 2.0
    particle_speed: float = 0.6  # m/s
    particle_opacity: float = 0.9
    camera: str = "static"
    zoom: float = 1.0
    pan: tuple[float, float] = (0.0, 0.0)  # m
    camera_smoothing: float = 0.15
    motion_blur: int = 0  # sub-samples per frame
    overlay_text: list = field(default_factory=list)  # [(x_frac, y_frac, text, size, hex)]
    seed: int = 0

    def __post_init__(self):
        if self.theme not in palettes.TOKENS:
            raise ValueError("theme must be 'dark' or 'light'")
        tok = palettes.TOKENS[self.theme]
        if self.background is None:
            self.background = tok["bg"]
        if self.palette is None:
            self.palette = palettes.THEME_TRAIL[self.theme]
        if self.rod_color is None:
            self.rod_color = tok["fg_2"]
        if self.bob_colors is None:
            self.bob_colors = (tok["fg"], tok["fg"])

    @property
    def ink(self) -> bool:
        """Light theme: marks are drawn as ink subtracted from the background."""
        return self.theme == "light"

    def validate(self):
        if self.trail not in TRAIL_MODES:
            raise ValueError(f"trail must be one of {TRAIL_MODES}")
        if self.camera not in CAMERA_MODES:
            raise ValueError(f"camera must be one of {CAMERA_MODES}")
        if self.particles not in PARTICLE_KINDS:
            raise ValueError(f"particles must be one of {PARTICLE_KINDS}")
        if not (16 <= self.width <= 8192 and 16 <= self.height <= 8192):
            raise ValueError("width/height out of range")
        return self


class Camera:
    def __init__(self, style: Style, extent: float, bounds=None):
        self.s = style
        self.extent = extent  # world half-size (m) to fit at zoom 1
        self.center = np.array(style.pan, dtype=float)
        self.bounds = bounds  # (xmin, xmax, ymin, ymax) for autofit

    def update(self, bob_xy):
        mode = self.s.camera
        if mode in ("static", "pivot"):
            self.center = np.array(self.s.pan, dtype=float)
        elif mode == "autofit" and self.bounds is not None:
            xmin, xmax, ymin, ymax = self.bounds
            self.center = np.array([(xmin + xmax) / 2, (ymin + ymax) / 2]) + self.s.pan
        elif mode == "follow":
            self.center = np.asarray(bob_xy, dtype=float) + self.s.pan
        elif mode == "smooth":
            target = 0.5 * np.asarray(bob_xy, dtype=float) + self.s.pan  # halfway: keeps the pivot in view
            self.center += self.s.camera_smoothing * (target - self.center)

    def scale(self, W, H):
        ext = self.extent
        if self.s.camera == "autofit" and self.bounds is not None:
            xmin, xmax, ymin, ymax = self.bounds
            ext = 0.55 * max(xmax - xmin, (ymax - ymin) * W / H, 1e-3)
        return min(W, H) / (2.0 * ext) * self.s.zoom

    def to_px(self, x, y, W, H):
        k = self.scale(W, H)
        return (W / 2 + (np.asarray(x) - self.center[0]) * k, H / 2 - (np.asarray(y) - self.center[1]) * k)


class Particles:
    """Purely visual particle system (seeded, deterministic)."""

    def __init__(self, style: Style, extent: float):
        self.s = style
        self.rng = np.random.default_rng(style.seed)
        self.pos = np.zeros((0, 2))
        self.vel = np.zeros((0, 2))
        self.age = np.zeros(0)
        self.life = np.zeros(0)
        self.col = np.zeros((0, 3))
        if style.particles == "starfield":
            n = style.particle_count
            self.pos = self.rng.uniform(-1.6 * extent, 1.6 * extent, (n, 2))
            self.vel = np.zeros((n, 2))
            self.age = self.rng.uniform(0, 10, n)
            self.life = np.full(n, np.inf)
            self.col = np.tile([0.85, 0.85, 0.85], (n, 1))

    def step(self, dt, bob, bob_vel, color, burst=False):
        kind = self.s.particles
        if kind in ("none", "starfield"):
            self.age += dt
            return
        rate = self.s.particle_count / max(self.s.particle_lifetime, 1e-3)
        n_new = self.rng.poisson(rate * dt) + (int(self.s.particle_count * 0.15) if burst else 0)
        if kind == "burst" and not burst:
            n_new = 0
        if n_new:
            ang = self.rng.uniform(0, 2 * np.pi, n_new)
            spd = self.s.particle_speed * self.rng.uniform(0.2, 1.0, n_new) * (3.0 if kind == "burst" else 1.0)
            v = np.stack([np.cos(ang), np.sin(ang)], 1) * spd[:, None]
            if kind in ("comet", "smoke", "dust"):
                v *= 0.3
            if kind == "comet":
                v -= 0.15 * np.asarray(bob_vel)
            if kind == "sparks":
                v += 0.25 * np.asarray(bob_vel)
            c = np.tile(color, (n_new, 1))
            if kind == "confetti":
                c = palettes.sample("gray", self.rng.uniform(0.4, 1.0, n_new))
            if kind == "smoke":
                c = np.tile([0.55, 0.6, 0.7], (n_new, 1))
            self.pos = np.concatenate([self.pos, np.tile(bob, (n_new, 1))])
            self.vel = np.concatenate([self.vel, v])
            self.age = np.concatenate([self.age, np.zeros(n_new)])
            self.life = np.concatenate([self.life, self.s.particle_lifetime * self.rng.uniform(0.5, 1.0, n_new)])
            self.col = np.concatenate([self.col, c])
        drag = {"sparks": 1.5, "dust": 0.4, "comet": 2.0, "burst": 2.5, "confetti": 1.0, "smoke": 0.8}[kind]
        self.vel *= np.exp(-drag * dt)
        if kind == "smoke":
            self.vel[:, 1] += 0.2 * dt
        if kind == "confetti":
            self.vel[:, 1] -= 0.8 * dt
        self.pos += self.vel * dt
        self.age += dt
        alive = self.age < self.life
        self.pos, self.vel, self.age, self.life, self.col = (a[alive] for a in
                                                              (self.pos, self.vel, self.age, self.life, self.col))
        cap = 4 * self.s.particle_count
        if len(self.age) > cap:
            self.pos, self.vel, self.age, self.life, self.col = (a[-cap:] for a in
                                                                  (self.pos, self.vel, self.age, self.life, self.col))

    def draw(self, draw: ImageDraw.ImageDraw, cam: Camera, W, H, ss):
        if len(self.age) == 0:
            return
        px, py = cam.to_px(self.pos[:, 0], self.pos[:, 1], W, H)
        if self.s.particles == "starfield":
            fade = 0.35 + 0.35 * np.sin(self.age * 2.0 + np.arange(len(self.age)))
        else:
            fade = np.clip(1 - self.age / self.life, 0, 1)
        size = self.s.particle_size * ss * (1.8 if self.s.particles in ("smoke", "dust") else 1.0)
        for x, y, f, c in zip(px, py, fade, self.col):
            r = size * (0.5 + 0.5 * f) if self.s.particles == "comet" else size
            a = f * self.s.particle_opacity * (0.35 if self.s.particles == "smoke" else 1.0)
            col = tuple(int(255 * min(1, ch * a)) for ch in c)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=col)


def _rgb255(c, a=1.0):
    return tuple(int(255 * max(0.0, min(1.0, v * a))) for v in c)


class PendulumRenderer:
    """Render frames of one or many double pendulums from precomputed samples.

    Parameters
    ----------
    t : (T,) sample times (physical seconds)
    xy : (T, N, 4) arrays of x1, y1, x2, y2 for N pendulums
    scalars : optional dict of (T, N) arrays for colouring ('speed', 'accel', 'energy')
    colors : optional (N, 3) per-pendulum colours (ensembles)
    """

    def __init__(self, t, xy, style: Style, extent: float, scalars=None, colors=None, events=None):
        style.validate()
        self.t = np.asarray(t)
        self.xy = np.asarray(xy)
        if self.xy.ndim == 2:
            self.xy = self.xy[:, None, :]
        self.N = self.xy.shape[1]
        self.s = style
        self.extent = extent
        self.scalars = scalars or {}
        self.colors = colors
        self.events = sorted(events or [])
        self.W, self.H = style.width * style.ssaa, style.height * style.ssaa
        bounds = None
        if style.camera == "autofit":
            xs = np.concatenate([self.xy[..., 0].ravel(), self.xy[..., 2].ravel(), [0]])
            ys = np.concatenate([self.xy[..., 1].ravel(), self.xy[..., 3].ravel(), [0]])
            bounds = (xs.min(), xs.max(), ys.min(), ys.max())
        self.cam = Camera(style, extent, bounds)
        self.particles = Particles(style, extent)
        self.accum = None
        self.prev_i = None
        self.dt = float(self.t[1] - self.t[0]) if len(self.t) > 1 else 1.0
        self.bg = np.array(palettes.hex_to_rgb(style.background))
        self._ghosts = []
        self._bg_img = None

    # ------------------------------------------------------------------ trails
    def _trail_values(self, k, j0, i):
        """Per-segment colour parameter in [0, 1] for pendulum k over samples j0..i."""
        mode = self.s.trail
        n = i - j0
        if mode in ("velocity", "acceleration", "energy"):
            key = {"velocity": "speed", "acceleration": "accel", "energy": "energy"}[mode]
            arr = self.scalars.get(key)
            if arr is not None:
                seg = arr[j0:i, k]
                lo, hi = self.scalars.get(key + "_range", (np.nanmin(arr), np.nanmax(arr)))
                return (seg - lo) / max(hi - lo, 1e-12)
        if mode in ("time", "exposure", "full") and not (self.N > 1 and self.colors is None):
            # global time gradient: incremental exposure chunks must not restart the ramp
            return (self.t[j0:i] / max(self.t[-1], 1e-9)) % 1.0
        if self.N > 1 and self.colors is None:
            return np.full(n, k / max(self.N - 1, 1))
        return np.linspace(0.15, 1.0, n)

    def _draw_trails(self, draw, i):
        s = self.s
        ss = s.ssaa
        mode = s.trail
        if mode in ("exposure", "full"):
            j0 = 0 if mode == "full" else max(0, (self.prev_i if self.prev_i is not None else 0) - 1)
        else:
            j0 = max(0, i - int(s.trail_seconds / self.dt))
        if i - j0 < 1:
            return
        width = max(1, int(round(s.trail_width * ss * (0.6 if mode == "lineart" else 1.0))))
        stride = max(1, (i - j0) // 4000)  # bound the segment count per frame
        idx = np.arange(j0, i + 1, stride)
        if idx[-1] != i:
            idx = np.append(idx, i)
        arms = (2, 0) if mode == "dual" else (2,)
        for k in range(self.N):
            for arm in arms:
                X, Y = self.cam.to_px(self.xy[idx, k, arm], self.xy[idx, k, arm + 1], self.W, self.H)
                n = len(idx) - 1
                vals = self._trail_values(k, j0, i)
                vals = np.interp(np.linspace(0, len(vals) - 1, n), np.arange(len(vals)), vals) if len(vals) else vals
                if mode == "lineart":
                    cols = np.tile([0.92, 0.94, 1.0], (n, 1))
                elif self.colors is not None:
                    cols = np.tile(self.colors[k], (n, 1))
                else:
                    cols = palettes.sample(s.palette, vals)
                if mode in ("fade", "velocity", "acceleration", "energy", "time", "dashed", "dual", "particles"):
                    alpha = np.linspace(0.0, 1.0, n) ** 1.6
                else:
                    alpha = np.ones(n)
                if arm == 0:
                    alpha *= 0.45
                if self.N > 30:
                    alpha *= 0.75
                for m in range(n):
                    if mode == "dashed" and (idx[m] // max(1, int(0.04 / self.dt))) % 2:
                        continue
                    if alpha[m] < 0.02:
                        continue
                    c = 1.0 - cols[m] if s.ink else cols[m]
                    draw.line([(X[m], Y[m]), (X[m + 1], Y[m + 1])], fill=_rgb255(c, alpha[m]), width=width)

    # ------------------------------------------------------------------ frame
    def render(self, i: int, overlay: list | None = None) -> Image.Image:
        s = self.s
        ss = s.ssaa
        W, H = self.W, self.H
        bob = self.xy[i, 0, 2:4]
        self.cam.update(bob)

        light = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(light)
        self._draw_trails(d, i)

        # particles (visual only)
        if s.particles != "none":
            fdt = self.dt * (i - self.prev_i) if self.prev_i is not None else 0.0
            j = max(i - 1, 0)
            v = (self.xy[i, 0, 2:4] - self.xy[j, 0, 2:4]) / max(self.dt * max(i - j, 1), 1e-9)
            burst = any(self.prev_i is not None and self.t[self.prev_i] < e <= self.t[i] for e in self.events)
            col = palettes.sample(s.palette, [0.8])[0]
            if s.ink:
                col = 1.0 - col
            self.particles.step(fdt, bob, v, col, burst=burst)
            self.particles.draw(d, self.cam, W, H, ss)

        # Long exposure: running per-pixel maximum (optionally decaying), all in C via Pillow.
        if s.trail == "exposure" or (s.exposure_decay < 1.0 and s.trail != "full"):
            if self.accum is not None and s.exposure_decay < 1.0:
                k = s.exposure_decay
                self.accum = self.accum.point(lambda v: int(v * k))
            light = light if self.accum is None else ImageChops.lighter(self.accum, light)
            self.accum = light
        lightsum = light
        if s.glow > 0:
            # glow computed at quarter resolution: blur + gain via lookup table, then upsample
            small = light.resize((W // 4, H // 4), Image.BILINEAR)
            small = small.filter(ImageFilter.GaussianBlur(s.glow_radius * ss / 4))
            gain = 2.2 * s.glow
            small = small.point(lambda v: min(255, int(v * gain)))
            lightsum = ImageChops.add(light, small.resize((W, H), Image.BILINEAR))

        if s.transparent:
            arr = np.asarray(lightsum, dtype=np.float32) / 255.0
            alpha = np.clip(arr.max(axis=2), 0, 1)
            rgb = np.where(alpha[..., None] > 1e-6, arr / np.maximum(alpha[..., None], 1e-6), 0)
            img = Image.fromarray((np.dstack([rgb, alpha]) * 255).astype(np.uint8), "RGBA")
        else:
            if self._bg_img is None:
                self._bg_img = Image.new("RGB", (W, H), tuple(int(255 * c) for c in self.bg))
            # dark theme adds light to the background; light theme subtracts ink from it
            img = (ImageChops.subtract if s.ink else ImageChops.add)(self._bg_img, lightsum)

        if s.show_pendulum:
            self._draw_pendulums(img, i)
        self.prev_i = i
        out = img.resize((s.width, s.height), Image.LANCZOS)
        for item in (s.overlay_text or []) + (overlay or []):
            _text(out, *item)
        return out

    def _draw_pendulums(self, img, i):
        """Rods as thin lines, bobs as solid discs. A soft halo is added only when glow > 0."""
        s = self.s
        ss = s.ssaa
        W, H = self.W, self.H
        d = ImageDraw.Draw(img, "RGBA")
        subs = [i]
        if s.motion_blur and self.prev_i is not None and i > self.prev_i:
            subs = list(np.linspace(self.prev_i, i, s.motion_blur + 1).astype(int)[1:])
        many = self.N > 12
        halo = s.glow > 0 and not many
        if halo:
            q = 4  # halo drawn and blurred at quarter resolution
            glow_layer = Image.new("RGBA", (W // q, H // q), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow_layer)
        P0 = self.cam.to_px(0.0, 0.0, W, H)
        for k in range(self.N):
            col_k = self.colors[k] if self.colors is not None else None
            for si, j in enumerate(subs):
                a = (si + 1) / len(subs)
                x1, y1, x2, y2 = self.xy[j, k]
                P1 = self.cam.to_px(x1, y1, W, H)
                P2 = self.cam.to_px(x2, y2, W, H)
                rod = palettes.hex_to_rgb(s.rod_color) if col_k is None else col_k
                rw = max(1, int(round(s.rod_width * ss * (0.5 if many else 1.0))))
                ra = int(255 * a * (0.5 if many else 1.0))
                d.line([P0, P1, P2], fill=_rgb255(rod) + (ra,), width=rw, joint="curve")
                if many:
                    continue
                for P, c, rr in ((P1, s.bob_colors[0], 0.72), (P2, s.bob_colors[1], 1.0)):
                    cc = palettes.hex_to_rgb(c) if col_k is None else col_k
                    r = s.bob_radius * ss * rr
                    if halo:
                        gd.ellipse([(P[0] - 2.4 * r) / q, (P[1] - 2.4 * r) / q, (P[0] + 2.4 * r) / q,
                                    (P[1] + 2.4 * r) / q], fill=_rgb255(cc) + (int(90 * a * s.glow),))
                    d.ellipse([P[0] - r, P[1] - r, P[0] + r, P[1] + r], fill=_rgb255(cc) + (int(255 * a),))
        if halo:
            glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(s.bob_radius * ss * 0.9 / q)).resize(
                (W, H), Image.BILINEAR)
            img.paste(Image.alpha_composite(img.convert("RGBA"), glow_layer).convert(img.mode))
            d = ImageDraw.Draw(img, "RGBA")
            for k in range(self.N):
                x1, y1, x2, y2 = self.xy[i, k]
                for (x, y), c, rr in (((x1, y1), s.bob_colors[0], 0.72), ((x2, y2), s.bob_colors[1], 1.0)):
                    cc = palettes.hex_to_rgb(c) if self.colors is None else self.colors[k]
                    P = self.cam.to_px(x, y, W, H)
                    r = s.bob_radius * ss * rr
                    d.ellipse([P[0] - r, P[1] - r, P[0] + r, P[1] + r], fill=_rgb255(cc) + (255,))
        if s.show_pivot:
            r = 2.5 * ss
            piv = palettes.hex_to_rgb(palettes.TOKENS[s.theme]["fg_3"])
            d.ellipse([P0[0] - r, P0[1] - r, P0[0] + r, P0[1] + r], fill=_rgb255(piv) + (255,))


_FONT_CACHE: dict = {}


def font(size: int, mono: bool = False):
    key = (size, mono)
    if key not in _FONT_CACHE:
        names = (["DejaVuSansMono.ttf", "Menlo.ttc", "Courier New.ttf"] if mono
                 else ["DejaVuSans.ttf", "Helvetica.ttc", "Arial.ttf"])
        f = None
        import matplotlib

        mpl_fonts = matplotlib.get_data_path() + "/fonts/ttf/"
        for n in names:
            for path in (mpl_fonts + n, n):
                try:
                    f = ImageFont.truetype(path, size)
                    break
                except OSError:
                    continue
            if f:
                break
        _FONT_CACHE[key] = f or ImageFont.load_default()
    return _FONT_CACHE[key]


def _text(img, xf, yf, text, size=16, color="#F2F2F2", mono=False, anchor="la"):
    d = ImageDraw.Draw(img)
    d.text((xf * img.width, yf * img.height), text, font=font(size, mono), fill=color, anchor=anchor)


def world_extent(L1: float, L2: float) -> float:
    return 1.12 * (L1 + L2)


def scalars_for(result) -> dict:
    """Colouring scalars for a single Result: bob speed, acceleration magnitude, kinetic energy."""
    from chaos_lab.core import physics

    p = result.config.physical
    _, _, vx2, vy2 = physics.velocities(result.y, p)
    _, _, ax2, ay2 = physics.cartesian_accelerations(result.t, result.y, p)
    speed = np.hypot(vx2, vy2)
    acc = np.hypot(ax2, ay2)
    T = physics.kinetic_energy(result.y, p)

    def rng(a):
        return (float(np.percentile(a, 2)), float(np.percentile(a, 98)))

    return {"speed": speed[:, None], "accel": acc[:, None], "energy": T[:, None],
            "speed_range": rng(speed), "accel_range": rng(acc), "energy_range": rng(T)}


def xy_from_result(result) -> np.ndarray:
    return np.stack(result.positions, axis=-1)[:, None, :]
