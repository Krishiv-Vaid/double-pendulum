// Stage: a canvas viewport hosting a PendulumRenderer, with HUD, toolbar and
// pointer interaction (zoom, pan, orbit, drag-to-set-initial-angles).

import { download } from "./api.js";
import { PendulumRenderer } from "./renderer.js";
import { bus, state } from "./state.js";
import { ICONS, btn, h, toast } from "./ui.js";

export class Stage {
  constructor(container, { hud = true, toolbar = true, draggable = false, onDragEnd, extraTools = [] } = {}) {
    this.canvas = h("canvas", { "aria-label": "Pendulum animation", role: "img" });
    this.hud = h("div", { class: "hud", "aria-live": "off" });
    this.loading = h("div", { class: "loading hidden" }, h("div", {}, h("div", { class: "spinner" }), h("div", { class: "msg" }, "Integrating…")));
    this.badge = h("div", { class: "badge-bl" });
    const tools = h("div", { class: "toolbar hide-in-saver" },
      ...extraTools,
      toolbar ? btn("", () => this.screenshot(), { cls: "sm icon", tip: "Screenshot (S)", icon: ICONS.camera }) : null,
      toolbar ? btn("", () => this.fullscreen(), { cls: "sm icon", tip: "Fullscreen (F)", icon: ICONS.full }) : null);
    this.el = h("div", { class: "stage" }, this.canvas, hud ? this.hud : null, tools, this.badge, this.loading);
    container.append(this.el);
    this.r = new PendulumRenderer(this.canvas);
    this.r.reducedMotion = document.documentElement.classList.contains("reduced-motion");
    this.r.setVisual(state.visual);
    this.draggable = draggable;
    this.onDragEnd = onDragEnd;
    this.hud.style.display = state.visual.hud && hud ? "" : "none";
    this.unsubs = [
      bus.on("visual", (v) => { this.r.setVisual(v); this.hud.style.display = v.hud && hud ? "" : "none"; }),
      bus.on("motion", (rm) => { this.r.reducedMotion = rm; }),
    ];
    this.bindPointer();
  }

  setLoading(on, msg = "Integrating…") {
    this.loading.classList.toggle("hidden", !on);
    this.loading.querySelector(".msg").textContent = msg;
  }

  bindPointer() {
    const c = this.canvas;
    let drag = null;
    c.addEventListener("pointerdown", (e) => {
      const r = c.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      const hit = this.draggable && !state.visual.render3d && this.canDrag && this.canDrag() ? this.r.hitTest(px, py) : null;
      c.setPointerCapture(e.pointerId);
      drag = { hit, x: e.clientX, y: e.clientY, pan: { ...this.r.pan }, yaw: this.r.yaw, pitch: this.r.pitch };
      if (hit) {
        const s = this.r.bodies[0].s;
        const fi = Math.max(0, Math.min(s.n - 1, (this.lastT || 0) / s.dt));
        this.r.override = { th1: s.th1[Math.floor(fi)], th2: s.th2[Math.floor(fi)] };
        c.style.cursor = "grabbing";
      }
    });
    c.addEventListener("pointermove", (e) => {
      const r = c.getBoundingClientRect();
      if (!drag) {
        if (this.draggable && this.canDrag && this.canDrag()) c.style.cursor = this.r.hitTest(e.clientX - r.left, e.clientY - r.top) ? "grab" : "default";
        return;
      }
      if (drag.hit) {
        const [wx, wy] = this.r.toWorld(e.clientX - r.left, e.clientY - r.top);
        const p = this.r.bodies[0].s.p;
        const o = this.r.override;
        if (drag.hit === "bob1") o.th1 = Math.atan2(wx, -wy);
        else {
          // keep rod lengths fixed: lower angle measured from the elbow
          const ex = p.L1 * Math.sin(o.th1), ey = -p.L1 * Math.cos(o.th1);
          o.th2 = Math.atan2(wx - ex, -(wy - ey));
        }
        this.redraw && this.redraw();
      } else if (state.visual.render3d) {
        this.r.yaw = drag.yaw + (e.clientX - drag.x) * 0.008;
        this.r.pitch = Math.max(-0.2, Math.min(1.3, drag.pitch + (e.clientY - drag.y) * 0.006));
        this.redraw && this.redraw();
      } else {
        this.r.pan = { x: drag.pan.x + (e.clientX - drag.x), y: drag.pan.y + (e.clientY - drag.y) };
        this.redraw && this.redraw();
      }
    });
    c.addEventListener("pointerup", () => {
      if (drag && drag.hit && this.r.override) {
        const o = this.r.override;
        this.onDragEnd && this.onDragEnd((o.th1 * 180) / Math.PI, (o.th2 * 180) / Math.PI);
      }
      drag = null;
      c.style.cursor = "default";
    });
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      const z = Math.max(0.2, Math.min(8, (state.visual.zoom || 1) * (e.deltaY > 0 ? 0.9 : 1.1)));
      state.visual.zoom = z;
      this.r.setVisual(state.visual);
      this.redraw && this.redraw();
    }, { passive: false });
    c.addEventListener("dblclick", () => { this.r.resetView(); state.visual.zoom = 1; this.r.setVisual(state.visual); this.redraw && this.redraw(); });
  }

  draw(t, dtWall) { this.lastT = t; this.r.draw(t, dtWall); }

  screenshot(name = "chaos-lab") {
    this.canvas.toBlob((b) => { download(b, `${name}-${Date.now()}.png`); toast("Screenshot saved", "ok"); }, "image/png");
  }

  fullscreen() {
    if (document.fullscreenElement) document.exitFullscreen();
    else this.el.requestFullscreen?.().catch(() => toast("Fullscreen not available", "err"));
  }

  destroy() { this.unsubs.forEach((u) => u()); }
}
