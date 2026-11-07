"""On-disk experiment notebook and artwork gallery.

Layout (root = ``$PENDULUM_SIM_HOME`` or ``~/.pendulum_sim``)::

    experiments/<id>.json      name, description, tags, favorite, config,
                               visual settings, notes, result *summary*
    gallery/<id>.png           rendered artwork
    gallery/<id>.json          exact SimConfig + visual settings + size

Trajectory arrays are never stored in these files: every result is a
deterministic function of its config, so it is recomputed on load. Large
numerical datasets are exported separately (CSV) on request.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from pendulum_sim.core.config import SimConfig

_ID = re.compile(r"^[a-f0-9]{12}$")
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_FIELD = 20_000


def root() -> Path:
    return Path(os.environ.get("PENDULUM_SIM_HOME", Path.home() / ".pendulum_sim"))


def _dir(name: str) -> Path:
    d = root() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check_id(eid: str) -> str:
    if not _ID.match(eid or ""):
        raise ValueError("invalid id")
    return eid


def _clean_text(v, limit=MAX_FIELD) -> str:
    s = str(v or "")
    if len(s) > limit:
        raise ValueError("text field too long")
    return s


# --------------------------------------------------------------------------
# Experiments
# --------------------------------------------------------------------------


def normalize_experiment(d: dict, eid: str | None = None) -> dict:
    cfg = SimConfig.from_dict(d.get("config") or {}).validate()  # rejects unknown/invalid fields
    tags = d.get("tags") or []
    if not isinstance(tags, list) or len(tags) > 32:
        raise ValueError("tags must be a list of at most 32 strings")
    now = time.time()
    return {
        "id": eid or uuid.uuid4().hex[:12],
        "name": _clean_text(d.get("name") or cfg.name, 200),
        "description": _clean_text(d.get("description"), 4000),
        "tags": [_clean_text(t, 40) for t in tags],
        "favorite": bool(d.get("favorite", False)),
        "mode": _clean_text(d.get("mode") or "playground", 40),
        "seed": d.get("seed"),
        "config": cfg.to_dict(),
        "digest": cfg.digest(),
        "visual": d.get("visual") if isinstance(d.get("visual"), dict) else {},
        "extra": d.get("extra") if isinstance(d.get("extra"), dict) else {},
        "notes": _clean_text(d.get("notes")),
        "results": d.get("results") if isinstance(d.get("results"), dict) else {},
        "exports": d.get("exports") if isinstance(d.get("exports"), list) else [],
        "created": float(d.get("created") or now),
        "updated": now,
        "schema": "pendulum-sim/experiment@1",
    }


def save_experiment(d: dict, eid: str | None = None) -> dict:
    if eid is not None:
        _check_id(eid)
    exp = normalize_experiment(d, eid)
    blob = json.dumps(exp, indent=2)
    if len(blob) > 2_000_000:
        raise ValueError("experiment too large; store trajectories as separate result files")
    (_dir("experiments") / f"{exp['id']}.json").write_text(blob)
    return exp


def list_experiments() -> list[dict]:
    out = []
    for f in _dir("experiments").glob("*.json"):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    out.sort(key=lambda e: e.get("updated", 0), reverse=True)
    return out


def get_experiment(eid: str) -> dict:
    f = _dir("experiments") / f"{_check_id(eid)}.json"
    if not f.exists():
        raise KeyError(eid)
    return json.loads(f.read_text())


def delete_experiment(eid: str) -> None:
    f = _dir("experiments") / f"{_check_id(eid)}.json"
    if f.exists():
        f.unlink()


def duplicate_experiment(eid: str) -> dict:
    src = get_experiment(eid)
    src = dict(src, name=f"{src['name']} (copy)", created=None)
    return save_experiment(src)


# --------------------------------------------------------------------------
# Gallery
# --------------------------------------------------------------------------

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def save_artwork(png: bytes, meta: dict) -> dict:
    if not png.startswith(PNG_MAGIC):
        raise ValueError("artwork must be a PNG image")
    if len(png) > MAX_IMAGE_BYTES:
        raise ValueError("image too large")
    cfg = SimConfig.from_dict(meta.get("config") or {}).validate()
    aid = uuid.uuid4().hex[:12]
    rec = {
        "id": aid,
        "title": _clean_text(meta.get("title") or cfg.name, 200),
        "config": cfg.to_dict(),
        "digest": cfg.digest(),
        "visual": meta.get("visual") if isinstance(meta.get("visual"), dict) else {},
        "width": int(meta.get("width") or 0),
        "height": int(meta.get("height") or 0),
        "t_end": float(meta.get("t_end") or cfg.numerics.t_max),
        "created": time.time(),
        "schema": "pendulum-sim/artwork@1",
    }
    d = _dir("gallery")
    (d / f"{aid}.png").write_bytes(png)
    (d / f"{aid}.json").write_text(json.dumps(rec, indent=2))
    return rec


def list_artworks() -> list[dict]:
    out = []
    for f in _dir("gallery").glob("*.json"):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    out.sort(key=lambda e: e.get("created", 0), reverse=True)
    return out


def artwork_path(aid: str) -> Path:
    p = _dir("gallery") / f"{_check_id(aid)}.png"
    if not p.exists():
        raise KeyError(aid)
    return p


def delete_artwork(aid: str) -> None:
    for ext in ("png", "json"):
        p = _dir("gallery") / f"{_check_id(aid)}.{ext}"
        if p.exists():
            p.unlink()
