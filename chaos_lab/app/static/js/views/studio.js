// Chaos Studio: generative-art engine on top of real trajectories.

import { api, download, runJob } from "../api.js";
import { visualControls } from "../controls.js";
import { isLight, paletteStops, rgba, sampler } from "../palettes.js";
import { PendulumRenderer } from "../renderer.js";
import { runSimulation, setPlaying } from "../sim.js";
import { Stage } from "../stage.js";
import { bus, clock, setConfig, setVisual, state } from "../state.js";
import { btn, check, fmt, h, panel, progressBar, select, slider, toast } from "../ui.js";

export const meta = { id: "studio" };

export const ART_SIZES = [
  ["1920x1080", "1080p 16:9"], ["2560x1440", "1440p 16:9"], ["3840x2160", "4K 16:9"], ["2048x2048", "Square 2048"],
  ["3440x1440", "Ultrawide 21:9"], ["1170x2532", "Phone wallpaper 9:19.5"], ["1080x1920", "Vertical 9:16"],
];

export function mount(root) {
  const cleanups = [];
  const vc = visualControls({ full: true, open: ["palette", "particles", "camera"] });

  // --- art generator
  const objectives = [["complexity", "High visual complexity"], ["coverage", "Maximum trail coverage"], ["symmetry", "Symmetrical-looking"],
    ["dense", "Dense swirling motion"], ["loops", "Multiple loops"], ["sparse", "Sparse elegant patterns"], ["exposure", "Rich long exposure"]];
  const obj = select({ label: "Aesthetic objective", value: "complexity", options: objectives });
  const nCand = slider({ label: "Candidates", min: 8, max: 400, step: 1, value: 96, digits: 0 });
  const seed = slider({ label: "Seed", min: 0, max: 9999, step: 1, value: 1, digits: 0 });
  const dur = slider({ label: "Duration", unit: "s", min: 5, max: 60, step: 1, value: 30, digits: 0 });
  let randPhys = false;
  const prog = progressBar();
  const cands = h("div", { class: "grid-auto", style: { gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" } });
  let job = null;
  const runBtn = btn("Generate candidates", () => generate(), { cls: "primary" });
  const cancelBtn = btn("Cancel", () => job && job.cancel(), { cls: "sm", disabled: true });
  const gen = panel("Chaos Art Generator", h("div", { style: { display: "grid", gap: "10px" } },
    obj, nCand, seed, dur, check("Randomize m₂ and L₂ too", false, (v) => { randPhys = v; }),
    h("div", { class: "btn-row" }, runBtn, cancelBtn), prog,
    h("div", { class: "faint", style: { fontSize: "11.5px" } },
      "Ranks random starts with explicit heuristics computed from the lower mass’s path: grid coverage of the reachable disc, mirror symmetry, total turning (loops) and angular speed about the pivot. Beauty can’t be measured objectively, so you choose.")));

  async function generate() {
    runBtn.disabled = true; cancelBtn.disabled = false; prog.set(0);
    cands.innerHTML = "";
    job = runJob("art", { objective: obj.get(), n_candidates: nCand.get(), seed: seed.get(), t_max: dur.get(), top: 12, randomize_physics: randPhys, config: state.config },
      { onProgress: (f) => prog.set(f) });
    try {
      const r = await job.promise;
      for (const c of r.candidates) cands.append(candidateCard(c));
      toast(`${r.candidates.length} candidates ranked by “${obj.get()}”`, "ok");
    } catch (e) { if (e.message !== "cancelled") toast(e.message, "err"); }
    runBtn.disabled = false; cancelBtn.disabled = true;
  }

  function candidateCard(c) {
    const cv = h("canvas", { width: 300, height: 300, class: "thumb", style: { aspectRatio: "1" } });
    const ctx = cv.getContext("2d");
    const light = isLight();
    ctx.fillStyle = light ? "#fff" : "#000"; ctx.fillRect(0, 0, 300, 300);
    const R = c.config.physical.L1 + c.config.physical.L2;
    const pal = sampler(paletteStops(state.visual.palette, null, light));
    ctx.globalCompositeOperation = light ? "source-over" : "lighter"; ctx.lineWidth = 1;
    const n = c.x2.length;
    for (let i = 1; i < n; i++) {
      ctx.strokeStyle = rgba(pal(i / n), 0.55);
      ctx.beginPath();
      ctx.moveTo(150 + (c.x2[i - 1] / R) * 140, 150 - (c.y2[i - 1] / R) * 140);
      ctx.lineTo(150 + (c.x2[i] / R) * 140, 150 - (c.y2[i] / R) * 140);
      ctx.stroke();
    }
    const m = c.metrics;
    return h("article", { class: "card" }, cv, h("div", { class: "card-body" },
      h("div", { class: "mono", style: { fontSize: "11px" } }, `score ${fmt(c.score, 3)}`),
      h("div", { class: "faint", style: { fontSize: "11px" } }, `cov ${fmt(m.coverage, 2)} · sym ${fmt(m.symmetry, 2)} · loops ${fmt(m.loops, 0)}`),
      h("div", { class: "faint mono", style: { fontSize: "11px" } }, `${fmt(c.config.initial.theta1_deg, 1)}° / ${fmt(c.config.initial.theta2_deg, 1)}°`),
      btn("Use", () => { setConfig({ ...c.config, name: `Art: ${obj.get()} #${seed.get()}` }); setVisual({ trail: "exposure" }); setPlaying(true); }, { cls: "sm primary" })));
  }

  // --- artwork export
  const size = select({ label: "Resolution", value: "3840x2160", options: ART_SIZES });
  const artTrail = select({ label: "Style", value: "exposure", options: [["exposure", "Long exposure (whole run)"], ["current", "Current trail settings at time T"]] });
  const tEnd = slider({ label: "Paint until T", unit: "s", min: 1, max: 120, step: 0.5, value: state.config.numerics.t_max, digits: 1 });
  let transparent = false, withPendulum = false;
  const artProg = progressBar();
  const exportPanel = panel("High-resolution artwork", h("div", { style: { display: "grid", gap: "10px" } },
    size, artTrail, tEnd,
    check("Transparent background (PNG)", false, (v) => { transparent = v; }),
    check("Include pendulum", false, (v) => { withPendulum = v; }),
    h("div", { class: "btn-row" },
      btn("PNG", () => renderArt("png"), { cls: "primary sm" }),
      btn("Save to gallery", () => renderArt("gallery"), { cls: "sm" }),
      btn("SVG (vector)", () => renderSVG(), { cls: "sm", tip: "True vector paths of the computed trajectory" })),
    artProg,
    h("div", { class: "faint", style: { fontSize: "11.5px" } }, "Artwork is painted from the stored samples of the current simulation. The exact configuration is attached in the gallery so every image can be reproduced.")));

  function renderCanvas() {
    const s = state.sim;
    if (!s) throw new Error("no simulation");
    const [W, H] = size.get().split("x").map(Number);
    const c = document.createElement("canvas");
    c.width = W; c.height = H;
    const r = new PendulumRenderer(c, { fixedSize: [W, H] });
    const v = { ...state.visual, hud: false, particles: "none", camera: "static", zoom: state.visual.zoom || 1 };
    if (artTrail.get() === "exposure") v.trail = "exposure";
    v.background = transparent ? "transparent" : (v.background === "theme" ? (isLight() ? "white" : "black") : v.background);
    v.rods = withPendulum; v.showPivot = withPendulum;
    if (!withPendulum) v.massSize = 0.0001;
    v.trailWidth = (v.trailWidth || 2) * Math.max(1, Math.min(W, H) / 1080);
    r.setVisual(v);
    r.setBodies([s]);
    r.dpr = 1;
    const T = Math.min(s.tEnd, tEnd.get());
    r.draw(T, 0);
    return { c, T };
  }

  async function renderArt(mode) {
    try {
      artProg.set(0.2);
      await new Promise((res) => setTimeout(res, 20));
      const { c, T } = renderCanvas();
      artProg.set(0.8);
      const blob = await new Promise((res) => c.toBlob(res, "image/png"));
      if (mode === "png") download(blob, `chaos-art-${state.sim.digest}-${c.width}x${c.height}.png`);
      else {
        const b64 = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob); });
        await api.post("/api/gallery", { png: b64, config: state.config, visual: state.visual, width: c.width, height: c.height, t_end: T, title: state.config.name });
        toast("Saved to gallery with its exact configuration", "ok");
      }
      artProg.set(1);
    } catch (e) { toast(e.message, "err"); artProg.set(0); }
  }

  function renderSVG() {
    const s = state.sim;
    if (!s) return;
    const [W, H] = size.get().split("x").map(Number);
    const R = s.p.L1 + s.p.L2, sc = (Math.min(W, H) / (2 * R * 1.14)) * (state.visual.zoom || 1);
    const lightArt = state.visual.background === "white" || (state.visual.background !== "black" && isLight());
    const pal = sampler(paletteStops(state.visual.palette, null, lightArt));
    const T = Math.min(s.tEnd, tEnd.get());
    const iEnd = Math.floor(T / s.dt);
    const step = Math.max(1, Math.floor(iEnd / 12000));
    // group segments into 48 colour buckets → one <path> per colour
    const buckets = Array.from({ length: 48 }, () => []);
    let prev = null;
    for (let i = 0; i <= iEnd; i += step) {
      const x = (W / 2 + s.x2[i] * sc).toFixed(1), y = (H / 2 - s.y2[i] * sc).toFixed(1);
      if (prev) buckets[Math.min(47, Math.floor((i / iEnd) * 48))].push(`M${prev}L${x} ${y}`);
      prev = `${x} ${y}`;
    }
    const w = ((state.visual.trailWidth || 2) * Math.max(1, Math.min(W, H) / 1080)).toFixed(2);
    const paths = buckets.map((b, k) => b.length ? `<path d="${b.join("")}" stroke="${rgba(pal(k / 47), 0.8)}"/>` : "").join("\n");
    const bg = transparent ? "" : `<rect width="100%" height="100%" fill="${lightArt ? "#ffffff" : "#000000"}"/>`;
    const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
<!-- Chaos Lab Ultra · config digest ${s.digest} · lower-mass trajectory 0–${T.toFixed(2)} s -->
<metadata>${JSON.stringify(state.config).replace(/</g, "&lt;")}</metadata>
${bg}
<g fill="none" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round">
${paths}
</g>
</svg>`;
    download(new Blob([svg], { type: "image/svg+xml" }), `chaos-art-${s.digest}.svg`);
  }

  // --- stage
  const centre = h("div", { class: "col stage-wrap" });
  const stage = new Stage(centre, { draggable: false, hud: false });
  stage.redraw = () => stage.draw(clock.t, 0);
  const playBtn = btn("Play / pause", () => setPlaying(!clock.playing), { cls: "sm" });
  centre.append(h("div", { class: "transport" }, playBtn, btn("Restart", () => { clock.set(0); stage.r.resetEffects(); }, { cls: "sm" }),
    btn("Screensaver", () => bus.emit("cmd:saver"), { cls: "sm", tip: "Fullscreen art loop (Esc to exit)" })));
  centre.append(panel("Candidates", cands));

  const left = h("div", { class: "panel col scroll" }, vc);
  const right = h("div", { class: "col scroll" }, gen, exportPanel);
  root.classList.add("fill");
  root.append(h("div", { class: "layout-3" }, left, centre, right));

  cleanups.push(
    bus.on("sim", (s) => { stage.r.setBodies([s]); tEnd.set(s.tEnd); }),
    bus.on("frame", (t, dt) => state.sim && stage.draw(t, dt)),
    bus.on("sim:loading", (on) => stage.setLoading(on)),
    bus.on("cmd:screenshot", () => stage.screenshot("chaos-studio")),
    bus.on("cmd:fullscreen", () => stage.fullscreen()),
  );
  if (state.sim) stage.r.setBodies([state.sim]); else runSimulation();
  return () => { cleanups.forEach((u) => u()); stage.destroy(); if (job) job.cancel(); };
}
