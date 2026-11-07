"""HTTP server for the Double Pendulum Simulator dashboard (standard library only).

Routes
------
GET  /                        static single-page app (pendulum_sim/app/static)
GET  /api/meta | /api/presets | /api/challenges | /api/experiments | /api/gallery | /api/jobs
POST /api/simulate | /api/modes | /api/landscape | /api/nlink | /api/pivot | /api/analysis | /api/random
POST /api/jobs/<kind>         start a background job (map, butterfly, lyapunov, lyapunov_scan,
                              lyapunov_validate, poincare, integrators, sweep, tolerance, art)
GET  /api/jobs/<id>[?partial=1]   poll progress (partial map data while running)
DELETE /api/jobs/<id>         cancel
POST /api/challenges/<id>     evaluate a challenge
POST /api/export/csv          CSV download with units and a reproducibility header
POST /api/encode/start, /api/encode/<id>/frame, /api/encode/<id>/finish ; GET /api/encode/<id>/file
                              frame-streaming GIF/MP4 encoder for the Export Studio

The server binds to 127.0.0.1 by default and has no authentication: it is a
local tool, not a public web service.
"""

from __future__ import annotations

import argparse
import io
import json
import mimetypes
import tempfile
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pendulum_sim.app import api, store
from pendulum_sim.app.jobs import JobLimitError, JobManager

STATIC = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024 * 1024
JOBS = JobManager()

SYNC_POST = {
    "simulate": api.simulate,
    "modes": api.modes,
    "landscape": api.landscape,
    "nlink": api.nlink_run,
    "pivot": api.pivot_run,
    "analysis": api.analysis,
    "random": api.random_config,
}

JOB_KINDS = {
    "map": api.chaos_map,
    "butterfly": api.butterfly,
    "lyapunov": api.lyapunov_run,
    "lyapunov_scan": api.lyapunov_scan,
    "lyapunov_validate": api.lyapunov_validate,
    "poincare": api.poincare_run,
    "integrators": api.integrators,
    "sweep": api.sweep_run,
    "tolerance": api.tolerance_sweep,
    "art": api.art_search,
}


# --------------------------------------------------------------------------
# Frame-streaming encoder (Export Studio)
# --------------------------------------------------------------------------


class Encoder:
    """Accumulates browser-rendered frames and writes a GIF or MP4.

    Frames are rendered offline by the client at exact physical-time steps, so
    the output frame rate is independent of how fast the browser renders.
    """

    MAX_FRAMES = 3600
    MAX_GIF_PIXELS = 1280 * 1280

    def __init__(self, fmt: str, fps: float, width: int, height: int, quality: int = 8, loop: bool = True):
        if fmt not in ("gif", "mp4"):
            raise api.ApiError("format must be gif or mp4")
        if not (1 <= fps <= 120):
            raise api.ApiError("fps must be in [1, 120]")
        if not (16 <= width <= 7680 and 16 <= height <= 4320):
            raise api.ApiError("invalid frame size")
        if fmt == "gif" and width * height > self.MAX_GIF_PIXELS:
            raise api.ApiError("GIF frames are limited to 1280x1280 pixels; use MP4 for larger exports")
        self.id = uuid.uuid4().hex[:12]
        self.fmt, self.fps, self.w, self.h, self.loop = fmt, float(fps), int(width), int(height), loop
        self.frames = 0
        self.created = time.time()
        self.path = Path(tempfile.gettempdir()) / f"pendulum-sim-{self.id}.{fmt}"
        self._gif = []
        self._lock = threading.Lock()
        self._writer = None
        if fmt == "mp4":
            try:
                import imageio_ffmpeg
            except ImportError:
                raise api.ApiError("MP4 export needs imageio-ffmpeg: pip install 'pendulum-sim[video]'") from None
            # libx264 needs even dimensions
            self.w -= self.w % 2
            self.h -= self.h % 2
            self._writer = imageio_ffmpeg.write_frames(
                str(self.path), (self.w, self.h), fps=self.fps, codec="libx264", pix_fmt_out="yuv420p",
                quality=max(1, min(10, quality)), macro_block_size=1,
                output_params=["-movflags", "+faststart"])
            self._writer.send(None)

    def add(self, data: bytes) -> int:
        from PIL import Image

        with self._lock:
            if self.frames >= self.MAX_FRAMES:
                raise api.ApiError(f"frame limit ({self.MAX_FRAMES}) reached")
            im = Image.open(io.BytesIO(data)).convert("RGB")
            if im.size != (self.w, self.h):
                im = im.resize((self.w, self.h), Image.LANCZOS)
            if self.fmt == "mp4":
                self._writer.send(im.tobytes())
            else:
                self._gif.append(im.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE))
            self.frames += 1
            return self.frames

    def finish(self) -> dict:
        with self._lock:
            if self.frames == 0:
                raise api.ApiError("no frames")
            if self.fmt == "mp4":
                self._writer.close()
            else:
                first, rest = self._gif[0], self._gif[1:]
                first.save(self.path, save_all=True, append_images=rest, duration=round(1000 / self.fps),
                           loop=0 if self.loop else 1, optimize=True, disposal=1)
                self._gif = []
            return {"id": self.id, "frames": self.frames, "bytes": self.path.stat().st_size,
                    "format": self.fmt, "fps": self.fps, "width": self.w, "height": self.h}

    def abort(self):
        with self._lock:
            if self._writer is not None:
                try:
                    self._writer.close()
                except Exception:
                    pass
            self._gif = []
            self.path.unlink(missing_ok=True)


ENCODERS: dict[str, Encoder] = {}


# --------------------------------------------------------------------------
# Request handler
# --------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "ChaosLab/1"
    quiet = False

    def log_message(self, fmt, *args):
        if not self.quiet:
            super().log_message(fmt, *args)

    # -- helpers -------------------------------------------------------------
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status: int = 200):
        self._send(status, json.dumps(obj, allow_nan=False, separators=(",", ":")).encode(), "application/json")

    def _error(self, status: int, msg: str):
        self._json({"error": msg}, status)

    def _body_bytes(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise api.ApiError("request body too large")
        return self.rfile.read(n) if n else b""

    def _body(self) -> dict:
        raw = self._body_bytes()
        if not raw:
            return {}
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            raise api.ApiError("body must be JSON") from None
        if not isinstance(d, dict):
            raise api.ApiError("body must be a JSON object")
        return d

    def _dispatch(self, fn):
        try:
            fn()
        except (BrokenPipeError, ConnectionResetError):
            return  # client went away (tab closed / navigation); nothing to report
        except api.ApiError as e:
            self._error(400, str(e))
        except JobLimitError as e:
            self._error(429, str(e))
        except KeyError as e:
            self._error(404, f"not found: {e}")
        except ValueError as e:
            self._error(400, str(e))
        except Exception as e:
            traceback.print_exc()
            self._error(500, f"{type(e).__name__}: {e}")

    # -- verbs -------------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._dispatch(self._get)

    def do_POST(self):
        self._dispatch(self._post)

    def do_PUT(self):
        self._dispatch(self._put)

    def do_DELETE(self):
        self._dispatch(self._delete)

    def _get(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        q = parse_qs(url.query)
        if not parts or parts[0] != "api":
            return self._static(url.path)
        route = parts[1:] if len(parts) > 1 else [""]
        head = route[0]
        if head == "meta":
            return self._json(api.meta())
        if head == "presets":
            return self._json(api.list_presets())
        if head == "challenges":
            return self._json(api.challenge_list())
        if head == "experiments":
            if len(route) == 2:
                return self._json(store.get_experiment(route[1]))
            return self._json({"experiments": store.list_experiments()})
        if head == "gallery":
            if len(route) == 3 and route[2] == "image":
                p = store.artwork_path(route[1])
                return self._send(200, p.read_bytes(), "image/png")
            return self._json({"artworks": store.list_artworks()})
        if head == "jobs":
            if len(route) == 1:
                return self._json({"jobs": JOBS.list()})
            job = JOBS.get(route[1])
            if job is None:
                raise KeyError(route[1])
            return self._json(job.info(include_partial=q.get("partial", ["0"])[0] == "1"))
        if head == "encode" and len(route) == 3 and route[2] == "file":
            enc = ENCODERS[route[1]]
            ctype = "image/gif" if enc.fmt == "gif" else "video/mp4"
            return self._send(200, enc.path.read_bytes(), ctype,
                              {"Content-Disposition": f'attachment; filename="pendulum-sim-{enc.id}.{enc.fmt}"'})
        self._error(404, "unknown endpoint")

    def _post(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if len(parts) < 2 or parts[0] != "api":
            return self._error(404, "unknown endpoint")
        head, rest = parts[1], parts[2:]
        if head in SYNC_POST and not rest:
            return self._json(SYNC_POST[head](self._body()))
        if head == "jobs" and len(rest) == 1:
            kind = rest[0]
            if kind not in JOB_KINDS:
                raise api.ApiError(f"unknown job kind {kind!r}")
            body = self._body()
            fn = JOB_KINDS[kind]
            # Validate cheaply up-front where possible so obvious errors are synchronous.
            if kind == "map":
                api.map_spec(body)
            elif kind not in ("lyapunov_validate",):
                api.parse_config(body.get("config") or {})
            job = JOBS.submit(kind, lambda ctx: fn(body, ctx))
            return self._json(job.info(), 202)
        if head == "challenges" and len(rest) == 1:
            return self._json(api.challenge_eval(rest[0], self._body()))
        if head == "experiments":
            if len(rest) == 2 and rest[1] == "duplicate":
                return self._json(store.duplicate_experiment(rest[0]))
            return self._json(store.save_experiment(self._body()))
        if head == "gallery":
            body = self._body()
            import base64

            png = base64.b64decode(str(body.get("png", "")).split(",")[-1])
            return self._json(store.save_artwork(png, body))
        if head == "export" and rest == ["csv"]:
            name, text = api.export_csv(self._body())
            return self._send(200, text.encode(), "text/csv; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="{name}"'})
        if head == "encode":
            if rest == ["start"]:
                b = self._body()
                enc = Encoder(str(b.get("format", "gif")), float(b.get("fps", 30)), int(b.get("width", 640)),
                              int(b.get("height", 640)), int(b.get("quality", 8)), bool(b.get("loop", True)))
                ENCODERS[enc.id] = enc
                _gc_encoders()
                return self._json({"id": enc.id, "width": enc.w, "height": enc.h})
            if len(rest) == 2 and rest[1] == "frame":
                return self._json({"frames": ENCODERS[rest[0]].add(self._body_bytes())})
            if len(rest) == 2 and rest[1] == "finish":
                return self._json(ENCODERS[rest[0]].finish())
        self._error(404, "unknown endpoint")

    def _put(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if len(parts) == 3 and parts[:2] == ["api", "experiments"]:
            return self._json(store.save_experiment(self._body(), parts[2]))
        self._error(404, "unknown endpoint")

    def _delete(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if len(parts) == 3 and parts[0] == "api":
            kind, ident = parts[1], parts[2]
            if kind == "jobs":
                return self._json({"cancelled": JOBS.cancel(ident)})
            if kind == "experiments":
                store.delete_experiment(ident)
                return self._json({"deleted": ident})
            if kind == "gallery":
                store.delete_artwork(ident)
                return self._json({"deleted": ident})
            if kind == "encode":
                enc = ENCODERS.pop(ident, None)
                if enc:
                    enc.abort()
                return self._json({"deleted": ident})
        self._error(404, "unknown endpoint")

    def _static(self, path: str):
        rel = path.lstrip("/") or "index.html"
        f = (STATIC / rel).resolve()
        if not str(f).startswith(str(STATIC.resolve())) or not f.is_file():
            f = STATIC / "index.html"  # single-page app fallback
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if f.suffix == ".js":
            ctype = "text/javascript"
        self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))


def _gc_encoders(max_age: float = 3600.0):
    now = time.time()
    for k in [k for k, e in ENCODERS.items() if now - e.created > max_age]:
        ENCODERS.pop(k).abort()


def make_server(host: str = "127.0.0.1", port: int = 8765, quiet: bool = False) -> ThreadingHTTPServer:
    Handler.quiet = quiet
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="pendulum-sim serve",
                                 description="Launch the Double Pendulum Simulator dashboard.")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1, local only)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    ap.add_argument("--quiet", action="store_true", help="suppress request logs")
    args = ap.parse_args(argv)
    httpd = make_server(args.host, args.port, args.quiet)
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{httpd.server_port}/"
    print(f"Double Pendulum Simulator running at {url}  (Ctrl+C to stop)")
    if args.host not in ("127.0.0.1", "localhost"):
        print("warning: the dashboard has no authentication; only bind to trusted networks")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
