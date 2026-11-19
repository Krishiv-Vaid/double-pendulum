// Fractal Universe Explorer: initial-condition maps with progressive refinement.

import { api, decodeF32, download, runJob } from "../api.js";
import { Heatmap } from "../charts.js";
import { nanRGB, token } from "../palettes.js";
import { cloneDeep, setConfig, state } from "../state.js";
import { btn, check, fmt, fmtSig, h, panel, progressBar, section, select, slider, toast } from "../ui.js";

export const meta = { id: "fractal" };

const OBS = {
  first_flip: { label: "First-flip time", unit: "s", nan: "no flip within T (or energetically impossible)", cmap: "auto", log: true,
    def: "Time until either arm first passes over the top (unwrapped angle crosses ±π). Background-coloured pixels: no flip before T." },
  rotations: { label: "Rotation count", unit: "flips", nan: "—", cmap: "auto", log: false, def: "Total over-the-top crossings of both arms during T." },
  max_omega: { label: "Max angular velocity", unit: "rad/s", nan: "—", cmap: "auto", log: false, def: "max over [0,T] of max(|ω₁|, |ω₂|)." },
  sensitivity: { label: "Finite-time sensitivity", unit: "1/s", nan: "—", cmap: "auto", log: false,
    def: "ln(d(T)/d₀)/T between the pixel and a twin displaced by d₀ in θ₁ (wrapped dimensionless norm). Saturates once separations become O(1): read it as an index, not a Lyapunov exponent." },
  energy: { label: "Initial energy", unit: "J", nan: "—", cmap: "auto", log: false, def: "Exact total energy of the initial condition (no integration)." },
};

let BOOKMARKS_KEY = "cl.fractalBookmarks";

export function mount(root) {
  const S = {
    obs: select({ label: "Observable", value: "first_flip", options: Object.entries(OBS).map(([k, o]) => [k, o.label]), onChange: () => { cmap.set(OBS[S.obs.get()].cmap); logScale.set(OBS[S.obs.get()].log); defBox.textContent = OBS[S.obs.get()].def; } }),
    res: slider({ label: "Resolution", unit: "px", min: 40, max: 800, step: 10, value: 240, digits: 0 }),
    tmax: slider({ label: "Integration time T", unit: "s", min: 1, max: 60, step: 0.5, value: 10, digits: 1 }),
    dt: slider({ label: "RK4 step", unit: "s", min: 0.001, max: 0.02, log: true, value: 0.005 }),
    w1: slider({ label: "ω₁(0) for all pixels", unit: "rad/s", min: -10, max: 10, step: 0.1, value: 0, digits: 2 }),
    w2: slider({ label: "ω₂(0) for all pixels", unit: "rad/s", min: -10, max: 10, step: 0.1, value: 0, digits: 2 }),
  };
  let progressive = true;
  const cmap = select({ label: "Greyscale ramp", value: "auto", options: [["auto", "Theme (fg₄ → fg)"], ["gray-full", "Black → white"], ["gray-light", "White → black"]], onChange: () => repaint() });
  const logScale = check("Log colour scale", true, () => repaint());
  logScale.set(true);
  const inv = check("Invert colormap", false, () => repaint());
  const clip = slider({ label: "Percentile clip", min: 0, max: 0.2, step: 0.005, value: 0.01, digits: 3, onChange: () => repaint() });
  const defBox = h("div", { class: "note", style: { fontSize: "12px" } }, OBS.first_flip.def);
  const prog = progressBar();
  const status = h("div", { class: "faint mono", style: { fontSize: "11.5px" } });
  const runBtn = btn("Compute view", () => compute(), { cls: "primary" });
  const cancelBtn = btn("Cancel", () => job && job.cancel(), { cls: "sm", disabled: true });
  const histBox = h("div", { class: "btn-row" });
  const bmBox = h("div", { style: { display: "grid", gap: "4px" } });
  const pick = h("div", { class: "faint", style: { fontSize: "12px" } }, "Click a pixel to inspect it.");

  const left = h("div", { class: "panel col scroll" },
    h("div", { class: "panel-body", style: { display: "grid", gap: "10px" } },
      h("div", { class: "btn-row" }, runBtn, cancelBtn), prog, status,
      check("Progressive refinement (¼-res preview first)", true, (v) => { progressive = v; })),
    section("Map", true, S.obs, defBox, S.res, S.tmax, S.dt, S.w1, S.w2),
    section("Colour", true, cmap, logScale, inv, clip),
    section("Zoom movie", false, ...movieControls()),
    h("div", { class: "panel-body faint", style: { fontSize: "11.5px" } },
      "Drag to pan, scroll to zoom, Shift-drag to box-zoom; each view is recomputed, never just enlarged. Physical parameters come from the shared configuration. Intricate boundaries suggest sensitive dependence, but a picture is not a proof that a set is fractal."));

  const mapBox = h("div", { style: { height: "100%", minHeight: "460px" } });
  const hm = new Heatmap(mapBox, {
    xlabel: "θ₁(0) [deg]", ylabel: "θ₂(0) [deg]", xname: "θ₁", yname: "θ₂", square: true, cls: "",
    onPick: (x, y, v) => showPick(x, y, v),
    onBox: (xr, yr) => { pushView([xr, yr]); compute(); },
    onPan: (dx, dy) => { const [xr, yr] = view; pushView([[xr[0] + dx, xr[1] + dx], [yr[0] + dy, yr[1] + dy]], true); compute(); },
    onZoom: (x, y, f) => { const [xr, yr] = view; pushView([[x + (xr[0] - x) * f, x + (xr[1] - x) * f], [y + (yr[0] - y) * f, y + (yr[1] - y) * f]], true); debounceCompute(); },
  });
  hm.el.style.height = "100%";
  const centre = h("div", { class: "col" }, h("div", { class: "panel", style: { flex: 1, padding: "10px", minHeight: "480px" } }, mapBox));
  const right = h("div", { class: "col scroll inspector" },
    panel("Selected pixel", pick),
    panel("Zoom history", histBox),
    panel("Bookmarks", h("div", { style: { display: "grid", gap: "8px" } }, btn("Bookmark this view", () => addBookmark(), { cls: "sm" }), bmBox)),
    panel("Export", h("div", { class: "btn-row" },
      btn("PNG (map pixels)", () => exportPNG(1), { cls: "sm" }), btn("PNG ×4", () => exportPNG(4), { cls: "sm" }),
      btn("PNG with axes", () => hm.canvas.toBlob((b) => download(b, "chaos-map-figure.png")), { cls: "sm" }),
      btn("CSV", () => exportCSV(), { cls: "sm" }))));
  root.classList.add("fill");
  root.append(h("div", { class: "layout-3" }, left, centre, right));

  let view = [[-180, 180], [-180, 180]];
  const history = [view];
  let job = null, last = null, timer = null;

  function pushView(v, replaceLast = false) {
    view = v.map((r) => [+r[0].toFixed(6), +r[1].toFixed(6)]);
    if (replaceLast && history.length > 1 && history[history.length - 1].pan) history[history.length - 1] = Object.assign(view, { pan: true });
    else history.push(replaceLast ? Object.assign(view, { pan: true }) : view);
    renderHistory();
  }
  function debounceCompute() { clearTimeout(timer); timer = setTimeout(compute, 350); }

  function renderHistory() {
    histBox.innerHTML = "";
    history.slice(-12).forEach((v, i, arr) => {
      const zoom = 360 / (v[0][1] - v[0][0]);
      const b = h("button", { class: `btn sm ${i === arr.length - 1 ? "primary" : ""}`, type: "button", "data-tip": `θ₁ ${fmt(v[0][0], 2)}…${fmt(v[0][1], 2)}°, θ₂ ${fmt(v[1][0], 2)}…${fmt(v[1][1], 2)}°` }, `${fmtSig(zoom, 3)}×`);
      b.addEventListener("click", () => { view = v; compute(); });
      histBox.append(b);
    });
  }

  function spec(nx, ny, xr = view[0], yr = view[1]) {
    return { config: state.config, observable: S.obs.get(), theta1_range: xr, theta2_range: yr, nx, ny, t_max: S.tmax.get(), dt: S.dt.get(), omega1: S.w1.get(), omega2: S.w2.get() };
  }

  async function compute() {
    if (job) job.cancel();
    const n = Math.round(S.res.get());
    runBtn.disabled = true; cancelBtn.disabled = false;
    const passes = progressive && n >= 120 ? [Math.round(n / 4), n] : [n];
    const t0 = performance.now();
    try {
      for (const res of passes) {
        status.textContent = `computing ${res}×${res} = ${res * res} initial conditions…`;
        prog.set(0);
        job = runJob("map", spec(res, res), {
          partial: true, interval: 300,
          onProgress: (f, info) => {
            prog.set(f);
            if (info.partial && info.partial.data) paint(decodeF32(info.partial.data), info.partial.nx, info.partial.ny);
          },
        });
        const r = await job.promise;
        last = { ...r, data: decodeF32(r.data) };
        paint(last.data, r.nx, r.ny);
        status.textContent = `${r.nx}×${r.ny} in ${fmt(r.runtime_s, 2)} s (server) · NaN ${fmt(100 * r.nan_fraction, 1)}% · cached by digest ${r.digest.slice(0, 8)}`;
      }
    } catch (e) { if (e.message !== "cancelled") toast(e.message, "err"); status.textContent = e.message; }
    runBtn.disabled = false; cancelBtn.disabled = true;
    void t0;
  }

  function paint(data, nx, ny) {
    const o = OBS[S.obs.get()];
    hm.set(data, nx, ny, view[0], view[1], { cmap: cmap.get(), log: logScale.querySelector("input").checked, invert: inv.querySelector("input").checked,
      clip: clip.get(), unit: `${o.label} [${o.unit}]${logScale.querySelector("input").checked ? " (log)" : ""}`, vname: o.label, nanLabel: o.nan,
      nanColor: nanRGB() });
  }
  function repaint() { if (last) paint(last.data, last.nx, last.ny); }

  function showPick(x, y, v) {
    const o = OBS[S.obs.get()];
    hm.overlay = [{ type: "cross", x, y, color: token("fg") }];
    hm.draw();
    pick.innerHTML = "";
    pick.append(h("dl", { class: "kv" },
      h("dt", {}, "θ₁(0)"), h("dd", {}, `${fmt(x, 3)}°`), h("dt", {}, "θ₂(0)"), h("dd", {}, `${fmt(y, 3)}°`),
      h("dt", {}, o.label), h("dd", {}, Number.isFinite(v) ? `${fmtSig(v, 4)} ${o.unit}` : o.nan)),
      h("div", { class: "btn-row", style: { marginTop: "8px" } },
        btn("Launch trajectory", () => {
          const c = cloneDeep(state.config);
          c.initial = { theta1_deg: +x.toFixed(3), theta2_deg: +y.toFixed(3), omega1: S.w1.get(), omega2: S.w2.get() };
          c.name = `Map pixel (${fmt(x, 1)}°, ${fmt(y, 1)}°)`;
          setConfig(c);
          location.hash = "#/playground";
        }, { cls: "sm primary" })));
  }

  function loadBookmarks() { try { return JSON.parse(localStorage.getItem(BOOKMARKS_KEY) || "[]"); } catch { return []; } }
  function renderBookmarks() {
    bmBox.innerHTML = "";
    const bms = loadBookmarks();
    if (!bms.length) bmBox.append(h("div", { class: "faint", style: { fontSize: "12px" } }, "No bookmarks yet."));
    bms.forEach((b, i) => bmBox.append(h("div", { class: "field-row" },
      h("button", { class: "btn ghost sm", type: "button", onclick: () => { S.obs.set(b.obs); view = b.view; pushView(b.view); compute(); } }, b.name),
      h("button", { class: "btn ghost sm", type: "button", "aria-label": "Delete bookmark", onclick: () => { const x = loadBookmarks(); x.splice(i, 1); localStorage.setItem(BOOKMARKS_KEY, JSON.stringify(x)); renderBookmarks(); } }, "×"))));
  }
  function addBookmark() {
    const name = prompt("Bookmark name", `${OBS[S.obs.get()].label} @ ${fmt((view[0][0] + view[0][1]) / 2, 1)}°, ${fmt((view[1][0] + view[1][1]) / 2, 1)}°`);
    if (!name) return;
    const x = loadBookmarks(); x.push({ name, view, obs: S.obs.get() });
    try { localStorage.setItem(BOOKMARKS_KEY, JSON.stringify(x)); } catch {}
    renderBookmarks();
  }

  function exportPNG(scale) {
    if (!last) return;
    hm.toPNG(scale).toBlob((b) => download(b, `chaos-map-${S.obs.get()}-${last.digest.slice(0, 8)}.png`));
  }
  function exportCSV() {
    if (!last) return;
    const xs = [], ys = [];
    for (let i = 0; i < last.nx; i++) xs.push(view[0][0] + ((i + 0.5) / last.nx) * (view[0][1] - view[0][0]));
    for (let j = 0; j < last.ny; j++) ys.push(view[1][0] + ((j + 0.5) / last.ny) * (view[1][1] - view[1][0]));
    const lines = [`# Double Pendulum Simulator map: ${S.obs.get()} [${OBS[S.obs.get()].unit}]`, `# spec: ${JSON.stringify(last.spec)}`, "theta1_deg,theta2_deg,value"];
    for (let j = 0; j < last.ny; j++) for (let i = 0; i < last.nx; i++) { const v = last.data[j * last.nx + i]; lines.push(`${xs[i].toFixed(6)},${ys[j].toFixed(6)},${Number.isFinite(v) ? v : ""}`); }
    download(new Blob([lines.join("\n")], { type: "text/csv" }), `chaos-map-${S.obs.get()}.csv`);
  }

  // --- zoom movie: recompute the map at every zoom level and encode on the server
  function movieControls() {
    const frames = slider({ label: "Frames", min: 4, max: 120, step: 1, value: 24, digits: 0 });
    const factor = slider({ label: "Total zoom", unit: "×", min: 2, max: 1000, log: true, value: 20 });
    const mres = slider({ label: "Frame resolution", unit: "px", min: 80, max: 400, step: 10, value: 180, digits: 0 });
    const fmtSel = select({ label: "Format", value: "gif", options: [["gif", "GIF"], ["mp4", "MP4"]] });
    const mprog = progressBar();
    let cancel = false;
    const go = btn("Render zoom movie", async () => {
      cancel = false; go.disabled = true;
      const [xr, yr] = view;
      const cx = (xr[0] + xr[1]) / 2, cy = (yr[0] + yr[1]) / 2, w0 = xr[1] - xr[0], h0 = yr[1] - yr[0];
      const N = frames.get(), F = factor.get(), res = Math.round(mres.get());
      const size = 640;
      try {
        const enc = await api.post("/api/encode/start", { format: fmtSel.get(), fps: 8, width: size, height: size, loop: true });
        for (let k = 0; k < N && !cancel; k++) {
          const z = Math.pow(F, k / Math.max(1, N - 1));
          const xrk = [cx - w0 / 2 / z, cx + w0 / 2 / z], yrk = [cy - h0 / 2 / z, cy + h0 / 2 / z];
          const j = runJob("map", spec(res, res, xrk, yrk));
          const r = await j.promise;
          const data = decodeF32(r.data);
          const cv = frameCanvas(data, r.nx, r.ny, xrk, yrk, z, size);
          const blob = await new Promise((rs) => cv.toBlob(rs, "image/png"));
          await fetch(`/api/encode/${enc.id}/frame`, { method: "POST", body: blob });
          mprog.set((k + 1) / N);
        }
        if (cancel) { await api.del(`/api/encode/${enc.id}`); toast("Zoom movie cancelled"); }
        else {
          const info = await api.post(`/api/encode/${enc.id}/finish`, {});
          const res2 = await fetch(`/api/encode/${enc.id}/file`);
          download(await res2.blob(), `fractal-zoom.${info.format}`);
          toast(`Zoom movie: ${info.frames} recomputed frames, ${fmt(info.bytes / 1e6, 2)} MB`, "ok");
        }
      } catch (e) { toast(e.message, "err"); }
      go.disabled = false;
    }, { cls: "sm primary" });
    const stop = btn("Cancel", () => { cancel = true; }, { cls: "sm" });
    return [frames, factor, mres, fmtSel, h("div", { class: "btn-row" }, go, stop), mprog,
      h("div", { class: "faint", style: { fontSize: "11.5px" } }, "Zooms toward the centre of the current view. Every frame is a new computation at its own zoom level.")];
  }

  function frameCanvas(data, nx, ny, xr, yr, z, size) {
    const tmp = document.createElement("div");
    tmp.style.cssText = `position:fixed;left:-9999px;width:${size}px;height:${size}px`;
    document.body.append(tmp);
    const off = new Heatmap(tmp, { square: true });
    off.set(data, nx, ny, xr, yr, { cmap: cmap.get() === "auto" ? "gray" : cmap.get(), log: logScale.querySelector("input").checked, invert: inv.querySelector("input").checked, clip: clip.get(), nanColor: [0, 0, 0] });
    const c = document.createElement("canvas");
    c.width = size; c.height = size;
    const ctx = c.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(off.img, 0, 0, size, size);
    ctx.fillStyle = "rgba(0,0,0,.75)"; ctx.fillRect(0, size - 26, size, 26);
    ctx.fillStyle = "#ffffff"; ctx.font = "13px ui-monospace, monospace";
    ctx.fillText(`${OBS[S.obs.get()].label} · zoom ${fmtSig(z, 3)}× · θ₁ ${fmt((xr[0] + xr[1]) / 2, 3)}°, θ₂ ${fmt((yr[0] + yr[1]) / 2, 3)}°`, 10, size - 9);
    off.destroy(); tmp.remove();
    return c;
  }

  renderHistory();
  renderBookmarks();
  compute();
  return () => { if (job) job.cancel(); clearTimeout(timer); hm.destroy(); };
}
