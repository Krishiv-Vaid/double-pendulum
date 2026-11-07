// Reusable control groups: physical/numerical configuration, visuals, presets, timeline.

import { PALETTES, cssGradient, paletteStops, token } from "./palettes.js";
import { bus, clock, cloneDeep, setConfig, setVisual, state } from "./state.js";
import { h, check, fitCanvas, info, section, select, slider, fmt } from "./ui.js";

export const GRAVITY = [
  ["Earth", 9.81], ["Moon", 1.62], ["Mars", 3.71], ["Jupiter", 24.79],
];

export const TRAIL_MODES = [
  ["fade", "Fading tail"], ["full", "Full history"], ["exposure", "Long exposure"], ["velocity", "Velocity-coloured"],
  ["acceleration", "Acceleration-coloured"], ["energy", "Kinetic-energy-coloured"], ["time", "Time gradient"],
  ["dashed", "Segmented dashed"], ["dual", "Dual-mass trails"], ["lineart", "Minimal line art"],
  ["ghost", "Ghost of previous run"], ["particles", "Particle emission"],
];

export const PARTICLES = [
  ["none", "None"], ["sparks", "Sparks"], ["dust", "Glowing dust"], ["comet", "Comet tail"], ["burst", "Energy bursts (flips)"],
  ["confetti", "Confetti"], ["stars", "Starfield"], ["smoke", "Smoke"],
];

export const BACKGROUNDS = [["theme", "Theme"], ["black", "Black"], ["white", "White"], ["transparent", "Transparent"]];

function commit(mutator) {
  const c = cloneDeep(state.config);
  mutator(c);
  setConfig(c);
}

/** Physical + initial + forcing + numerics controls bound to state.config. */
export function configControls({ open = ["initial", "physical"], forcing = true, numerics = true } = {}) {
  const c = state.config;
  const S = (sec, key, o) => slider({
    ...o, value: c[sec][key],
    onChange: (v) => commit((cfg) => { cfg[sec][key] = v; }),
  });
  const refs = {};
  const sections = [];
  refs.th1 = S("initial", "theta1_deg", { label: "θ₁(0)", unit: "deg", min: -180, max: 180, step: 0.1, digits: 2, tip: "Upper rod angle from the downward vertical, counter-clockwise positive" });
  refs.th2 = S("initial", "theta2_deg", { label: "θ₂(0)", unit: "deg", min: -180, max: 180, step: 0.1, digits: 2, tip: "Lower rod angle from the downward vertical" });
  refs.w1 = S("initial", "omega1", { label: "ω₁(0)", unit: "rad/s", min: -15, max: 15, step: 0.01, digits: 3 });
  refs.w2 = S("initial", "omega2", { label: "ω₂(0)", unit: "rad/s", min: -15, max: 15, step: 0.01, digits: 3 });
  sections.push(section("Initial conditions", open.includes("initial"), refs.th1, refs.th2, refs.w1, refs.w2,
    h("div", { class: "faint", style: { fontSize: "11.5px" } }, "Tip: pause and drag a mass on the stage to set the angles.")));

  refs.m1 = S("physical", "m1", { label: "m₁", unit: "kg", min: 0.05, max: 10, step: 0.01, digits: 3 });
  refs.m2 = S("physical", "m2", { label: "m₂", unit: "kg", min: 0.05, max: 10, step: 0.01, digits: 3 });
  refs.L1 = S("physical", "L1", { label: "L₁", unit: "m", min: 0.1, max: 3, step: 0.01, digits: 3 });
  refs.L2 = S("physical", "L2", { label: "L₂", unit: "m", min: 0.1, max: 3, step: 0.01, digits: 3 });
  refs.g = S("physical", "g", { label: "g", unit: "m/s²", min: 0.1, max: 30, step: 0.01, digits: 3, tip: "Constant uniform gravitational acceleration" });
  const gbtns = h("div", { class: "btn-row" }, ...GRAVITY.map(([n, g]) =>
    h("button", { class: "btn sm", type: "button", onclick: () => commit((cfg) => { cfg.physical.g = g; }), "data-tip": `${n}: g = ${g} m/s² (simplified constant-gravity experiment)` }, n)));
  sections.push(section("Physical parameters", open.includes("physical"), refs.m1, refs.m2, refs.L1, refs.L2, refs.g, gbtns));

  if (forcing) {
    refs.b1 = S("physical", "damping1", { label: "Pivot damping b₁", unit: "N·m·s", min: 0, max: 1, step: 0.001, digits: 3, tip: "Viscous torque −b₁ω₁ at the pivot" });
    refs.b2 = S("physical", "damping2", { label: "Elbow damping b₂", unit: "N·m·s", min: 0, max: 1, step: 0.001, digits: 3, tip: "Viscous torque −b₂(ω₂−ω₁) at the elbow joint" });
    refs.A = S("physical", "drive_amplitude", { label: "Drive torque A", unit: "N·m", min: 0, max: 10, step: 0.01, digits: 3, tip: "Applied torque A cos(Ωt + φ) on the upper rod at the pivot" });
    refs.W = S("physical", "drive_frequency", { label: "Drive frequency Ω", unit: "rad/s", min: 0, max: 15, step: 0.01, digits: 3 });
    refs.phi = S("physical", "drive_phase", { label: "Drive phase φ", unit: "rad", min: -3.1416, max: 3.1416, step: 0.01, digits: 3 });
    sections.push(section("Damping & driving", open.includes("forcing"), refs.b1, refs.b2, refs.A, refs.W, refs.phi,
      h("div", { class: "faint", style: { fontSize: "11.5px" } }, "With forcing, the energy diagnostic becomes the energy-balance residual E(t) − E₀ − (W_drive − W_damp).")));
  }

  if (numerics) {
    refs.method = select({ label: "Integrator", value: c.numerics.method, options: [["rk4", "RK4 (fixed step)"], ["rk45", "RK45 (Dormand–Prince 5(4))"], ["dop853", "DOP853 (8th order)"]],
      onChange: (v) => commit((cfg) => { cfg.numerics.method = v; }) });
    refs.dt = S("numerics", "dt", { label: "RK4 step Δt", unit: "s", min: 1e-5, max: 0.05, log: true, tip: "Used by RK4 only" });
    refs.rtol = S("numerics", "rtol", { label: "rtol", min: 1e-13, max: 1e-3, log: true, tip: "Relative tolerance (adaptive methods)" });
    refs.atol = S("numerics", "atol", { label: "atol", min: 1e-13, max: 1e-3, log: true, tip: "Absolute tolerance (adaptive methods)" });
    refs.tmax = S("numerics", "t_max", { label: "Duration", unit: "s (physical)", min: 1, max: 120, step: 1, digits: 1 });
    refs.odt = S("numerics", "output_dt", { label: "Output spacing", unit: "s", min: 1 / 960, max: 1 / 30, log: true, tip: "Spacing of stored samples. Playback interpolates between samples for display only." });
    sections.push(section("Numerics", open.includes("numerics"), refs.method, refs.dt, refs.rtol, refs.atol, refs.tmax, refs.odt));
  }

  const el = h("div", {}, ...sections);
  const sync = (cfg) => {
    const m = { th1: ["initial", "theta1_deg"], th2: ["initial", "theta2_deg"], w1: ["initial", "omega1"], w2: ["initial", "omega2"],
      m1: ["physical", "m1"], m2: ["physical", "m2"], L1: ["physical", "L1"], L2: ["physical", "L2"], g: ["physical", "g"],
      b1: ["physical", "damping1"], b2: ["physical", "damping2"], A: ["physical", "drive_amplitude"], W: ["physical", "drive_frequency"], phi: ["physical", "drive_phase"],
      dt: ["numerics", "dt"], rtol: ["numerics", "rtol"], atol: ["numerics", "atol"], tmax: ["numerics", "t_max"], odt: ["numerics", "output_dt"] };
    for (const [k, [s, key]] of Object.entries(m)) if (refs[k]) refs[k].set(cfg[s][key]);
    if (refs.method) refs.method.set(cfg.numerics.method);
  };
  el.unsub = bus.on("config", sync);
  return el;
}

export function paletteGrid(onPick) {
  const grid = h("div", { class: "palette-grid" });
  const btns = Object.entries(PALETTES).map(([k, p]) => {
    const b = h("button", { type: "button", "aria-pressed": String(state.visual.palette === k), title: p.label },
      h("span", { class: "swatch", style: { background: cssGradient(paletteStops(k)), border: "1px solid var(--border)" } }), p.label);
    b.addEventListener("click", () => {
      btns.forEach((x) => x.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");
      setVisual({ palette: k });
      onPick && onPick(k);
    });
    return b;
  });
  grid.append(...btns);
  return grid;
}

/** Visual settings. `full` adds the studio-only controls. */
export function visualControls({ full = false, open = [] } = {}) {
  const v = state.visual;
  const V = (key, o) => slider({ ...o, value: v[key], onInput: (x) => setVisual({ [key]: x }) });
  const parts = [];
  parts.push(section("Palette & trail", open.includes("palette") || !full,
    paletteGrid(),
    select({ label: "Trail mode", value: v.trail, options: TRAIL_MODES, onChange: (x) => setVisual({ trail: x }) }),
    V("trailSeconds", { label: "Trail length", unit: "s", min: 0.1, max: 30, step: 0.1, digits: 1 }),
    V("trailWidth", { label: "Trail width", unit: "px", min: 0.5, max: 8, step: 0.1, digits: 1 }),
    V("glow", { label: "Bloom", min: 0, max: 0.25, step: 0.01, digits: 2, tip: "A faint grey bloom; a rendering effect only" }),
  ));
  if (full) {
    parts.push(section("Particles", open.includes("particles"),
      select({ label: "Effect", value: v.particles, options: PARTICLES, onChange: (x) => setVisual({ particles: x }) }),
      V("particleRate", { label: "Emission rate", min: 0, max: 5, step: 0.05, digits: 2 }),
      V("particleLife", { label: "Lifetime", unit: "s", min: 0.1, max: 5, step: 0.05, digits: 2 }),
      V("particleSize", { label: "Size", min: 0.2, max: 4, step: 0.05, digits: 2 }),
      V("particleSpeed", { label: "Speed", min: 0, max: 4, step: 0.05, digits: 2 }),
      V("particleOpacity", { label: "Opacity", min: 0.05, max: 1, step: 0.01, digits: 2 }),
      h("div", { class: "faint", style: { fontSize: "11.5px" } }, "Particles are purely decorative; they never touch the numerical simulation.")));
    parts.push(section("Camera", open.includes("camera"),
      select({ label: "Mode", value: v.camera, options: [["static", "Static (centre on pivot)"], ["autofit", "Auto-fit"], ["follow", "Follow lower mass"]], onChange: (x) => setVisual({ camera: x }) }),
      V("zoom", { label: "Zoom", min: 0.3, max: 4, step: 0.01, digits: 2 }),
      V("easing", { label: "Camera easing", min: 0.01, max: 0.6, step: 0.01, digits: 2 }),
      V("motionBlur", { label: "Motion blur", min: 0, max: 0.95, step: 0.01, digits: 2 }),
      h("div", { class: "faint", style: { fontSize: "11.5px" } }, "Scroll to zoom and drag empty space to pan. Double-click resets the view. Scaling is uniform, so the geometry is never distorted.")));
    parts.push(section("Scene", open.includes("scene"),
      select({ label: "Background", value: v.background, options: BACKGROUNDS, onChange: (x) => setVisual({ background: x }) }),
      V("massSize", { label: "Mass size", min: 0.3, max: 3, step: 0.05, digits: 2 }),
      check("Show rods", v.rods, (x) => setVisual({ rods: x })),
      check("Show pivot", v.showPivot, (x) => setVisual({ showPivot: x }))));
  }
  parts.push(section("Overlays", open.includes("overlays"),
    check("HUD readout", v.hud, (x) => setVisual({ hud: x })),
    check("Metric grid + scale bar", v.grid, (x) => setVisual({ grid: x })),
    check("Centre-of-mass tracker", v.com, (x) => setVisual({ com: x })),
    select({ label: "Vectors at lower mass", value: v.vectors, options: [["none", "None"], ["velocity", "Velocity v₂"], ["acceleration", "Acceleration a₂"]], onChange: (x) => setVisual({ vectors: x }),
      tip: "Vectors at the current trajectory sample only — not a vector field over the 4D state space" }),
    check("3D presentation", v.render3d, (x) => setVisual({ render3d: x }), "A perspective rendering of the same planar motion; no extra degree of freedom")));
  return h("div", {}, ...parts);
}

export function presetPicker(onPick) {
  const sel = select({
    label: "Preset", value: state.activePreset || "",
    options: [["", "— choose a preset —"], ...state.presets.map((p) => [p.id, p.title])],
    onChange: (id) => { const p = state.presets.find((x) => x.id === id); if (p) onPick(p); },
  });
  const desc = h("div", { class: "note", style: { display: state.activePreset ? "" : "none" } });
  const show = (id) => {
    const p = state.presets.find((x) => x.id === id);
    if (!p) { desc.style.display = "none"; return; }
    desc.style.display = "";
    desc.innerHTML = "";
    desc.append(h("div", {}, p.description), h("div", { style: { marginTop: "4px", color: "var(--text)" } }, "Expected: ", p.expected));
  };
  show(state.activePreset);
  const el = h("div", { class: "field" }, sel, desc);
  el.unsub = bus.on("preset", (id) => { sel.set(id || ""); show(id); });
  return el;
}

export function applyPreset(p) {
  state.activePreset = p.id;
  if (p.visual) setVisual({ ...p.visual, trailSeconds: p.visual.trail_seconds ?? state.visual.trailSeconds });
  setConfig(p.config);
  bus.emit("preset", p.id);
}

// Event kinds are told apart by grey level and marker height, not hue.
const EVENT_COLORS = { flip: "fg", max_speed: "fg-2", acceleration: "fg-3", energy_error: "fg-2", bookmark: "fg", divergence: "fg", poincare: "fg-2" };
export function eventColor(kind) { return token(EVENT_COLORS[kind] || "fg-2"); }

/** Timeline scrubber with event markers, bookmarks, A/B marks and a selection range. */
export class Timeline {
  constructor(container, { onSeek, onRange } = {}) {
    this.canvas = h("canvas", { "aria-label": "Timeline. Drag to scrub; Shift-drag to select a range.", role: "slider", tabindex: "0" });
    this.el = h("div", { class: "timeline" }, this.canvas);
    container.append(this.el);
    this.onSeek = onSeek; this.onRange = onRange;
    this.range = null; this.marks = {};
    let mode = null, start = 0;
    const tAt = (e) => {
      const r = this.canvas.getBoundingClientRect();
      return Math.max(0, Math.min(1, (e.clientX - r.left - 6) / (r.width - 12))) * (state.sim ? state.sim.tEnd : 0);
    };
    this.canvas.addEventListener("pointerdown", (e) => {
      this.canvas.setPointerCapture(e.pointerId);
      if (e.shiftKey) { mode = "range"; start = tAt(e); this.range = [start, start]; }
      else { mode = "seek"; onSeek && onSeek(tAt(e)); }
    });
    this.canvas.addEventListener("pointermove", (e) => {
      if (mode === "seek") onSeek && onSeek(tAt(e));
      else if (mode === "range") { const t = tAt(e); this.range = [Math.min(start, t), Math.max(start, t)]; this.draw(); }
    });
    this.canvas.addEventListener("pointerup", () => {
      if (mode === "range") { if (this.range[1] - this.range[0] < 0.05) this.range = null; onRange && onRange(this.range); }
      mode = null; this.draw();
    });
    this.canvas.addEventListener("keydown", (e) => {
      if (!state.sim) return;
      if (e.key === "ArrowRight") { onSeek(Math.min(state.sim.tEnd, clock.t + (e.shiftKey ? 1 : state.sim.dt))); e.preventDefault(); }
      if (e.key === "ArrowLeft") { onSeek(Math.max(0, clock.t - (e.shiftKey ? 1 : state.sim.dt))); e.preventDefault(); }
    });
    new ResizeObserver(() => this.draw()).observe(this.el);
  }
  draw() {
    const [w, hh, dpr] = fitCanvas(this.canvas);
    const ctx = this.canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, hh);
    const s = state.sim;
    const x = (t) => 6 + (s ? t / s.tEnd : 0) * (w - 12);
    const y = hh / 2;
    ctx.fillStyle = token("panel-3");
    roundRect(ctx, 6, y - 3, w - 12, 6, 3); ctx.fill();
    if (!s) return;
    if (this.range) { ctx.fillStyle = token("fg-4"); ctx.fillRect(x(this.range[0]), y - 12, x(this.range[1]) - x(this.range[0]), 24); }
    ctx.fillStyle = token("fg");
    roundRect(ctx, 6, y - 3, Math.max(0, x(clock.t) - 6), 6, 3); ctx.fill();
    for (const e of s.events || []) {
      ctx.fillStyle = eventColor(e.kind);
      ctx.fillRect(x(e.t) - 0.75, y - (e.kind === "flip" ? 11 : 8), 1.5, e.kind === "flip" ? 6 : 4);
    }
    for (const b of state.bookmarks) { ctx.fillStyle = token("green"); ctx.beginPath(); ctx.moveTo(x(b.t), y + 6); ctx.lineTo(x(b.t) - 4, y + 12); ctx.lineTo(x(b.t) + 4, y + 12); ctx.fill(); }
    for (const [k, t] of Object.entries(this.marks)) {
      if (t === null || t === undefined) continue;
      ctx.fillStyle = token("gold"); ctx.font = "600 10px ui-monospace"; ctx.textAlign = "center";
      ctx.fillText(k, x(t), y + 15); ctx.fillRect(x(t) - 0.5, y - 6, 1, 12);
    }
    ctx.fillStyle = token("fg");
    ctx.beginPath(); ctx.arc(x(clock.t), y, 5, 0, 7); ctx.fill();
  }
}

function roundRect(ctx, x, y, w, hh, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + hh, r); ctx.arcTo(x + w, y + hh, x, y + hh, r);
  ctx.arcTo(x, y + hh, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

export function readout(label, unitless) { return h("div", { class: "r" }, h("span", {}, label), h("span", { "data-k": unitless })); }

export function fmtTime(t) { return `${fmt(t, 3)} s`; }

export { info };

/** Local playback clock for views that animate their own datasets. */
export class LocalClock {
  constructor(tEnd = 1) { this.t = 0; this.tEnd = tEnd; this.playing = false; this.speed = 1; this.loop = true; this.listeners = new Set(); }
  advance(dtWall) {
    if (!this.playing) return this.t;
    this.t += dtWall * this.speed;
    if (this.t > this.tEnd) { if (this.loop) this.t = 0; else { this.t = this.tEnd; this.playing = false; this.emit(); } }
    return this.t;
  }
  set(t) { this.t = Math.max(0, Math.min(this.tEnd, t)); this.emit(); }
  play(p) { this.playing = p; this.emit(); }
  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit() { this.listeners.forEach((f) => f(this)); }
}

export function miniTransport(lc, { speeds = [0.1, 0.25, 0.5, 1, 2, 4] } = {}) {
  const play = h("button", { class: "btn icon", type: "button", "aria-label": "Play/pause", "data-tip": "Play / pause" });
  const setIcon = () => { play.innerHTML = lc.playing ? '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>' : '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M7 5v14l12-7z"/></svg>'; };
  play.addEventListener("click", () => lc.play(!lc.playing));
  const restart = h("button", { class: "btn icon sm", type: "button", "aria-label": "Restart", "data-tip": "Restart" }, "↺");
  restart.addEventListener("click", () => lc.set(0));
  const sp = h("select", { "aria-label": "Playback speed", style: { width: "auto" } }, ...speeds.map((s) => h("option", { value: s }, `${s}×`)));
  sp.value = String(lc.speed);
  sp.addEventListener("change", () => { lc.speed = +sp.value; });
  const scrub = h("input", { type: "range", min: 0, max: 1000, value: 0, "aria-label": "Scrub time", style: { flex: 1, minWidth: "140px" } });
  scrub.addEventListener("input", () => { lc.play(false); lc.set((scrub.value / 1000) * lc.tEnd); });
  const time = h("span", { class: "time mono" });
  const el = h("div", { class: "transport" }, restart, play, sp, time, scrub);
  el.update = () => {
    time.textContent = `${fmt(lc.t, 2)} / ${fmt(lc.tEnd, 1)} s`;
    if (document.activeElement !== scrub) scrub.value = Math.round((lc.t / (lc.tEnd || 1)) * 1000);
    scrub.style.setProperty("--fill", `${(lc.t / (lc.tEnd || 1)) * 100}%`);
  };
  lc.on(() => { setIcon(); el.update(); });
  setIcon(); el.update();
  return el;
}
