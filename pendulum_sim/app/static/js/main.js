// Double Pendulum Simulator — application shell: navigation, routing, shortcuts, commands.

import { api } from "./api.js";
import { applyPreset } from "./controls.js";
import { requestSimulation, setPlaying, stepFrames, jumpTo, togglePlay } from "./sim.js";
import { bus, clock, decodeShare, setConfig, setVisual, state } from "./state.js";
import { $, h, installTooltips, modal, toast } from "./ui.js";

const I = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
export const VIEWS = [
  { id: "playground", title: "Playground", sub: "Real-time double pendulum laboratory", icon: I('<circle cx="12" cy="3" r="1"/><path d="M12 3 7 12l8 7"/><circle cx="7" cy="12" r="2"/><circle cx="15" cy="19" r="2"/>') },
  { id: "studio", title: "Chaos Studio", sub: "Generative art from real trajectories", icon: I('<path d="M3 17c4-10 8 6 12-4s4-6 6-6"/><circle cx="18" cy="5" r="1.5"/>') },
  { id: "butterfly", title: "Butterfly Effect", sub: "Sensitive dependence on initial conditions", icon: I('<path d="M12 6v14M12 9C9 3 3 4 4 10c1 4 5 4 8 2M12 9c3-6 9-5 8 1-1 4-5 4-8 2M12 13c-3 0-6 2-5 5s4 1 5-2M12 13c3 0 6 2 5 5s-4 1-5-2"/>') },
  { id: "fractal", title: "Fractal Explorer", sub: "Initial-condition maps", icon: I('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 12h9V3M12 12h9M12 12v9M7.5 7.5h0M16.5 16.5h0"/>') },
  { id: "phase", title: "Phase Space", sub: "Portraits, Poincaré sections, spectra", icon: I('<ellipse cx="12" cy="12" rx="9" ry="5"/><ellipse cx="12" cy="12" rx="5" ry="2.5"/><path d="M12 3v18"/>') },
  { id: "lab", title: "Physics Lab", sub: "Integrators, modes, Lyapunov, sweeps", icon: I('<path d="M9 3h6M10 3v6L4 20h16L14 9V3"/><path d="M7 15h10"/>') },
  { id: "experiments", title: "Experiments", sub: "Reproducible experiment notebook", icon: I('<path d="M5 4h11l3 3v13H5z"/><path d="M8 9h8M8 13h8M8 17h5"/>') },
  { id: "gallery", title: "Gallery", sub: "Saved artworks with exact configurations", icon: I('<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-8 8"/>') },
  { id: "export", title: "Export Studio", sub: "GIF, MP4, WebM, PNG, SVG, CSV, JSON", icon: I('<path d="M12 3v12M7 8l5-5 5 5M5 21h14"/>') },
  { id: "challenges", title: "Challenges", sub: "Measurable experiments with feedback", icon: I('<path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/>') },
  { id: "academy", title: "Academy", sub: "Guided lessons and documentation", icon: I('<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11v5c3 2 9 2 12 0v-5"/>') },
];

let current = null, cleanup = null;

async function show(id) {
  const v = VIEWS.find((x) => x.id === id) || VIEWS[0];
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  const root = $("#view");
  root.innerHTML = "";
  root.className = "view";
  $("#view-title").textContent = v.title;
  $("#view-subtitle").textContent = v.sub;
  $("#topbar-extra").innerHTML = "";
  document.querySelectorAll(".nav-item").forEach((b) => { if (b.dataset.id !== v.id) b.removeAttribute("aria-current"); else b.setAttribute("aria-current", "page"); });
  current = v.id;
  try {
    const mod = await import(`./views/${v.id}.js`);
    if (current !== v.id) return;
    cleanup = mod.mount(root) || null;
  } catch (e) {
    console.error(e);
    root.append(h("div", { class: "note err" }, `Failed to load ${v.title}: ${e.message}`));
  }
  document.title = `${v.title} · Double Pendulum Simulator`;
}

export function navigate(id) {
  if (location.hash !== `#/${id}`) location.hash = `#/${id}`;
  else show(id);
}

function route() {
  const share = decodeShare(location.hash);
  if (share) {
    setConfig(share.config, { silent: true });
    if (share.visual) setVisual(share.visual);
    toast("Loaded shared experiment", "ok");
    history.replaceState(null, "", "#/playground");
    requestSimulation(0);
    return show("playground");
  }
  const m = /^#\/([a-z]+)/.exec(location.hash);
  show(m ? m[1] : "playground");
}

function buildNav() {
  const ul = $("#nav-list");
  VIEWS.forEach((v, i) => {
    const b = h("button", { class: "nav-item", type: "button", "data-id": v.id, title: v.title }, h("span", { html: v.icon }), h("span", { class: "nav-label" }, v.title), i < 9 ? h("kbd", {}, String(i + 1)) : null);
    b.addEventListener("click", () => navigate(v.id));
    ul.append(h("li", {}, b));
  });
  $("#btn-theme").addEventListener("click", toggleTheme);
  $("#btn-motion").addEventListener("click", toggleMotion);
  $("#btn-collapse").addEventListener("click", () => $("#app").classList.toggle("nav-collapsed"));
  $("#btn-palette").addEventListener("click", openPalette);
  $("#btn-help").addEventListener("click", showHelp);
  updateMotionLabel();
}

function toggleTheme() {
  const r = document.documentElement;
  r.dataset.theme = r.dataset.theme === "light" ? "dark" : "light";
  try { localStorage.setItem("cl.theme", r.dataset.theme); } catch {}
  bus.emit("theme", r.dataset.theme);
  if (state.sim) bus.emit("sim", state.sim); // recolour charts
}

function toggleMotion() {
  const on = document.documentElement.classList.toggle("reduced-motion");
  try { localStorage.setItem("cl.reducedMotion", on ? "1" : "0"); } catch {}
  bus.emit("motion", on);
  updateMotionLabel();
  toast(on ? "Reduced motion on: particles, motion blur and flashes disabled" : "Reduced motion off");
}
function updateMotionLabel() {
  $("#btn-motion").textContent = document.documentElement.classList.contains("reduced-motion") ? "Motion: low" : "Motion: full";
}

// ---------------- screensaver
let saverTimer = null;
function toggleSaver() {
  const app = $("#app");
  const on = !app.classList.contains("screensaver");
  app.classList.toggle("screensaver", on);
  clearInterval(saverTimer);
  if (on) {
    if (current !== "playground") navigate("playground");
    setVisual({ hud: false, trail: state.visual.trail === "lineart" ? "fade" : state.visual.trail });
    setPlaying(true);
    document.documentElement.requestFullscreen?.().catch(() => {});
    // Cycle through single-pendulum presets (no hardcoded ids: presets are data).
    const art = state.presets.filter((p) => ["playground", "studio"].includes(p.mode) && !p.config.physical.damping1 && !p.config.physical.drive_amplitude);
    let k = 0;
    saverTimer = setInterval(() => { if (art.length) { applyPreset(art[k++ % art.length]); setPlaying(true); } }, 25000);
    toast("Screensaver — press Esc to exit");
  } else {
    setVisual({ hud: true });
    if (document.fullscreenElement) document.exitFullscreen();
  }
}

// ---------------- command palette
function commands() {
  const cmds = [
    ...VIEWS.map((v) => ({ label: `Go to ${v.title}`, grp: "Navigate", run: () => navigate(v.id) })),
    { label: "Play / pause", grp: "Playback", run: togglePlay },
    { label: "Reset to t = 0", grp: "Playback", run: () => { setPlaying(false); jumpTo(0); } },
    { label: "Slow motion (0.25×)", grp: "Playback", run: () => { clock.speed = 0.25; toast("Playback 0.25×"); } },
    { label: "Normal speed (1×)", grp: "Playback", run: () => { clock.speed = 1; toast("Playback 1×"); } },
    { label: "Toggle reverse playback (recorded states)", grp: "Playback", run: () => { clock.reverse = !clock.reverse; } },
    { label: "Toggle loop", grp: "Playback", run: () => { clock.loop = !clock.loop; toast(`Loop ${clock.loop ? "on" : "off"}`); } },
    { label: "Screenshot", grp: "Capture", run: () => bus.emit("cmd:screenshot") },
    { label: "Bookmark current time", grp: "Capture", run: () => bus.emit("cmd:bookmark") },
    { label: "Export simulation data (CSV)", grp: "Capture", run: () => bus.emit("cmd:csv") },
    { label: "Quick capture: 6 s GIF", grp: "Capture", run: () => { navigate("export"); setTimeout(() => bus.emit("cmd:quickgif"), 400); } },
    { label: "Fullscreen stage", grp: "View", run: () => bus.emit("cmd:fullscreen") },
    { label: "Toggle theme", grp: "View", run: toggleTheme },
    { label: "Toggle reduced motion", grp: "View", run: toggleMotion },
    { label: "Toggle 3D presentation", grp: "View", run: () => setVisual({ render3d: !state.visual.render3d }) },
    { label: "Chaos screensaver", grp: "View", run: toggleSaver },
    { label: "Keyboard shortcuts", grp: "Help", run: showHelp },
    ...state.presets.map((p) => ({ label: `Preset: ${p.title}`, grp: "Presets", run: () => { applyPreset(p); if (current !== "playground") navigate("playground"); } })),
  ];
  return cmds;
}

function openPalette() {
  const input = h("input", { type: "search", placeholder: "Type a command, view or preset…", "aria-label": "Command" });
  const list = h("ul", { role: "listbox" });
  const box = h("div", { class: "palette" }, input, list);
  const m = modal(box);
  m.box.classList.remove("modal");
  m.box.style.background = "none"; m.box.style.border = "0"; m.box.style.boxShadow = "none"; m.box.style.padding = "0";
  const all = commands();
  let sel = 0, shown = all;
  const render = () => {
    const q = input.value.toLowerCase().trim();
    shown = q ? all.filter((c) => q.split(/\s+/).every((w) => c.label.toLowerCase().includes(w) || c.grp.toLowerCase().includes(w))) : all;
    sel = Math.min(sel, Math.max(0, shown.length - 1));
    list.innerHTML = "";
    shown.slice(0, 60).forEach((c, i) => {
      const li = h("li", { role: "option", "aria-selected": String(i === sel) }, c.label, h("span", { class: "grp" }, c.grp));
      li.addEventListener("mousedown", (e) => { e.preventDefault(); m.close(); c.run(); });
      list.append(li);
    });
  };
  input.addEventListener("input", () => { sel = 0; render(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { sel = Math.min(shown.length - 1, sel + 1); render(); e.preventDefault(); }
    if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); render(); e.preventDefault(); }
    if (e.key === "Enter" && shown[sel]) { m.close(); shown[sel].run(); }
  });
  render();
  setTimeout(() => input.focus(), 10);
}

function showHelp() {
  const rows = [["Space", "Play / pause"], ["← / →", "Step one sample (Shift: 1 s)"], ["R", "Reset to t = 0"], ["[ / ]", "Slower / faster playback"],
    ["V", "Toggle reverse playback"], ["B", "Bookmark this moment"], ["S", "Screenshot"], ["F", "Fullscreen stage"], ["T", "Toggle theme"],
    ["1–9", "Switch view"], ["⌘K / Ctrl+K", "Command palette"], ["Esc", "Close dialogs / exit screensaver"], ["?", "This help"]];
  modal(h("div", {}, h("h3", {}, "Keyboard shortcuts"),
    h("table", { class: "data" }, ...rows.map(([k, d]) => h("tr", {}, h("td", {}, h("kbd", {}, k)), h("td", {}, d)))),
    h("p", { class: "faint" }, "On the Playground stage: scroll to zoom, drag empty space to pan, double-click to reset the view. When paused, drag a mass to set the initial angles; rod lengths stay fixed.")));
}

const SPEEDS = [0.1, 0.25, 0.5, 1, 2, 4];
function keys(e) {
  const tag = (e.target.tagName || "").toLowerCase();
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
  if (e.key === "Escape" && $("#app").classList.contains("screensaver")) { toggleSaver(); return; }
  if (["input", "textarea", "select"].includes(tag) || e.metaKey || e.ctrlKey || e.altKey) return;
  if (document.querySelector(".overlay")) return;
  const k = e.key;
  if (k === " ") { e.preventDefault(); togglePlay(); }
  else if (k === "ArrowRight" && tag !== "canvas") { stepFrames(e.shiftKey ? Math.round(1 / (state.sim?.dt || 1)) : 1); e.preventDefault(); }
  else if (k === "ArrowLeft" && tag !== "canvas") { stepFrames(e.shiftKey ? -Math.round(1 / (state.sim?.dt || 1)) : -1); e.preventDefault(); }
  else if (k === "r" || k === "R") { setPlaying(false); jumpTo(0); }
  else if (k === "[" || k === "]") {
    const i = SPEEDS.indexOf(clock.speed);
    clock.speed = SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, (i < 0 ? 3 : i) + (k === "]" ? 1 : -1)))];
    toast(`Playback ${clock.speed}× (physical seconds per second)`);
  }
  else if (k === "v" || k === "V") { clock.reverse = !clock.reverse; toast(clock.reverse ? "Reverse playback of recorded states" : "Forward playback"); }
  else if (k === "b" || k === "B") bus.emit("cmd:bookmark");
  else if (k === "s" || k === "S") bus.emit("cmd:screenshot");
  else if (k === "f" || k === "F") bus.emit("cmd:fullscreen");
  else if (k === "t" || k === "T") toggleTheme();
  else if (k === "?") showHelp();
  else if (/^[1-9]$/.test(k)) navigate(VIEWS[+k - 1].id);
}

async function boot() {
  installTooltips();
  buildNav();
  document.addEventListener("keydown", keys);
  bus.on("config", () => requestSimulation());
  bus.on("cmd:saver", toggleSaver);
  try {
    const [meta, presets] = await Promise.all([api.get("/api/meta"), api.get("/api/presets")]);
    state.meta = meta;
    state.presets = presets.presets;
  } catch (e) {
    toast(`Could not reach the Double Pendulum Simulator server: ${e.message}`, "err");
  }
  window.addEventListener("hashchange", route);
  route();
  const q = new URLSearchParams(location.search);
  if (q.has("autoplay")) bus.on("sim", () => setPlaying(true));
  if (q.has("t")) bus.on("sim", () => jumpTo(+q.get("t")));
  if (q.has("preset")) {
    const p = state.presets.find((x) => x.id === q.get("preset"));
    if (p) applyPreset(p);
  }
}

boot();
