// Physics Lab: integrators, normal modes, equilibria, energy landscape,
// Lyapunov exponents, parameter sweeps and the isolated advanced models.

import { api, decodeF32, download, runJob } from "../api.js";
import { Heatmap, LineChart } from "../charts.js";
import { LocalClock, miniTransport } from "../controls.js";
import { paletteStops, rgba, sampler, seriesStyle, token } from "../palettes.js";
import { PendulumRenderer } from "../renderer.js";
import { addPositions, bus, cloneDeep, setConfig, state } from "../state.js";
import { btn, fmt, fmtSig, h, panel, progressBar, select, slider, toast } from "../ui.js";

export const meta = { id: "lab" };
const F = (a) => Float64Array.from(a || [], (v) => (v === null ? NaN : v));

export function mount(root) {
  const TABS = [["integrators", "Integrators"], ["modes", "Normal modes & equilibria"], ["landscape", "Energy landscape"], ["lyapunov", "Lyapunov lab"], ["sweeps", "Parameter sweeps"], ["advanced", "Advanced models"]];
  const tabs = h("div", { class: "tabs", role: "tablist" });
  const body = h("div");
  root.append(tabs, body);
  let teardown = null;
  const fns = { integrators, modes, landscape, lyapunov, sweeps, advanced };
  function open(id) {
    if (teardown) teardown();
    body.innerHTML = "";
    [...tabs.children].forEach((b, i) => b.setAttribute("aria-selected", String(TABS[i][0] === id)));
    teardown = fns[id](body) || null;
  }
  for (const [id, label] of TABS) {
    const b = h("button", { role: "tab", type: "button" }, label);
    b.addEventListener("click", () => open(id));
    tabs.append(b);
  }
  open("integrators");
  return () => teardown && teardown();
}

function jobButton(label, start) {
  const prog = progressBar();
  let job = null;
  const run = btn(label, async () => {
    run.disabled = true; cancel.disabled = false; prog.set(0.02);
    try { job = start((f) => prog.set(f)); await job; } catch (e) { if (e.message !== "cancelled") toast(e.message, "err"); }
    run.disabled = false; cancel.disabled = true; prog.set(1);
  }, { cls: "primary" });
  const cancel = btn("Cancel", () => { if (start.current) start.current.cancel(); }, { cls: "sm", disabled: true });
  return h("div", { style: { display: "grid", gap: "8px" } }, h("div", { class: "btn-row" }, run, cancel), prog);
}

// ---------------------------------------------------------------- integrators
function integrators(root) {
  const tmax = slider({ label: "Horizon", unit: "s", min: 2, max: 60, step: 1, value: 20, digits: 0 });
  const table = h("div");
  const c1 = h("div", { class: "panel", style: { padding: "8px" } }), c2 = h("div", { class: "panel", style: { padding: "8px" } }), c3 = h("div", { class: "panel", style: { padding: "8px" } });
  const chE = new LineChart(c1, { title: "log₁₀ |energy error|", xlabel: "time [s]", cls: "tall", logY: true });
  const chD = new LineChart(c2, { title: "log₁₀ distance from DOP853 reference (rtol = 1e-13)", xlabel: "time [s]", cls: "tall", logY: true });
  const chC = new LineChart(c3, { title: "RK4 convergence: final-state error vs Δt (5 s horizon)", xlabel: "log₁₀ Δt", cls: "tall", logY: true, xname: "log₁₀Δt" });
  const tolBox = h("div");
  const start = (onP) => {
    const j = runJob("integrators", { config: state.config, t_max: tmax.get() }, { onProgress: onP });
    start.current = j;
    return j.promise.then(show);
  };
  root.append(h("div", { class: "layout-2" },
    h("div", { class: "col" },
      panel("Integrator showdown", h("div", { style: { display: "grid", gap: "10px" } }, tmax, jobButton("Run comparison", start),
        h("div", { class: "faint", style: { fontSize: "12px" } }, "Runs the current configuration with RK4 at two steps and RK45/DOP853 at two tolerances each, against a DOP853 reference at rtol = atol = 1e-13. With damping or driving, the energy column is the energy-balance residual."))),
      panel("Tolerance sweep", h("div", { style: { display: "grid", gap: "8px" } }, btn("Runtime vs tolerance (DOP853)", () => tolSweep(), { cls: "sm" }), tolBox)),
      h("div", { class: "note warn" }, "Chaotic trajectories computed with different methods diverge eventually even when all of them are accurate: tiny round-off differences grow exponentially. Long-term divergence is not proof of incorrect integration. Judge accuracy by energy error, short-horizon agreement, and convergence as settings are refined.")),
    h("div", { class: "col" }, table, h("div", { class: "grid-2" }, c1, c2), c3)));

  function show(r) {
    const pal = [0, 1, 2, 3, 4, 5].map((i) => seriesStyle(i).color); // grey levels; dashes come from the chart
    table.innerHTML = "";
    table.append(panel("Results", h("table", { class: "data" },
      h("tr", {}, ...["Integrator", "runtime", "fn evals", "max |ΔE/E₀|", "final Δ vs ref", "max Δ vs ref"].map((x) => h("th", {}, x))),
      ...r.rows.map((x, i) => h("tr", {}, h("td", {}, h("span", { class: "dot", style: { background: pal[i % 6], display: "inline-block", marginRight: "6px" } }), x.label),
        h("td", { class: "num" }, `${fmt(x.runtime_s, 3)} s`), h("td", { class: "num" }, x.nfev),
        h("td", { class: "num" }, fmtSig(x.max_abs_rel_energy_error, 2)), h("td", { class: "num" }, fmtSig(x.final_state_difference, 2)), h("td", { class: "num" }, fmtSig(x.max_state_difference, 2))))),
      h("div", { class: "faint", style: { fontSize: "11.5px", marginTop: "6px" } }, `Reference: ${r.reference_nfev} function evaluations. Distances use the wrapped dimensionless norm.`)));
    const labels = Object.keys(r.trajectories);
    chE.set(labels.map((l, i) => ({ x: F(r.trajectories[l].t), y: F(r.trajectories[l].log10_energy_error), color: pal[i % 6], label: l, width: 1.2 })));
    chD.set(labels.map((l, i) => ({ x: F(r.trajectories[l].t), y: F(r.trajectories[l].log10_distance), color: pal[i % 6], label: l, width: 1.2 })));
    const cv = r.convergence;
    const lx = cv.dt.map(Math.log10), ly = cv.error.map((e) => Math.log10(e));
    const ref = lx.map((x) => ly[ly.length - 1] + 4 * (x - lx[lx.length - 1]));
    chC.set([{ x: lx, y: ly, color: token("cyan"), label: `observed order ${fmt(cv.observed_order, 2)}`, points: true, noMinMax: true },
      { x: lx, y: ref, color: token("text-3"), dash: [5, 4], label: "slope 4 reference", noMinMax: true }]);
  }
  async function tolSweep() {
    tolBox.innerHTML = "computing…";
    try {
      const r = await runJob("tolerance", { config: state.config, t_max: tmax.get() }).promise;
      tolBox.innerHTML = "";
      tolBox.append(h("table", { class: "data" }, h("tr", {}, h("th", {}, "tol"), h("th", {}, "runtime"), h("th", {}, "nfev"), h("th", {}, "max |ΔE|")),
        ...r.rows.map((x) => h("tr", {}, h("td", { class: "num" }, fmtSig(x.tolerance, 1)), h("td", { class: "num" }, `${fmt(x.runtime_s, 3)} s`), h("td", { class: "num" }, x.nfev), h("td", { class: "num" }, fmtSig(x.max_abs_rel_energy_error, 2))))));
    } catch (e) { tolBox.textContent = e.message; }
  }
  return () => [chE, chD, chC].forEach((c) => c.destroy());
}

// ---------------------------------------------------------------- normal modes
function modes(root) {
  const amp = slider({ label: "Comparison amplitude θ₁(0)", unit: "deg", min: 0.5, max: 90, step: 0.5, value: 5, digits: 1 });
  const ratio = select({ label: "Initial shape", value: "mode1", options: [["mode1", "Pure mode 1 (slow)"], ["mode2", "Pure mode 2 (fast)"], ["current", "Current θ₂/θ₁ ratio"]] });
  const tmax = slider({ label: "Horizon", unit: "s", min: 5, max: 60, step: 1, value: 20, digits: 0 });
  const info = h("div"), eq = h("div");
  const cBox = h("div", { class: "panel", style: { padding: "8px" } }), eBox = h("div", { class: "panel", style: { padding: "8px" } });
  const ch = new LineChart(cBox, { title: "Nonlinear (solid) vs linearized (dashed)", xlabel: "time [s]", ylabel: "angle [rad]", cls: "tall" });
  const chErr = new LineChart(eBox, { title: "max |θ_nonlinear − θ_linear| [rad]", xlabel: "time [s]", cls: "tall" });
  root.append(h("div", { class: "layout-2" },
    h("div", { class: "col" }, panel("Small-angle comparison", h("div", { style: { display: "grid", gap: "10px" } }, amp, ratio, tmax, btn("Compare", () => run(), { cls: "primary" }))), info),
    h("div", { class: "col" }, h("div", { class: "grid-2" }, cBox, eBox), eq)));
  let nm = null;
  async function run() {
    const c = cloneDeep(state.config);
    if (nm && ratio.get() !== "current") {
      const r = nm.normal_modes.shape_ratio_theta2_over_theta1[ratio.get() === "mode1" ? 0 : 1];
      c.initial = { theta1_deg: amp.get(), theta2_deg: amp.get() * r, omega1: 0, omega2: 0 };
    } else if (ratio.get() === "current") {
      const r0 = c.initial.theta1_deg ? c.initial.theta2_deg / c.initial.theta1_deg : 1;
      c.initial = { theta1_deg: amp.get(), theta2_deg: amp.get() * r0, omega1: 0, omega2: 0 };
    }
    try {
      const r = await api.post("/api/modes", { config: c, t_max: tmax.get(), breakdown_deg: 2 });
      if (!nm) { nm = r; if (ratio.get() !== "current") return run(); }
      nm = r;
      const m = r.normal_modes, cmp = r.comparison, t = F(cmp.t);
      ch.set([{ x: t, y: F(cmp.theta1), color: token("cyan"), label: "θ₁" }, { x: t, y: F(cmp.theta2), color: token("pink"), label: "θ₂" },
        { x: t, y: F(cmp.theta1_linear), color: token("cyan"), dash: [5, 4], alpha: 0.8 }, { x: t, y: F(cmp.theta2_linear), color: token("pink"), dash: [5, 4], alpha: 0.8 }]);
      chErr.set([{ x: t, y: F(cmp.max_abs_error), color: token("gold"), label: "deviation" }]);
      chErr.setHLines([{ y: (cmp.breakdown_threshold_deg * Math.PI) / 180, color: token("red"), label: `${cmp.breakdown_threshold_deg}° breakdown threshold` }]);
      chErr.setMarkers(cmp.breakdown_t !== null ? [{ x: cmp.breakdown_t, label: "approximation breaks down", color: token("red") }] : []);
      info.innerHTML = "";
      info.append(panel("Normal modes (linearized about hanging rest)", h("div", {},
        h("table", { class: "data" }, h("tr", {}, h("th", {}, "mode"), h("th", {}, "ω [rad/s]"), h("th", {}, "f [Hz]"), h("th", {}, "T [s]"), h("th", {}, "θ₂/θ₁")),
          ...[0, 1].map((k) => h("tr", {}, h("td", {}, k ? "2 (fast, anti-phase)" : "1 (slow, in-phase)"), h("td", { class: "num" }, fmt(m.omega[k], 4)), h("td", { class: "num" }, fmt(m.frequency_hz[k], 4)),
            h("td", { class: "num" }, fmt(m.period_s[k], 4)), h("td", { class: "num" }, fmt(m.shape_ratio_theta2_over_theta1[k], 4))))),
        h("div", { class: "btn-row", style: { marginTop: "8px" } },
          ...[0, 1].map((k) => btn(`Excite mode ${k + 1} in Playground`, () => {
            const cc = cloneDeep(state.config);
            cc.initial = { theta1_deg: 3, theta2_deg: +(3 * m.shape_ratio_theta2_over_theta1[k]).toFixed(4), omega1: 0, omega2: 0 };
            cc.name = `Normal mode ${k + 1}`;
            setConfig(cc); location.hash = "#/playground";
          }, { cls: "sm" }))),
        h("p", { class: "faint", style: { fontSize: "12px" } }, `Max amplitude in this run: ${fmt(cmp.max_amplitude_deg, 1)}°. ${cmp.breakdown_t === null ? "The linear model stays within 2° over the whole horizon." : `Linear prediction deviates by more than 2° after ${fmt(cmp.breakdown_t, 2)} s.`}`))));
      eq.innerHTML = "";
      eq.append(panel("The four vertical equilibria (mod 2π)", h("table", { class: "data" },
        h("tr", {}, h("th", {}, "configuration"), h("th", {}, "V [J]"), h("th", {}, "eigenvalues of J"), h("th", {}, "classification")),
        ...r.equilibria.map((e) => h("tr", {}, h("td", {}, `${e.name} (θ₁=${fmt(e.theta1_deg, 0)}°, θ₂=${fmt(e.theta2_deg, 0)}°)`), h("td", { class: "num" }, fmt(e.potential_energy, 2)),
          h("td", { class: "mono", style: { fontSize: "11px" } }, e.eigenvalues.map(([re, im]) => `${fmt(re, 2)}${im >= 0 ? "+" : "−"}${fmt(Math.abs(im), 2)}i`).join(", ")),
          h("td", {}, e.classification))))));
    } catch (e) { toast(e.message, "err"); }
  }
  run();
  return () => { ch.destroy(); chErr.destroy(); };
}

// ---------------------------------------------------------------- energy landscape
function landscape(root) {
  const box = h("div", { class: "panel", style: { padding: "10px", height: "620px" } });
  const hm = new Heatmap(box, {
    xlabel: "θ₁ [rad]", ylabel: "θ₂ [rad]", xname: "θ₁", yname: "θ₂", vname: "V [J]", square: true,
    onPick: (x, y) => {
      const c = cloneDeep(state.config);
      c.initial = { theta1_deg: +((x * 180) / Math.PI).toFixed(2), theta2_deg: +((y * 180) / Math.PI).toFixed(2), omega1: 0, omega2: 0 };
      setConfig(c);
      toast(`Initial configuration set (at rest): E₀ = V(θ₁, θ₂)`, "ok");
    },
  });
  hm.el.style.height = "100%";
  const info = h("div");
  root.append(h("div", { class: "layout-2 wide-left" },
    h("div", { class: "col" }, panel("Potential energy V(θ₁, θ₂)", h("div", { class: "faint", style: { fontSize: "12.5px", display: "grid", gap: "6px" } },
      h("div", {}, "V = −(m₁+m₂) g L₁ cos θ₁ − m₂ g L₂ cos θ₂ with zero at the pivot height."),
      h("div", {}, "Starting at rest, motion is confined to the region V ≤ E₀ (dotted contour). Click the map to choose a new initial configuration; the current trajectory is projected as a thin line."))), info),
    box));
  async function run() {
    try {
      const r = await api.post("/api/landscape", { config: state.config, n: 181 });
      const V = decodeF32(r.V);
      const s = state.sim;
      const traj = [];
      if (s) {
        const wrap = (a) => ((((a + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) - Math.PI;
        const step = Math.max(1, Math.floor(s.n / 4000));
        let prev = null;
        for (let i = 0; i < s.n; i += step) {
          const p = [wrap(s.th1[i]), wrap(s.th2[i])];
          if (prev && (Math.abs(p[0] - prev[0]) > Math.PI || Math.abs(p[1] - prev[1]) > Math.PI)) traj.push([NaN, NaN]);
          traj.push(p); prev = p;
        }
      }
      // E0 contour: mark grid cells where V crosses E0
      const n = r.n, cont = [];
      for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
        const a = V[j * n + i] - r.E0, b = V[j * n + i + 1] - r.E0, c = V[(j + 1) * n + i] - r.E0;
        if (a * b < 0 || a * c < 0) cont.push([-Math.PI + ((i + 0.5) / (n - 1)) * 2 * Math.PI, -Math.PI + ((j + 0.5) / (n - 1)) * 2 * Math.PI]);
      }
      hm.overlay = [
        { type: "points", pts: cont, color: token("fg"), r: 1.1, alpha: 0.9 },
        { type: "path", pts: traj, color: token("cyan"), width: 1, alpha: 0.6 },
        { type: "points", pts: r.equilibria.map((e) => [wrap0(e.theta1), wrap0(e.theta2), e.name]), color: token("gold"), r: 5 },
      ];
      hm.set(V, n, n, [-Math.PI, Math.PI], [-Math.PI, Math.PI], { cmap: "auto", unit: "V [J]", clip: 0 });
      info.innerHTML = "";
      info.append(panel("Equilibria", h("table", { class: "data" }, ...r.equilibria.map((e) => h("tr", {}, h("td", {}, e.name), h("td", { class: "num" }, `${fmt(e.potential_energy, 2)} J`), h("td", {}, e.classification)))),
        h("p", { class: "faint", style: { fontSize: "12px" } }, `Current E₀ = ${fmt(r.E0, 3)} J. Equilibria at ±π appear on the map edges (θ = π ≡ −π).`)));
    } catch (e) { toast(e.message, "err"); }
  }
  const wrap0 = (a) => (a >= Math.PI - 1e-9 ? Math.PI - 1e-6 : a);
  const off = bus.on("sim", run);
  run();
  return () => { off(); hm.destroy(); };
}

// ---------------------------------------------------------------- Lyapunov
function lyapunov(root) {
  const P = {
    tmax: slider({ label: "Averaging time", unit: "s", min: 5, max: 300, step: 5, value: 60, digits: 0 }),
    dt: slider({ label: "RK4 step", unit: "s", min: 2e-4, max: 0.005, log: true, value: 0.002 }),
    iv: slider({ label: "Renormalization interval", unit: "s", min: 0.01, max: 2, log: true, value: 0.1 }),
    d0: slider({ label: "Initial separation d₀ (two-trajectory)", min: 1e-12, max: 1e-4, log: true, value: 1e-8 }),
    transient: slider({ label: "Discard transient", unit: "s", min: 0, max: 30, step: 1, value: 0, digits: 0 }),
    method: select({ label: "Estimator", value: "tangent", options: [["tangent", "Tangent (variational equations)"], ["two_trajectory", "Two-trajectory (Benettin)"]] }),
    delta0: slider({ label: "Initial uncertainty δ₀", min: 1e-12, max: 1e-1, log: true, value: 1e-6 }),
    dmax: slider({ label: "Tolerated error δmax", min: 1e-3, max: 3, log: true, value: 0.5 }),
  };
  const out = h("div");
  const cBox = h("div", { class: "panel", style: { padding: "8px" } }), lBox = h("div", { class: "panel", style: { padding: "8px" } });
  const ch = new LineChart(cBox, { title: "Running finite-time estimate λ(t) [1/s]", xlabel: "time [s]", cls: "tall" });
  const chL = new LineChart(lBox, { title: "Local stretching rates ln(dₖ/d₀)/Δt [1/s]", xlabel: "time [s]", cls: "tall" });
  const scanBox = h("div"), valBox = h("div");
  let lastLam = null;
  const start = (onP) => {
    const j = runJob("lyapunov", { config: state.config, t_max: P.tmax.get(), dt: P.dt.get(), renorm_interval: P.iv.get(), d0: P.d0.get(), method: P.method.get(),
      transient: P.transient.get(), delta0: P.delta0.get(), delta_max: P.dmax.get() }, { onProgress: onP });
    start.current = j;
    return j.promise.then(show);
  };
  root.append(h("div", { class: "layout-2" },
    h("div", { class: "col" },
      panel("Estimator", h("div", { style: { display: "grid", gap: "10px" } }, P.method, P.tmax, P.dt, P.iv, P.d0, P.transient, jobButton("Estimate λ", start))),
      panel("Predictability horizon", h("div", { style: { display: "grid", gap: "10px" } }, P.delta0, P.dmax, out)),
      panel("Validation", h("div", { style: { display: "grid", gap: "8px" } }, btn("Validate on Lorenz-63", () => validate(), { cls: "sm" }), valBox))),
    h("div", { class: "col" }, h("div", { class: "grid-2" }, cBox, lBox),
      panel("Sensitivity to estimator settings", h("div", { style: { display: "grid", gap: "8px" } },
        btn("Run settings scan (12 estimates, 30 s each)", () => scan(), { cls: "sm" }), scanBox)),
      h("div", { class: "note" }, "A finite-time estimate depends on the averaging time, the initial condition and the norm; only the infinite-time limit is norm-independent. Treat it as a measured rate for this trajectory and these settings, not as a universal constant. Norm: Euclidean in (θ₁, θ₂, τω₁, τω₂), τ = √(L₁/g), angle differences wrapped."))));
  function horizon() {
    if (lastLam === null) return;
    const T = lastLam > 0 ? Math.log(P.dmax.get() / P.delta0.get()) / lastLam : Infinity;
    out.innerHTML = "";
    out.append(h("div", { class: "stats" },
      h("div", { class: "stat" }, h("div", { class: "v" }, `${fmt(lastLam, 3)}`), h("div", { class: "l" }, "λ [1/s]")),
      h("div", { class: "stat" }, h("div", { class: "v" }, Number.isFinite(T) ? `${fmt(T, 1)} s` : "∞"), h("div", { class: "l" }, "T ≈ ln(δmax/δ₀)/λ"))),
      h("div", { class: "faint", style: { fontSize: "11.5px", marginTop: "6px" } }, "Assumes errors grow exponentially at the average rate λ from the start: a rough scale, not a guarantee. Real growth fluctuates (see the local rates)."));
  }
  P.delta0.addEventListener("change", horizon); P.dmax.addEventListener("change", horizon);
  function show(r) {
    lastLam = r.lambda;
    ch.set([{ x: F(r.t), y: F(r.running), color: token("cyan"), label: `${r.method}` }]);
    ch.setHLines([{ y: r.lambda, color: token("gold"), label: `λ ≈ ${fmt(r.lambda, 3)}` }, { y: 0, color: token("text-3") }]);
    chL.set([{ x: F(r.t), y: F(r.local), color: token("purple"), width: 1 }]);
    horizon();
  }
  async function scan() {
    scanBox.textContent = "running 12 estimates…";
    try {
      const r = await runJob("lyapunov_scan", { config: state.config, t_max: 30 }).promise;
      scanBox.innerHTML = "";
      scanBox.append(h("div", { class: "faint", style: { fontSize: "12px" } }, `mean ${fmt(r.mean, 3)} · std ${fmt(r.std, 3)} · range [${fmt(r.min, 3)}, ${fmt(r.max, 3)}] 1/s`),
        h("table", { class: "data" }, h("tr", {}, h("th", {}, "method"), h("th", {}, "d₀"), h("th", {}, "interval [s]"), h("th", {}, "λ [1/s]")),
          ...r.rows.map((x) => h("tr", {}, h("td", {}, x.method), h("td", { class: "num" }, x.d0 === null ? "—" : fmtSig(x.d0, 1)), h("td", { class: "num" }, fmt(x.renorm_interval, 3)), h("td", { class: "num" }, fmt(x.lambda, 4))))));
    } catch (e) { scanBox.textContent = e.message; }
  }
  async function validate() {
    valBox.textContent = "running…";
    try {
      const r = await runJob("lyapunov_validate", {}).promise;
      valBox.innerHTML = "";
      valBox.append(h("div", { class: "note ok" }, `${r.system}: estimate ${fmt(r.estimate, 3)} vs literature ≈ ${r.reference} (60 s average after a 10 s transient; finite-time scatter of a few percent is expected).`));
    } catch (e) { valBox.textContent = e.message; }
  }
  return () => { ch.destroy(); chL.destroy(); };
}

// ---------------------------------------------------------------- sweeps
function sweeps(root) {
  const keys = state.meta ? state.meta.sweep_keys : ["theta1_deg", "theta2_deg", "m1", "m2", "L1", "L2", "g", "mass_ratio", "length_ratio"];
  const labels = { theta1_deg: "θ₁(0) [deg]", theta2_deg: "θ₂(0) [deg]", omega1: "ω₁(0) [rad/s]", omega2: "ω₂(0) [rad/s]", m1: "m₁ [kg]", m2: "m₂ [kg]", L1: "L₁ [m]", L2: "L₂ [m]", g: "g [m/s²]",
    mass_ratio: "m₁/m₂", length_ratio: "L₁/L₂", damping1: "b₁", damping2: "b₂", drive_amplitude: "A [N·m]", drive_frequency: "Ω [rad/s]" };
  const opts = keys.map((k) => [k, labels[k] || k]);
  const dim = select({ label: "Sweep", value: "2d", options: [["1d", "1D (line chart)"], ["2d", "2D (heatmap)"]] });
  const xk = select({ label: "x parameter", value: "mass_ratio", options: opts });
  const x0 = slider({ label: "x from", min: -180, max: 180, step: 0.01, value: 0.2, digits: 2 }), x1 = slider({ label: "x to", min: -180, max: 180, step: 0.01, value: 5, digits: 2 });
  const nx = slider({ label: "x points", min: 2, max: 300, step: 1, value: 80, digits: 0 });
  const yk = select({ label: "y parameter", value: "theta1_deg", options: opts });
  const y0 = slider({ label: "y from", min: -180, max: 180, step: 0.01, value: 0, digits: 2 }), y1 = slider({ label: "y to", min: -180, max: 180, step: 0.01, value: 180, digits: 2 });
  const ny = slider({ label: "y points", min: 2, max: 300, step: 1, value: 80, digits: 0 });
  const obs = select({ label: "Observable", value: "rotations", options: (state.meta ? state.meta.sweep_observables : ["rotations"]).map((o) => [o, { rotations: "Rotation count", first_flip: "First-flip time [s]", max_omega: "max |ω| [rad/s]", max_speed: "max |v₂| [m/s]", final_energy: "Final energy [J]" }[o] || o]) });
  const tmax = slider({ label: "Integration time", unit: "s", min: 1, max: 60, step: 0.5, value: 10, digits: 1 });
  const dt = slider({ label: "RK4 step", unit: "s", min: 1e-3, max: 0.02, log: true, value: 0.005 });
  const info = h("div", { class: "faint mono", style: { fontSize: "11.5px" } });
  const lineBox = h("div", { class: "panel", style: { padding: "8px" } }), heatBox = h("div", { class: "panel", style: { padding: "8px", height: "560px" } });
  const lc = new LineChart(lineBox, { cls: "xl", title: "" });
  const hm = new Heatmap(heatBox, {});
  hm.el.style.height = "100%";
  let last = null;
  const start = (onP) => {
    const body = { config: state.config, x_key: xk.get(), x_range: [x0.get(), x1.get()], nx: nx.get(), observable: obs.get(), t_max: tmax.get(), dt: dt.get() };
    if (dim.get() === "2d") Object.assign(body, { y_key: yk.get(), y_range: [y0.get(), y1.get()], ny: ny.get() });
    const j = runJob("sweep", body, { onProgress: onP });
    start.current = j;
    return j.promise.then(show);
  };
  function show(r) {
    last = r;
    const v = decodeF32(r.values);
    const xs = F(r.x);
    info.textContent = `${v.length} vectorized simulations in ${fmt(r.runtime_s, 2)} s (T = ${r.t_max} s, Δt = ${r.dt} s)`;
    lineBox.style.display = r.y_key ? "none" : ""; heatBox.style.display = r.y_key ? "" : "none";
    if (!r.y_key) lc.set([{ x: xs, y: Float64Array.from(v), color: token("cyan"), points: xs.length < 80, noMinMax: true }], { xlabel: labels[r.x_key] || r.x_key, ylabel: obs.input.selectedOptions[0].text, xname: r.x_key });
    else hm.set(v, r.shape[1], r.shape[0], [xs[0], xs[xs.length - 1]], [r.y[0], r.y[r.y.length - 1]], { xlabel: labels[r.x_key], ylabel: labels[r.y_key], cmap: "auto", unit: obs.input.selectedOptions[0].text, vname: r.observable, xname: r.x_key, yname: r.y_key });
  }
  function csv() {
    if (!last) return;
    const v = decodeF32(last.values);
    const lines = [`# Chaos Lab sweep · observable ${last.observable} · T ${last.t_max} s · dt ${last.dt} s`, `# base config: ${JSON.stringify(state.config)}`];
    if (!last.y_key) { lines.push(`${last.x_key},${last.observable}`); last.x.forEach((x, i) => lines.push(`${x},${v[i]}`)); }
    else { lines.push(`${last.x_key},${last.y_key},${last.observable}`); last.y.forEach((y, j) => last.x.forEach((x, i) => lines.push(`${x},${y},${v[j * last.x.length + i]}`))); }
    download(new Blob([lines.join("\n")], { type: "text/csv" }), "chaos-lab-sweep.csv");
  }
  root.append(h("div", { class: "layout-2" },
    h("div", { class: "col scroll" }, panel("Sweep setup", h("div", { style: { display: "grid", gap: "10px" } }, dim, xk, x0, x1, nx, yk, y0, y1, ny, obs, tmax, dt,
      jobButton("Run sweep", start), info, btn("Export CSV", csv, { cls: "sm" }),
      h("div", { class: "faint", style: { fontSize: "11.5px" } }, "Parameters are broadcast as arrays through the vectorized equations, so a whole sweep is one batched RK4 run. Bounded at 6×10⁸ point-steps.")))),
    h("div", { class: "col" }, lineBox, heatBox)));
  lineBox.style.display = "none";
  return () => { lc.destroy(); hm.destroy(); };
}

// ---------------------------------------------------------------- advanced models
function advanced(root) {
  const lc = new LocalClock(1);
  const cv = h("canvas");
  const stage = h("div", { class: "stage", style: { minHeight: "460px" } }, cv);
  const tr = miniTransport(lc);
  const errBox = h("div", { class: "panel", style: { padding: "8px" } });
  const chErr = new LineChart(errBox, { title: "Relative energy error", compact: true });
  const model = select({ label: "Model", value: "nlink", options: [["nlink", "Triple / N-link pendulum"], ["pivot", "Moving suspension point"]], onChange: () => form() });
  const formBox = h("div", { style: { display: "grid", gap: "10px" } });
  const note = h("div", { class: "note" });
  root.append(h("div", { class: "layout-2" },
    h("div", { class: "col scroll" }, panel("Isolated advanced models", h("div", { style: { display: "grid", gap: "10px" } }, model, formBox)), note),
    h("div", { class: "col" }, stage, tr, errBox)));
  let anim = null;
  const ctx = cv.getContext("2d");

  function form() {
    formBox.innerHTML = "";
    if (model.get() === "nlink") {
      const n = slider({ label: "Links N", min: 2, max: 8, step: 1, value: 3, digits: 0 });
      const ang = h("input", { type: "text", value: "120, -10, 30" }), ms = h("input", { type: "text", value: "1, 1, 1" }), ls = h("input", { type: "text", value: "1, 1, 1" });
      const tmax = slider({ label: "Duration", unit: "s", min: 2, max: 60, step: 1, value: 20, digits: 0 });
      formBox.append(n, h("div", { class: "field" }, h("label", {}, "Angles θᵢ(0) [deg]"), ang), h("div", { class: "field" }, h("label", {}, "Masses [kg]"), ms), h("div", { class: "field" }, h("label", {}, "Lengths [m]"), ls), tmax,
        btn("Simulate", async () => {
          const N = n.get(), parse = (s, d) => { const a = s.value.split(",").map(Number).filter(Number.isFinite); while (a.length < N) a.push(d); return a.slice(0, N); };
          try {
            const r = await api.post("/api/nlink", { masses: parse(ms, 1), lengths: parse(ls, 1), theta_deg: parse(ang, 0), omega: Array(N).fill(0), t_max: tmax.get(), g: state.config.physical.g });
            anim = { kind: "nlink", r, t: F(r.t), th: r.theta.map(F) };
            lc.tEnd = anim.t[anim.t.length - 1]; lc.set(0); lc.play(true);
            chErr.set([{ x: anim.t, y: F(r.energy_error), color: token("green") }], { symmetric: true });
          } catch (e) { toast(e.message, "err"); }
        }, { cls: "primary" }));
      note.textContent = "Separate model built from the generalized mass matrix M_ij = μ_ij L_i L_j cos(θᵢ−θⱼ), μ_ij = Σ_{k≥max(i,j)} m_k (Euler–Lagrange of T − V). It reduces exactly to the double pendulum for N = 2 (checked in the test suite). The double pendulum code is not modified to fake a triple pendulum.";
    } else {
      const ax = slider({ label: "Horizontal amplitude", unit: "m", min: 0, max: 0.3, step: 0.005, value: 0, digits: 3 });
      const ay = slider({ label: "Vertical amplitude", unit: "m", min: 0, max: 0.3, step: 0.005, value: 0.05, digits: 3 });
      const om = slider({ label: "Pivot frequency", unit: "rad/s", min: 0, max: 200, step: 0.5, value: 60, digits: 1 });
      formBox.append(ax, ay, om, btn("Simulate (uses current θ, m, L, g)", async () => {
        try {
          const c = cloneDeep(state.config); c.numerics.t_max = Math.min(c.numerics.t_max, 30);
          const r = await api.post("/api/pivot", { config: c, amp_x: ax.get(), amp_y: ay.get(), omega: om.get() });
          anim = { kind: "pivot", r, t: F(r.t), th: [F(r.theta1), F(r.theta2)], px: F(r.pivot_x), py: F(r.pivot_y), p: c.physical };
          lc.tEnd = anim.t[anim.t.length - 1]; lc.set(0); lc.play(true);
          chErr.set([]);
        } catch (e) { toast(e.message, "err"); }
      }, { cls: "primary" }),
      h("div", { class: "btn-row" }, btn("Kapitza-style: inverted start", () => { const c = cloneDeep(state.config); c.initial = { theta1_deg: 175, theta2_deg: 175, omega1: 0, omega2: 0 }; setConfig(c); ay.set(0.04); om.set(150); toast("Set an inverted start; now press Simulate"); }, { cls: "sm" })));
      note.textContent = "In the frame moving with the pivot each mass feels −m a_pivot, so the fixed-pivot equations apply with g sin θ → ẍ_p cos θ + (g + ÿ_p) sin θ. This model is isolated from the standard fixed-pivot engine; energy is not conserved because the pivot does work. Its RK4 step is reduced automatically to resolve the drive.";
    }
  }
  form();

  const off = bus.on("frame", (_, dtWall) => {
    const t = lc.advance(dtWall);
    tr.update();
    chErr.setCursor(t);
    const dpr = Math.min(2, devicePixelRatio || 1), r = cv.getBoundingClientRect();
    cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
    const W = cv.width, H = cv.height;
    ctx.clearRect(0, 0, W, H);
    if (!anim) { ctx.fillStyle = token("text-3"); ctx.font = `${13 * dpr}px system-ui, -apple-system, sans-serif`; ctx.textAlign = "center"; ctx.fillText("Choose a model and press Simulate.", W / 2, H / 2); return; }
    const i = Math.min(anim.t.length - 1, Math.round(t / (anim.t[1] - anim.t[0])));
    const pal = sampler(paletteStops(state.visual.palette));
    if (anim.kind === "nlink") {
      const L = anim.r.lengths, Ltot = L.reduce((a, b) => a + b, 0), sc = Math.min(W, H) / (2.3 * Ltot);
      const pts = [[W / 2, H / 2]];
      let x = 0, y = 0;
      const k0 = Math.max(0, i - 360), tip = [];
      for (let k = k0; k <= i; k += 2) { let xx = 0, yy = 0; for (let j = 0; j < anim.th.length; j++) { xx += L[j] * Math.sin(anim.th[j][k]); yy -= L[j] * Math.cos(anim.th[j][k]); } tip.push([W / 2 + xx * sc, H / 2 - yy * sc]); }
      ctx.globalCompositeOperation = "lighter"; ctx.lineWidth = 2 * dpr;
      for (let k = 1; k < tip.length; k++) { ctx.strokeStyle = rgba(pal(k / tip.length), k / tip.length); ctx.beginPath(); ctx.moveTo(...tip[k - 1]); ctx.lineTo(...tip[k]); ctx.stroke(); }
      ctx.globalCompositeOperation = "source-over";
      for (let j = 0; j < anim.th.length; j++) { x += L[j] * Math.sin(anim.th[j][i]); y -= L[j] * Math.cos(anim.th[j][i]); pts.push([W / 2 + x * sc, H / 2 - y * sc]); }
      ctx.strokeStyle = token("text"); ctx.lineWidth = 2.5 * dpr; ctx.beginPath(); pts.forEach((p, k) => (k ? ctx.lineTo(...p) : ctx.moveTo(...p))); ctx.stroke();
      pts.slice(1).forEach((p, k) => { ctx.fillStyle = rgba(pal(k / Math.max(1, pts.length - 2))); ctx.beginPath(); ctx.arc(p[0], p[1], 7 * dpr, 0, 7); ctx.fill(); });
    } else {
      const p = anim.p, sc = Math.min(W, H) / (2.4 * (p.L1 + p.L2));
      const ox = W / 2 + anim.px[i] * sc, oy = H / 2 - anim.py[i] * sc;
      const x1 = ox + p.L1 * Math.sin(anim.th[0][i]) * sc, y1 = oy + p.L1 * Math.cos(anim.th[0][i]) * sc;
      const x2 = x1 + p.L2 * Math.sin(anim.th[1][i]) * sc, y2 = y1 + p.L2 * Math.cos(anim.th[1][i]) * sc;
      ctx.strokeStyle = token("text-3"); ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(W / 2 - 60 * dpr, H / 2); ctx.lineTo(W / 2 + 60 * dpr, H / 2); ctx.stroke(); ctx.setLineDash([]);
      ctx.strokeStyle = token("text"); ctx.lineWidth = 2.5 * dpr; ctx.beginPath(); ctx.moveTo(ox, oy); ctx.lineTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      ctx.fillStyle = token("gold"); ctx.fillRect(ox - 8 * dpr, oy - 3 * dpr, 16 * dpr, 6 * dpr);
      ctx.fillStyle = rgba(pal(0.15)); ctx.beginPath(); ctx.arc(x1, y1, 7 * dpr, 0, 7); ctx.fill();
      ctx.fillStyle = rgba(pal(0.85)); ctx.beginPath(); ctx.arc(x2, y2, 7 * dpr, 0, 7); ctx.fill();
    }
  });
  void PendulumRenderer; void addPositions;
  return () => { off(); chErr.destroy(); };
}
