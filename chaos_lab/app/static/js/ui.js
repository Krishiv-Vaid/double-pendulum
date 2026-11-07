// Small DOM toolkit: element builder, controls, toasts, tooltips, modals.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") el.innerHTML = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);

export function fmt(v, digits = 3) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (!Number.isFinite(v)) return v > 0 ? "∞" : "−∞";
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(Math.max(1, digits - 1)).replace("e", "e");
  return v.toFixed(digits);
}

export function fmtSig(v, sig = 3) {
  if (v === null || v === undefined || !Number.isFinite(v)) return fmt(v);
  return Math.abs(v) >= 1e-3 && Math.abs(v) < 1e5 ? String(Number(v.toPrecision(sig))) : v.toExponential(sig - 1);
}

/** Slider + numeric input. opts: {label, unit, min, max, step, value, log, tip, onInput, onChange, digits} */
export function slider(opts) {
  const { label, unit = "", min, max, step = "any", log = false, tip, digits = 3 } = opts;
  const toSlider = (v) => (log ? Math.log10(Math.max(v, 1e-300)) : v);
  const fromSlider = (s) => (log ? 10 ** s : s);
  const range = h("input", {
    type: "range", min: toSlider(min), max: toSlider(max), step: log ? 0.01 : step, "aria-label": label,
  });
  const num = h("input", { type: "text", class: "value", inputmode: "decimal", "aria-label": `${label} value` });
  const setFill = () => {
    const f = ((range.value - range.min) / (range.max - range.min)) * 100;
    range.style.setProperty("--fill", `${f}%`);
  };
  const show = (v) => {
    if (log || (Math.abs(v) < 1e-3 && v !== 0)) { num.value = fmtSig(v, 3); return; }
    const s = (+v).toFixed(digits);
    num.value = s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
  };
  const el = h("div", { class: "field" },
    h("div", { class: "field-row" },
      h("label", {}, label, unit ? h("span", { class: "unit" }, unit) : null, tip ? info(tip) : null),
      num),
    range);
  const set = (v, emit = false) => {
    range.value = toSlider(v);
    setFill();
    show(v);
    if (emit) opts.onChange && opts.onChange(v);
  };
  range.addEventListener("input", () => {
    const v = fromSlider(+range.value);
    show(v); setFill();
    opts.onInput && opts.onInput(v);
  });
  range.addEventListener("change", () => opts.onChange && opts.onChange(fromSlider(+range.value)));
  num.addEventListener("change", () => {
    const v = parseFloat(num.value);
    if (Number.isFinite(v)) set(v, true); else show(fromSlider(+range.value));
  });
  num.addEventListener("keydown", (e) => { if (e.key === "Enter") num.blur(); });
  set(opts.value ?? min);
  el.set = (v) => set(v);
  el.get = () => parseFloat(num.value);
  return el;
}

export function select(opts) {
  const { label, options, value, onChange, tip } = opts;
  const s = h("select", { "aria-label": label });
  for (const o of options) {
    const [v, text] = Array.isArray(o) ? o : [o, o];
    s.append(h("option", { value: v }, text));
  }
  s.value = value;
  s.addEventListener("change", () => onChange && onChange(s.value));
  const el = label ? h("div", { class: "field" }, h("label", {}, label, tip ? info(tip) : null), s) : s;
  el.set = (v) => { s.value = v; };
  el.get = () => s.value;
  el.input = s;
  return el;
}

export function check(label, value, onChange, tip) {
  const i = h("input", { type: "checkbox" });
  i.checked = !!value;
  i.addEventListener("change", () => onChange(i.checked));
  const el = h("label", { class: "check" }, i, label, tip ? info(tip) : null);
  el.set = (v) => { i.checked = !!v; };
  return el;
}

export function seg(options, value, onChange) {
  const el = h("div", { class: "seg", role: "group" });
  const btns = options.map(([v, label]) => {
    const b = h("button", { type: "button", "aria-pressed": String(v === value) }, label);
    b.addEventListener("click", () => {
      btns.forEach((x) => x.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");
      onChange(v);
    });
    return b;
  });
  el.append(...btns);
  el.set = (v) => btns.forEach((b, i) => b.setAttribute("aria-pressed", String(options[i][0] === v)));
  return el;
}

export function textField(label, value, onChange, attrs = {}) {
  const i = h(attrs.multiline ? "textarea" : "input", { type: "text", ...attrs, multiline: null });
  i.value = value ?? "";
  i.addEventListener("change", () => onChange && onChange(i.value));
  const el = h("div", { class: "field" }, h("label", {}, label), i);
  el.input = i;
  return el;
}

export function section(title, open, ...children) {
  return h("details", { class: "section", open: open || null }, h("summary", {}, title), h("div", { class: "section-body" }, ...children));
}

export function panel(title, body, { actions = [], cls = "" } = {}) {
  return h("section", { class: `panel ${cls}` },
    title ? h("div", { class: "panel-head" }, h("h2", {}, title), h("div", { class: "spacer" }), ...actions) : null,
    h("div", { class: "panel-body" }, body));
}

export function info(text) {
  return h("span", { class: "info-i", "data-tip": text, tabindex: "0", "aria-label": text }, "i");
}

export function btn(label, onClick, { cls = "", tip, icon, disabled } = {}) {
  const b = h("button", { type: "button", class: `btn ${cls}`, "data-tip": tip, disabled }, icon ? h("span", { html: icon }) : null, label);
  b.addEventListener("click", onClick);
  return b;
}

export function progressBar() {
  const inner = h("div");
  const el = h("div", { class: "progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100 }, inner);
  el.set = (f) => { inner.style.width = `${Math.round(f * 100)}%`; el.setAttribute("aria-valuenow", Math.round(f * 100)); };
  return el;
}

export function toast(msg, kind = "") {
  const t = h("div", { class: `toast ${kind}` }, msg);
  document.getElementById("toasts").append(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; }, kind === "err" ? 6000 : 3200);
  setTimeout(() => t.remove(), kind === "err" ? 6400 : 3600);
}

export function modal(content, { onClose } = {}) {
  const box = h("div", { class: "modal", role: "dialog", "aria-modal": "true" }, content);
  const ov = h("div", { class: "overlay" }, box);
  const close = () => { ov.remove(); document.removeEventListener("keydown", esc); onClose && onClose(); };
  const esc = (e) => { if (e.key === "Escape") close(); };
  ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(); });
  document.addEventListener("keydown", esc);
  document.body.append(ov);
  return { close, box };
}

// ---------- tooltips ----------
let tipEl = null;
export function installTooltips() {
  tipEl = h("div", { class: "tooltip", role: "tooltip" });
  document.body.append(tipEl);
  const show = (e) => {
    const t = e.target.closest && e.target.closest("[data-tip]");
    if (!t || !t.dataset.tip) return;
    tipEl.textContent = t.dataset.tip;
    const r = t.getBoundingClientRect();
    tipEl.classList.add("show");
    const w = tipEl.offsetWidth, hh = tipEl.offsetHeight;
    let x = r.left + r.width / 2 - w / 2, y = r.bottom + 8;
    if (y + hh > innerHeight - 6) y = r.top - hh - 8;
    tipEl.style.left = `${Math.max(6, Math.min(innerWidth - w - 6, x))}px`;
    tipEl.style.top = `${y}px`;
  };
  const hide = () => tipEl.classList.remove("show");
  document.addEventListener("mouseover", show);
  document.addEventListener("focusin", show);
  document.addEventListener("mouseout", hide);
  document.addEventListener("focusout", hide);
}

/** Resize a canvas to its CSS box at device pixel ratio; returns [w, h, dpr] in CSS pixels. */
export function fitCanvas(c, maxDpr = 2) {
  const dpr = Math.min(window.devicePixelRatio || 1, maxDpr);
  const r = c.getBoundingClientRect();
  const w = Math.max(1, Math.round(r.width * dpr)), hgt = Math.max(1, Math.round(r.height * dpr));
  if (c.width !== w || c.height !== hgt) { c.width = w; c.height = hgt; }
  return [r.width, r.height, dpr];
}

export function onResize(el, fn) {
  const ro = new ResizeObserver(() => fn());
  ro.observe(el);
  return () => ro.disconnect();
}

export const ICONS = {
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 5v14l12-7z"/></svg>',
  pause: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>',
  reset: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4v6h6"/><path d="M20 12a8 8 0 1 1-2.3-5.7L20 9"/></svg>',
  step: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5v14l9-7zM16 5h3v14h-3z"/></svg>',
  back: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M18 5v14l-9-7zM5 5h3v14H5z"/></svg>',
  rev: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M17 5v14L5 12z"/></svg>',
  full: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>',
  camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  export: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12M7 8l5-5 5 5M5 21h14"/></svg>',
  bookmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 3h12v18l-6-4-6 4z"/></svg>',
  dice: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="9" cy="9" r="1" fill="currentColor"/><circle cx="15" cy="15" r="1" fill="currentColor"/><circle cx="15" cy="9" r="1" fill="currentColor"/><circle cx="9" cy="15" r="1" fill="currentColor"/></svg>',
  save: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 3h11l3 3v15H5z"/><path d="M8 3v6h8V3M8 21v-7h8v7"/></svg>',
  share: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.2 11l7.6-4M8.2 13l7.6 4"/></svg>',
  sound: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/></svg>',
};
