// Simulation service: debounced requests, race-safe updates, playback loop.

import { api } from "./api.js";
import { bus, clock, ingestSim, state } from "./state.js";
import { toast } from "./ui.js";

let seq = 0;
let timer = null;

export async function runSimulation(cfg = state.config, { keepTime = false } = {}) {
  const my = ++seq;
  bus.emit("sim:loading", true);
  const t0 = performance.now();
  try {
    const r = await api.post("/api/simulate", { config: cfg });
    if (my !== seq) return null; // a newer request superseded this one
    const s = ingestSim(r);
    s.requestMs = performance.now() - t0;
    if (state.sim && state.sim.digest !== s.digest) state.ghost = state.sim;
    state.sim = s;
    if (!keepTime || clock.t > s.tEnd) clock.set(0);
    try { // recent-experiments history (configs only)
      const hist = JSON.parse(localStorage.getItem("cl.history") || "[]").filter((x) => x.digest !== s.digest);
      hist.unshift({ digest: s.digest, config: s.config, at: Date.now() });
      localStorage.setItem("cl.history", JSON.stringify(hist.slice(0, 20)));
    } catch {}
    bus.emit("sim", s);
    return s;
  } catch (e) {
    if (my === seq) toast(`Simulation failed: ${e.message}`, "err");
    return null;
  } finally {
    if (my === seq) bus.emit("sim:loading", false);
  }
}

export function requestSimulation(delay = 220) {
  clearTimeout(timer);
  timer = setTimeout(() => runSimulation(state.config), delay);
}

// ---- global animation loop: one RAF drives every visible view ----
let last = performance.now();
let fpsAcc = 0, fpsN = 0;
export const perf = { fps: 0 };

function loop(now) {
  const dtWall = Math.min(0.1, (now - last) / 1000);
  last = now;
  fpsAcc += dtWall; fpsN++;
  if (fpsAcc > 0.5) { perf.fps = fpsN / fpsAcc; fpsAcc = 0; fpsN = 0; }
  const s = state.sim;
  if (clock.playing && s) {
    let t = clock.t + dtWall * clock.speed * (clock.reverse ? -1 : 1);
    if (t > s.tEnd) {
      if (clock.loop) t = 0; else { t = s.tEnd; clock.playing = false; bus.emit("play", false); }
    } else if (t < 0) {
      if (clock.loop) t = s.tEnd; else { t = 0; clock.playing = false; bus.emit("play", false); }
    }
    clock.t = t;
  }
  bus.emit("frame", clock.t, dtWall);
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);

export function setPlaying(p) {
  clock.playing = p;
  bus.emit("play", p);
}

export function togglePlay() { setPlaying(!clock.playing); }

export function stepFrames(n) {
  const s = state.sim;
  if (!s) return;
  setPlaying(false);
  clock.set(Math.max(0, Math.min(s.tEnd, clock.t + n * s.dt)));
}

export function jumpTo(t) {
  const s = state.sim;
  if (!s) return;
  clock.set(Math.max(0, Math.min(s.tEnd, t)));
}
