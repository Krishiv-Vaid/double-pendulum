// Chaos Challenges: measurable goals with scientific feedback (no points).

import { api } from "../api.js";
import { setConfig, state } from "../state.js";
import { btn, fmtSig, h, panel, toast } from "../ui.js";

export const meta = { id: "challenges" };

const INPUTS = {
  theta1_deg: { label: "θ₁(0) [deg]", type: "number", value: 120, step: 0.1 },
  theta2_deg: { label: "θ₂(0) [deg]", type: "number", value: -10, step: 0.1 },
  epsilon: { label: "θ₁ offset ε [rad]", type: "number", value: 1e-6, step: "any" },
  method: { label: "Integrator", type: "select", options: ["rk4", "rk45", "dop853"], value: "rk4" },
  dt: { label: "RK4 step [s]", type: "number", value: 0.001, step: "any" },
  rtol: { label: "Tolerance (adaptive)", type: "number", value: 1e-8, step: "any" },
  quadrant: { label: "Your prediction", type: "select", options: ["upper-left", "upper-right", "lower-left", "lower-right"], value: "lower-left" },
  answer: { label: "Which run is under-resolved?", type: "select", options: [["rk4", "Run A: RK4, Δt = 0.05 s"], ["dop853", "Run B: DOP853, rtol = 1e-10"]], value: "rk4" },
};

export function mount(root) {
  const grid = h("div", { class: "grid-auto", style: { gridTemplateColumns: "repeat(auto-fill, minmax(330px, 1fr))" } });
  root.append(h("div", { class: "note", style: { marginBottom: "14px" } },
    "Each challenge runs a real simulation on the server and explains why the result happened. There are no scores: the physics is the feedback."), grid);
  api.get("/api/challenges").then(({ challenges }) => {
    challenges.forEach((c, i) => grid.append(card(c, i + 1)));
  }).catch((e) => toast(e.message, "err"));

  function card(c, n) {
    const fields = {};
    const form = h("div", { style: { display: "grid", gap: "8px" } });
    for (const key of c.inputs) {
      const spec = INPUTS[key] || { label: key, type: "text", value: "" };
      let el;
      if (spec.type === "select") {
        el = h("select", {}, ...spec.options.map((o) => (Array.isArray(o) ? h("option", { value: o[0] }, o[1]) : h("option", { value: o }, o))));
        el.value = spec.value;
      } else {
        el = h("input", { type: spec.type, step: spec.step });
        el.value = key in state.config.initial ? state.config.initial[key] : spec.value;
      }
      fields[key] = el;
      form.append(h("div", { class: "field" }, h("label", {}, spec.label), el));
    }
    const out = h("div");
    const go = btn("Run", async () => {
      go.disabled = true;
      const body = {};
      for (const [k, el] of Object.entries(fields)) body[k] = el.type === "number" ? parseFloat(el.value) : el.value;
      out.innerHTML = "";
      out.append(h("div", { class: "faint" }, "simulating…"));
      try {
        const r = await api.post(`/api/challenges/${c.id}`, body);
        out.innerHTML = "";
        out.append(h("div", { class: `note ${r.success ? "ok" : "warn"}` }, h("b", {}, r.success ? "Goal reached. " : "Not yet. "), r.feedback),
          Object.keys(r.metrics || {}).length ? h("dl", { class: "kv", style: { marginTop: "8px" } }, ...Object.entries(r.metrics).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, typeof v === "number" ? fmtSig(v, 4) : Array.isArray(v) ? v.map((x) => fmtSig(x, 3)).join(", ") : String(v))])) : null);
      } catch (e) { out.innerHTML = ""; out.append(h("div", { class: "note err" }, e.message)); }
      go.disabled = false;
    }, { cls: "primary sm" });
    const tryIt = "theta1_deg" in fields ? btn("Open in Playground", () => {
      const cfg = JSON.parse(JSON.stringify(state.config));
      cfg.initial.theta1_deg = parseFloat(fields.theta1_deg.value); cfg.initial.theta2_deg = parseFloat(fields.theta2_deg.value);
      cfg.initial.omega1 = 0; cfg.initial.omega2 = 0; cfg.name = c.title;
      setConfig(cfg); location.hash = "#/playground";
    }, { cls: "sm" }) : null;
    return panel(`${n}. ${c.title}`, h("div", { style: { display: "grid", gap: "10px" } }, h("p", { class: "muted", style: { margin: 0 } }, c.goal), form, h("div", { class: "btn-row" }, go, tryIt), out));
  }
}
