// Minimal, fast canvas charts that follow the theme tokens.

import { colormapLUT, token } from "./palettes.js";
import { fitCanvas, fmtSig, h } from "./ui.js";

function niceTicks(lo, hi, n = 5) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (hi === lo) { hi = lo + 1; lo = lo - 1; }
  const span = hi - lo, step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const err = step0 / mag;
  const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  return out;
}

function tickLabel(v, log, step) {
  if (log) return `1e${Math.round(v)}`;
  const a = Math.abs(v);
  if (step && a < 1e5 && step >= 1e-9) {
    const dec = Math.max(0, Math.min(10, Math.ceil(-Math.log10(step) - 1e-9)));
    if (a === 0 || a >= 1e-3 || dec <= 6) return v.toFixed(dec);
  }
  if (a !== 0 && (a < 1e-2 || a >= 1e4)) return v.toExponential(0);
  return String(Number(v.toPrecision(4)));
}
const stepOf = (t) => (t.length > 1 ? t[1] - t[0] : 0);

function theme() {
  return { text: token("text-2"), faint: token("text-3"), grid: token("grid"), border: token("border"), panel: token("panel") };
}

class Base {
  constructor(container, opts = {}) {
    this.opts = opts;
    this.el = h("div", { class: `chart ${opts.cls || ""}` });
    this.canvas = h("canvas", { role: "img", "aria-label": opts.title || opts.ylabel || "chart" });
    this.tip = h("div", { class: "tip" });
    this.el.append(this.canvas, this.tip);
    container.append(this.el);
    this.ctx = this.canvas.getContext("2d");
    this.ro = new ResizeObserver(() => this.draw());
    this.ro.observe(this.el);
  }
  frame() {
    const [w, hh, dpr] = fitCanvas(this.canvas);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.ctx.clearRect(0, 0, w, hh);
    return [w, hh];
  }
  destroy() { this.ro.disconnect(); this.el.remove(); }
}

/** Line chart. series: [{x:Array, y:Array, color, width, dash, label, alpha}] */
export class LineChart extends Base {
  constructor(container, opts = {}) {
    super(container, opts);
    this.series = [];
    this.cursor = null;
    this.markers = [];
    this.hlines = [];
    this.canvas.addEventListener("mousemove", (e) => this.hover(e));
    this.canvas.addEventListener("mouseleave", () => { this.tip.style.display = "none"; this.hoverX = null; this.draw(); });
    this.canvas.addEventListener("click", (e) => {
      if (!this.opts.onClick || !this.map) return;
      const r = this.canvas.getBoundingClientRect();
      this.opts.onClick(this.map.invX(e.clientX - r.left));
    });
  }
  set(series, extra = {}) { this.series = series; Object.assign(this.opts, extra); this.draw(); }
  setCursor(x) { this.cursor = x; this.draw(); }
  setMarkers(m) { this.markers = m; this.draw(); }
  setHLines(l) { this.hlines = l; this.draw(); }

  bounds() {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const s of this.series) {
      const n = s.y.length, step = Math.max(1, Math.floor(n / 4000));
      for (let i = 0; i < n; i += step) {
        const x = s.x[i], y = s.y[i];
        if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
        if (x < x0) x0 = x; if (x > x1) x1 = x;
        if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
    }
    for (const l of this.hlines) { y0 = Math.min(y0, l.y); y1 = Math.max(y1, l.y); }
    if (this.opts.xrange) [x0, x1] = this.opts.xrange;
    if (this.opts.yrange) [y0, y1] = this.opts.yrange;
    if (this.opts.symmetric) { const m = Math.max(Math.abs(y0), Math.abs(y1)); y0 = -m; y1 = m; }
    if (!Number.isFinite(x0)) { x0 = 0; x1 = 1; }
    if (!Number.isFinite(y0)) { y0 = 0; y1 = 1; }
    if (y1 === y0) { y0 -= 1; y1 += 1; }
    const pad = (y1 - y0) * 0.06;
    return [x0, x1, this.opts.yrange ? y0 : y0 - pad, this.opts.yrange ? y1 : y1 + pad];
  }

  draw() {
    const [w, hh] = this.frame();
    const ctx = this.ctx, th = theme(), o = this.opts;
    const L = o.compact ? 44 : 60, R = 10, T = o.title ? 22 : 10, B = o.xlabel ? 32 : 22;
    const [x0, x1, y0, y1] = this.bounds();
    const sx = (x) => L + ((x - x0) / (x1 - x0 || 1)) * (w - L - R);
    const sy = (y) => hh - B - ((y - y0) / (y1 - y0 || 1)) * (hh - T - B);
    this.map = { invX: (px) => x0 + ((px - L) / (w - L - R)) * (x1 - x0), sx, sy, L, R, T, B };
    ctx.font = "10.5px ui-monospace, Menlo, monospace";
    ctx.fillStyle = th.faint; ctx.strokeStyle = th.grid; ctx.lineWidth = 1;
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    let yt = niceTicks(y0, y1, o.compact ? 3 : 5);
    if (o.logY) { yt = []; const st = Math.max(1, Math.ceil((y1 - y0) / (o.compact ? 3 : 6))); for (let v = Math.ceil(y0); v <= y1; v += st) yt.push(v); }
    const ys = stepOf(yt);
    for (const v of yt) {
      const y = sy(v);
      ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(w - R, y); ctx.stroke();
      ctx.fillText(tickLabel(v, o.logY, ys), L - 5, y);
    }
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    const xt = niceTicks(x0, x1, Math.max(3, Math.floor((w - L) / 90))), xs = stepOf(xt);
    for (const v of xt) {
      const x = sx(v);
      ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, hh - B); ctx.stroke();
      ctx.fillText(tickLabel(v, false, xs), x, hh - B + 4);
    }
    if (o.xlabel) { ctx.fillStyle = th.text; ctx.font = "11px system-ui, -apple-system, \"Segoe UI\", sans-serif"; ctx.fillText(o.xlabel, L + (w - L - R) / 2, hh - 14); }
    if (o.title) {
      ctx.fillStyle = th.text; ctx.font = "600 11.5px system-ui, -apple-system, \"Segoe UI\", sans-serif"; ctx.textAlign = "left";
      ctx.fillText(o.title, L, 4);
    }
    // horizontal reference lines
    for (const l of this.hlines) {
      ctx.save(); ctx.setLineDash([5, 4]); ctx.strokeStyle = l.color || th.faint; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(L, sy(l.y)); ctx.lineTo(w - R, sy(l.y)); ctx.stroke();
      if (l.label) { ctx.fillStyle = l.color || th.faint; ctx.textAlign = "right"; ctx.textBaseline = "bottom"; ctx.font = "10.5px system-ui, -apple-system, sans-serif"; ctx.fillText(l.label, w - R - 2, sy(l.y) - 2); }
      ctx.restore();
    }
    // series
    ctx.save();
    ctx.beginPath(); ctx.rect(L, T, w - L - R, hh - T - B); ctx.clip();
    const pxBudget = Math.max(200, (w - L - R) * 2);
    for (const s of this.series) {
      const n = s.y.length;
      if (!n) continue;
      ctx.strokeStyle = s.color || token("cyan");
      ctx.globalAlpha = s.alpha ?? 1;
      ctx.lineWidth = s.width || 1.5;
      ctx.setLineDash(s.dash || []);
      ctx.beginPath();
      const step = Math.max(1, Math.floor(n / pxBudget));
      let pen = false;
      if (step > 1 && !s.noMinMax) {
        // min/max decimation preserves spikes (important for energy-error plots)
        for (let i = 0; i < n; i += step) {
          let lo = Infinity, hi = -Infinity;
          for (let j = i; j < Math.min(n, i + step); j++) { const v = s.y[j]; if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } }
          if (!Number.isFinite(lo)) { pen = false; continue; }
          const x = sx(s.x[i]);
          if (!pen) { ctx.moveTo(x, sy(lo)); pen = true; } else ctx.lineTo(x, sy(lo));
          ctx.lineTo(x, sy(hi));
        }
      } else {
        for (let i = 0; i < n; i++) {
          const v = s.y[i];
          if (!Number.isFinite(v) || !Number.isFinite(s.x[i])) { pen = false; continue; }
          const x = sx(s.x[i]), y = sy(v);
          if (!pen) { ctx.moveTo(x, y); pen = true; } else ctx.lineTo(x, y);
        }
      }
      ctx.stroke();
      if (s.points) {
        ctx.fillStyle = ctx.strokeStyle;
        for (let i = 0; i < n; i++) if (Number.isFinite(s.y[i])) { ctx.beginPath(); ctx.arc(sx(s.x[i]), sy(s.y[i]), 3, 0, 7); ctx.fill(); }
      }
    }
    ctx.restore();
    ctx.globalAlpha = 1; ctx.setLineDash([]);
    // markers
    for (const m of this.markers) {
      const x = sx(m.x);
      if (x < L || x > w - R) continue;
      ctx.strokeStyle = m.color || token("gold"); ctx.globalAlpha = 0.75; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, hh - B); ctx.stroke();
      ctx.setLineDash([]); ctx.globalAlpha = 1;
      if (m.label) { ctx.fillStyle = m.color || token("gold"); ctx.font = "10px system-ui, -apple-system, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.fillText(m.label, x + 3, T + 1); }
    }
    if (this.cursor !== null && this.cursor !== undefined) {
      const x = sx(this.cursor);
      ctx.strokeStyle = th.text; ctx.globalAlpha = 0.6;
      ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, hh - B); ctx.stroke();
      ctx.globalAlpha = 1;
    }
    // legend
    const labeled = this.series.filter((s) => s.label);
    if (labeled.length && !o.noLegend) {
      ctx.font = "10.5px system-ui, -apple-system, \"Segoe UI\", sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
      let lx = L + 6, ly = T + 8;
      let rows = 1, tx = lx;
      for (const s of labeled.slice(0, 8)) { const tw = ctx.measureText(s.label).width; if (tx + tw + 24 > w - R) { tx = L + 6; rows++; } tx += tw + 30; }
      ctx.save(); ctx.globalAlpha = 0.82; ctx.fillStyle = th.panel; ctx.fillRect(L + 2, T + 1, w - L - R - 4, rows * 14 + 2); ctx.restore();
      for (const s of labeled.slice(0, 8)) {
        const tw = ctx.measureText(s.label).width;
        if (lx + tw + 24 > w - R) { lx = L + 6; ly += 14; }
        ctx.fillStyle = s.color; ctx.fillRect(lx, ly - 1.5, 12, 3);
        ctx.fillStyle = th.text; ctx.fillText(s.label, lx + 16, ly);
        lx += tw + 30;
      }
    }
    if (o.ylabel) {
      ctx.save(); ctx.translate(11, T + (hh - T - B) / 2); ctx.rotate(-Math.PI / 2);
      ctx.fillStyle = th.text; ctx.font = "11px system-ui, -apple-system, \"Segoe UI\", sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(o.ylabel, 0, 0); ctx.restore();
    }
  }

  hover(e) {
    if (!this.map || !this.series.length) return;
    const r = this.canvas.getBoundingClientRect();
    const xv = this.map.invX(e.clientX - r.left);
    const lines = [`${this.opts.xname || "t"} = ${fmtSig(xv, 4)}`];
    for (const s of this.series.slice(0, 6)) {
      if (!s.x.length) continue;
      let lo = 0, hi = s.x.length - 1;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (s.x[m] < xv) lo = m; else hi = m; }
      const v = s.y[Math.abs(s.x[lo] - xv) < Math.abs(s.x[hi] - xv) ? lo : hi];
      if (s.label) lines.push(`${s.label}: ${this.opts.logY ? `1e${fmtSig(v, 3)}` : fmtSig(v, 4)}`);
    }
    this.tip.innerHTML = lines.join("<br>");
    this.tip.style.display = "block";
    const tx = Math.min(e.clientX - r.left + 12, r.width - this.tip.offsetWidth - 4);
    this.tip.style.left = `${Math.max(0, tx)}px`;
    this.tip.style.top = `${Math.max(0, e.clientY - r.top - 10)}px`;
  }
}

/** Heatmap of a Float32Array (row-major ny x nx, row 0 = lowest y). */
export class Heatmap extends Base {
  constructor(container, opts = {}) {
    super(container, { cls: "xl", ...opts });
    this.data = null;
    this.overlay = [];
    this.img = document.createElement("canvas");
    this.drag = null;
    const c = this.canvas;
    c.style.cursor = "crosshair";
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      this.drag = { x: e.offsetX, y: e.offsetY, x1: e.offsetX, y1: e.offsetY, box: e.shiftKey || this.opts.boxDefault, moved: false };
    });
    c.addEventListener("pointermove", (e) => {
      this.hover(e);
      if (!this.drag) return;
      this.drag.x1 = e.offsetX; this.drag.y1 = e.offsetY;
      if (Math.hypot(this.drag.x1 - this.drag.x, this.drag.y1 - this.drag.y) > 4) this.drag.moved = true;
      this.draw();
    });
    c.addEventListener("pointerup", (e) => {
      const d = this.drag; this.drag = null;
      if (!d || !this.map) return;
      const a = this.map.inv(d.x, d.y), b = this.map.inv(e.offsetX, e.offsetY);
      if (!d.moved) { this.opts.onPick && this.opts.onPick(a[0], a[1], this.valueAt(a[0], a[1])); this.draw(); return; }
      if (d.box) this.opts.onBox && this.opts.onBox([Math.min(a[0], b[0]), Math.max(a[0], b[0])], [Math.min(a[1], b[1]), Math.max(a[1], b[1])]);
      else this.opts.onPan && this.opts.onPan(a[0] - b[0], a[1] - b[1]);
      this.draw();
    });
    c.addEventListener("wheel", (e) => {
      if (!this.opts.onZoom || !this.map) return;
      e.preventDefault();
      const [x, y] = this.map.inv(e.offsetX, e.offsetY);
      this.opts.onZoom(x, y, e.deltaY > 0 ? 1.25 : 0.8);
    }, { passive: false });
    c.addEventListener("mouseleave", () => { this.tip.style.display = "none"; });
  }

  set(data, nx, ny, xr, yr, opts = {}) {
    Object.assign(this, { data, nx, ny, xr, yr });
    Object.assign(this.opts, opts);
    this.paint();
    this.draw();
  }

  valueAt(x, y) {
    if (!this.data) return NaN;
    const i = Math.floor(((x - this.xr[0]) / (this.xr[1] - this.xr[0])) * this.nx);
    const j = Math.floor(((y - this.yr[0]) / (this.yr[1] - this.yr[0])) * this.ny);
    if (i < 0 || j < 0 || i >= this.nx || j >= this.ny) return NaN;
    return this.data[j * this.nx + i];
  }

  range() {
    const o = this.opts;
    let lo = o.vmin, hi = o.vmax;
    if (lo === undefined || hi === undefined || lo === null || hi === null) {
      const vals = [];
      const st = Math.max(1, Math.floor(this.data.length / 20000));
      for (let i = 0; i < this.data.length; i += st) if (Number.isFinite(this.data[i])) vals.push(o.log ? Math.log10(Math.max(this.data[i], 1e-12)) : this.data[i]);
      vals.sort((a, b) => a - b);
      const q = (p) => vals[Math.min(vals.length - 1, Math.max(0, Math.floor(p * (vals.length - 1))))];
      const clip = o.clip ?? 0.01;
      lo = vals.length ? q(clip) : 0; hi = vals.length ? q(1 - clip) : 1;
      if (hi === lo) hi = lo + 1;
    } else if (o.log) { lo = Math.log10(Math.max(lo, 1e-12)); hi = Math.log10(Math.max(hi, 1e-12)); }
    return [lo, hi];
  }

  paint() {
    if (!this.data) return;
    const { nx, ny } = this;
    this.img.width = nx; this.img.height = ny;
    const ic = this.img.getContext("2d");
    const im = ic.createImageData(nx, ny);
    const L = colormapLUT(this.opts.cmap || "magma");
    const [lo, hi] = this.range();
    this.vr = [lo, hi];
    const nan = this.opts.nanColor || [12, 15, 26];
    const inv = this.opts.invert;
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        let v = this.data[j * nx + i];
        const o = ((ny - 1 - j) * nx + i) * 4; // flip: row 0 = lowest y at bottom
        if (!Number.isFinite(v)) { im.data[o] = nan[0]; im.data[o + 1] = nan[1]; im.data[o + 2] = nan[2]; im.data[o + 3] = 255; continue; }
        if (this.opts.log) v = Math.log10(Math.max(v, 1e-12));
        let u = (v - lo) / (hi - lo);
        u = Math.max(0, Math.min(1, inv ? 1 - u : u));
        const k = Math.round(u * 255) * 3;
        im.data[o] = L[k]; im.data[o + 1] = L[k + 1]; im.data[o + 2] = L[k + 2]; im.data[o + 3] = 255;
      }
    }
    ic.putImageData(im, 0, 0);
  }

  draw() {
    const [w, hh] = this.frame();
    const ctx = this.ctx, th = theme();
    const L = 46, R = 84, T = 10, B = 34;
    const pw = w - L - R, ph = hh - T - B;
    const side = this.opts.square ? Math.min(pw, ph) : null;
    const W = side || pw, H = side || ph;
    const ox = L + (pw - W) / 2, oy = T + (ph - H) / 2;
    if (!this.data) { ctx.fillStyle = th.faint; ctx.textAlign = "center"; ctx.fillText(this.opts.empty || "No data yet", w / 2, hh / 2); return; }
    const { xr, yr } = this;
    this.map = {
      inv: (px, py) => [xr[0] + ((px - ox) / W) * (xr[1] - xr[0]), yr[0] + ((oy + H - py) / H) * (yr[1] - yr[0])],
      fwd: (x, y) => [ox + ((x - xr[0]) / (xr[1] - xr[0])) * W, oy + H - ((y - yr[0]) / (yr[1] - yr[0])) * H],
    };
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(this.img, ox, oy, W, H);
    ctx.strokeStyle = th.border; ctx.strokeRect(ox + 0.5, oy + 0.5, W - 1, H - 1);
    ctx.font = "10.5px ui-monospace, monospace"; ctx.fillStyle = th.faint;
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (const v of niceTicks(xr[0], xr[1], 5)) { const [x] = this.map.fwd(v, yr[0]); ctx.fillText(tickLabel(v), x, oy + H + 4); }
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (const v of niceTicks(yr[0], yr[1], 5)) { const [, y] = this.map.fwd(xr[0], v); ctx.fillText(tickLabel(v), ox - 5, y); }
    ctx.fillStyle = th.text; ctx.font = "11px system-ui, -apple-system, \"Segoe UI\", sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    if (this.opts.xlabel) ctx.fillText(this.opts.xlabel, ox + W / 2, hh - 4);
    if (this.opts.ylabel) { ctx.save(); ctx.translate(11, oy + H / 2); ctx.rotate(-Math.PI / 2); ctx.fillText(this.opts.ylabel, 0, 0); ctx.restore(); }
    // colourbar
    const cbx = ox + W + 14, cbw = 12;
    const Lut = colormapLUT(this.opts.cmap || "magma");
    for (let k = 0; k < H; k++) {
      let u = 1 - k / (H - 1);
      if (this.opts.invert) u = 1 - u;
      const i = Math.round(u * 255) * 3;
      ctx.fillStyle = `rgb(${Lut[i]},${Lut[i + 1]},${Lut[i + 2]})`;
      ctx.fillRect(cbx, oy + k, cbw, 1.5);
    }
    ctx.strokeStyle = th.border; ctx.strokeRect(cbx + 0.5, oy + 0.5, cbw, H - 1);
    ctx.fillStyle = th.faint; ctx.font = "10px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
    const [lo, hi] = this.vr || [0, 1];
    for (const v of niceTicks(lo, hi, 4)) {
      const y = oy + H - ((v - lo) / (hi - lo)) * H;
      if (y < oy - 1 || y > oy + H + 1) continue;
      ctx.fillText(this.opts.log ? fmtSig(10 ** v, 2) : tickLabel(v), cbx + cbw + 4, y);
    }
    if (this.opts.unit) { ctx.save(); ctx.translate(w - 6, oy + H / 2); ctx.rotate(-Math.PI / 2); ctx.textAlign = "center"; ctx.fillStyle = th.text; ctx.fillText(this.opts.unit, 0, 0); ctx.restore(); }
    // overlays: points/paths in data coords
    for (const ov of this.overlay) {
      ctx.save();
      ctx.beginPath(); ctx.rect(ox, oy, W, H); ctx.clip();
      ctx.strokeStyle = ov.color || "#fff"; ctx.fillStyle = ov.color || "#fff"; ctx.lineWidth = ov.width || 1.5; ctx.globalAlpha = ov.alpha ?? 1;
      if (ov.type === "points") for (const [x, y, lab] of ov.pts) {
        const [a, b] = this.map.fwd(x, y);
        ctx.beginPath(); ctx.arc(a, b, ov.r || 4, 0, 7); ctx.fill();
        if (lab) { ctx.font = "10.5px system-ui, -apple-system, sans-serif"; ctx.fillText(lab, a + 6, b - 6); }
      }
      if (ov.type === "path") {
        ctx.beginPath(); let pen = false;
        for (const [x, y] of ov.pts) {
          if (!Number.isFinite(x)) { pen = false; continue; }
          const [a, b] = this.map.fwd(x, y);
          pen ? ctx.lineTo(a, b) : ctx.moveTo(a, b); pen = true;
        }
        ctx.stroke();
      }
      if (ov.type === "cross") {
        const [a, b] = this.map.fwd(ov.x, ov.y);
        ctx.beginPath(); ctx.arc(a, b, 7, 0, 7); ctx.moveTo(a - 11, b); ctx.lineTo(a + 11, b); ctx.moveTo(a, b - 11); ctx.lineTo(a, b + 11); ctx.stroke();
      }
      ctx.restore();
    }
    if (this.drag && this.drag.moved) {
      ctx.save();
      if (this.drag.box) {
        ctx.strokeStyle = token("cyan"); ctx.setLineDash([4, 3]); ctx.lineWidth = 1.5;
        ctx.strokeRect(this.drag.x, this.drag.y, this.drag.x1 - this.drag.x, this.drag.y1 - this.drag.y);
      } else {
        ctx.strokeStyle = token("text-2"); ctx.beginPath(); ctx.moveTo(this.drag.x, this.drag.y); ctx.lineTo(this.drag.x1, this.drag.y1); ctx.stroke();
      }
      ctx.restore();
    }
  }

  hover(e) {
    if (!this.map || !this.data) return;
    const [x, y] = this.map.inv(e.offsetX, e.offsetY);
    if (x < this.xr[0] || x > this.xr[1] || y < this.yr[0] || y > this.yr[1]) { this.tip.style.display = "none"; return; }
    const v = this.valueAt(x, y);
    this.tip.innerHTML = `${this.opts.xname || "x"} ${fmtSig(x, 4)}, ${this.opts.yname || "y"} ${fmtSig(y, 4)}<br>${this.opts.vname || "value"} ${Number.isFinite(v) ? fmtSig(v, 4) : this.opts.nanLabel || "—"}`;
    this.tip.style.display = "block";
    const r = this.el.getBoundingClientRect();
    this.tip.style.left = `${Math.min(e.offsetX + 14, r.width - this.tip.offsetWidth - 4)}px`;
    this.tip.style.top = `${e.offsetY + 12}px`;
  }

  toPNG(scale = 1) {
    // Raw map pixels (no axes) at native resolution, optionally upscaled.
    const c = document.createElement("canvas");
    c.width = this.nx * scale; c.height = this.ny * scale;
    const x = c.getContext("2d");
    x.imageSmoothingEnabled = false;
    x.drawImage(this.img, 0, 0, c.width, c.height);
    return c;
  }
}

/** Scatter plot with wheel zoom and drag pan (Poincaré sections). */
export class Scatter extends Base {
  constructor(container, opts = {}) {
    super(container, { cls: "xl", ...opts });
    this.groups = [];
    this.view = null;
    const c = this.canvas;
    let drag = null;
    c.addEventListener("pointerdown", (e) => { c.setPointerCapture(e.pointerId); drag = [e.offsetX, e.offsetY]; });
    c.addEventListener("pointermove", (e) => {
      if (!drag || !this.map) return;
      const [a, b] = this.map.inv(drag[0], drag[1]), [cx, cy] = this.map.inv(e.offsetX, e.offsetY);
      const v = this.view;
      this.view = [v[0] - (cx - a), v[1] - (cx - a), v[2] - (cy - b), v[3] - (cy - b)];
      drag = [e.offsetX, e.offsetY];
      this.draw();
    });
    c.addEventListener("pointerup", () => { drag = null; });
    c.addEventListener("wheel", (e) => {
      if (!this.map) return;
      e.preventDefault();
      const [x, y] = this.map.inv(e.offsetX, e.offsetY), f = e.deltaY > 0 ? 1.2 : 1 / 1.2, v = this.view;
      this.view = [x + (v[0] - x) * f, x + (v[1] - x) * f, y + (v[2] - y) * f, y + (v[3] - y) * f];
      this.draw();
    }, { passive: false });
    c.addEventListener("dblclick", () => { this.view = null; this.draw(); });
  }
  set(groups, opts = {}) { this.groups = groups; Object.assign(this.opts, opts); this.view = null; this.draw(); }
  autoView() {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const g of this.groups) for (let i = 0; i < g.x.length; i++) {
      const x = g.x[i], y = g.y[i]; if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
    }
    if (this.opts.xrange) [x0, x1] = this.opts.xrange;
    if (!Number.isFinite(x0)) return [-1, 1, -1, 1];
    const px = (x1 - x0) * 0.05 || 1, py = (y1 - y0) * 0.05 || 1;
    return [x0 - (this.opts.xrange ? 0 : px), x1 + (this.opts.xrange ? 0 : px), y0 - py, y1 + py];
  }
  draw() {
    const [w, hh] = this.frame();
    const ctx = this.ctx, th = theme();
    if (!this.view) this.view = this.autoView();
    const [x0, x1, y0, y1] = this.view;
    const L = 50, R = 12, T = 12, B = 34;
    const sx = (x) => L + ((x - x0) / (x1 - x0)) * (w - L - R), sy = (y) => hh - B - ((y - y0) / (y1 - y0)) * (hh - T - B);
    this.map = { inv: (px, py) => [x0 + ((px - L) / (w - L - R)) * (x1 - x0), y0 + ((hh - B - py) / (hh - T - B)) * (y1 - y0)] };
    ctx.font = "10.5px ui-monospace, monospace"; ctx.fillStyle = th.faint; ctx.strokeStyle = th.grid;
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (const v of niceTicks(y0, y1, 5)) { ctx.beginPath(); ctx.moveTo(L, sy(v)); ctx.lineTo(w - R, sy(v)); ctx.stroke(); ctx.fillText(tickLabel(v), L - 5, sy(v)); }
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (const v of niceTicks(x0, x1, 6)) { ctx.beginPath(); ctx.moveTo(sx(v), T); ctx.lineTo(sx(v), hh - B); ctx.stroke(); ctx.fillText(tickLabel(v), sx(v), hh - B + 4); }
    ctx.fillStyle = th.text; ctx.font = "11px system-ui, -apple-system, sans-serif";
    if (this.opts.xlabel) ctx.fillText(this.opts.xlabel, L + (w - L - R) / 2, hh - 16);
    if (this.opts.ylabel) { ctx.save(); ctx.translate(12, T + (hh - T - B) / 2); ctx.rotate(-Math.PI / 2); ctx.textBaseline = "middle"; ctx.fillText(this.opts.ylabel, 0, 0); ctx.restore(); }
    ctx.save(); ctx.beginPath(); ctx.rect(L, T, w - L - R, hh - T - B); ctx.clip();
    const r = this.opts.pointSize || 1.4;
    for (const g of this.groups) {
      ctx.fillStyle = g.color; ctx.globalAlpha = g.alpha ?? 0.85;
      for (let i = 0; i < g.x.length; i++) {
        if (!Number.isFinite(g.x[i]) || !Number.isFinite(g.y[i])) continue;
        ctx.fillRect(sx(g.x[i]) - r / 2, sy(g.y[i]) - r / 2, r, r);
      }
      if (g.line) {
        ctx.strokeStyle = g.color; ctx.lineWidth = g.width || 1; ctx.beginPath();
        for (let i = 0; i < g.x.length; i++) { const a = sx(g.x[i]), b = sy(g.y[i]); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); }
        ctx.stroke();
      }
      if (g.head !== undefined && g.head >= 0 && g.head < g.x.length) {
        ctx.globalAlpha = 1; ctx.fillStyle = g.headColor || "#fff";
        ctx.beginPath(); ctx.arc(sx(g.x[g.head]), sy(g.y[g.head]), 4, 0, 7); ctx.fill();
      }
    }
    ctx.restore(); ctx.globalAlpha = 1;
    if (this.opts.title) { ctx.fillStyle = th.text; ctx.font = "600 11.5px system-ui, -apple-system, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.fillText(this.opts.title, L, 0); }
  }
}

/** Rotatable 3D line plot (projection of 4D state space onto three axes). */
export class Plot3D extends Base {
  constructor(container, opts = {}) {
    super(container, { cls: "xl", ...opts });
    this.yaw = 0.7; this.pitch = 0.4; this.pts = null;
    let drag = null;
    const c = this.canvas;
    c.style.cursor = "grab";
    c.addEventListener("pointerdown", (e) => { c.setPointerCapture(e.pointerId); drag = [e.clientX, e.clientY]; });
    c.addEventListener("pointermove", (e) => {
      if (!drag) return;
      this.yaw += (e.clientX - drag[0]) * 0.01; this.pitch = Math.max(-1.5, Math.min(1.5, this.pitch + (e.clientY - drag[1]) * 0.01));
      drag = [e.clientX, e.clientY]; this.draw();
    });
    c.addEventListener("pointerup", () => { drag = null; });
  }
  set(x, y, z, labels, colorFn, head = -1) { this.pts = { x, y, z }; this.labels = labels; this.colorFn = colorFn; this.head = head; this.norm(); this.draw(); }
  setHead(i) { this.head = i; this.draw(); }
  norm() {
    const n = (a) => { let lo = Infinity, hi = -Infinity; for (const v of a) { if (v < lo) lo = v; if (v > hi) hi = v; } return [lo, hi]; };
    this.rng = [n(this.pts.x), n(this.pts.y), n(this.pts.z)];
  }
  proj(x, y, z, w, hh) {
    const c = (v, [lo, hi]) => ((v - lo) / (hi - lo || 1)) * 2 - 1;
    let X = c(x, this.rng[0]), Y = c(z, this.rng[2]), Z = c(y, this.rng[1]);
    const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw), cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
    const X1 = cy * X + sy * Z, Z1 = -sy * X + cy * Z;
    const Y1 = cp * Y - sp * Z1, Z2 = sp * Y + cp * Z1;
    const k = (Math.min(w, hh) * 0.36) / (1 - Z2 * 0.22);
    return [w / 2 + X1 * k, hh / 2 - Y1 * k];
  }
  draw() {
    const [w, hh] = this.frame();
    if (!this.pts) return;
    const ctx = this.ctx, th = theme();
    // axes box
    ctx.strokeStyle = th.grid; ctx.lineWidth = 1;
    const corners = [-1, 1];
    const lo = this.rng.map((r) => r[0]), hi = this.rng.map((r) => r[1]);
    const P = (a, b, c) => this.proj(a ? hi[0] : lo[0], b ? hi[1] : lo[1], c ? hi[2] : lo[2], w, hh);
    ctx.beginPath();
    for (const a of [0, 1]) for (const b of [0, 1]) {
      let p = P(a, b, 0), q = P(a, b, 1); ctx.moveTo(...p); ctx.lineTo(...q);
      p = P(a, 0, b); q = P(a, 1, b); ctx.moveTo(...p); ctx.lineTo(...q);
      p = P(0, a, b); q = P(1, a, b); ctx.moveTo(...p); ctx.lineTo(...q);
    }
    ctx.stroke();
    void corners;
    ctx.fillStyle = th.text; ctx.font = "11px system-ui, -apple-system, sans-serif";
    const [lx, ly, lz] = this.labels;
    ctx.fillText(lx, ...P(1, 0, 0)); ctx.fillText(ly, ...P(0, 1, 0)); ctx.fillText(lz, ...P(0, 0, 1));
    const { x, y, z } = this.pts, n = x.length, step = Math.max(1, Math.floor(n / 3000));
    ctx.lineWidth = 1.1;
    let prev = null;
    for (let i = 0; i < n; i += step) {
      const p = this.proj(x[i], y[i], z[i], w, hh);
      if (prev) { ctx.strokeStyle = this.colorFn ? this.colorFn(i / n) : token("cyan"); ctx.beginPath(); ctx.moveTo(...prev); ctx.lineTo(...p); ctx.stroke(); }
      prev = p;
    }
    if (this.head >= 0 && this.head < n) {
      const p = this.proj(x[this.head], y[this.head], z[this.head], w, hh);
      ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(p[0], p[1], 4, 0, 7); ctx.fill();
    }
    ctx.fillStyle = th.faint; ctx.font = "10.5px system-ui, -apple-system, sans-serif"; ctx.textAlign = "left";
    ctx.fillText("3D projection of the 4D state space · drag to rotate", 8, hh - 8);
  }
}
