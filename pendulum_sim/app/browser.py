"""In-browser transport for the dashboard API (used by the web demo under Pyodide).

The hosted demo runs this package inside the browser with Pyodide: there is no
server process, so the page's ``fetch("/api/...")`` calls are routed to a web
worker that calls :func:`handle`. The routes and their responses match
``server.py`` exactly, and the same handler functions in ``api`` do the work.

Background jobs are not routed through here: the page keeps the job table
itself and calls :func:`run_job` in a dedicated worker, which reports progress
through a callback. A job cannot poll for cancellation (the worker is busy
running it), so the page cancels a job by stopping that worker.
"""

from __future__ import annotations

import base64
import json
import time
import traceback
from urllib.parse import urlparse

from pendulum_sim.app import api, store
from pendulum_sim.app.server import JOB_KINDS, SYNC_POST, Encoder

ENCODERS: dict[str, Encoder] = {}

Response = tuple[int, str, bytes]


def _json(obj, status: int = 200) -> Response:
    return status, "application/json", json.dumps(obj, allow_nan=False, separators=(",", ":")).encode()


def _error(status: int, msg: str) -> Response:
    return _json({"error": msg}, status)


def _body(raw: bytes) -> dict:
    if not raw:
        return {}
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        raise api.ApiError("body must be JSON") from None
    if not isinstance(d, dict):
        raise api.ApiError("body must be a JSON object")
    return d


def _artwork_with_src(rec: dict) -> dict:
    """Gallery records carry the image inline: the browser cannot load ``<img src="/api/...">``
    from a worker, so the picture travels as a data URL instead."""
    try:
        png = store.artwork_path(rec["id"]).read_bytes()
    except (KeyError, OSError, ValueError):
        return rec
    return rec | {"src": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}


def handle(method: str, url: str, raw: bytes | None = None) -> Response:
    """Answer one API request. Returns ``(status, content_type, body_bytes)``."""
    if hasattr(raw, "to_bytes"):  # a JavaScript Uint8Array passed in by Pyodide
        raw = raw.to_bytes()
    raw = bytes(raw or b"")
    try:
        return _route(method.upper(), url, raw)
    except api.ApiError as e:
        return _error(400, str(e))
    except KeyError as e:
        return _error(404, f"not found: {e}")
    except ValueError as e:
        return _error(400, str(e))
    except ModuleNotFoundError:
        raise  # the worker loads the missing Pyodide package and retries
    except Exception as e:
        traceback.print_exc()
        return _error(500, f"{type(e).__name__}: {e}")


def _route(method: str, url: str, raw: bytes) -> Response:
    u = urlparse(url)
    parts = [p for p in u.path.split("/") if p]
    if not parts or parts[0] != "api":
        return _error(404, "unknown endpoint")
    route = parts[1:] or [""]
    head, rest = route[0], route[1:]

    if method == "GET":
        if head == "meta":
            return _json(api.meta() | {"backend": "browser"})
        if head == "presets":
            return _json(api.list_presets())
        if head == "challenges":
            return _json(api.challenge_list())
        if head == "experiments":
            if len(rest) == 1:
                return _json(store.get_experiment(rest[0]))
            return _json({"experiments": store.list_experiments()})
        if head == "gallery":
            if len(rest) == 2 and rest[1] == "image":
                return 200, "image/png", store.artwork_path(rest[0]).read_bytes()
            return _json({"artworks": [_artwork_with_src(a) for a in store.list_artworks()]})
        if head == "encode" and len(rest) == 2 and rest[1] == "file":
            enc = ENCODERS[rest[0]]
            ctype = "image/gif" if enc.fmt == "gif" else "video/mp4"
            return 200, ctype, enc.path.read_bytes()
        return _error(404, "unknown endpoint")

    if method == "POST":
        if head in SYNC_POST and not rest:
            return _json(SYNC_POST[head](_body(raw)))
        if head == "challenges" and len(rest) == 1:
            return _json(api.challenge_eval(rest[0], _body(raw)))
        if head == "experiments":
            if len(rest) == 2 and rest[1] == "duplicate":
                return _json(store.duplicate_experiment(rest[0]))
            return _json(store.save_experiment(_body(raw)))
        if head == "gallery":
            body = _body(raw)
            png = base64.b64decode(str(body.get("png", "")).split(",")[-1])
            return _json(store.save_artwork(png, body))
        if head == "export" and rest == ["csv"]:
            _name, text = api.export_csv(_body(raw))
            return 200, "text/csv; charset=utf-8", text.encode()
        if head == "encode":
            if rest == ["start"]:
                b = _body(raw)
                enc = Encoder(str(b.get("format", "gif")), float(b.get("fps", 30)), int(b.get("width", 640)),
                              int(b.get("height", 640)), int(b.get("quality", 8)), bool(b.get("loop", True)))
                ENCODERS[enc.id] = enc
                return _json({"id": enc.id, "width": enc.w, "height": enc.h})
            if len(rest) == 2 and rest[1] == "frame":
                return _json({"frames": ENCODERS[rest[0]].add(raw)})
            if len(rest) == 2 and rest[1] == "finish":
                return _json(ENCODERS[rest[0]].finish())
        return _error(404, "unknown endpoint")

    if method == "PUT":
        if head == "experiments" and len(rest) == 1:
            return _json(store.save_experiment(_body(raw), rest[0]))
        return _error(404, "unknown endpoint")

    if method == "DELETE" and len(rest) == 1:
        ident = rest[0]
        if head == "experiments":
            store.delete_experiment(ident)
            return _json({"deleted": ident})
        if head == "gallery":
            store.delete_artwork(ident)
            return _json({"deleted": ident})
        if head == "encode":
            enc = ENCODERS.pop(ident, None)
            if enc:
                enc.abort()
            return _json({"deleted": ident})
    return _error(404, "unknown endpoint")


# --------------------------------------------------------------------------
# Background jobs
# --------------------------------------------------------------------------


class BrowserJobContext:
    """Same interface as ``jobs.JobContext``; progress is pushed to the page, throttled."""

    def __init__(self, report, interval: float = 0.25):
        self._report = report
        self._interval = interval
        self._last = 0.0

    def progress(self, fraction: float, partial=None, message: str | None = None) -> None:
        now = time.monotonic()
        fraction = max(0.0, min(1.0, float(fraction)))
        if fraction < 1.0 and now - self._last < self._interval:
            return
        self._last = now
        payload = json.dumps(partial, allow_nan=False, separators=(",", ":")) if partial is not None else None
        self._report(fraction, payload, message)

    def cancelled(self) -> bool:
        return False  # the page cancels by stopping the worker

    def check(self) -> None:
        return None


def validate_job(kind: str, body: dict) -> None:
    """The cheap synchronous checks ``server.py`` runs before starting a job."""
    if kind not in JOB_KINDS:
        raise api.ApiError(f"unknown job kind {kind!r}")
    if kind == "map":
        api.map_spec(body)
    elif kind != "lyapunov_validate":
        api.parse_config(body.get("config") or {})


def run_job(kind: str, body_json: str, report) -> str:
    """Run one job to completion. Returns ``{"status": "done", "result": ...}`` or
    ``{"status": "error", "message": ...}`` as a JSON string."""
    try:
        body = _body(body_json.encode())
        validate_job(kind, body)
        result = JOB_KINDS[kind](body, BrowserJobContext(report))
        return json.dumps({"status": "done", "result": result}, allow_nan=False, separators=(",", ":"))
    except ModuleNotFoundError:
        raise
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"status": "error", "message": f"{type(e).__name__}: {e}"})
