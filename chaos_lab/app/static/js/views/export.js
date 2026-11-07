// Export Studio: frame-exact video/GIF export, image sequences, data and sharing.

import { api, download } from "../api.js";
import { token } from "../palettes.js";
import { PendulumRenderer } from "../renderer.js";
import { runSimulation } from "../sim.js";
import { bus, encodeShare, lerpAt, state } from "../state.js";
import { btn, check, fmt, fmtSig, h, panel, progressBar, select, slider, textField, toast } from "../ui.js";

export const meta = { id: "export" };

export const VIDEO_PRESETS = {
  youtube: { label: "YouTube 16:9 · 1920×1080", w: 1920, h: 1080 },
  reels: { label: "TikTok / Reels 9:16 · 1080×1920", w: 1080, h: 1920 },
  square: { label: "Square 1:1 · 1080×1080", w: 1080, h: 1080 },
  ultrawide: { label: "Ultrawide 21:9 · 2560×1080", w: 2560, h: 1080 },
  science: { label: "Scientific presentation 16:9 (with energy panel)", w: 1920, h: 1080, graph: true },
  cinema4k: { label: "4K cinematic · 3840×2160", w: 3840, h: 2160 },
  gif: { label: "GIF · 640×640", w: 640, h: 640 },
  gifwide: { label: "GIF hero · 800×450", w: 800, h: 450 },
};

export function mount(root) {
  const fmtSel = select({ label: "Format", value: "gif", options: [["gif", "GIF (server encoder)"], ["mp4", "MP4 H.264 (server encoder)"], ["webm", "WebM (real-time browser capture)"], ["png-seq", "PNG sequence (.zip)"], ["png", "Single PNG frame"]], onChange: () => sync() });
  const preset = select({ label: "Preset", value: "gif", options: Object.entries(VIDEO_PRESETS).map(([k, p]) => [k, p.label]), onChange: () => sync() });
  const fps = slider({ label: "Frame rate", unit: "fps", min: 5, max: 60, step: 1, value: 30, digits: 0 });
  const scale = slider({ label: "Resolution scale", min: 0.25, max: 1, step: 0.05, value: 1, digits: 2, tip: "Multiply the preset size (useful for drafts)" });
  const t0 = slider({ label: "Start", unit: "s", min: 0, max: 120, step: 0.05, value: 0, digits: 2 });
  const t1 = slider({ label: "End", unit: "s", min: 0.1, max: 120, step: 0.05, value: 8, digits: 2 });
  const speed = slider({ label: "Physical seconds per video second", min: 0.05, max: 4, step: 0.05, value: 1, digits: 2, tip: "0.25 = 4× slow motion. Labels always show physical time." });
  const quality = slider({ label: "MP4 quality", min: 3, max: 10, step: 1, value: 8, digits: 0 });
  const title = textField("Title overlay", "");
  let opts = { params: true, timecode: true, graph: false, stamp: true };
  const overlays = h("div", { style: { display: "grid", gap: "6px" } },
    check("Parameter overlay", true, (v) => { opts.params = v; preview(); }),
    check("Timecode (physical time)", true, (v) => { opts.timecode = v; preview(); }),
    check("Energy graph inset", false, (v) => { opts.graph = v; preview(); }),
    check("Reproducibility stamp (config digest)", true, (v) => { opts.stamp = v; preview(); }));
  const prog = progressBar();
  const status = h("div", { class: "faint mono", style: { fontSize: "11.5px" } });
  const goBtn = btn("Export", () => run(), { cls: "primary" });
  const cancelBtn = btn("Cancel", () => { cancelled = true; }, { cls: "sm", disabled: true });
  const est = h("div", { class: "faint", style: { fontSize: "12px" } });
  const previewCanvas = h("canvas", { style: { width: "100%", height: "100%", objectFit: "contain", display: "block" } });
  const previewBox = h("div", { class: "stage", style: { minHeight: "420px", display: "grid", placeItems: "center" } }, previewCanvas);
  const scrub = h("input", { type: "range", min: 0, max: 1000, value: 0, "aria-label": "Preview time" });
  scrub.addEventListener("input", () => preview());

  root.append(h("div", { class: "layout-2 wide-left" },
    h("div", { class: "col scroll" },
      panel("Video & image export", h("div", { style: { display: "grid", gap: "10px" } }, fmtSel, preset, scale, fps, t0, t1, speed, quality, title, overlays,
        h("div", { class: "btn-row" }, goBtn, cancelBtn), prog, status, est,
        h("div", { class: "faint", style: { fontSize: "11.5px" } }, "GIF/MP4/PNG frames are rendered offline at exact physical-time steps, so the output never drops or duplicates frames regardless of browser speed. Visual style, trail and camera come from the Studio settings."))),
      panel("Data & sharing", h("div", { style: { display: "grid", gap: "8px" } },
        btn("CSV (all columns with units)", () => csv(), { cls: "sm" }),
        btn("Experiment bundle (.json)", () => bundle(), { cls: "sm" }),
        btn("Copy share link", () => share(), { cls: "sm" }),
        h("div", { class: "faint", style: { fontSize: "11.5px" } }, "The share link encodes the configuration and visual style in the URL fragment: no server or account needed. Bundles include a reproducibility summary.")))),
    h("div", { class: "col" }, previewBox, h("div", { class: "transport" }, h("span", { class: "faint" }, "Preview"), scrub))));

  let cancelled = false;
  function size() {
    const p = VIDEO_PRESETS[preset.get()];
    let w = Math.round(p.w * scale.get()), hh = Math.round(p.h * scale.get());
    if (fmtSel.get() === "gif" && w * hh > 1280 * 1280) { const k = Math.sqrt((1280 * 1280) / (w * hh)); w = Math.floor(w * k); hh = Math.floor(hh * k); }
    return [w - (w % 2), hh - (hh % 2), !!p.graph];
  }
  function sync() {
    const s = state.sim;
    if (s) {
      t1.set(Math.min(s.tEnd, Math.max(t1.get(), 0.1)));
      if (state.range) { t0.set(state.range[0]); t1.set(state.range[1]); }
    }
    if (fmtSel.get() === "gif" && !preset.get().startsWith("gif")) preset.set("gif");
    if (fmtSel.get() === "mp4" && preset.get().startsWith("gif")) preset.set("youtube");
    const [w, hh] = size();
    const n = Math.ceil(((t1.get() - t0.get()) / speed.get()) * fps.get());
    est.textContent = `${w}×${hh}, ${n} frames, ${fmt(n / fps.get(), 1)} s of video covering ${fmt(t1.get() - t0.get(), 2)} s of physical time.`;
    preview();
  }
  [fps, scale, t0, t1, speed].forEach((s) => s.addEventListener("change", sync));

  // --- frame composition (shared by preview and export)
  function makeComposer(W, H, graph) {
    const out = document.createElement("canvas");
    out.width = W; out.height = H;
    const ctx = out.getContext("2d");
    const pw = graph ? Math.round(W * 0.62) : W;
    const sc = document.createElement("canvas");
    sc.width = pw; sc.height = H;
    const r = new PendulumRenderer(sc, { fixedSize: [pw, H] });
    const v = { ...state.visual, hud: false, background: state.visual.background === "theme" || state.visual.background === "transparent" ? "space" : state.visual.background };
    v.trailWidth = (v.trailWidth || 2) * Math.max(1, Math.min(pw, H) / 720);
    r.setVisual(v);
    r.setBodies([state.sim]);
    r.reducedMotion = false;
    const s = state.sim;
    const u = Math.min(W, H) / 1080;
    return {
      out, r,
      frame(t, dtFrame) {
        r.dpr = Math.max(1, Math.min(pw, H) / 700);
        r.draw(t, dtFrame);
        ctx.fillStyle = "#070910"; ctx.fillRect(0, 0, W, H);
        ctx.drawImage(sc, 0, 0);
        const fi = t / s.dt;
        ctx.textBaseline = "top";
        if (title.input.value) { ctx.fillStyle = "#f4f7ff"; ctx.font = `700 ${Math.round(46 * u)}px Inter, system-ui, -apple-system, sans-serif`; ctx.fillText(title.input.value, 40 * u, 36 * u); }
        if (opts.timecode) { ctx.fillStyle = "#f4f7ff"; ctx.font = `${Math.round(28 * u)}px ui-monospace, Menlo, monospace`; ctx.fillText(`t = ${t.toFixed(2)} s${speed.get() !== 1 ? `  (${fmtSig(1 / speed.get(), 3)}× slow-mo)` : ""}`, 40 * u, (title.input.value ? 96 : 36) * u); }
        if (opts.params) {
          const c = s.config, p = c.physical;
          const lines = [`θ₁(0)=${c.initial.theta1_deg}°  θ₂(0)=${c.initial.theta2_deg}°`, `m=${p.m1}/${p.m2} kg  L=${p.L1}/${p.L2} m  g=${p.g} m/s²`, `${c.numerics.method.toUpperCase()}  E=${lerpAt(s.E, fi).toFixed(4)} J`];
          ctx.fillStyle = "rgba(149,163,186,0.95)"; ctx.font = `${Math.round(22 * u)}px ui-monospace, Menlo, monospace`;
          lines.forEach((l, i) => ctx.fillText(l, 40 * u, pw === W ? H - (40 + (lines.length - i) * 30) * u : H - (40 + (lines.length - i) * 30) * u));
        }
        if (opts.stamp) { ctx.fillStyle = "rgba(100,113,138,0.9)"; ctx.font = `${Math.round(16 * u)}px ui-monospace, monospace`; ctx.textAlign = "right"; ctx.fillText(`Chaos Lab Ultra · ${s.digest}`, pw - 24 * u, H - 34 * u); ctx.textAlign = "left"; }
        if (graph || opts.graph) drawGraph(ctx, graph ? [pw, 0, W - pw, H] : [W - 0.36 * W - 24 * u, 24 * u, 0.36 * W, 0.26 * H], t, u);
        return out;
      },
    };
  }

  function drawGraph(ctx, [x, y, w, hh], t, u) {
    const s = state.sim;
    ctx.save();
    ctx.fillStyle = "rgba(16,21,34,0.92)"; ctx.fillRect(x, y, w, hh);
    ctx.strokeStyle = "#222b40"; ctx.strokeRect(x + 0.5, y + 0.5, w - 1, hh - 1);
    const pad = 28 * u, half = (hh - 3 * pad) / 2;
    const plot = (oy, arrs, cols, label, sym) => {
      let lo = Infinity, hi = -Infinity;
      for (const a of arrs) for (let i = 0; i < a.length; i += 4) { if (a[i] < lo) lo = a[i]; if (a[i] > hi) hi = a[i]; }
      if (sym) { const m = Math.max(Math.abs(lo), Math.abs(hi)) || 1; lo = -m; hi = m; }
      if (hi === lo) { hi += 1; lo -= 1; }
      const X = (tt) => x + pad + (tt / s.tEnd) * (w - 2 * pad), Y = (v) => oy + half - ((v - lo) / (hi - lo)) * half;
      ctx.fillStyle = "#95a3ba"; ctx.font = `${Math.round(18 * u)}px Inter, system-ui, -apple-system, sans-serif`; ctx.fillText(label, x + pad, oy - 22 * u);
      arrs.forEach((a, k) => {
        ctx.strokeStyle = cols[k]; ctx.lineWidth = 2 * u; ctx.beginPath();
        const step = Math.max(1, Math.floor(a.length / 1500));
        for (let i = 0; i < a.length; i += step) { const px = X(s.t[i]), py = Y(a[i]); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }
        ctx.stroke();
      });
      ctx.strokeStyle = "#f4f7ff"; ctx.globalAlpha = 0.7; ctx.beginPath(); ctx.moveTo(X(t), oy); ctx.lineTo(X(t), oy + half); ctx.stroke(); ctx.globalAlpha = 1;
    };
    ctx.textBaseline = "alphabetic";
    plot(y + pad + 10 * u, [s.T, s.V, s.E], ["#00e5ff", "#ff3cac", "#f4f7ff"], "Energy: T (cyan), V (pink), E (white) [J]");
    plot(y + 2 * pad + half + 10 * u, [s.err], ["#39ff88"], `Energy error ${s.errKind}`, true);
    ctx.restore();
  }

  function preview() {
    const s = state.sim;
    if (!s) return;
    const [W, H, graph] = size();
    const k = Math.min(1, 900 / Math.max(W, H));
    const comp = makeComposer(Math.round(W * k), Math.round(H * k), graph);
    const t = t0.get() + (scrub.value / 1000) * (t1.get() - t0.get());
    // pre-roll so trails are populated in the preview
    const pre = Math.max(0, t - (state.visual.trailSeconds || 3));
    comp.r.draw(pre, 0);
    const c = comp.frame(t, 1 / 30);
    previewCanvas.width = c.width; previewCanvas.height = c.height;
    previewCanvas.getContext("2d").drawImage(c, 0, 0);
  }

  async function run() {
    const s = state.sim;
    if (!s) return toast("No simulation yet", "err");
    const fmtv = fmtSel.get();
    const [W, H, graph] = size();
    const f = fps.get(), a = t0.get(), b = Math.min(t1.get(), s.tEnd);
    const n = Math.max(1, Math.ceil(((b - a) / speed.get()) * f));
    if (fmtv === "png") {
      const comp = makeComposer(W, H, graph);
      comp.r.draw(Math.max(0, a - (state.visual.trailSeconds || 3)), 0);
      comp.frame(a, 1 / f).toBlob((bl) => download(bl, `chaos-lab-frame-${s.digest}-${a.toFixed(2)}s.png`));
      return;
    }
    cancelled = false; goBtn.disabled = true; cancelBtn.disabled = false; prog.set(0);
    const tStart = performance.now();
    try {
      if (fmtv === "webm") await recordWebM(W, H, graph, a, b);
      else {
        const comp = makeComposer(W, H, graph);
        if (a > 0) comp.r.draw(Math.max(0, a - (state.visual.trailSeconds || 3)), 0); // pre-roll trails
        let enc = null;
        const zipFiles = [];
        if (fmtv === "gif" || fmtv === "mp4") enc = await api.post("/api/encode/start", { format: fmtv, fps: f, width: W, height: H, quality: quality.get(), loop: true });
        for (let k = 0; k < n; k++) {
          if (cancelled) break;
          const t = a + (k * speed.get()) / f; // physical time of frame k
          const c = comp.frame(Math.min(t, b), speed.get() / f);
          const mime = fmtv === "mp4" ? "image/jpeg" : "image/png";
          const blob = await new Promise((res) => c.toBlob(res, mime, 0.94));
          if (enc) { const r = await fetch(`/api/encode/${enc.id}/frame`, { method: "POST", body: blob }); if (!r.ok) throw new Error((await r.json()).error); }
          else zipFiles.push([`frame_${String(k).padStart(5, "0")}.png`, new Uint8Array(await blob.arrayBuffer())]);
          prog.set((k + 1) / n);
          if (k % 5 === 0) status.textContent = `frame ${k + 1}/${n} · t = ${t.toFixed(2)} s · ${fmt((k + 1) / ((performance.now() - tStart) / 1000), 1)} frames/s`;
        }
        if (cancelled) { if (enc) await api.del(`/api/encode/${enc.id}`); status.textContent = "cancelled"; }
        else if (enc) {
          status.textContent = "encoding…";
          const info = await api.post(`/api/encode/${enc.id}/finish`, {});
          const file = await fetch(`/api/encode/${enc.id}/file`);
          download(await file.blob(), `chaos-lab-${s.digest}.${fmtv}`);
          status.textContent = `${info.frames} frames · ${info.width}×${info.height} · ${fmt(info.bytes / 1e6, 2)} MB · ${fmt((performance.now() - tStart) / 1000, 1)} s`;
          toast(`${fmtv.toUpperCase()} exported`, "ok");
        } else {
          zipFiles.push(["config.json", new TextEncoder().encode(JSON.stringify(bundleData(), null, 2))]);
          download(makeZip(zipFiles), `chaos-lab-frames-${s.digest}.zip`);
          status.textContent = `${n} PNG frames zipped`;
        }
      }
    } catch (e) { toast(e.message, "err"); status.textContent = e.message; }
    goBtn.disabled = false; cancelBtn.disabled = true;
  }

  async function recordWebM(W, H, graph, a, b) {
    if (!window.MediaRecorder) throw new Error("MediaRecorder is not supported in this browser");
    const comp = makeComposer(W, H, graph);
    const stream = comp.out.captureStream(fps.get());
    const mime = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find((m) => MediaRecorder.isTypeSupported(m));
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 12e6 });
    const chunks = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    const done = new Promise((res) => { rec.onstop = res; });
    rec.start();
    status.textContent = "recording in real time…";
    const wall0 = performance.now();
    await new Promise((res) => {
      const step = () => {
        const t = a + ((performance.now() - wall0) / 1000) * speed.get();
        if (cancelled || t > b) return res();
        comp.frame(t, 1 / 60);
        prog.set((t - a) / (b - a));
        requestAnimationFrame(step);
      };
      step();
    });
    rec.stop();
    await done;
    if (!cancelled) download(new Blob(chunks, { type: "video/webm" }), `chaos-lab-${state.sim.digest}.webm`);
    status.textContent = "WebM recorded in real time (frame timing follows the browser's clock; use MP4 for frame-exact output).";
  }

  function bundleData() {
    const s = state.sim;
    return {
      schema: "chaos-lab/bundle@1", app_version: state.meta ? state.meta.version : "?", generated_at: new Date().toISOString(),
      name: s.config.name, config: s.config, digest: s.digest, visual: state.visual,
      reproducibility: {
        deterministic: true,
        note: "Results are a deterministic function of `config` (fixed-step RK4 or SciPy RK45/DOP853 at the stated tolerances). Load via Experiments → Import JSON, or in Python: chaos_lab.simulate(SimConfig.from_dict(bundle['config'])).",
        summary: s.summary, rotations: s.rotations, events: s.events.slice(0, 200),
      },
    };
  }
  function bundle() { download(new Blob([JSON.stringify(bundleData(), null, 2)], { type: "application/json" }), `chaos-lab-${state.sim.digest}.json`); }
  async function csv() {
    try { const r = await api.raw("POST", "/api/export/csv", { config: state.config, t_start: t0.get(), t_end: t1.get() }); download(await r.blob(), `chaos-lab-${state.sim.digest}.csv`); }
    catch (e) { toast(e.message, "err"); }
  }
  function share() {
    const url = encodeShare(state.config, state.visual);
    navigator.clipboard?.writeText(url).then(() => toast("Share link copied", "ok"), () => prompt("Share link", url));
  }

  const offs = [
    bus.on("sim", () => sync()),
    bus.on("cmd:quickgif", () => { fmtSel.set("gif"); preset.set("gif"); scale.set(0.75); fps.set(20); t0.set(0); t1.set(Math.min(6, state.sim ? state.sim.tEnd : 6)); speed.set(1); sync(); run(); }),
  ];
  if (state.sim) sync(); else runSimulation();
  return () => { cancelled = true; offs.forEach((o) => o()); };
}

// ---- minimal ZIP writer (STORE method) for PNG sequences ----
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
function crc32(d) { let c = 0xffffffff; for (let i = 0; i < d.length; i++) c = CRC[(c ^ d[i]) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
function makeZip(files) {
  const parts = [], central = [];
  let off = 0;
  for (const [name, data] of files) {
    const nb = new TextEncoder().encode(name), crc = crc32(data);
    const lh = new DataView(new ArrayBuffer(30));
    lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint32(14, crc, true);
    lh.setUint32(18, data.length, true); lh.setUint32(22, data.length, true); lh.setUint16(26, nb.length, true);
    parts.push(lh.buffer, nb, data);
    const ch = new DataView(new ArrayBuffer(46));
    ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true); ch.setUint32(16, crc, true);
    ch.setUint32(20, data.length, true); ch.setUint32(24, data.length, true); ch.setUint16(28, nb.length, true); ch.setUint32(42, off, true);
    central.push(ch.buffer, nb);
    off += 30 + nb.length + data.length;
  }
  const csize = central.reduce((a, p) => a + (p.byteLength ?? p.length), 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, csize, true); end.setUint32(16, off, true);
  return new Blob([...parts, ...central, end.buffer], { type: "application/zip" });
}

void token;
