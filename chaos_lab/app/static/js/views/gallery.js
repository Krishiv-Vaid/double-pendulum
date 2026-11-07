// Gallery of saved artworks, each with its exact reproducible configuration.

import { api, download } from "../api.js";
import { sanitizeVisual, setConfig, setVisual } from "../state.js";
import { btn, fmt, h, modal, toast } from "../ui.js";

export const meta = { id: "gallery" };

export function mount(root) {
  const grid = h("div", { class: "grid-auto", style: { gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" } });
  root.append(h("div", { class: "note", style: { marginBottom: "14px" } },
    "Artworks rendered in Chaos Studio. Each image is stored with the exact simulation configuration and visual settings that produced it; “Reproduce” reloads both."), grid);
  async function refresh() {
    grid.innerHTML = "";
    let arts = [];
    try { arts = (await api.get("/api/gallery")).artworks; } catch (e) { toast(e.message, "err"); }
    if (!arts.length) grid.append(h("div", { class: "empty" }, "No artworks yet. Open Chaos Studio and choose “Save to gallery”."));
    for (const a of arts) {
      const src = `/api/gallery/${a.id}/image`;
      const img = h("img", { class: "thumb", src, alt: a.title, loading: "lazy", style: { cursor: "zoom-in" } });
      img.addEventListener("click", () => modal(h("div", {}, h("img", { src, alt: a.title, style: { width: "100%", borderRadius: "10px" } }),
        h("pre", { class: "mono", style: { fontSize: "11px", whiteSpace: "pre-wrap", color: "var(--text-2)" } }, JSON.stringify(a.config, null, 2)))));
      const c = a.config;
      grid.append(h("article", { class: "card" }, img, h("div", { class: "card-body" },
        h("h4", {}, a.title),
        h("p", { class: "mono", style: { fontSize: "11.5px" } }, `${a.width}×${a.height} · 0–${fmt(a.t_end, 1)} s · θ₁ ${c.initial.theta1_deg}°, θ₂ ${c.initial.theta2_deg}°`),
        h("p", { class: "faint mono", style: { fontSize: "11px" } }, `digest ${a.digest} · ${new Date(a.created * 1000).toLocaleString()}`),
        h("div", { class: "btn-row" },
          btn("Reproduce", () => { setConfig(a.config); if (a.visual) setVisual(sanitizeVisual(a.visual)); location.hash = "#/studio"; }, { cls: "sm primary" }),
          btn("Download", async () => download(await (await fetch(src)).blob(), `${a.title.replace(/\W+/g, "-")}-${a.width}x${a.height}.png`), { cls: "sm" }),
          btn("Config", () => download(new Blob([JSON.stringify(a, null, 2)], { type: "application/json" }), `${a.id}.json`), { cls: "sm" }),
          btn("Delete", async () => { if (confirm("Delete this artwork?")) { await api.del(`/api/gallery/${a.id}`); refresh(); } }, { cls: "sm danger" })))));
    }
  }
  refresh();
}
