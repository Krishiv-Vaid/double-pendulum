// Thin client for the Chaos Lab JSON API.

async function request(method, url, body, opts = {}) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    if (body instanceof Blob || body instanceof ArrayBuffer) {
      init.body = body;
      init.headers["Content-Type"] = "application/octet-stream";
    } else {
      init.body = JSON.stringify(body);
      init.headers["Content-Type"] = "application/json";
    }
  }
  if (opts.signal) init.signal = opts.signal;
  const res = await fetch(url, init);
  if (opts.raw) {
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
    return res;
  }
  const data = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export const api = {
  get: (url, o) => request("GET", url, undefined, o),
  post: (url, body, o) => request("POST", url, body, o),
  put: (url, body) => request("PUT", url, body),
  del: (url) => request("DELETE", url),
  raw: (method, url, body) => request(method, url, body, { raw: true }),
};

/** Start a background job and poll until done.
 *  onProgress(fraction, info) receives partial results when `partial` is set.
 *  Returns {promise, cancel}. */
export function runJob(kind, body, { onProgress, partial = false, interval = 350 } = {}) {
  let id = null, cancelled = false, timer = null;
  const promise = new Promise(async (resolve, reject) => {
    try {
      const job = await api.post(`/api/jobs/${kind}`, body);
      id = job.id;
      if (cancelled) { api.del(`/api/jobs/${id}`); return reject(new Error("cancelled")); }
      const poll = async () => {
        try {
          const info = await api.get(`/api/jobs/${id}${partial ? "?partial=1" : ""}`);
          if (info.status === "running") {
            onProgress && onProgress(info.progress, info);
            timer = setTimeout(poll, interval);
          } else if (info.status === "done") {
            onProgress && onProgress(1, info);
            resolve(info.result);
          } else if (info.status === "cancelled") {
            reject(new Error("cancelled"));
          } else {
            reject(new Error(info.message || "job failed"));
          }
        } catch (e) { reject(e); }
      };
      poll();
    } catch (e) { reject(e); }
  });
  return {
    promise,
    cancel() {
      cancelled = true;
      clearTimeout(timer);
      if (id) api.del(`/api/jobs/${id}`).catch(() => {});
    },
  };
}

/** Decode a base64 little-endian float32 array. */
export function decodeF32(b64) {
  const bin = atob(b64);
  const buf = new ArrayBuffer(bin.length);
  const u8 = new Uint8Array(buf);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Float32Array(buf);
}

export function decodeBits(b64, n) {
  const bin = atob(b64);
  const out = new Uint8Array(n * n);
  for (let i = 0; i < n * n; i++) out[i] = (bin.charCodeAt(i >> 3) >> (7 - (i & 7))) & 1;
  return out;
}

export function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
}
