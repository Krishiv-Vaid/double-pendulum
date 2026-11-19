// Web worker that runs the pendulum_sim Python package with Pyodide.
//
// Two of these run in the web demo: a "sync" worker that answers ordinary API
// requests, and a "job" worker for long background jobs (chaos maps, Lyapunov
// scans, ...), so the playground stays responsive while a job runs.
//
// Messages in:  {type: "init", indexURL, zipURL, persist}
//               {type: "request", rid, method, url, body: Uint8Array|null}
//               {type: "job", jid, kind, body: string}
// Messages out: {type: "stage", text} during start-up, then {type: "ready"} or {type: "fatal", message}
//               {type: "response", rid, status, ctype, body: Uint8Array}
//               {type: "progress", jid, progress, partial: string|null, message}
//               {type: "jobdone", jid, outcome: string}

/* global loadPyodide, importScripts */

const LAZY_PACKAGES = { PIL: "pillow", matplotlib: "matplotlib" };
const DATA_DIR = "/data";

let py = null;
let browser = null;
let persist = false;
let queue = Promise.resolve();

const stage = (text) => postMessage({ type: "stage", text });

async function init({ indexURL, zipURL, persist: wantPersist }) {
  stage("Downloading Python runtime");
  importScripts(indexURL + "pyodide.js");
  py = await loadPyodide({ indexURL });
  stage("Loading NumPy and SciPy");
  await py.loadPackage(["numpy", "scipy"]);
  stage("Loading the simulator");
  const zip = await fetch(zipURL);
  if (!zip.ok) throw new Error(`could not download ${zipURL} (HTTP ${zip.status})`);
  py.unpackArchive(await zip.arrayBuffer(), "zip", { extractDir: "/home/pyodide/app" });

  persist = !!wantPersist && typeof indexedDB !== "undefined";
  py.FS.mkdirTree(DATA_DIR);
  if (persist) {
    try {
      py.FS.mount(py.FS.filesystems.IDBFS, {}, DATA_DIR);
      await syncfs(true);
    } catch (e) {
      persist = false; // private browsing etc.: keep data for this session only
    }
  }
  py.runPython(`
import os, sys
sys.path.insert(0, "/home/pyodide/app")
os.environ["PENDULUM_SIM_HOME"] = "${DATA_DIR}"
os.environ["MPLBACKEND"] = "Agg"
`);
  browser = py.pyimport("pendulum_sim.app.browser");
  postMessage({ type: "ready", version: py.version });
}

function syncfs(populate) {
  return new Promise((resolve, reject) => py.FS.syncfs(populate, (err) => (err ? reject(err) : resolve())));
}

/** Call fn(); if Python raises ModuleNotFoundError for a package Pyodide ships, load it and retry. */
async function withLazyPackages(fn) {
  for (let attempt = 0; ; attempt++) {
    try {
      return fn();
    } catch (e) {
      const m = /ModuleNotFoundError: No module named '([\w]+)/.exec(String(e && e.message));
      const pkg = m && LAZY_PACKAGES[m[1]];
      if (!pkg || attempt >= 2) throw e;
      stage(`Loading ${pkg}`);
      await py.loadPackage(pkg);
    }
  }
}

async function onRequest({ rid, method, url, body }) {
  let status = 500, ctype = "application/json", out;
  try {
    const res = await withLazyPackages(() => browser.handle(method, url, body || null));
    const js = res.toJs();
    res.destroy();
    [status, ctype, out] = js;
    out = out instanceof Uint8Array ? out : new Uint8Array(out);
    if (persist && method !== "GET" && /^\/api\/(experiments|gallery)/.test(new URL(url, "http://x").pathname)) {
      await syncfs(false).catch(() => {});
    }
  } catch (e) {
    out = new TextEncoder().encode(JSON.stringify({ error: String((e && e.message) || e).split("\n").slice(-2).join(" ") }));
  }
  postMessage({ type: "response", rid, status, ctype, body: out }, [out.buffer]);
}

async function onJob({ jid, kind, body }) {
  const report = (progress, partial, message) =>
    postMessage({ type: "progress", jid, progress, partial: partial ?? null, message: message ?? null });
  let outcome;
  try {
    outcome = await withLazyPackages(() => browser.run_job(kind, body, report));
  } catch (e) {
    outcome = JSON.stringify({ status: "error", message: String((e && e.message) || e).split("\n").slice(-2).join(" ") });
  }
  postMessage({ type: "jobdone", jid, outcome });
}

onmessage = (ev) => {
  const msg = ev.data;
  if (msg.type === "init") {
    queue = init(msg).catch((e) => postMessage({ type: "fatal", message: String((e && e.message) || e) }));
    return;
  }
  // Python is single-threaded: handle messages strictly one after another.
  const handler = msg.type === "request" ? onRequest : msg.type === "job" ? onJob : null;
  if (handler) queue = queue.then(() => handler(msg));
};
