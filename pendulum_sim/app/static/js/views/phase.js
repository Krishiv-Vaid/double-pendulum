// Phase-Space Observatory and Poincaré Section Explorer.

import { api, decodeBits, download, runJob } from "../api.js";
import { LineChart, Plot3D, Scatter } from "../charts.js";
import { distinct, paletteStops, rgba, sampler, token } from "../palettes.js";
import { jumpTo, runSimulation, setPlaying } from "../sim.js";
import { bus, clock, state } from "../state.js";
import { btn, check, fmt, fmtSig, h, panel, progressBar, select, slider, toast } from "../ui.js";

export const meta = { id: "phase" };

const wrap = (a) => ((((a + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) - Math.PI;

export function mount(root) {
  const cleanups = [];
  const tabs = h("div", { class: "tabs", role: "tablist" });
  const body = h("div");
  root.append(tabs, body);
  const TABS = [["portraits", "Phase portraits"], ["poincare", "Poincaré sections"], ["spectra", "Spectra & recurrence"]];
  let active = null, teardown = null;
  for (const [id, label] of TABS) {
    const b = h("button", { role: "tab", type: "button", "aria-selected": "false" }, label);
    b.addEventListener("click", () => open(id));
    tabs.append(b);
  }
  function open(id) {
    if (teardown) teardown();
    body.innerHTML = "";
    [...tabs.children].forEach((b, i) => b.setAttribute("aria-selected", String(TABS[i][0] === id)));
    active = id;
    teardown = { portraits, poincare, spectra }[id](body);
  }
  open("portraits");
  return () => { if (teardown) teardown(); cleanups.forEach((u) => u()); void active; };
}

// ---------------------------------------------------------------- portraits
function portraits(root) {
  const cleanups = [];
  let wrapAngles = true, colorTime = true;
  const axes = select({ label: "3D axes", value: "t1t2w2", options: [["t1t2w2", "θ₁, θ₂, ω₂"], ["t1w1w2", "θ₁, ω₁, ω₂"], ["t1t2w1", "θ₁, θ₂, ω₁"], ["t2w1w2", "θ₂, ω₁, ω₂"]], onChange: () => draw() });
  axes.input.style.width = "auto";
  const ctrl = h("div", { class: "btn-row", style: { marginBottom: "12px" } },
    check("Wrap angles to (−π, π]", true, (v) => { wrapAngles = v; draw(); }),
    check("Colour by elapsed time", true, (v) => { colorTime = v; draw(); }),
    axes.input,
    btn("Compute twin separation", () => twin(), { cls: "sm", tip: "Integrate a copy perturbed by 1e-8 rad in θ₁" }),
    btn("Export figure (PNG)", () => exportFigure(), { cls: "sm" }),
    h("span", { class: "faint", style: { fontSize: "12px" } }, "Synchronized with the Playground clock — press Space to play."));
  const grid = h("div", { class: "grid-2" });
  const mk = (title, xl, yl) => { const box = h("div", { class: "panel", style: { padding: "8px" } }); grid.append(box); return new Scatter(box, { title, xlabel: xl, ylabel: yl, cls: "tall", pointSize: 1.2 }); };
  const p1 = mk("θ₁ vs ω₁", "θ₁ [rad]", "ω₁ [rad/s]");
  const p2 = mk("θ₂ vs ω₂", "θ₂ [rad]", "ω₂ [rad/s]");
  const p3 = mk("θ₁ vs θ₂ (configuration space)", "θ₁ [rad]", "θ₂ [rad]");
  const p4 = mk("ω₁ vs ω₂", "ω₁ [rad/s]", "ω₂ [rad/s]");
  const tgrid = h("div", { class: "grid-2" });
  const lc = (title, yl) => { const box = h("div", { class: "panel", style: { padding: "8px" } }); tgrid.append(box); return new LineChart(box, { title, ylabel: yl, xlabel: "time [s]", cls: "tall", onClick: (t) => jumpTo(t) }); };
  const cE = lc("Total energy E(t)", "J"), cTV = lc("Kinetic & potential energy", "J"), cA = lc("Angular accelerations", "rad/s²"), cV = lc("Lower-mass speed |v₂|", "m/s");
  const cSep = lc("Separation from twin (ε = 1e-8 rad)", "log₁₀ d");
  const box3 = h("div", { class: "panel", style: { padding: "8px" } });
  tgrid.append(box3);
  const p3d = new Plot3D(box3, { cls: "tall" });
  root.append(ctrl, grid, h("div", { style: { height: "14px" } }), tgrid,
    h("p", { class: "faint", style: { fontSize: "12px" } }, "The state space (θ₁, θ₂, ω₁, ω₂) is four-dimensional: every panel, including the 3D view, is a projection, not a complete picture."));

  function data() {
    const s = state.sim;
    const W = (a) => (wrapAngles ? Float64Array.from(a, wrap) : a);
    return { s, th1: W(s.th1), th2: W(s.th2) };
  }

  function groupsFor(x, y, head) {
    // colour by time: split into 24 chunks with a palette gradient
    const s = state.sim, n = x.length;
    const pal = sampler(paletteStops(state.visual.palette));
    if (!colorTime) return [{ x, y, color: token("cyan"), alpha: 0.7, head, headColor: token("text") }];
    const k = 24, out = [];
    for (let c = 0; c < k; c++) {
      const a = Math.floor((c * n) / k), b = Math.floor(((c + 1) * n) / k);
      out.push({ x: x.subarray(a, b), y: y.subarray(a, b), color: rgba(pal(c / (k - 1)), 1), alpha: 0.7 });
    }
    out.push({ x: new Float64Array([x[head]]), y: new Float64Array([y[head]]), color: token("fg"), head: 0, headColor: token("fg") });
    void s;
    return out;
  }

  let headIdx = 0;
  function draw() {
    if (!state.sim) return;
    const { s, th1, th2 } = data();
    headIdx = Math.min(s.n - 1, Math.round(clock.t / s.dt));
    p1.set(groupsFor(th1, s.w1, headIdx), { xrange: wrapAngles ? [-Math.PI, Math.PI] : undefined });
    p2.set(groupsFor(th2, s.w2, headIdx), { xrange: wrapAngles ? [-Math.PI, Math.PI] : undefined });
    p3.set(groupsFor(th1, th2, headIdx), { xrange: wrapAngles ? [-Math.PI, Math.PI] : undefined });
    p4.set(groupsFor(s.w1, s.w2, headIdx));
    cE.set([{ x: s.t, y: s.E, color: token("text"), label: "E" }]);
    cTV.set([{ x: s.t, y: s.T, color: token("cyan"), label: "T" }, { x: s.t, y: s.V, color: token("pink"), label: "V" }]);
    cA.set([{ x: s.t, y: s.a1, color: token("cyan"), label: "α₁" }, { x: s.t, y: s.a2, color: token("purple"), label: "α₂" }]);
    cV.set([{ x: s.t, y: s.speed2, color: token("green"), label: "|v₂|" }]);
    const pal = sampler(paletteStops(state.visual.palette));
    const pick = { t1: th1, t2: th2, w1: s.w1, w2: s.w2 };
    const keys = { t1t2w2: ["t1", "t2", "w2"], t1w1w2: ["t1", "w1", "w2"], t1t2w1: ["t1", "t2", "w1"], t2w1w2: ["t2", "w1", "w2"] }[axes.get()];
    const lab = { t1: "θ₁", t2: "θ₂", w1: "ω₁", w2: "ω₂" };
    p3d.set(pick[keys[0]], pick[keys[1]], pick[keys[2]], keys.map((k) => lab[k]), colorTime ? (u) => rgba(pal(u), 0.8) : null, headIdx);
  }

  async function twin() {
    const c = JSON.parse(JSON.stringify(state.config));
    c.initial.theta1_deg += (1e-8 * 180) / Math.PI;
    try {
      const r = await api.post("/api/simulate", { config: c });
      const s = state.sim;
      const tau = Math.sqrt(s.p.L1 / s.p.g);
      const n = Math.min(s.n, r.theta1.length);
      const d = new Float64Array(n);
      for (let i = 0; i < n; i++) {
        const a = wrap(r.theta1[i] - s.th1[i]), b = wrap(r.theta2[i] - s.th2[i]), e = tau * (r.omega1[i] - s.w1[i]), f = tau * (r.omega2[i] - s.w2[i]);
        d[i] = Math.log10(Math.max(1e-300, Math.hypot(a, b, e, f)));
      }
      cSep.set([{ x: s.t.subarray(0, n), y: d, color: token("gold"), label: "log₁₀ d(t)" }]);
    } catch (e) { toast(e.message, "err"); }
  }

  function exportFigure() {
    // Publication-style composite of the four portraits
    const charts = [p1, p2, p3, p4].map((c) => c.canvas);
    const w = charts[0].width, hh = charts[0].height;
    const out = document.createElement("canvas");
    out.width = w * 2; out.height = hh * 2;
    const ctx = out.getContext("2d");
    ctx.fillStyle = token("panel"); ctx.fillRect(0, 0, out.width, out.height);
    charts.forEach((c, i) => ctx.drawImage(c, (i % 2) * w, Math.floor(i / 2) * hh));
    out.toBlob((b) => download(b, `phase-portraits-${state.sim.digest}.png`));
  }

  let tick = 0;
  cleanups.push(bus.on("sim", () => draw()), bus.on("frame", () => {
    if (!state.sim || ++tick % 4) return;
    const i = Math.min(state.sim.n - 1, Math.round(clock.t / state.sim.dt));
    if (i === headIdx) return;
    headIdx = i;
    // update heads cheaply by re-setting only the head group
    const { s, th1, th2 } = data();
    const setHead = (p, x, y) => { const g = p.groups[p.groups.length - 1]; g.x = new Float64Array([x[i]]); g.y = new Float64Array([y[i]]); p.draw(); };
    if (colorTime) { setHead(p1, th1, s.w1); setHead(p2, th2, s.w2); setHead(p3, th1, th2); setHead(p4, s.w1, s.w2); }
    else for (const p of [p1, p2, p3, p4]) { p.groups[0].head = i; p.draw(); }
    for (const c of [cE, cTV, cA, cV, cSep]) c.setCursor(clock.t);
    p3d.setHead(i);
  }));
  if (state.sim) draw(); else runSimulation();
  void setPlaying; void fmt;
  return () => { cleanups.forEach((u) => u()); [p1, p2, p3, p4, cE, cTV, cA, cV, cSep, p3d].forEach((c) => c.destroy()); };
}

// ---------------------------------------------------------------- Poincaré
function poincare(root) {
  const E = slider({ label: "Total energy E", unit: "J", min: -29, max: 30, step: 0.1, value: -15, digits: 2, tip: "Hanging equilibrium has E = −(m₁+m₂)gL₁ − m₂gL₂ (−29.43 J for the defaults)" });
  const nTraj = slider({ label: "Trajectories", min: 1, max: 24, step: 1, value: 10, digits: 0 });
  const th2max = slider({ label: "θ₂(0) spread up to", unit: "rad", min: 0.1, max: 3.1, step: 0.05, value: 2.0, digits: 2 });
  const tmax = slider({ label: "Integration time", unit: "s", min: 20, max: 2000, step: 10, value: 300, digits: 0 });
  const tol = slider({ label: "DOP853 tolerance", min: 1e-13, max: 1e-6, log: true, value: 1e-10 });
  let density = false;
  const prog = progressBar();
  const runBtn = btn("Compute sections", () => run(), { cls: "primary" });
  const cancelBtn = btn("Cancel", () => job && job.cancel(), { cls: "sm", disabled: true });
  const info = h("div", { class: "faint mono", style: { fontSize: "11.5px" } });
  const plotBox = h("div", { class: "panel", style: { padding: "8px" } });
  const sc = new Scatter(plotBox, { xlabel: "θ₂ (wrapped) [rad]", ylabel: "ω₂ [rad/s]", title: "Surface θ₁ = 0, crossing with ω₁ > 0", pointSize: 1.6, xrange: [-Math.PI, Math.PI] });
  sc.el.style.height = "560px";
  const legend = h("div", { class: "events" });
  root.append(h("div", { class: "layout-2", style: { height: "auto" } },
    h("div", { class: "col" },
      panel("Experiment", h("div", { style: { display: "grid", gap: "10px" } }, E, nTraj, th2max, tmax, tol,
        check("Density map (all trajectories, one colour)", false, (v) => { density = v; if (last) show(last); }),
        h("div", { class: "btn-row" }, runBtn, cancelBtn), prog, info)),
      panel("Trajectories", legend),
      panel("How to read a section", h("div", { class: "faint", style: { fontSize: "12.5px", display: "grid", gap: "6px" } },
        h("div", {}, "Each point is an exact crossing of the surface θ₁ = 0 in the positive direction (ω₁ > 0), located by root-finding on the integrator’s dense output, not by sampling."),
        h("div", {}, "All trajectories share one total energy, so their points live on the same 3D energy surface; the section reduces it to 2D."),
        h("div", {}, "Regular (quasi-periodic) motion traces closed curves: “islands”. Chaotic motion scatters points over a region: the “chaotic sea”. As E rises, islands shrink."),
        h("div", {}, "A scatter plot of sampled states is not a Poincaré section.")))),
    h("div", { class: "col" }, plotBox, h("div", { class: "faint", style: { fontSize: "12px" } }, "Scroll to zoom, drag to pan, double-click to reset."))));

  let job = null, last = null;
  async function run() {
    const n = nTraj.get();
    const th2 = Array.from({ length: n }, (_, k) => +(0.05 + (k / Math.max(1, n - 1)) * (th2max.get() - 0.05)).toFixed(4));
    runBtn.disabled = true; cancelBtn.disabled = false; prog.set(0);
    const cfg = JSON.parse(JSON.stringify(state.config));
    cfg.physical = { ...cfg.physical, damping1: 0, damping2: 0, drive_amplitude: 0 };
    job = runJob("poincare", { config: cfg, energy: E.get(), theta2_values: th2, t_max: tmax.get(), rtol: tol.get() }, { onProgress: (f) => prog.set(f) });
    try { last = await job.promise; show(last); } catch (e) { if (e.message !== "cancelled") toast(e.message, "err"); }
    runBtn.disabled = false; cancelBtn.disabled = true;
  }
  function show(r) {
    const n = r.sections.length;
    const tones = distinct(n);
    const groups = r.sections.map((s, k) => ({ x: s.theta2.map((v) => v ?? NaN), y: s.omega2.map((v) => v ?? NaN), color: density ? token("fg") : rgba(tones[k]), alpha: density ? 0.25 : 0.9 }));
    sc.set(groups);
    legend.innerHTML = "";
    r.sections.forEach((s, k) => legend.append(h("li", {}, h("button", { type: "button" },
      h("span", { class: "dot", style: { background: groups[k].color } }), `θ₂(0) = ${fmt(s.initial[1], 3)}, ω₁(0) = ${fmt(s.initial[2], 3)}`,
      h("span", { class: "faint mono" }, `${s.count} pts · drift ${fmtSig(s.energy_drift, 2)} J`)))));
    info.textContent = `E = ${r.energy} J · ${r.sections.reduce((a, s) => a + s.count, 0)} crossings`;
  }
  return () => { if (job) job.cancel(); sc.destroy(); };
}

// ---------------------------------------------------------------- spectra & recurrence
function spectra(root) {
  const thr = slider({ label: "Recurrence threshold ε", min: 0.02, max: 2, step: 0.01, value: 0.3, digits: 2, tip: "Pairs of states closer than ε (wrapped dimensionless norm) are marked recurrent" });
  const pts = slider({ label: "Recurrence samples", min: 100, max: 800, step: 50, value: 400, digits: 0 });
  const go = btn("Analyse current simulation", () => run(), { cls: "primary" });
  const sBox = h("div", { class: "panel", style: { padding: "8px" } });
  const rBox = h("div", { class: "panel", style: { padding: "8px", display: "grid", placeItems: "center" } });
  const ch = new LineChart(sBox, { title: "Amplitude spectrum of sin θ (Hann window)", xlabel: "frequency [Hz]", cls: "xl", xname: "f" });
  const rc = h("canvas", { width: 520, height: 520, style: { width: "min(520px, 100%)", aspectRatio: "1", imageRendering: "pixelated" } });
  const rInfo = h("div", { class: "faint mono", style: { fontSize: "11.5px" } });
  rBox.append(h("div", { style: { fontWeight: 600, fontSize: "12px" } }, "Recurrence plot R(i, j) = ‖yᵢ − yⱼ‖ < ε"), rc, rInfo);
  root.append(h("div", { class: "btn-row", style: { marginBottom: "12px" } }, go, thr, pts),
    h("div", { class: "grid-2" }, sBox, rBox),
    h("p", { class: "note", style: { marginTop: "12px" } }, "Exploratory only. Broadband spectral content is consistent with chaos but does not prove it: noise and quasi-periodic motion with many incommensurate frequencies also look broadband. Regular motion shows sharp peaks; recurrence plots of regular motion show long diagonal lines."));
  async function run() {
    try {
      const r = await api.post("/api/analysis", { config: state.config, threshold: thr.get(), points: pts.get(), fmax: 5 });
      const f = (a) => Float64Array.from(a, (v) => v ?? NaN);
      ch.set([{ x: f(r.spectrum_theta1.f), y: f(r.spectrum_theta1.amp), color: token("cyan"), label: "sin θ₁", noMinMax: true },
        { x: f(r.spectrum_theta2.f), y: f(r.spectrum_theta2.amp), color: token("pink"), label: "sin θ₂", noMinMax: true }]);
      const n = r.recurrence.n, bits = decodeBits(r.recurrence.bits, n);
      rc.width = n; rc.height = n;
      const ctx = rc.getContext("2d"), im = ctx.createImageData(n, n);
      const light = document.documentElement.dataset.theme === "light";
      const on = light ? [0, 0, 0] : [255, 255, 255], off = light ? [255, 255, 255] : [0, 0, 0];
      for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
        const c = bits[(n - 1 - i) * n + j] ? on : off, o = (i * n + j) * 4;
        im.data[o] = c[0]; im.data[o + 1] = c[1]; im.data[o + 2] = c[2]; im.data[o + 3] = 255;
      }
      ctx.putImageData(im, 0, 0);
      rInfo.textContent = `${n} samples over ${fmt(r.recurrence.t[n - 1], 1)} s · recurrence rate ${fmt(100 * r.recurrence.rate, 2)}% · time runs left→right, bottom→top`;
    } catch (e) { toast(e.message, "err"); }
  }
  run();
  return () => ch.destroy();
}
