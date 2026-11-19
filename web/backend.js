// In-browser backend for the hosted web demo.
//
// The dashboard talks to a JSON API at /api/*. Locally that is the Python
// server (`python -m pendulum_sim serve`). On the static demo there is no
// server, so this module intercepts those fetch() calls and answers them by
// running the same Python package in web workers with Pyodide. The dashboard
// code itself is unchanged.
//
// It must load before js/main.js (it is the first module script on the page).

const CFG = Object.assign(
  {
    pyodide: "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/",
    zip: "pendulum_sim.zip",
    repo: "https://github.com/Krishiv-Vaid/double-pendulum",
  },
  window.PENDULUM_WEB || {},
);
const WORKER_URL = new URL("./pyworker.js", import.meta.url);
const ZIP_URL = new URL(CFG.zip, document.baseURI).href;
const MAX_QUEUED_JOBS = 6;

// ---------------------------------------------------------------- workers

class PyWorker {
  constructor(role, { persist = false, onStage } = {}) {
    this.role = role;
    this.pending = new Map();
    this.rid = 0;
    this.onJobMessage = null;
    this.worker = new Worker(WORKER_URL);
    this.ready = new Promise((resolve, reject) => {
      this.worker.onmessage = (ev) => {
        const m = ev.data;
        if (m.type === "stage") onStage && onStage(m.text);
        else if (m.type === "ready") resolve();
        else if (m.type === "fatal") reject(new Error(m.message));
        else if (m.type === "response") {
          const p = this.pending.get(m.rid);
          this.pending.delete(m.rid);
          p && p.resolve(m);
        } else if (this.onJobMessage) this.onJobMessage(m);
      };
      this.worker.onerror = (ev) => reject(new Error(ev.message || "worker failed to start"));
    });
    this.worker.postMessage({ type: "init", indexURL: CFG.pyodide, zipURL: ZIP_URL, persist });
  }

  async request(method, url, body) {
    await this.ready;
    const rid = ++this.rid;
    return new Promise((resolve, reject) => {
      this.pending.set(rid, { resolve, reject });
      this.worker.postMessage({ type: "request", rid, method, url, body }, body ? [body.buffer] : []);
    });
  }

  terminate() {
    this.worker.terminate();
    for (const p of this.pending.values()) p.reject(new Error("cancelled"));
    this.pending.clear();
  }
}

// ---------------------------------------------------------------- loading screen

const overlay = (() => {
  const el = document.createElement("div");
  el.className = "web-boot";
  el.setAttribute("role", "status");
  el.innerHTML = `
    <div class="web-boot-card">
      <svg viewBox="0 0 34 34" width="44" height="44" aria-hidden="true">
        <path d="M17 7 L11 17 L21 26" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/>
        <circle cx="17" cy="7" r="1.4" fill="currentColor" fill-opacity=".6"/>
        <circle cx="11" cy="17" r="2.6" fill="currentColor"/><circle cx="21" cy="26" r="2.6" fill="currentColor"/>
      </svg>
      <h2>Double Pendulum Simulator</h2>
      <p class="web-boot-stage">Starting…</p>
      <div class="web-boot-bar"><div></div></div>
      <p class="web-boot-note">The full Python engine runs in your browser with Pyodide.
      The first visit downloads about 30&nbsp;MB; later visits load from cache.</p>
    </div>`;
  const style = document.createElement("style");
  style.textContent = `
    .web-boot{position:fixed;inset:0;z-index:9999;display:grid;place-items:center;background:var(--bg,#000);color:var(--text,#fff);
      font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;transition:opacity .35s}
    .web-boot.done{opacity:0;pointer-events:none}
    .web-boot-card{max-width:380px;padding:28px;text-align:center}
    .web-boot-card h2{margin:12px 0 6px;font-size:18px;font-weight:600}
    .web-boot-stage{margin:0 0 14px;opacity:.85}
    .web-boot-bar{height:2px;background:currentColor;opacity:.15;border-radius:2px;overflow:hidden;position:relative}
    .web-boot-bar>div{position:absolute;inset:0;width:30%;background:currentColor;animation:web-boot-slide 1.3s ease-in-out infinite}
    .web-boot-note{margin-top:16px;font-size:12px;opacity:.6}
    .web-boot-note a{color:inherit}
    .web-boot.err .web-boot-bar{display:none}
    @keyframes web-boot-slide{0%{left:-30%}100%{left:100%}}
    .web-badge{display:block;margin:6px 0 2px;font-size:11px;line-height:1.4;opacity:.6;color:inherit;text-decoration:none}
    .web-badge:hover{opacity:1;text-decoration:underline}
    .app.nav-collapsed .web-badge{display:none}`;
  const mount = () => document.body.append(el);
  document.head.append(style);
  if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount, { once: true });
  const stageEl = el.querySelector(".web-boot-stage");
  return {
    stage: (t) => { stageEl.textContent = t + "…"; },
    done: () => { el.classList.add("done"); setTimeout(() => el.remove(), 400); },
    fail: (msg) => {
      el.classList.add("err");
      stageEl.textContent = "The in-browser engine could not start.";
      el.querySelector(".web-boot-note").innerHTML =
        `${escapeHtml(msg)}<br><br>Try a recent version of Chrome, Firefox, Safari or Edge, or run it locally: ` +
        `<a href="${CFG.repo}#30-second-quick-start">quick start</a>.`;
    },
  };
})();

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

const main = new PyWorker("sync", { persist: true, onStage: overlay.stage });
main.ready.then(() => { overlay.done(); addBadge(); }, (e) => overlay.fail(e.message));

function addBadge() {
  const foot = document.querySelector(".nav-foot");
  if (!foot || foot.querySelector(".web-badge")) return;
  const a = document.createElement("a");
  a.className = "web-badge";
  a.href = CFG.repo + "#30-second-quick-start";
  a.target = "_blank";
  a.rel = "noopener";
  a.textContent = "Web demo · runs in your browser. Install locally for full speed and MP4 export ↗";
  foot.prepend(a);
}

// ---------------------------------------------------------------- background jobs

const jobs = new Map();
const queued = [];
let jobWorker = null;
let running = null;

function newId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => b.toString(16).padStart(2, "0")).join("");
}

function jobInfo(job, includePartial) {
  const d = {
    id: job.id, kind: job.kind, status: job.status, progress: Math.round(job.progress * 1e4) / 1e4,
    message: job.message, elapsed_s: Math.round(((job.finished || Date.now()) - job.created)) / 1000,
  };
  if (job.status === "done") d.result = job.result;
  else if (includePartial && job.partial != null) {
    if (typeof job.partial === "string") job.partial = JSON.parse(job.partial);
    d.partial = job.partial;
  }
  return d;
}

function ensureJobWorker() {
  if (jobWorker) return jobWorker;
  jobWorker = new PyWorker("job");
  jobWorker.onJobMessage = (m) => {
    const job = jobs.get(m.jid);
    if (!job || job.status !== "running") return;
    if (m.type === "progress") {
      job.progress = m.progress;
      if (m.partial != null) job.partial = m.partial;
      if (m.message != null) job.message = m.message;
    } else if (m.type === "jobdone") {
      const out = JSON.parse(m.outcome);
      job.status = out.status;
      if (out.status === "done") { job.result = out.result; job.progress = 1; }
      else job.message = out.message || "job failed";
      job.partial = null;
      job.finished = Date.now();
      running = null;
      pump();
    }
  };
  jobWorker.ready.catch((e) => {
    // the worker could not start: fail everything waiting on it
    for (const id of [running, ...queued.splice(0)]) {
      const job = id && jobs.get(id);
      if (job) Object.assign(job, { status: "error", message: e.message, finished: Date.now() });
    }
    running = null;
    jobWorker = null;
  });
  return jobWorker;
}

function pump() {
  if (running || !queued.length) return;
  const job = jobs.get(queued.shift());
  running = job.id;
  const w = ensureJobWorker();
  w.ready.then(() => w.worker.postMessage({ type: "job", jid: job.id, kind: job.kind, body: job.body }), () => {});
}

function cancelJob(id) {
  const job = jobs.get(id);
  if (!job || job.status !== "running") return false;
  Object.assign(job, { status: "cancelled", message: "cancelled", partial: null, finished: Date.now() });
  const qi = queued.indexOf(id);
  if (qi >= 0) queued.splice(qi, 1);
  if (running === id) {
    // Python cannot be interrupted mid-job here, so stop the worker; a fresh one starts for the next job.
    jobWorker.terminate();
    jobWorker = null;
    running = null;
    pump();
  }
  return true;
}

function jobsRoute(method, parts, url, bodyText) {
  if (method === "POST" && parts.length === 3) {
    const waiting = queued.length + (running ? 1 : 0);
    if (waiting >= MAX_QUEUED_JOBS) return json({ error: `too many running jobs (limit ${MAX_QUEUED_JOBS}); cancel one or wait` }, 429);
    const job = { id: newId(), kind: parts[2], body: bodyText || "{}", status: "running", progress: 0, message: "",
                  result: null, partial: null, created: Date.now(), finished: null };
    jobs.set(job.id, job);
    queued.push(job.id);
    pump();
    return json(jobInfo(job, false), 202);
  }
  if (method === "GET" && parts.length === 2) return json({ jobs: [...jobs.values()].map((j) => jobInfo(j, false)) });
  const job = jobs.get(parts[2]);
  if (!job) return json({ error: `not found: '${parts[2]}'` }, 404);
  if (method === "GET") return json(jobInfo(job, url.searchParams.get("partial") === "1"));
  if (method === "DELETE") return json({ cancelled: cancelJob(job.id) });
  return json({ error: "unknown endpoint" }, 404);
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}

// ---------------------------------------------------------------- fetch shim

const realFetch = window.fetch.bind(window);

async function bodyBytes(body) {
  if (body == null) return null;
  if (typeof body === "string") return new TextEncoder().encode(body);
  if (body instanceof Blob) return new Uint8Array(await body.arrayBuffer());
  if (body instanceof ArrayBuffer) return new Uint8Array(body.slice(0));
  if (ArrayBuffer.isView(body)) return new Uint8Array(body.buffer.slice(body.byteOffset, body.byteOffset + body.byteLength));
  return new TextEncoder().encode(String(body));
}

window.fetch = async function (input, init = {}) {
  const req = input instanceof Request ? input : null;
  const url = new URL(req ? req.url : String(input), location.href);
  if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return realFetch(input, init);
  if (init.signal && init.signal.aborted) throw new DOMException("Aborted", "AbortError");
  const method = (init.method || (req && req.method) || "GET").toUpperCase();
  let body = await bodyBytes(init.body ?? (req && method !== "GET" ? await req.arrayBuffer() : null));
  const parts = url.pathname.split("/").filter(Boolean);
  if (parts[1] === "jobs") {
    try {
      return await jobsRoute(method, parts, url, body ? new TextDecoder().decode(body) : "");
    } catch (e) {
      return json({ error: e.message }, 500);
    }
  }
  if (!body || !body.byteLength) body = null;
  const r = await main.request(method, url.pathname + url.search, body);
  return new Response(r.body, { status: r.status, headers: { "Content-Type": r.ctype } });
};

window.PENDULUM_WEB_BACKEND = { ready: main.ready, jobs };
