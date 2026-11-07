// Butterfly Effect Arena: ensembles of nearly identical pendulums.

import { runJob } from "../api.js";
import { LineChart } from "../charts.js";
import { LocalClock, configControls, miniTransport, paletteGrid } from "../controls.js";
import { paletteStops, sampler, token } from "../palettes.js";
import { PendulumRenderer } from "../renderer.js";
import { addPositions, bus, state, setVisual } from "../state.js";
import { btn, fmt, fmtSig, h, panel, progressBar, section, select, slider, toast } from "../ui.js";
import { saveExperimentDialog } from "./experiments.js";

export const meta = { id: "butterfly" };

export function mount(root) {
  const cleanups = [];
  const P = {
    n: slider({ label: "Pendulums", min: 2, max: 400, step: 1, value: 24, digits: 0, tip: "Above ~120 members the arena switches to a lighter display sampling (high-performance mode)" }),
    eps: slider({ label: "Perturbation ε", unit: "rad or rad/s", min: 1e-12, max: 1e-1, log: true, value: 1e-6 }),
    variable: select({ label: "Perturbed variable", value: "theta1", options: [["theta1", "θ₁"], ["theta2", "θ₂"], ["omega1", "ω₁"], ["omega2", "ω₂"]] }),
    dist: select({ label: "Distribution", value: "linear", options: [["linear", "Linear spread 0…ε"], ["gaussian", "Gaussian (σ = ε, seeded)"]] }),
    seed: slider({ label: "Seed", min: 0, max: 9999, step: 1, value: 0, digits: 0 }),
    thr: slider({ label: "Divergence threshold", min: 0.01, max: 3, step: 0.01, value: 0.5, digits: 2, tip: "Separation (dimensionless state-space distance) at which a member counts as diverged" }),
    tmax: slider({ label: "Duration", unit: "s", min: 2, max: 60, step: 1, value: 20, digits: 0 }),
    dt: slider({ label: "RK4 step", unit: "s", min: 2e-4, max: 0.01, log: true, value: 0.002 }),
  };
  const view = select({ label: "Display", value: "overlay", options: [["overlay", "Overlay swarm"], ["grid", "Side-by-side (first 16)"], ["cloud", "Endpoint cloud"]],
    onChange: () => layoutStage() });
  const trail = slider({ label: "Trail length", unit: "s", min: 0, max: 10, step: 0.1, value: 1.5, digits: 1, onInput: () => applyVisual() });
  const prog = progressBar();
  const runBtn = btn("Run ensemble", () => run(), { cls: "primary" });
  const cancelBtn = btn("Cancel", () => job && job.cancel(), { cls: "sm", disabled: true });
  const base = configControls({ open: ["initial"], forcing: false, numerics: false });
  cleanups.push(base.unsub);
  const left = h("div", { class: "panel col scroll" },
    h("div", { class: "panel-body", style: { display: "grid", gap: "10px" } },
      h("div", { class: "btn-row" }, runBtn, cancelBtn), prog,
      h("div", { class: "faint", style: { fontSize: "11.5px" } }, "Base state comes from the shared configuration below; members are offset in one variable.")),
    section("Ensemble", true, P.n, P.eps, P.variable, P.dist, P.seed, P.thr, P.tmax, P.dt),
    section("Display", true, view, trail, paletteGrid(() => applyVisual())),
    base);

  const stageBox = h("div", { class: "stage", style: { minHeight: "360px" } });
  const lc = new LocalClock(1);
  const tr = miniTransport(lc);
  const replayBtn = btn("Replay divergence", () => replay(), { cls: "sm", disabled: true, tip: "Jump to 2 s before the first member crosses the threshold and play at 0.25×" });
  tr.append(replayBtn);
  const chartA = h("div"), chartB = h("div"), chartC = h("div");
  const chSep = new LineChart(chartA, { title: "log₁₀ separation  ‖(Δθ₁, Δθ₂, τΔω₁, τΔω₂)‖", cls: "tall", logY: true, xlabel: "time [s]", onClick: (t) => { lc.play(false); lc.set(t); } });
  const chAng = new LineChart(chartB, { title: "median |Δθ₂| (wrapped) [rad]", compact: true, onClick: (t) => lc.set(t) });
  const chCart = new LineChart(chartC, { title: "median lower-mass distance [m]", compact: true, onClick: (t) => lc.set(t) });
  const statsBox = h("div", { class: "stats" });
  const centre = h("div", { class: "col" }, stageBox, tr,
    panel("Divergence timeline", h("div", {}, chartA, h("div", { class: "grid-2" }, chartB, chartC))));
  const right = h("div", { class: "col scroll inspector" },
    panel("Statistics", statsBox),
    panel("Definitions", h("div", { class: "faint", style: { fontSize: "12px", display: "grid", gap: "6px" } },
      h("div", {}, "Separation of member k from the unperturbed reference: d = ‖(wrap Δθ₁, wrap Δθ₂, τΔω₁, τΔω₂)‖₂ with τ = √(L₁/g), so the metric is dimensionless and angle differences use the shortest arc."),
      h("div", {}, "Dashed grey: the reference integrated at Δt and Δt/2. This numerical-error control must stay far below the ensemble curves; physical sensitivity is only meaningful above it."),
      h("div", {}, "Initial-condition sensitivity is a property of the dynamics, not an integration error: even perfect arithmetic would show the same exponential growth."))),
    panel("Save", btn("Save as experiment", () => saveExperimentDialog({ mode: "butterfly", extra: params() }), { cls: "sm" })));
  root.classList.add("fill");
  root.append(h("div", { class: "layout-3" }, left, centre, right));

  let job = null, data = null, renderers = [];

  function params() {
    return { n: P.n.get(), epsilon: P.eps.get(), variable: P.variable.get(), distribution: P.dist.get(), seed: P.seed.get(), threshold: P.thr.get() };
  }

  async function run() {
    const cfg = JSON.parse(JSON.stringify(state.config));
    cfg.numerics = { ...cfg.numerics, method: "rk4", dt: P.dt.get(), t_max: P.tmax.get(), output_dt: 1 / 120 };
    cfg.physical = { ...cfg.physical, damping1: 0, damping2: 0, drive_amplitude: 0 };
    runBtn.disabled = true; cancelBtn.disabled = false; prog.set(0);
    job = runJob("butterfly", { config: cfg, ...params(), numerical_control: true }, { onProgress: (f) => prog.set(f) });
    try {
      const r = await job.promise;
      ingest(r, cfg);
      toast(`${r.stats.members} pendulums · ${fmtSig(r.steps_per_second, 3)} RK4 steps/s`, "ok");
    } catch (e) { if (e.message !== "cancelled") toast(e.message, "err"); }
    runBtn.disabled = false; cancelBtn.disabled = true;
  }

  function ingest(r, cfg) {
    const p = cfg.physical;
    const t = Float64Array.from(r.t);
    const dt = t[1] - t[0];
    const sims = r.theta1.map((a, k) => addPositions({ t, dt, n: t.length, tEnd: t[t.length - 1], p, th1: Float64Array.from(a), th2: Float64Array.from(r.theta2[k]), config: cfg }, p));
    data = { r, sims, t };
    lc.tEnd = t[t.length - 1]; lc.set(0); lc.play(true);
    layoutStage();
    // charts
    const n = r.log10_separation.length;
    const pal = sampler(paletteStops(state.visual.palette, state.visual.custom));
    const series = r.log10_separation.slice(0, 60).map((y, k) => ({ x: t, y: nul(y), color: `rgb(${pal((k + 1) / n).join(",")})`, alpha: 0.35, width: 1 }));
    series.push({ x: t, y: nul(r.median_log10_separation), color: token("text"), width: 2.2, label: "median" });
    if (r.numerical_control_log10) series.push({ x: t, y: nul(r.numerical_control_log10), color: token("text-3"), dash: [5, 4], width: 1.5, label: "numerical control (Δt vs Δt/2)" });
    chSep.set(series);
    chSep.setHLines([{ y: Math.log10(r.threshold), color: token("gold"), label: `threshold ${r.threshold}` }]);
    const firstDiv = r.stats.min_divergence_time;
    chSep.setMarkers(firstDiv !== null ? [{ x: firstDiv, label: "first divergence", color: token("pink") }] : []);
    chAng.set([{ x: t, y: nul(r.angular_difference2), color: token("cyan") }]);
    chCart.set([{ x: t, y: nul(r.cartesian_separation_median), color: token("pink") }]);
    replayBtn.disabled = firstDiv === null;
    const st = r.stats;
    statsBox.innerHTML = "";
    const stat = (v, l) => h("div", { class: "stat" }, h("div", { class: "v" }, v), h("div", { class: "l" }, l));
    statsBox.append(
      stat(String(st.members), "members"),
      stat(`${st.diverged}/${st.members - 1}`, "crossed threshold"),
      stat(st.min_divergence_time === null ? "—" : `${fmt(st.min_divergence_time, 2)} s`, "first divergence"),
      stat(st.median_divergence_time === null ? "—" : `${fmt(st.median_divergence_time, 2)} s`, "median divergence"),
      stat(`${fmt(st.final_spread_m, 3)} m`, "final endpoint spread (σ)"),
      stat(`${fmt(r.runtime_s, 2)} s`, "integration time"),
      stat(fmtSig(r.steps_per_second, 3), "RK4 steps / s (all members)"),
      stat(fmtSig(P.eps.get(), 2), `ε in ${P.variable.get()}`));
  }

  const nul = (a) => Float64Array.from(a, (v) => (v === null ? NaN : v));

  function colors(n) {
    const pal = sampler(paletteStops(state.visual.palette, state.visual.custom));
    return Array.from({ length: n }, (_, k) => pal(n === 1 ? 0.5 : k / (n - 1)));
  }

  function applyVisual() {
    const v = { ...state.visual, trail: view.get() === "cloud" ? "fade" : "fade", trailSeconds: view.get() === "cloud" ? 0.15 : trail.get(), glow: Math.min(state.visual.glow, 0.9), particles: "none", camera: "static", render3d: false };
    renderers.forEach((r, k) => { r.setVisual(view.get() === "grid" ? { ...v, trailSeconds: trail.get() } : v); });
    if (data && view.get() !== "grid") renderers[0] && renderers[0].setBodies(data.sims, colors(data.sims.length));
  }

  function layoutStage() {
    stageBox.innerHTML = "";
    renderers = [];
    if (!data) { stageBox.append(h("div", { class: "empty", style: { position: "absolute", inset: 0, display: "grid", placeItems: "center" } }, "Run an ensemble to watch nearly identical pendulums diverge.")); return; }
    if (view.get() === "grid") {
      const k = Math.min(16, data.sims.length);
      const cols = Math.ceil(Math.sqrt(k));
      const grid = h("div", { style: { position: "absolute", inset: 0, display: "grid", gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: "1px" } });
      const cs = colors(data.sims.length);
      for (let i = 0; i < k; i++) {
        const c = h("canvas", { style: { width: "100%", height: "100%" } });
        const cell = h("div", { style: { position: "relative", border: "1px solid var(--border)" } }, c,
          h("span", { class: "faint mono", style: { position: "absolute", left: "6px", top: "4px", fontSize: "10.5px" } }, `#${i} ${i === 0 ? "ref" : `+${fmtSig(data.r.offsets[i], 2)}`}`));
        grid.append(cell);
        const r = new PendulumRenderer(c);
        r.setBodies([data.sims[i]], [cs[i]]);
        renderers.push(r);
      }
      stageBox.append(grid);
    } else {
      const c = h("canvas");
      stageBox.append(c);
      const r = new PendulumRenderer(c);
      renderers.push(r);
    }
    applyVisual();
  }

  function replay() {
    const t0 = data.r.stats.min_divergence_time;
    if (t0 === null) return;
    lc.set(Math.max(0, t0 - 2)); lc.speed = 0.25; lc.play(true);
    toast("Replaying the divergence at 0.25× — playback of stored states");
  }

  cleanups.push(bus.on("frame", (_, dtWall) => {
    if (!data) return;
    const t = lc.advance(dtWall);
    for (const r of renderers) {
      if (view.get() === "cloud") r.visual.rods = false;
      r.draw(t, dtWall);
    }
    chSep.setCursor(t); chAng.setCursor(t); chCart.setCursor(t);
    tr.update();
  }));
  cleanups.push(bus.on("visual", () => applyVisual()));
  layoutStage();
  void setVisual;
  return () => { cleanups.forEach((u) => u()); if (job) job.cancel(); [chSep, chAng, chCart].forEach((c) => c.destroy()); };
}
