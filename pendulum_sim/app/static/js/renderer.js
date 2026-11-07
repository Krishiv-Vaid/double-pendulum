// PendulumRenderer — canvas renderer for one or many precomputed trajectories.
//
// Everything here is presentation: trails, glow, particles and camera motion
// are drawn *on top of* computed states and never feed back into the physics.
// Time passed to draw() is physical simulation time (s); positions between
// stored samples are linearly interpolated for display only.

import { distinct, paletteStops, rgba, sampler, token } from "./palettes.js";
import { lerpAt } from "./state.js";

const TAU = Math.PI * 2;

// Deterministic PRNG so exports with particles are reproducible.
function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function makeCanvas(w = 1, h = 1) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  return c;
}

/** Cartesian velocity/acceleration of the lower mass (derived, for display). */
export function deriveKinematics(s) {
  if (s.vx2) return s;
  const p = s.p || s.config.physical;
  const n = s.th1.length;
  s.vx2 = new Float32Array(n); s.vy2 = new Float32Array(n);
  s.ax2 = new Float32Array(n); s.ay2 = new Float32Array(n); s.acc2 = new Float32Array(n);
  let m = 1e-9;
  for (let i = 0; i < n; i++) {
    const c1 = Math.cos(s.th1[i]), s1 = Math.sin(s.th1[i]), c2 = Math.cos(s.th2[i]), s2 = Math.sin(s.th2[i]);
    const w1 = s.w1 ? s.w1[i] : 0, w2 = s.w2 ? s.w2[i] : 0, a1 = s.a1 ? s.a1[i] : 0, a2 = s.a2 ? s.a2[i] : 0;
    s.vx2[i] = p.L1 * c1 * w1 + p.L2 * c2 * w2;
    s.vy2[i] = p.L1 * s1 * w1 + p.L2 * s2 * w2;
    s.ax2[i] = p.L1 * (c1 * a1 - s1 * w1 * w1) + p.L2 * (c2 * a2 - s2 * w2 * w2);
    s.ay2[i] = p.L1 * (s1 * a1 + c1 * w1 * w1) + p.L2 * (s2 * a2 + c2 * w2 * w2);
    s.acc2[i] = Math.hypot(s.ax2[i], s.ay2[i]);
    if (s.acc2[i] > m) m = s.acc2[i];
  }
  s.maxAcc2 = m;
  return s;
}

export class PendulumRenderer {
  constructor(canvas, { fixedSize = null, maxDpr = 2 } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: true });
    this.fixedSize = fixedSize;
    this.maxDpr = maxDpr;
    this.bodies = [];
    this.ghost = null;
    this.visual = {};
    this.trailC = makeCanvas();
    this.expC = makeCanvas();
    this.b1 = makeCanvas();
    this.b2 = makeCanvas();
    this.b3 = makeCanvas();
    this.cam = { x: 0, y: 0, zoom: 1, init: false };
    this.pan = { x: 0, y: 0 };
    this.yaw = 0.55; this.pitch = 0.32; // 3D presentation camera
    this.override = null; // {th1, th2} pose while dragging
    this.particles = [];
    this.rng = mulberry32(7);
    this.stars = null;
    this.prevT = null;
    this.expIdx = -1;
    this.screen = { bob1: null, bob2: null, pivot: null };
    this.reducedMotion = false;
    this.lightBg = false;
    this.flash = 0;
    this.comTrail = [];
    this.label3d = true;
  }

  // ---------------------------------------------------------------- data
  setBodies(sims, colors = null) {
    this.bodies = sims.map((s, k) => ({ s: deriveKinematics(s), color: colors ? colors[k] : null }));
    this.R = Math.max(...sims.map((s) => (s.p || s.config.physical).L1 + (s.p || s.config.physical).L2), 0.1);
    this.resetEffects();
  }

  setGhost(sim) { this.ghost = sim; }

  setVisual(v) {
    const exposureKeys = ["palette", "custom", "trail", "trailWidth"];
    const changed = exposureKeys.some((k) => this.visual[k] !== v[k] || JSON.stringify(this.visual.custom) !== JSON.stringify(v.custom));
    this.visual = { ...v };
    this.pal = sampler(paletteStops(v.palette, v.custom));
    if (changed) this.expIdx = -1;
  }

  resetEffects() {
    this.particles = [];
    this.rng = mulberry32(7);
    this.prevT = null;
    this.expIdx = -1;
    this.cam.init = false;
    this.comTrail = [];
  }

  resetView() { this.pan = { x: 0, y: 0 }; this.cam.init = false; }

  // ---------------------------------------------------------------- geometry
  size() {
    if (this.fixedSize) return [this.fixedSize[0], this.fixedSize[1], 1];
    const dpr = Math.min(window.devicePixelRatio || 1, this.maxDpr);
    const r = this.canvas.getBoundingClientRect();
    return [Math.max(1, Math.round(r.width * dpr)), Math.max(1, Math.round(r.height * dpr)), dpr];
  }

  ensureSize() {
    const [W, H, dpr] = this.size();
    this.dpr = dpr;
    for (const c of [this.canvas, this.trailC, this.expC]) {
      if (c.width !== W || c.height !== H) { c.width = W; c.height = H; if (c === this.expC) this.expIdx = -1; }
    }
    const w1 = Math.max(1, W >> 2), h1 = Math.max(1, H >> 2);
    if (this.b1.width !== w1 || this.b1.height !== h1) { this.b1.width = w1; this.b1.height = h1; }
    const w2 = Math.max(1, W >> 3), h2 = Math.max(1, H >> 3);
    if (this.b2.width !== w2 || this.b2.height !== h2) { this.b2.width = w2; this.b2.height = h2; }
    const w3 = Math.max(1, W >> 4), h3 = Math.max(1, H >> 4);
    if (this.b3.width !== w3 || this.b3.height !== h3) { this.b3.width = w3; this.b3.height = h3; }
    this.W = W; this.H = H;
    return [W, H];
  }

  scale() {
    // Uniform scale (pixels per metre): geometry is never stretched.
    return (Math.min(this.W, this.H) / (2 * this.R * 1.14)) * this.cam.zoom * (this.visual.zoom || 1);
  }

  toScreen(x, y) {
    const sc = this.scale();
    return [this.W / 2 + (x - this.cam.x) * sc + this.pan.x * this.dpr, this.H / 2 - (y - this.cam.y) * sc + this.pan.y * this.dpr];
  }

  toWorld(px, py) {
    const sc = this.scale();
    return [(px * this.dpr - this.W / 2 - this.pan.x * this.dpr) / sc + this.cam.x, -(py * this.dpr - this.H / 2 - this.pan.y * this.dpr) / sc + this.cam.y];
  }

  hitTest(px, py) {
    const d = (p) => (p ? Math.hypot(p[0] - px * this.dpr, p[1] - py * this.dpr) : Infinity);
    const r = 22 * this.dpr;
    const d2 = d(this.screen.bob2), d1 = d(this.screen.bob1);
    if (d2 < r && d2 <= d1) return "bob2";
    if (d1 < r) return "bob1";
    return null;
  }

  // ---------------------------------------------------------------- camera
  updateCamera(fi, dtWall) {
    const v = this.visual;
    const b = this.bodies[0];
    if (!b) return;
    const mode = v.camera || "static";
    let tx = 0, ty = 0, tz = 1;
    if (mode === "follow") {
      tx = lerpAt(b.s.x2, fi) * 0.75; ty = lerpAt(b.s.y2, fi) * 0.75; tz = 1.35;
    } else if (mode === "autofit") {
      // Fit the visible trail window and the current pose.
      const s = b.s, i1 = Math.floor(fi), i0 = Math.max(0, i1 - Math.round((v.trailSeconds || 3) / s.dt));
      let x0 = 0, x1 = 0, y0 = 0, y1 = 0;
      const step = Math.max(1, Math.floor((i1 - i0) / 200));
      for (let i = i0; i <= i1; i += step) {
        x0 = Math.min(x0, s.x2[i], s.x1[i]); x1 = Math.max(x1, s.x2[i], s.x1[i]);
        y0 = Math.min(y0, s.y2[i], s.y1[i]); y1 = Math.max(y1, s.y2[i], s.y1[i]);
      }
      tx = (x0 + x1) / 2; ty = (y0 + y1) / 2;
      const ext = Math.max(x1 - x0, y1 - y0, 0.4 * this.R);
      tz = Math.min(2.6, Math.max(1, (2 * this.R) / (ext * 1.15)));
    }
    if (!this.cam.init || mode === "static") {
      this.cam.x = tx; this.cam.y = ty; this.cam.zoom = tz; this.cam.init = true;
      return;
    }
    // Frame-rate independent exponential easing.
    const e = 1 - Math.pow(1 - Math.min(0.95, Math.max(0.005, v.easing || 0.08)), Math.max(0, dtWall) * 60);
    this.cam.x += (tx - this.cam.x) * e;
    this.cam.y += (ty - this.cam.y) * e;
    this.cam.zoom += (tz - this.cam.zoom) * e;
  }

  // ---------------------------------------------------------------- main
  /** Draw the scene at physical time t. dtWall = wall seconds since last frame. */
  draw(t, dtWall = 1 / 60) {
    const [W, H] = this.ensureSize();
    const ctx = this.ctx;
    const v = this.visual;
    if (!this.bodies.length) { ctx.clearRect(0, 0, W, H); return; }
    const s0 = this.bodies[0].s;
    const fi = Math.max(0, Math.min(s0.n - 1, t / s0.dt));
    this.updateCamera(fi, dtWall);
    const themeLight = document.documentElement.dataset.theme === "light";
    const light = v.background === "white" || ((v.background === "theme" || v.background === "transparent") && themeLight);
    if (light !== this.lightBg) this.expIdx = -1; // exposure layer must be repainted in the other ramp
    this.lightBg = light;
    // Trails resolve against the actual canvas background, so a white ramp is
    // never drawn on white (and black never on black), including in exports.
    this.pal = sampler(paletteStops(v.palette, null, light));
    this.fg = light ? [0, 0, 0] : [255, 255, 255];
    this.fg2 = light ? [74, 74, 74] : [176, 176, 176];
    this.fg3 = light ? [143, 143, 143] : [107, 107, 107];

    if (v.render3d) return this.draw3D(t, fi, dtWall);

    // background (+ optional motion blur by partial clearing)
    const blur = this.reducedMotion ? 0 : (v.motionBlur || 0);
    if (blur > 0 && this.prevT !== null) {
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1 - Math.min(0.92, blur * 0.92);
      this.paintBackground(ctx, W, H);
      ctx.globalAlpha = 1;
    } else {
      ctx.clearRect(0, 0, W, H);
      this.paintBackground(ctx, W, H);
    }
    if (v.particles === "stars" && !this.reducedMotion) this.drawStars(ctx, t);
    if (v.grid) this.drawGrid(ctx);

    // trails
    const tctx = this.trailC.getContext("2d");
    tctx.clearRect(0, 0, W, H);
    if (v.trail === "exposure") {
      this.drawExposure(fi);
      tctx.drawImage(this.expC, 0, 0);
    } else {
      this.drawTrails(tctx, t, fi);
    }
    this.composite(ctx, this.trailC, v.trail === "lineart" ? 0 : v.glow);

    // particles
    const dtPhys = this.prevT === null ? 0 : Math.min(0.1, Math.abs(t - this.prevT));
    if (!this.reducedMotion && v.particles && v.particles !== "none") {
      this.stepParticles(fi, dtPhys, t);
      this.drawParticles(ctx);
    }

    // centre of mass
    if (v.com) this.drawCOM(ctx, fi);

    // rods and masses
    for (let k = this.bodies.length - 1; k >= 0; k--) this.drawPendulum(ctx, k, fi);
    if (v.vectors && v.vectors !== "none") this.drawVectors(ctx, fi);
    if (this.flash > 0 && !this.reducedMotion) {
      ctx.globalCompositeOperation = "lighter";
      ctx.fillStyle = `rgba(255,255,255,${this.flash * 0.06})`;
      ctx.fillRect(0, 0, W, H);
      this.flash *= 0.85;
      ctx.globalCompositeOperation = "source-over";
    }
    this.prevT = t;
  }

  paintBackground(ctx, W, H) {
    const bg = this.visual.background || "theme";
    const fill = bg === "black" ? "#000" : bg === "white" ? "#fff" : (bg === "theme" ? (token("bg") || "#000") : null);
    if (bg === "transparent" && !(this.visual.motionBlur && this.prevT !== null && !this.reducedMotion)) return;
    ctx.fillStyle = fill || (this.lightBg ? "#fff" : "#000");
    ctx.fillRect(0, 0, W, H);
  }

  drawGrid(ctx) {
    const sc = this.scale();
    const step = 0.5;
    ctx.save();
    ctx.strokeStyle = this.lightBg ? "#efefef" : "#161616";
    ctx.lineWidth = 1;
    const [wx0, wy1] = this.toWorld(0, 0), [wx1, wy0] = this.toWorld(this.W / this.dpr, this.H / this.dpr);
    ctx.beginPath();
    for (let x = Math.floor(wx0 / step) * step; x <= wx1; x += step) { const [px] = this.toScreen(x, 0); ctx.moveTo(px, 0); ctx.lineTo(px, this.H); }
    for (let y = Math.floor(wy0 / step) * step; y <= wy1; y += step) { const [, py] = this.toScreen(0, y); ctx.moveTo(0, py); ctx.lineTo(this.W, py); }
    ctx.stroke();
    // scale bar: 1 m
    const x0 = this.W - 24 * this.dpr - sc, y0 = this.H - 22 * this.dpr;
    ctx.strokeStyle = rgba(this.fg3);
    ctx.lineWidth = 2 * this.dpr;
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x0 + sc, y0); ctx.moveTo(x0, y0 - 4 * this.dpr); ctx.lineTo(x0, y0 + 4 * this.dpr);
    ctx.moveTo(x0 + sc, y0 - 4 * this.dpr); ctx.lineTo(x0 + sc, y0 + 4 * this.dpr); ctx.stroke();
    ctx.fillStyle = ctx.strokeStyle;
    ctx.font = `${11 * this.dpr}px ui-monospace, monospace`;
    ctx.textAlign = "center";
    ctx.fillText("1 m", x0 + sc / 2, y0 - 7 * this.dpr);
    ctx.restore();
  }

  // ---------------------------------------------------------------- trails
  /** Stroke a polyline whose segments have (u, a) colour/alpha params, batched
   *  into runs that share a quantized key — one stroke per run, not per segment. */
  strokeRuns(ctx, xs, ys, us, as, n, width, fixedColor, taper) {
    if (n < 2) return;
    const pal = this.pal;
    let key = -1, open = false;
    const flush = () => { if (open) ctx.stroke(); open = false; };
    for (let j = 0; j < n - 1; j++) {
      const ab = Math.max(0, Math.min(15, Math.round(as[j] * 15)));
      if (ab === 0) continue;
      const cb = fixedColor ? 0 : Math.max(0, Math.min(63, Math.round(us[j] * 63)));
      const k = cb * 16 + ab;
      if (k !== key) {
        flush();
        key = k;
        const col = fixedColor || pal(cb / 63);
        ctx.strokeStyle = rgba(col, ab / 15);
        ctx.lineWidth = taper ? width * (0.3 + 0.7 * (ab / 15)) : width;
        ctx.beginPath();
        ctx.moveTo(xs[j], ys[j]);
        open = true;
      }
      ctx.lineTo(xs[j + 1], ys[j + 1]);
    }
    flush();
  }

  trailWindow(s, t, fi, seconds) {
    const iEnd = Math.floor(fi);
    const i0 = seconds === Infinity ? 0 : Math.max(0, Math.floor((t - seconds) / s.dt));
    return [i0, iEnd];
  }

  buildTrail(s, which, i0, iEnd, fi, maxPts) {
    const X = which === 1 ? s.x1 : s.x2, Y = which === 1 ? s.y1 : s.y2;
    const count = iEnd - i0 + 1;
    const step = Math.max(1, Math.ceil(count / maxPts));
    const m = Math.floor((count - 1) / step) + 2;
    const xs = new Float32Array(m), ys = new Float32Array(m), idx = new Float32Array(m);
    let k = 0;
    for (let i = i0; i <= iEnd; i += step) {
      const [px, py] = this.toScreen(X[i], Y[i]);
      xs[k] = px; ys[k] = py; idx[k] = i; k++;
    }
    const [hx, hy] = this.toScreen(lerpAt(X, fi), lerpAt(Y, fi)); // exact head
    xs[k] = hx; ys[k] = hy; idx[k] = fi; k++;
    return { xs, ys, idx, n: k };
  }

  drawTrails(ctx, t, fi) {
    const v = this.visual;
    const mode = v.trail || "fade";
    const many = this.bodies.length > 1;
    const width = (v.trailWidth || 2) * this.dpr * (many ? 0.7 : 1);
    const secs = mode === "full" || mode === "lineart" ? Infinity : Math.max(0.05, v.trailSeconds || 3);
    ctx.globalCompositeOperation = this.lightBg ? "source-over" : "lighter";
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    const budget = Math.max(60, Math.floor(60000 / this.bodies.length));

    if (mode === "ghost" && this.ghost && !many) {
      const g = this.ghost;
      const gi = Math.min(g.n - 1, fi * (this.bodies[0].s.dt / g.dt));
      const tr = this.buildTrail(g, 2, 0, Math.floor(gi), gi, 2500);
      const a = new Float32Array(tr.n).fill(0.28), u = new Float32Array(tr.n).fill(0.5);
      this.strokeRuns(ctx, tr.xs, tr.ys, u, a, tr.n, width * 0.8, this.fg3);
      // ghost pendulum outline
      ctx.save();
      ctx.globalCompositeOperation = "source-over";
      ctx.strokeStyle = rgba(this.fg3, 0.6);
      ctx.setLineDash([4 * this.dpr, 4 * this.dpr]);
      ctx.lineWidth = 1.5 * this.dpr;
      const [p0x, p0y] = this.toScreen(0, 0), [g1x, g1y] = this.toScreen(lerpAt(g.x1, gi), lerpAt(g.y1, gi)), [g2x, g2y] = this.toScreen(lerpAt(g.x2, gi), lerpAt(g.y2, gi));
      ctx.beginPath(); ctx.moveTo(p0x, p0y); ctx.lineTo(g1x, g1y); ctx.lineTo(g2x, g2y); ctx.stroke();
      ctx.restore();
    }

    if (mode === "dashed") ctx.setLineDash([7 * this.dpr, 7 * this.dpr]);
    this.bodies.forEach((b, k) => {
      const s = b.s;
      const [i0, iEnd] = this.trailWindow(s, t, fi, secs);
      const trails = mode === "dual" ? [1, 2] : [2];
      for (const which of trails) {
        const tr = this.buildTrail(s, which, i0, iEnd, fi, Math.min(budget, mode === "full" ? 3000 : 1500));
        const us = new Float32Array(tr.n), as = new Float32Array(tr.n);
        const t0 = s.t[i0], span = Math.max(1e-9, t - t0);
        for (let j = 0; j < tr.n; j++) {
          const i = Math.min(s.n - 1, Math.round(tr.idx[j]));
          const age = Math.max(0, Math.min(1, (tr.idx[j] * s.dt - t0) / span)); // 0 old -> 1 new
          let u = age, a = Math.pow(age, 1.25);
          switch (mode) {
            case "full": u = s.t[i] / s.tEnd; a = 0.8; break;
            case "time": u = s.t[i] / s.tEnd; a = 0.2 + 0.8 * age; break;
            case "velocity": u = Math.min(1, Math.hypot(s.vx2[i], s.vy2[i]) / (s.maxSpeed || 1)); break;
            case "acceleration": u = Math.min(1, s.acc2[i] / (s.maxAcc2 || 1)); break;
            case "energy": u = s.T ? Math.min(1, s.T[i] / (s.maxT || 1)) : age; break;
            case "lineart": a = 0.85; break;
            case "dual": u = which === 1 ? 0.15 + 0.2 * age : 0.55 + 0.45 * age; a = which === 1 ? a * 0.6 : a; break;
            default: break;
          }
          us[j] = u; as[j] = a;
        }
        let fixed = b.color || null;
        if (mode === "lineart") fixed = this.fg;
        const w = mode === "lineart" ? Math.max(0.8, width * 0.45) : width;
        this.strokeRuns(ctx, tr.xs, tr.ys, us, as, tr.n, w, fixed, mode === "fade" || mode === "particles" || mode === "ghost");
      }
    });
    ctx.setLineDash([]);
    ctx.globalCompositeOperation = "source-over";
  }

  drawExposure(fi) {
    // Long exposure: segments accumulate additively on a persistent layer.
    const ctx = this.expC.getContext("2d");
    const iEnd = Math.floor(fi);
    if (this.expIdx < 0 || iEnd < this.expIdx) { ctx.clearRect(0, 0, this.W, this.H); this.expIdx = 0; }
    if (this.visual.camera && this.visual.camera !== "static") { ctx.clearRect(0, 0, this.W, this.H); this.expIdx = 0; }
    if (iEnd <= this.expIdx) return;
    ctx.globalCompositeOperation = this.lightBg ? "source-over" : "lighter";
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    const width = (this.visual.trailWidth || 2) * this.dpr * (this.bodies.length > 1 ? 0.6 : 0.9);
    const alpha = this.bodies.length > 1 ? 0.25 : 0.55;
    for (const b of this.bodies) {
      const s = b.s;
      const tr = this.buildTrail(s, 2, this.expIdx, iEnd, iEnd, 4000);
      const us = new Float32Array(tr.n), as = new Float32Array(tr.n).fill(alpha);
      for (let j = 0; j < tr.n; j++) us[j] = s.t[Math.min(s.n - 1, Math.round(tr.idx[j]))] / s.tEnd;
      this.strokeRuns(ctx, tr.xs, tr.ys, us, as, tr.n, width, b.color || null, false);
    }
    this.expIdx = iEnd;
    ctx.globalCompositeOperation = "source-over";
  }

  /** Bloom: blur by downsampling (1/4 and 1/8 scale) and add back. */
  composite(ctx, layer, glow) {
    const g = Math.min(0.25, Math.max(0, glow || 0)) * (this.visual.bloom ?? 1); // faint grey bloom only
    if (g > 0.01 && !this.lightBg) {
      const c1 = this.b1.getContext("2d"), c2 = this.b2.getContext("2d");
      c1.clearRect(0, 0, this.b1.width, this.b1.height);
      c1.imageSmoothingEnabled = true; c1.imageSmoothingQuality = "high";
      c1.drawImage(layer, 0, 0, this.b1.width, this.b1.height);
      c2.clearRect(0, 0, this.b2.width, this.b2.height);
      c2.imageSmoothingEnabled = true; c2.imageSmoothingQuality = "high";
      c2.drawImage(this.b1, 0, 0, this.b2.width, this.b2.height);
      const c3 = this.b3.getContext("2d");
      c3.clearRect(0, 0, this.b3.width, this.b3.height);
      c3.imageSmoothingEnabled = true; c3.imageSmoothingQuality = "high";
      c3.drawImage(this.b2, 0, 0, this.b3.width, this.b3.height);
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
      ctx.globalAlpha = Math.min(1, 0.9 * g);
      ctx.drawImage(this.b3, 0, 0, this.W, this.H); // wide halo
      ctx.globalAlpha = Math.min(1, 1.0 * g);
      ctx.drawImage(this.b2, 0, 0, this.W, this.H);
      ctx.globalAlpha = Math.min(1, 0.8 * g);
      ctx.drawImage(this.b1, 0, 0, this.W, this.H); // tight core glow
      ctx.restore();
    }
    ctx.save();
    ctx.globalCompositeOperation = this.lightBg ? "source-over" : "lighter";
    ctx.drawImage(layer, 0, 0);
    ctx.restore();
  }

  // ---------------------------------------------------------------- pendulum
  pose(k, fi) {
    const b = this.bodies[k];
    if (k === 0 && this.override) {
      const p = b.s.p || b.s.config.physical;
      const x1 = p.L1 * Math.sin(this.override.th1), y1 = -p.L1 * Math.cos(this.override.th1);
      return [x1, y1, x1 + p.L2 * Math.sin(this.override.th2), y1 - p.L2 * Math.cos(this.override.th2)];
    }
    const s = b.s;
    return [lerpAt(s.x1, fi), lerpAt(s.y1, fi), lerpAt(s.x2, fi), lerpAt(s.y2, fi)];
  }

  drawPendulum(ctx, k, fi) {
    const v = this.visual;
    const b = this.bodies[k];
    const many = this.bodies.length > 1;
    const p = b.s.p || b.s.config.physical;
    const [x1, y1, x2, y2] = this.pose(k, fi);
    const [px, py] = this.toScreen(0, 0), [ax, ay] = this.toScreen(x1, y1), [bx, by] = this.toScreen(x2, y2);
    const dpr = this.dpr;
    const sc = this.scale();
    ctx.save();
    if (v.rods !== false) {
      ctx.lineCap = "round"; ctx.lineJoin = "round";
      ctx.strokeStyle = many ? rgba(b.color || this.fg2, 0.45) : rgba(this.fg2);
      ctx.lineWidth = many ? 1 * dpr : Math.max(1.5 * dpr, 0.012 * sc);
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    }
    const base = Math.max(3.5 * dpr, 0.045 * sc) * (v.massSize || 1);
    const r1 = many ? 2 * dpr : base * Math.cbrt(p.m1), r2 = many ? 2.4 * dpr : base * Math.cbrt(p.m2);
    const col = many ? (b.color || this.fg) : this.fg;
    this.drawMass(ctx, ax, ay, r1, col);
    this.drawMass(ctx, bx, by, r2, col);
    if (k === 0) {
      if (v.showPivot !== false) {
        ctx.fillStyle = rgba(this.fg3);
        ctx.beginPath(); ctx.arc(px, py, 2.5 * dpr, 0, TAU); ctx.fill();
      }
      this.screen = { pivot: [px, py], bob1: [ax, ay], bob2: [bx, by] };
    }
    ctx.restore();
  }

  massColor() { return this.fg; }

  /** Solid bob: flat fill, no specular highlight, no halo. */
  drawMass(ctx, x, y, r, col) {
    ctx.fillStyle = rgba(col, 1);
    ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.fill();
  }

  drawVectors(ctx, fi) {
    const s = this.bodies[0].s;
    const [, , x2, y2] = this.pose(0, fi);
    const which = this.visual.vectors;
    const vx = which === "velocity" ? lerpAt(s.vx2, fi) * 0.12 : lerpAt(s.ax2, fi) * 0.012;
    const vy = which === "velocity" ? lerpAt(s.vy2, fi) * 0.12 : lerpAt(s.ay2, fi) * 0.012;
    const [a, b] = this.toScreen(x2, y2), [c, d] = this.toScreen(x2 + vx, y2 + vy);
    const col = rgba(which === "velocity" ? this.fg : this.fg2);
    arrow(ctx, a, b, c, d, col, 2 * this.dpr);
    ctx.fillStyle = col;
    ctx.font = `${11 * this.dpr}px ui-monospace, monospace`;
    const mag = which === "velocity" ? Math.hypot(vx, vy) / 0.12 : Math.hypot(vx, vy) / 0.012;
    ctx.fillText(which === "velocity" ? `|v₂| ${mag.toFixed(2)} m/s` : `|a₂| ${mag.toFixed(1)} m/s²`, c + 8 * this.dpr, d);
  }

  drawCOM(ctx, fi) {
    const s = this.bodies[0].s, p = s.p || s.config.physical;
    const m = p.m1 + p.m2;
    const cx = (p.m1 * lerpAt(s.x1, fi) + p.m2 * lerpAt(s.x2, fi)) / m;
    const cy = (p.m1 * lerpAt(s.y1, fi) + p.m2 * lerpAt(s.y2, fi)) / m;
    this.comTrail.push([cx, cy]);
    if (this.comTrail.length > 240) this.comTrail.shift();
    ctx.save();
    ctx.strokeStyle = rgba(this.fg2, 0.5);
    ctx.lineWidth = 1.2 * this.dpr;
    ctx.beginPath();
    this.comTrail.forEach(([x, y], i) => { const [a, b] = this.toScreen(x, y); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); });
    ctx.stroke();
    const [a, b] = this.toScreen(cx, cy);
    ctx.strokeStyle = rgba(this.fg2); ctx.lineWidth = 1.5 * this.dpr;
    ctx.beginPath(); ctx.arc(a, b, 5 * this.dpr, 0, TAU); ctx.moveTo(a - 8 * this.dpr, b); ctx.lineTo(a + 8 * this.dpr, b); ctx.moveTo(a, b - 8 * this.dpr); ctx.lineTo(a, b + 8 * this.dpr); ctx.stroke();
    ctx.restore();
  }

  // ---------------------------------------------------------------- particles
  stepParticles(fi, dtPhys, t) {
    const v = this.visual;
    const kind = v.particles;
    const s = this.bodies[0].s;
    const rate = v.particleRate ?? 1, life = v.particleLife ?? 1.2, spd = v.particleSpeed ?? 1;
    const [, , x2, y2] = this.pose(0, fi);
    const vx = lerpAt(s.vx2, fi), vy = lerpAt(s.vy2, fi);
    const speed = Math.hypot(vx, vy);
    const rnd = this.rng;
    // Flip detection between frames → burst
    if (this.prevT !== null && kind === "burst") {
      const pf = Math.max(0, Math.min(s.n - 1, this.prevT / s.dt));
      const wi = (a) => Math.floor((a + Math.PI) / TAU);
      for (const arr of [s.th1, s.th2]) {
        if (wi(lerpAt(arr, pf)) !== wi(lerpAt(arr, fi))) {
          for (let k = 0; k < 70 * rate; k++) {
            const ang = rnd() * TAU, sp = (0.6 + rnd() * 2.2) * spd;
            this.spawn(x2, y2, Math.cos(ang) * sp, Math.sin(ang) * sp, life * (0.6 + rnd() * 0.8), this.pal(rnd()), 1.4, "burst");
          }
          this.flash = 1;
        }
      }
    }
    if (dtPhys <= 0) { this.ageParticles(0); return; }
    const intensity = Math.min(1, speed / (s.maxSpeed || 1));
    let count = rate * dtPhys * (kind === "smoke" ? 25 : kind === "dust" ? 40 : 160) * (kind === "dust" || kind === "smoke" ? 1 : intensity);
    let nEmit = Math.floor(count) + (rnd() < count % 1 ? 1 : 0);
    nEmit = Math.min(nEmit, 200);
    for (let k = 0; k < nEmit; k++) {
      const u = rnd();
      switch (kind) {
        case "sparks": {
          const ang = rnd() * TAU, sp = (0.3 + rnd() * 1.6) * spd;
          this.spawn(x2, y2, vx * 0.35 + Math.cos(ang) * sp, vy * 0.35 + Math.sin(ang) * sp, life * (0.3 + rnd() * 0.5), this.pal(0.6 + 0.4 * u), 0.8, "spark");
          break;
        }
        case "dust": {
          const ang = rnd() * TAU, sp = 0.08 * spd * rnd();
          this.spawn(x2 + (rnd() - 0.5) * 0.04, y2 + (rnd() - 0.5) * 0.04, Math.cos(ang) * sp, Math.sin(ang) * sp, life * (1 + rnd() * 2), this.pal(u), 0.6, "dust");
          break;
        }
        case "comet":
          this.spawn(x2, y2, -vx * 0.08 * spd + (rnd() - 0.5) * 0.1, -vy * 0.08 * spd + (rnd() - 0.5) * 0.1, life * (0.5 + rnd() * 0.5), this.pal(intensity), 2.2, "comet");
          break;
        case "confetti": {
          const ang = rnd() * TAU, sp = (0.4 + rnd()) * spd;
          this.spawn(x2, y2, Math.cos(ang) * sp, Math.sin(ang) * sp + 0.6, life * (0.8 + rnd()), this.pal(rnd()), 1.6, "confetti");
          break;
        }
        case "smoke":
          this.spawn(x2, y2, (rnd() - 0.5) * 0.12 * spd, 0.12 * spd, life * (1.5 + rnd()), this.pal(0.5 + 0.2 * u), 4, "smoke");
          break;
        case "burst": case "stars":
          if (rnd() < 0.3) this.spawn(x2, y2, (rnd() - 0.5) * 0.2, (rnd() - 0.5) * 0.2, life, this.pal(u), 0.7, "dust");
          break;
        default: break;
      }
    }
    this.ageParticles(dtPhys);
  }

  spawn(x, y, vx, vy, life, col, size, kind) {
    if (this.particles.length > 5000) this.particles.shift();
    this.particles.push({ x, y, vx, vy, life, max: life, col, size, kind, rot: this.rng() * TAU, vr: (this.rng() - 0.5) * 12 });
  }

  ageParticles(dt) {
    const ps = this.particles;
    let w = 0;
    for (let i = 0; i < ps.length; i++) {
      const q = ps[i];
      q.life -= dt;
      if (q.life <= 0) continue;
      const drag = q.kind === "spark" ? 2.4 : q.kind === "comet" ? 1.2 : q.kind === "smoke" ? 0.4 : 1;
      q.vx *= Math.exp(-drag * dt); q.vy *= Math.exp(-drag * dt);
      if (q.kind === "confetti") q.vy -= 2.0 * dt; // decorative fall (visual only)
      q.x += q.vx * dt; q.y += q.vy * dt; q.rot += q.vr * dt;
      ps[w++] = q;
    }
    ps.length = w;
  }

  drawParticles(ctx) {
    const op = this.visual.particleOpacity ?? 0.9, sz = (this.visual.particleSize ?? 1) * this.dpr;
    ctx.save();
    ctx.globalCompositeOperation = this.lightBg ? "source-over" : "lighter";
    for (const q of this.particles) {
      const f = q.life / q.max;
      const [x, y] = this.toScreen(q.x, q.y);
      if (q.kind === "spark") {
        const [x0, y0] = this.toScreen(q.x - q.vx * 0.03, q.y - q.vy * 0.03);
        ctx.strokeStyle = rgba(q.col, op * f);
        ctx.lineWidth = q.size * sz * 1.4;
        ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x, y); ctx.stroke();
      } else if (q.kind === "confetti") {
        ctx.save(); ctx.translate(x, y); ctx.rotate(q.rot);
        ctx.fillStyle = rgba(q.col, op * Math.min(1, f * 2));
        ctx.fillRect(-2.5 * sz, -1.2 * sz, 5 * sz, 2.4 * sz);
        ctx.restore();
      } else {
        const r = q.kind === "smoke" ? q.size * sz * (1 + 5 * (1 - f)) : q.size * sz * (q.kind === "comet" ? 0.6 + f : 1) * 1.6;
        const a = op * (q.kind === "smoke" ? 0.12 * f : f);
        const g = ctx.createRadialGradient(x, y, 0, x, y, r * 2);
        g.addColorStop(0, rgba(q.col, a)); g.addColorStop(1, rgba(q.col, 0));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, r * 2, 0, TAU); ctx.fill();
      }
    }
    ctx.restore();
  }

  drawStars(ctx, t) {
    if (!this.stars) {
      const r = mulberry32(99);
      this.stars = Array.from({ length: 220 }, () => [r(), r(), r() * 1.2 + 0.3, r() * TAU]);
    }
    ctx.save();
    for (const [u, v, s, ph] of this.stars) {
      const a = 0.25 + 0.35 * (0.5 + 0.5 * Math.sin(t * 1.3 + ph));
      ctx.fillStyle = this.lightBg ? `rgba(0,0,0,${a * 0.5})` : `rgba(255,255,255,${a})`;
      ctx.fillRect(u * this.W, v * this.H, s * this.dpr, s * this.dpr);
    }
    ctx.restore();
  }

  // ---------------------------------------------------------------- 3D presentation
  project(x, y, z) {
    // orbit camera: yaw about y, pitch about x; perspective divide.
    const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw), cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
    const X = cy * x + sy * z, Z0 = -sy * x + cy * z;
    const Y = cp * y - sp * Z0, Z = sp * y + cp * Z0;
    const D = 3.6 * this.R;
    const f = (Math.min(this.W, this.H) * 0.95) * (this.visual.zoom || 1);
    const k = f / (D - Z);
    return [this.W / 2 + X * k + this.pan.x * this.dpr, this.H * 0.47 - (Y + 0.15 * this.R) * k + this.pan.y * this.dpr, k];
  }

  draw3D(t, fi, dtWall) {
    const ctx = this.ctx, W = this.W, H = this.H, v = this.visual, dpr = this.dpr;
    if (v.camera === "follow" || v.camera === "autofit") this.yaw += dtWall * 0.18; // cinematic orbit
    ctx.clearRect(0, 0, W, H);
    this.paintBackground(ctx, W, H);
    const R = this.R, floorY = -R - 0.25;
    // floor grid
    ctx.save();
    ctx.strokeStyle = this.lightBg ? "#efefef" : "#161616";
    ctx.lineWidth = 1;
    const ext = R * 1.6, st = R / 4;
    ctx.beginPath();
    for (let a = -ext; a <= ext + 1e-9; a += st) {
      let [x0, y0] = this.project(a, floorY, -ext), [x1, y1] = this.project(a, floorY, ext);
      ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
      [x0, y0] = this.project(-ext, floorY, a); [x1, y1] = this.project(ext, floorY, a);
      ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
    }
    ctx.stroke();
    // support frame
    const [sx0, sy0] = this.project(0, 0, -0.3 * R), [sx1, sy1] = this.project(0, 0, 0.3 * R);
    ctx.strokeStyle = rgba(this.fg3); ctx.lineWidth = 3 * dpr;
    ctx.beginPath(); ctx.moveTo(sx0, sy0); ctx.lineTo(sx1, sy1); ctx.stroke();
    ctx.restore();

    const s = this.bodies[0].s;
    const [x1, y1, x2, y2] = this.pose(0, fi);
    // shadows (light from directly above → orthographic drop onto the floor)
    ctx.save();
    ctx.strokeStyle = "rgba(0,0,0,0.35)"; ctx.lineWidth = 5 * dpr; ctx.lineCap = "round";
    const sh = (x) => this.project(x, floorY, 0);
    const [s0x, s0y] = sh(0), [s1x, s1y] = sh(x1), [s2x, s2y] = sh(x2);
    ctx.beginPath(); ctx.moveTo(s0x, s0y); ctx.lineTo(s1x, s1y); ctx.lineTo(s2x, s2y); ctx.stroke();
    for (const [x, y, k] of [[s1x, s1y, 1], [s2x, s2y, 1]]) {
      ctx.fillStyle = "rgba(0,0,0,0.35)";
      ctx.beginPath(); ctx.ellipse(x, y, 10 * dpr * k, 4 * dpr * k, 0, 0, TAU); ctx.fill();
    }
    ctx.restore();

    // trail (projected) into the glow layer
    const tctx = this.trailC.getContext("2d");
    tctx.clearRect(0, 0, W, H);
    const [i0, iEnd] = this.trailWindow(s, t, fi, Math.max(0.05, v.trailSeconds || 3));
    const n = Math.min(1500, iEnd - i0 + 2);
    const step = Math.max(1, Math.ceil((iEnd - i0 + 1) / 1500));
    const xs = new Float32Array(n + 1), ys = new Float32Array(n + 1), us = new Float32Array(n + 1), as = new Float32Array(n + 1);
    let m = 0;
    for (let i = i0; i <= iEnd && m < n; i += step) {
      const [a, b] = this.project(s.x2[i], s.y2[i], 0);
      xs[m] = a; ys[m] = b;
      const age = (i - i0) / Math.max(1, iEnd - i0);
      us[m] = age; as[m] = Math.pow(age, 1.25); m++;
    }
    const [hx, hy] = this.project(x2, y2, 0);
    xs[m] = hx; ys[m] = hy; us[m] = 1; as[m] = 1; m++;
    tctx.globalCompositeOperation = this.lightBg ? "source-over" : "lighter";
    tctx.lineCap = "round"; tctx.lineJoin = "round";
    this.strokeRuns(tctx, xs, ys, us, as, m, (v.trailWidth || 2) * dpr, null, true);
    this.composite(ctx, this.trailC, v.glow);

    // rods as shaded cylinders, masses as lit spheres
    const P0 = this.project(0, 0, 0), P1 = this.project(x1, y1, 0), P2 = this.project(x2, y2, 0);
    const rod = (A, B) => {
      const g = ctx.createLinearGradient(A[0] - 6, A[1], A[0] + 6, A[1]);
      void g;
      ctx.strokeStyle = rgba(this.fg2); ctx.lineWidth = Math.max(2, 0.02 * A[2] * R); ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(A[0], A[1]); ctx.lineTo(B[0], B[1]); ctx.stroke();
    };
    rod(P0, P1); rod(P1, P2);
    const p = s.p || s.config.physical;
    this.drawMass(ctx, P1[0], P1[1], 0.07 * P1[2] * Math.cbrt(p.m1) * (v.massSize || 1), this.fg);
    this.drawMass(ctx, P2[0], P2[1], 0.07 * P2[2] * Math.cbrt(p.m2) * (v.massSize || 1), this.fg);
    this.screen = { pivot: P0, bob1: P1, bob2: P2 };
    if (this.label3d) {
      ctx.fillStyle = rgba(this.fg3);
      ctx.font = `${11 * dpr}px system-ui, -apple-system, sans-serif`;
      ctx.textAlign = "right";
      ctx.fillText("3D presentation of planar motion — the physics stays 2D", W - 14 * dpr, H - 14 * dpr);
      ctx.textAlign = "left";
    }
    this.prevT = t;
  }
}

function arrow(ctx, x0, y0, x1, y1, col, w) {
  const ang = Math.atan2(y1 - y0, x1 - x0), L = Math.hypot(x1 - x0, y1 - y0);
  if (L < 2) return;
  ctx.save();
  ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = w;
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
  const hl = Math.min(12 * w / 2, L * 0.4);
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x1 - hl * Math.cos(ang - 0.4), y1 - hl * Math.sin(ang - 0.4));
  ctx.lineTo(x1 - hl * Math.cos(ang + 0.4), y1 - hl * Math.sin(ang + 0.4));
  ctx.closePath(); ctx.fill();
  ctx.restore();
}
