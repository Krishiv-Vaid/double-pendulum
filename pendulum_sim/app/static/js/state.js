// Application state: numerical config (sent to the server), visual settings
// (browser only), and a shared playback clock. Three kinds of state are kept
// strictly apart so that a colour change never triggers an integration.

import { PALETTES } from "./palettes.js";

export const DEFAULT_CONFIG = {
  name: "Classic Double Pendulum",
  physical: { m1: 1, m2: 1, L1: 1, L2: 1, g: 9.81, damping1: 0, damping2: 0, drive_amplitude: 0, drive_frequency: 0, drive_phase: 0 },
  initial: { theta1_deg: 120, theta2_deg: -10, omega1: 0, omega2: 0 },
  numerics: { method: "rk4", dt: 0.001, rtol: 1e-10, atol: 1e-10, t_max: 30, output_dt: 1 / 240 },
};

export const DEFAULT_VISUAL = {
  palette: "auto", // auto | white | silver | black | gray
  trail: "fade", // full | fade | exposure | velocity | acceleration | energy | time | dashed | dual | lineart | ghost | particles
  trailSeconds: 3,
  trailWidth: 1.6,
  glow: 0, // at most MAX_GLOW: a faint grey bloom, never a coloured halo
  bloom: 1,
  rods: true,
  massSize: 1,
  showPivot: true,
  background: "theme", // theme | black | white | transparent
  particles: "none", // none | sparks | dust | comet | burst | confetti | stars | smoke
  particleRate: 1,
  particleLife: 1.2,
  particleSize: 1,
  particleSpeed: 1,
  particleOpacity: 0.9,
  camera: "static", // static | autofit | follow
  zoom: 1,
  easing: 0.08,
  motionBlur: 0,
  hud: true,
  grid: false,
  vectors: "none", // none | velocity | acceleration
  com: false,
  render3d: false,
};

export const MAX_GLOW = 0.25;
export const BACKGROUNDS = ["theme", "black", "white", "transparent"];

/** Coerce any visual settings (old localStorage, share links, presets, saved
 *  experiments) into the monochrome design: unknown palettes fall back to the
 *  theme ramp and glow is capped. */
export function monochrome(v) {
  const out = { ...v };
  if (!(out.palette in PALETTES)) out.palette = out.palette === "gray" ? "gray" : "auto";
  if (typeof out.glow === "number") out.glow = Math.min(MAX_GLOW, Math.max(0, out.glow));
  if (out.background === "light") out.background = "white";
  if (!BACKGROUNDS.includes(out.background)) out.background = "theme";
  delete out.custom; delete out.massGlow; delete out.rodColor;
  return out;
}

export const DEFAULT_PREFS = { sound: false, volume: 0.4 };

function clone(o) { return JSON.parse(JSON.stringify(o)); }

function load(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v ? { ...clone(fallback), ...JSON.parse(v) } : clone(fallback);
  } catch { return clone(fallback); }
}
function save(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch {} }

class Emitter {
  constructor() { this._h = {}; }
  on(ev, fn) { (this._h[ev] ||= new Set()).add(fn); return () => this._h[ev].delete(fn); }
  emit(ev, ...a) { (this._h[ev] || []).forEach((fn) => fn(...a)); }
}

export const bus = new Emitter();

export const state = {
  config: clone(DEFAULT_CONFIG),
  visual: monochrome(load("cl.visual", DEFAULT_VISUAL)),
  prefs: load("cl.prefs", DEFAULT_PREFS),
  sim: null, // last simulation result (typed arrays)
  ghost: null, // previous simulation for ghost trails
  presets: [],
  meta: null,
  bookmarks: [],
  activePreset: null,
};

export function setConfig(cfg, { silent = false } = {}) {
  state.config = mergeConfig(cfg);
  if (!silent) bus.emit("config", state.config);
}

export function patchConfig(section, key, value) {
  const c = clone(state.config);
  c[section][key] = value;
  setConfig(c);
}

export function mergeConfig(cfg) {
  const d = clone(DEFAULT_CONFIG);
  if (!cfg) return d;
  for (const s of ["physical", "initial", "numerics"]) Object.assign(d[s], cfg[s] || {});
  d.name = cfg.name || d.name;
  return d;
}

export function setVisual(patch) {
  Object.assign(state.visual, monochrome({ ...state.visual, ...patch }));
  save("cl.visual", state.visual);
  bus.emit("visual", state.visual, patch);
}

export function setPrefs(patch) {
  Object.assign(state.prefs, patch);
  save("cl.prefs", state.prefs);
  bus.emit("prefs", state.prefs);
}

/** Convert a /api/simulate payload into typed arrays + derived positions. */
export function ingestSim(r) {
  const F = (a) => Float64Array.from(a, (v) => (v === null ? NaN : v));
  const p = r.config.physical;
  const s = {
    raw: r, config: r.config, digest: r.digest, p,
    t: F(r.t), th1: F(r.theta1), th2: F(r.theta2), w1: F(r.omega1), w2: F(r.omega2),
    a1: F(r.alpha1), a2: F(r.alpha2), T: F(r.T), V: F(r.V), E: F(r.E), err: F(r.energy_error),
    speed2: F(r.speed2), Lz: F(r.angular_momentum),
    events: r.events, summary: r.summary, rotations: r.rotations, work: r.work,
    errKind: r.energy_error_kind, stepsPerSecond: r.steps_per_second,
  };
  s.n = s.t.length;
  s.dt = s.n > 1 ? s.t[1] - s.t[0] : 1;
  s.tEnd = s.t[s.n - 1];
  addPositions(s, p);
  s.maxSpeed = Math.max(1e-9, ...sampleMax(s.speed2));
  s.maxAcc = Math.max(1e-9, ...sampleMax(s.a2.map(Math.abs)));
  s.maxT = Math.max(1e-9, ...sampleMax(s.T));
  return s;
}

function sampleMax(a) { // spread-safe max helper
  let m = -Infinity;
  for (const v of a) if (v > m) m = v;
  return [m];
}

export function addPositions(s, p) {
  const n = s.th1.length;
  s.x1 = new Float32Array(n); s.y1 = new Float32Array(n); s.x2 = new Float32Array(n); s.y2 = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const x1 = p.L1 * Math.sin(s.th1[i]), y1 = -p.L1 * Math.cos(s.th1[i]);
    s.x1[i] = x1; s.y1[i] = y1;
    s.x2[i] = x1 + p.L2 * Math.sin(s.th2[i]); s.y2[i] = y1 - p.L2 * Math.cos(s.th2[i]);
  }
  return s;
}

/** Interpolated sample index for physical time t (fractional). */
export function indexAt(s, t) {
  return Math.max(0, Math.min(s.n - 1, t / s.dt));
}

export function lerpAt(arr, fi) {
  const i = Math.floor(fi), f = fi - i;
  if (i >= arr.length - 1) return arr[arr.length - 1];
  return arr[i] + (arr[i + 1] - arr[i]) * f;
}

// ---------- shared playback clock (physical time) ----------
export const clock = {
  t: 0, playing: false, speed: 1, reverse: false, loop: true,
  set(t) { this.t = t; bus.emit("time", t); },
};

// ---------- URL sharing: compact, safe, no backend ----------
export function encodeShare(cfg, visual) {
  const payload = { v: 1, c: cfg, s: visual ? pickVisual(visual) : undefined };
  const json = JSON.stringify(payload);
  const b64 = btoa(unescape(encodeURIComponent(json))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${location.origin}/#share=${b64}`;
}

export function decodeShare(hash) {
  const m = /share=([A-Za-z0-9_-]+)/.exec(hash || "");
  if (!m) return null;
  try {
    const b64 = m[1].replace(/-/g, "+").replace(/_/g, "/");
    const obj = JSON.parse(decodeURIComponent(escape(atob(b64))));
    if (obj.v !== 1 || typeof obj.c !== "object") return null;
    return { config: mergeConfig(obj.c), visual: obj.s && typeof obj.s === "object" ? sanitizeVisual(obj.s) : null };
  } catch { return null; }
}

function pickVisual(v) {
  const keys = ["palette", "trail", "trailSeconds", "trailWidth", "glow", "particles", "camera", "background"];
  return Object.fromEntries(keys.map((k) => [k, v[k]]));
}

export function sanitizeVisual(v) {
  v = monochrome(v || {});
  const out = {};
  for (const [k, val] of Object.entries(v)) {
    if (!(k in DEFAULT_VISUAL)) continue;
    const def = DEFAULT_VISUAL[k];
    if (typeof def === typeof val || (Array.isArray(def) && Array.isArray(val))) out[k] = val;
  }
  return out;
}

export function cloneDeep(o) { return clone(o); }
