// Experiment Notebook: save, tag, favourite, duplicate, import/export, compare.

import { api, download } from "../api.js";
import { LineChart } from "../charts.js";
import { token } from "../palettes.js";
import { PendulumRenderer } from "../renderer.js";
import { bus, cloneDeep, ingestSim, mergeConfig, sanitizeVisual, setConfig, setVisual, state } from "../state.js";
import { btn, check, fmt, fmtSig, h, modal, panel, textField, toast } from "../ui.js";

export const meta = { id: "experiments" };

export function saveExperimentDialog(extra = {}) {
  const f = {
    name: textField("Name", state.config.name),
    description: textField("Description", "", null, { multiline: true }),
    tags: textField("Tags (comma separated)", (state.activePreset ? [state.activePreset] : []).join(", ")),
    notes: textField("Notes", "", null, { multiline: true }),
  };
  const fav = h("input", { type: "checkbox" });
  const m = modal(h("div", { style: { display: "grid", gap: "10px" } },
    h("h3", {}, "Save experiment"),
    h("p", { class: "faint", style: { margin: 0 } }, "Stores the exact configuration, visual settings and a result summary. Trajectories are recomputed deterministically on load, so they are not stored."),
    f.name, f.description, f.tags, f.notes, h("label", { class: "check" }, fav, "Favourite"),
    h("div", { class: "btn-row" }, btn("Save", async () => {
      const cfg = cloneDeep(state.config);
      cfg.name = f.name.input.value || cfg.name;
      const body = {
        name: cfg.name, description: f.description.input.value, notes: f.notes.input.value,
        tags: f.tags.input.value.split(",").map((s) => s.trim()).filter(Boolean), favorite: fav.checked,
        config: cfg, visual: state.visual, mode: extra.mode || "playground", extra: extra.extra || {},
        results: state.sim ? { summary: state.sim.summary, rotations: state.sim.rotations } : {},
      };
      try { await api.post("/api/experiments", body); toast("Experiment saved", "ok"); m.close(); bus.emit("experiments:changed"); }
      catch (e) { toast(e.message, "err"); }
    }, { cls: "primary" }), btn("Cancel", () => m.close(), { cls: "ghost" }))));
}

export function mount(root) {
  let all = [];
  const selected = new Set();
  const search = h("input", { type: "search", placeholder: "Search name, tags, notes…", "aria-label": "Search experiments" });
  let favOnly = false;
  const list = h("div", { class: "grid-auto" });
  const compareBox = h("div");
  const fileIn = h("input", { type: "file", accept: "application/json,.json", class: "hidden" });
  fileIn.addEventListener("change", async () => {
    const file = fileIn.files[0];
    if (!file) return;
    try {
      const d = JSON.parse(await file.text());
      const items = Array.isArray(d) ? d : d.experiments || [d];
      for (const x of items) await api.post("/api/experiments", { ...x, id: undefined, created: undefined });
      toast(`Imported ${items.length} experiment(s)`, "ok");
      refresh();
    } catch (e) { toast(`Import failed: ${e.message}`, "err"); }
    fileIn.value = "";
  });
  const history = h("div", { class: "events" });

  const left = h("div", { class: "col" },
    panel("Notebook", h("div", { style: { display: "grid", gap: "10px" } },
      btn("Save current experiment", () => saveExperimentDialog(), { cls: "primary" }),
      search, check("Favourites only", false, (v) => { favOnly = v; render(); }),
      h("div", { class: "btn-row" }, btn("Import JSON", () => fileIn.click(), { cls: "sm" }), btn("Export all", () => download(new Blob([JSON.stringify({ experiments: all }, null, 2)], { type: "application/json" }), "chaos-lab-experiments.json"), { cls: "sm" })),
      fileIn)),
    panel("Recent runs", history),
    panel("Storage", h("div", { class: "faint", style: { fontSize: "12px" } }, "Experiments live in ~/.chaos_lab/experiments as JSON (override with CHAOS_LAB_HOME). Large numerical results are exported separately as CSV and never stored in configuration files.")));
  search.addEventListener("input", render);
  root.append(h("div", { class: "layout-2" }, left, h("div", { class: "col" }, compareBox, list)));

  function renderHistory() {
    history.innerHTML = "";
    let hist = [];
    try { hist = JSON.parse(localStorage.getItem("cl.history") || "[]"); } catch {}
    if (!hist.length) history.append(h("div", { class: "faint" }, "Runs you simulate appear here."));
    for (const r of hist) history.append(h("li", {}, h("button", { type: "button", onclick: () => { setConfig(r.config); location.hash = "#/playground"; } },
      h("span", { class: "mono faint" }, new Date(r.at).toLocaleTimeString()), r.config.name, h("span", { class: "faint mono" }, r.digest.slice(0, 6)))));
  }

  async function refresh() {
    try { all = (await api.get("/api/experiments")).experiments; } catch (e) { toast(e.message, "err"); all = []; }
    render();
  }

  function render() {
    const q = search.value.toLowerCase();
    const shown = all.filter((e) => (!favOnly || e.favorite) && (!q || [e.name, e.description, e.notes, ...(e.tags || [])].join(" ").toLowerCase().includes(q)));
    list.innerHTML = "";
    if (!shown.length) list.append(h("div", { class: "empty" }, all.length ? "No experiments match." : "No saved experiments yet. Save one from the Playground or here."));
    for (const e of shown) {
      const c = e.config;
      const sel = h("input", { type: "checkbox", "aria-label": "Select for comparison" });
      sel.checked = selected.has(e.id);
      sel.addEventListener("change", () => { sel.checked ? selected.add(e.id) : selected.delete(e.id); renderCompare(); card.classList.toggle("selected", sel.checked); });
      const star = h("button", { class: "btn ghost sm", type: "button", "aria-label": "Toggle favourite", "data-tip": "Favourite" }, e.favorite ? "★" : "☆");
      star.addEventListener("click", async () => { await api.put(`/api/experiments/${e.id}`, { ...e, favorite: !e.favorite }); refresh(); });
      const card = h("article", { class: `card ${selected.has(e.id) ? "selected" : ""}` },
        h("div", { class: "card-body" },
          h("div", { class: "field-row" }, h("h4", {}, e.name), star),
          e.description ? h("p", {}, e.description) : null,
          h("div", { class: "btn-row" }, ...(e.tags || []).map((t) => h("span", { class: "tag accent" }, t))),
          h("dl", { class: "kv" },
            h("dt", {}, "θ₁, θ₂"), h("dd", {}, `${c.initial.theta1_deg}°, ${c.initial.theta2_deg}°`),
            h("dt", {}, "m, L"), h("dd", {}, `${c.physical.m1}/${c.physical.m2} kg · ${c.physical.L1}/${c.physical.L2} m`),
            h("dt", {}, "g"), h("dd", {}, `${c.physical.g} m/s²`),
            h("dt", {}, "numerics"), h("dd", {}, `${c.numerics.method} · ${c.numerics.t_max} s`),
            e.results && e.results.summary ? [h("dt", {}, "max |ΔE|"), h("dd", {}, fmtSig(e.results.summary.max_abs_rel_energy_error, 2))] : null,
            h("dt", {}, "digest"), h("dd", {}, e.digest)),
          e.notes ? h("p", { class: "faint" }, e.notes) : null,
          h("div", { class: "btn-row" },
            h("label", { class: "check" }, sel, "Compare"),
            btn("Load", () => { setConfig(e.config); if (e.visual) setVisual(sanitizeVisual(e.visual)); location.hash = `#/${["butterfly", "fractal", "studio", "phase", "lab"].includes(e.mode) ? e.mode : "playground"}`; }, { cls: "sm primary" }),
            btn("Duplicate", async () => { await api.post(`/api/experiments/${e.id}/duplicate`, {}); refresh(); }, { cls: "sm" }),
            btn("JSON", () => download(new Blob([JSON.stringify(e, null, 2)], { type: "application/json" }), `${e.name.replace(/\W+/g, "-")}.json`), { cls: "sm" }),
            btn("Delete", async () => { if (confirm(`Delete “${e.name}”?`)) { await api.del(`/api/experiments/${e.id}`); selected.delete(e.id); refresh(); } }, { cls: "sm danger" })),
          h("div", { class: "faint", style: { fontSize: "11px" } }, `saved ${new Date(e.updated * 1000).toLocaleString()}`)));
      list.append(card);
    }
    renderCompare();
  }

  let cmp = null;
  async function renderCompare() {
    if (cmp) { cmp(); cmp = null; }
    compareBox.innerHTML = "";
    const ids = [...selected];
    if (ids.length !== 2) {
      if (ids.length) compareBox.append(h("div", { class: "note" }, "Select exactly two experiments to compare them side by side."));
      return;
    }
    const [a, b] = ids.map((id) => all.find((e) => e.id === id));
    const rows = [];
    for (const sec of ["physical", "initial", "numerics"]) for (const k of Object.keys(a.config[sec])) {
      const va = a.config[sec][k], vb = b.config[sec][k];
      rows.push(h("tr", { style: { color: va === vb ? "var(--text-3)" : "var(--text)" } }, h("td", {}, `${sec}.${k}`), h("td", { class: "num" }, String(va)), h("td", { class: "num" }, String(vb))));
    }
    const ca = h("canvas"), cb = h("canvas");
    const sa = h("div", { class: "stage", style: { minHeight: "320px" } }, ca), sb = h("div", { class: "stage", style: { minHeight: "320px" } }, cb);
    const chartBox = h("div");
    compareBox.append(panel(`Compare: ${a.name} vs ${b.name}`, h("div", { style: { display: "grid", gap: "12px" } },
      h("div", { class: "split" }, sa, sb), chartBox,
      h("details", {}, h("summary", { class: "faint" }, "Configuration differences"),
        h("table", { class: "data" }, h("tr", {}, h("th", {}, "field"), h("th", {}, a.name), h("th", {}, b.name)), ...rows)))));
    const ra = new PendulumRenderer(ca), rb = new PendulumRenderer(cb);
    ra.setVisual(state.visual); rb.setVisual(state.visual);
    let t = 0, alive = true, last = performance.now();
    try {
      const [xa, xb] = await Promise.all([a, b].map((e) => api.post("/api/simulate", { config: mergeConfig(e.config) })));
      if (!alive) return;
      const s1 = ingestSim(xa), s2 = ingestSim(xb);
      ra.setBodies([s1]); rb.setBodies([s2]);
      const ch = new LineChart(chartBox, { title: "Energy error (synchronized clock)", compact: true });
      ch.set([{ x: s1.t, y: s1.err, color: token("cyan"), label: a.name }, { x: s2.t, y: s2.err, color: token("pink"), label: b.name }]);
      const tEnd = Math.min(s1.tEnd, s2.tEnd);
      const off = bus.on("frame", () => {
        const now = performance.now(); t += (now - last) / 1000; last = now;
        if (t > tEnd) t = 0;
        ra.draw(t, 1 / 60); rb.draw(t, 1 / 60); ch.setCursor(t);
      });
      cmp = () => { alive = false; off(); ch.destroy(); };
    } catch (e) { toast(e.message, "err"); }
    if (!cmp) cmp = () => { alive = false; };
  }

  const unsub = bus.on("experiments:changed", refresh);
  renderHistory();
  refresh();
  return () => { unsub(); if (cmp) cmp(); };
}

void fmt;
