// Playground: the main simulation lab with the Chaos Time Machine.

import { api, download } from "../api.js";
import { setSound, setVolume, sonify } from "../audio.js";
import { LineChart } from "../charts.js";
import { Timeline, applyPreset, configControls, eventColor, presetPicker, visualControls } from "../controls.js";
import { token } from "../palettes.js";
import { perf, runSimulation, setPlaying, stepFrames, jumpTo } from "../sim.js";
import { Stage } from "../stage.js";
import { bus, clock, cloneDeep, encodeShare, lerpAt, setConfig, setPrefs, state } from "../state.js";
import { ICONS, btn, check, fmt, fmtSig, h, panel, section, select, slider, toast } from "../ui.js";
import { saveExperimentDialog } from "./experiments.js";

export const meta = { id: "playground", title: "Playground", subtitle: "Real-time double pendulum laboratory", key: "1" };

export function mount(root) {
  const cleanups = [];
  // ---------------- left controls
  const left = h("div", { class: "panel col scroll hide-in-saver" });
  const pp = presetPicker(applyPreset);
  const rand = btn("Randomize", async () => {
    const seed = Math.floor(Math.random() * 1e6);
    try {
      const r = await api.post("/api/random", { seed, config: state.config });
      state.activePreset = null;
      bus.emit("preset", null);
      setConfig(r.config);
      toast(`Random experiment, seed ${seed} (reproducible)`, "ok");
    } catch (e) { toast(e.message, "err"); }
  }, { cls: "sm", icon: ICONS.dice, tip: "Valid random parameters from a saved seed" });
  const cc = configControls({ open: ["initial", "physical"] });
  const vc = visualControls({ open: ["palette"] });
  const vol = slider({ label: "Volume", min: 0, max: 1, step: 0.01, value: state.prefs.volume, onInput: (v) => { setPrefs({ volume: v }); setVolume(v); } });
  const sound = section("Sonification", false,
    check("Enable sound", state.prefs.sound, (on) => { setPrefs({ sound: on }); setSound(on); }),
    vol,
    h("div", { class: "faint", style: { fontSize: "11.5px" } }, "An artistic mapping: |ω₂| → pitch, |v₂| → volume, kinetic energy → timbre, x₂ → stereo, rotations → clicks. Real pendulums do not make these sounds."));
  left.append(h("div", { class: "panel-body", style: { display: "grid", gap: "8px" } }, pp, h("div", { class: "btn-row" }, rand,
    btn("Save", () => saveExperimentDialog(), { cls: "sm", icon: ICONS.save, tip: "Save to the Experiment Notebook" }),
    btn("Share", () => share(), { cls: "sm", icon: ICONS.share, tip: "Copy a link that encodes this configuration" }))), cc, vc, sound);
  cleanups.push(pp.unsub, cc.unsub);

  // ---------------- centre stage
  const centre = h("div", { class: "col stage-wrap" });
  const stage = new Stage(centre, {
    draggable: true,
    onDragEnd: (t1, t2) => {
      const c = cloneDeep(state.config);
      c.initial.theta1_deg = +t1.toFixed(2); c.initial.theta2_deg = +t2.toFixed(2);
      c.initial.omega1 = 0; c.initial.omega2 = 0;
      stage.r.override = null;
      setConfig(c);
      toast(`Initial angles set to θ₁ = ${t1.toFixed(1)}°, θ₂ = ${t2.toFixed(1)}° (at rest)`, "ok");
    },
  });
  stage.canDrag = () => !clock.playing;
  stage.redraw = () => stage.draw(clock.t, 0);

  const playBtn = btn("", () => setPlaying(!clock.playing), { cls: "icon", tip: "Play / pause (Space)", icon: ICONS.play });
  const revBtn = btn("", () => { clock.reverse = !clock.reverse; revBtn.classList.toggle("primary", clock.reverse); },
    { cls: "icon sm", tip: "Reverse playback of the recorded states (not a reverse-time integration)", icon: ICONS.rev });
  const timeEl = h("div", { class: "time" });
  const speedSel = select({ value: "1", options: [["0.1", "0.1×"], ["0.25", "0.25×"], ["0.5", "0.5×"], ["1", "1×"], ["2", "2×"], ["4", "4×"]],
    onChange: (v) => { clock.speed = +v; } });
  speedSel.input.setAttribute("aria-label", "Playback speed (physical seconds per real second)");
  speedSel.input.style.width = "auto";
  const tl = new Timeline(h("div"), { onSeek: (t) => { setPlaying(false); jumpTo(t); }, onRange: (r) => { state.range = r; rangeInfo.textContent = r ? `range ${fmt(r[0], 2)}–${fmt(r[1], 2)} s` : ""; } });
  const rangeInfo = h("span", { class: "faint mono", style: { fontSize: "11.5px" } });
  const transport = h("div", { class: "transport hide-in-saver" },
    btn("", () => stepFrames(-1), { cls: "icon sm", tip: "Step back one sample (←)", icon: ICONS.back }),
    playBtn,
    btn("", () => stepFrames(1), { cls: "icon sm", tip: "Step forward one sample (→)", icon: ICONS.step }),
    revBtn,
    btn("", () => { setPlaying(false); jumpTo(0); stage.r.resetEffects(); }, { cls: "icon sm", tip: "Reset to t = 0 (R)", icon: ICONS.reset }),
    speedSel.input, timeEl, tl.el,
    btn("", () => addBookmark(), { cls: "icon sm", tip: "Bookmark this moment (B)", icon: ICONS.bookmark }),
    btn("A", () => setMark("A"), { cls: "sm", tip: "Mark timestamp A for comparison" }),
    btn("B", () => setMark("B"), { cls: "sm", tip: "Mark timestamp B for comparison" }),
    rangeInfo);
  centre.append(transport);

  // ---------------- right inspector
  const right = h("div", { class: "col scroll inspector hide-in-saver" });
  const ro = h("div", { class: "readouts" });
  const R = {};
  const rows = [["t", "t"], ["θ₁", "th1"], ["θ₂", "th2"], ["ω₁", "w1"], ["ω₂", "w2"], ["α₁", "a1"], ["α₂", "a2"], ["T", "T"], ["V", "V"], ["E", "E"],
    ["ΔE", "err"], ["|v₂|", "v2"], ["L₀", "Lz"], ["flips", "rot"]];
  for (const [lab, k] of rows) { const v = h("span"); R[k] = v; ro.append(h("div", { class: "r" }, h("span", {}, lab), v)); }
  const energyBox = h("div");
  const errBox = h("div");
  const chE = new LineChart(energyBox, { title: "Energy (J)", compact: true, onClick: (t) => jumpTo(t) });
  const chErr = new LineChart(errBox, { title: "Energy error", compact: true, onClick: (t) => jumpTo(t) });
  const evList = h("ul", { class: "events" });
  const perfBox = h("div", { class: "readouts" });
  const P = {};
  for (const [lab, k] of [["render FPS", "fps"], ["integration", "rt"], ["RK4 steps/s", "sps"], ["samples", "n"], ["fn evals", "nfev"], ["request", "req"], ["trajectories", "traj"], ["JS heap", "mem"]]) {
    const v = h("span"); P[k] = v; perfBox.append(h("div", { class: "r" }, h("span", {}, lab), v));
  }
  const cmpBox = h("div", { class: "faint", style: { fontSize: "12px" } }, "Mark two timestamps with A and B to compare states.");
  const marks = { A: null, B: null };
  right.append(
    panel("State", ro),
    panel("Energy", h("div", {}, energyBox, errBox, h("div", { class: "faint", style: { fontSize: "11.5px" } }, "Click a chart to jump in time."))),
    panel("Events", evList, { actions: [h("span", { class: "faint", style: { fontSize: "11px" } }, "click to jump")] }),
    panel("Compare timestamps", cmpBox),
    panel("Performance", perfBox));

  const layout = h("div", { class: "layout-3" }, left, centre, right);
  root.classList.add("fill");
  root.append(layout);

  // ---------------- behaviour
  function setMark(k) {
    marks[k] = clock.t; tl.marks = { ...marks }; tl.draw(); renderCompare();
  }
  function stateAt(t) {
    const s = state.sim, fi = t / s.dt;
    return { th1: lerpAt(s.th1, fi), th2: lerpAt(s.th2, fi), w1: lerpAt(s.w1, fi), w2: lerpAt(s.w2, fi), E: lerpAt(s.E, fi), x2: lerpAt(s.x2, fi), y2: lerpAt(s.y2, fi) };
  }
  function renderCompare() {
    if (!state.sim || marks.A === null || marks.B === null) return;
    const a = stateAt(marks.A), b = stateAt(marks.B);
    const deg = (x) => (x * 180) / Math.PI;
    const wrap = (x) => ((x + Math.PI) % (2 * Math.PI) + 3 * Math.PI) % (2 * Math.PI) - Math.PI;
    cmpBox.innerHTML = "";
    cmpBox.append(h("table", { class: "data" },
      h("tr", {}, h("th", {}, ""), h("th", {}, `A ${fmt(marks.A, 2)} s`), h("th", {}, `B ${fmt(marks.B, 2)} s`), h("th", {}, "Δ")),
      ...[["θ₁ (deg)", deg(a.th1), deg(b.th1), deg(wrap(b.th1 - a.th1))], ["θ₂ (deg)", deg(a.th2), deg(b.th2), deg(wrap(b.th2 - a.th2))],
        ["ω₁ (rad/s)", a.w1, b.w1, b.w1 - a.w1], ["ω₂ (rad/s)", a.w2, b.w2, b.w2 - a.w2], ["E (J)", a.E, b.E, b.E - a.E],
        ["x₂ (m)", a.x2, b.x2, b.x2 - a.x2], ["y₂ (m)", a.y2, b.y2, b.y2 - a.y2]]
        .map(([l, x, y, d]) => h("tr", {}, h("td", {}, l), h("td", { class: "num" }, fmt(x, 3)), h("td", { class: "num" }, fmt(y, 3)), h("td", { class: "num" }, fmt(d, 3))))),
      h("div", { class: "faint", style: { marginTop: "6px", fontSize: "11.5px" } }, "Angle differences are wrapped to (−180°, 180°]."));
  }
  function addBookmark() {
    if (!state.sim) return;
    state.bookmarks.push({ t: clock.t, label: `Bookmark @ ${fmt(clock.t, 2)} s` });
    renderEvents(); tl.draw();
    toast(`Bookmarked t = ${fmt(clock.t, 2)} s`, "ok");
  }
  function share() {
    const url = encodeShare(state.config, state.visual);
    navigator.clipboard?.writeText(url).then(() => toast("Share link copied — it encodes the full configuration", "ok"), () => prompt("Share link", url));
  }

  function renderEvents() {
    const s = state.sim;
    evList.innerHTML = "";
    if (!s) return;
    const evs = [...(s.events || []), ...state.bookmarks.map((b) => ({ ...b, kind: "bookmark" }))].sort((a, b) => a.t - b.t);
    if (!evs.length) evList.append(h("li", { class: "faint" }, "No notable events."));
    for (const e of evs.slice(0, 300)) {
      evList.append(h("li", {}, h("button", { type: "button", onclick: () => { setPlaying(false); jumpTo(e.t); } },
        h("span", { class: "dot", style: { background: eventColor(e.kind) } }), h("span", { class: "mono" }, `${fmt(e.t, 2)} s`), e.label)));
    }
  }

  function onSim(s) {
    stage.r.setBodies([s]);
    stage.r.setGhost(state.ghost);
    const cE = [token("cyan"), token("pink"), token("text")];
    chE.set([{ x: s.t, y: s.T, color: cE[0], label: "T" }, { x: s.t, y: s.V, color: cE[1], label: "V" }, { x: s.t, y: s.E, color: cE[2], label: "E", width: 1.8 }]);
    chErr.set([{ x: s.t, y: s.err, color: token("green"), label: s.errKind }], { symmetric: true });
    renderEvents();
    tl.draw();
    state.bookmarks = state.bookmarks.filter((b) => b.t <= s.tEnd);
    P.rt.textContent = `${fmt(s.summary.runtime_s, 3)} s`;
    P.sps.textContent = s.stepsPerSecond ? fmtSig(s.stepsPerSecond, 3) : "adaptive";
    P.n.textContent = s.n;
    P.nfev.textContent = s.summary.nfev;
    P.req.textContent = `${Math.round(s.requestMs)} ms`;
    P.traj.textContent = "1";
    stage.badge.textContent = `${s.config.numerics.method.toUpperCase()} · max |ΔE| ${fmtSig(s.summary.max_abs_rel_energy_error, 2)} · flips ${s.rotations[0]}/${s.rotations[1]}`;
  }

  let hudTick = 0;
  function onFrame(t, dtWall) {
    const s = state.sim;
    if (!s) return;
    stage.draw(t, dtWall);
    sonify(t / s.dt, clock.playing);
    if (++hudTick % 3 !== 0 && clock.playing) return; // throttle DOM updates
    const fi = t / s.dt, L = (a) => lerpAt(a, fi);
    const deg = (x) => `${fmt((((((x + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) - Math.PI) * 180 / Math.PI, 2)}°`; // wrapped to (−180°, 180°]
    R.t.textContent = `${fmt(t, 3)} s`; R.th1.textContent = deg(L(s.th1)); R.th2.textContent = deg(L(s.th2));
    R.w1.textContent = `${fmt(L(s.w1), 3)} rad/s`; R.w2.textContent = `${fmt(L(s.w2), 3)} rad/s`;
    R.a1.textContent = `${fmt(L(s.a1), 2)} rad/s²`; R.a2.textContent = `${fmt(L(s.a2), 2)} rad/s²`;
    R.T.textContent = `${fmt(L(s.T), 4)} J`; R.V.textContent = `${fmt(L(s.V), 4)} J`; R.E.textContent = `${fmt(L(s.E), 6)} J`;
    R.err.textContent = fmtSig(L(s.err), 3); R.v2.textContent = `${fmt(L(s.speed2), 3)} m/s`;
    R.Lz.textContent = `${fmt(L(s.Lz), 3)}`;
    const wi = (a) => Math.floor((a + Math.PI) / (2 * Math.PI));
    R.rot.textContent = `${Math.abs(wi(L(s.th1)) - wi(s.th1[0]))} / ${Math.abs(wi(L(s.th2)) - wi(s.th2[0]))} (net)`;
    timeEl.textContent = `${fmt(t, 2)} / ${fmt(s.tEnd, 1)} s`;
    chE.setCursor(t); chErr.setCursor(t);
    tl.draw();
    if (state.visual.hud) {
      stage.hud.innerHTML = `<span class="k">t</span> <b>${fmt(t, 2)} s</b> <span class="k">×${clock.speed}${clock.reverse ? " ◀" : ""}</span><br>` +
        `<span class="k">θ₁</span> ${deg(L(s.th1))} <span class="k">θ₂</span> ${deg(L(s.th2))}<br>` +
        `<span class="k">E</span> ${fmt(L(s.E), 4)} J <span class="k">ΔE</span> ${fmtSig(L(s.err), 2)}<br>` +
        `<span class="k">${s.config.name}</span>`;
    }
    P.fps.textContent = fmt(perf.fps, 0);
    P.mem.textContent = performance.memory ? `${fmt(performance.memory.usedJSHeapSize / 1e6, 0)} MB` : "n/a";
  }

  cleanups.push(
    bus.on("sim", onSim),
    bus.on("frame", onFrame),
    bus.on("sim:loading", (on) => stage.setLoading(on)),
    bus.on("play", (p) => { playBtn.innerHTML = ""; playBtn.append(h("span", { html: p ? ICONS.pause : ICONS.play })); }),
    bus.on("cmd:screenshot", () => stage.screenshot()),
    bus.on("cmd:fullscreen", () => stage.fullscreen()),
    bus.on("cmd:bookmark", () => addBookmark()),
    bus.on("cmd:csv", () => exportCSV()),
  );
  if (state.sim) onSim(state.sim); else runSimulation();

  async function exportCSV() {
    try {
      const body = { config: state.config };
      if (state.range) { body.t_start = state.range[0]; body.t_end = state.range[1]; }
      const res = await api.raw("POST", "/api/export/csv", body);
      download(await res.blob(), `pendulum-sim-${state.sim ? state.sim.digest : "run"}.csv`);
    } catch (e) { toast(e.message, "err"); }
  }

  return () => { cleanups.forEach((u) => u && u()); stage.destroy(); chE.destroy(); chErr.destroy(); };
}
