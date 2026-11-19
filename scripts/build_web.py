"""Build the static web demo (GitHub Pages) into ``_site/``.

The demo is the regular dashboard (``pendulum_sim/app/static``) plus a small
in-browser backend (``web/``) that runs this Python package with Pyodide, so
it needs no server::

    python scripts/build_web.py                 # -> _site/
    python -m http.server -d _site 8000         # preview at http://localhost:8000

Options:
    --out DIR          output directory (default: _site)
    --pyodide URL      Pyodide distribution to load (default: the jsDelivr CDN);
                       point it at a local copy to work offline
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "pendulum_sim" / "app" / "static"
WEB = ROOT / "web"
PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/"
MAIN_TAG = '<script type="module" src="js/main.js"></script>'


def build(out: Path, pyodide: str = PYODIDE_CDN) -> Path:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out)
    shutil.copytree(WEB, out / "web")

    # The Python package, without the dashboard files (already served above) or caches.
    with zipfile.ZipFile(out / "pendulum_sim.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "pendulum_sim").rglob("*")):
            rel = f.relative_to(ROOT)
            if f.is_dir() or "__pycache__" in rel.parts or "static" in rel.parts or f.suffix == ".pyc":
                continue
            z.write(f, rel.as_posix())

    if not pyodide.endswith("/"):
        pyodide += "/"
    index = out / "index.html"
    html = index.read_text()
    if MAIN_TAG not in html:
        raise SystemExit(f"could not find {MAIN_TAG!r} in index.html")
    cfg = json.dumps({"pyodide": pyodide, "zip": "pendulum_sim.zip"})
    boot = (f"<script>window.PENDULUM_WEB = {cfg};</script>\n"
            '  <script type="module" src="web/backend.js"></script>\n  ')
    index.write_text(html.replace(MAIN_TAG, boot + MAIN_TAG))
    (out / ".nojekyll").write_text("")  # serve files as-is; skip GitHub's Jekyll step
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "_site")
    ap.add_argument("--pyodide", default=PYODIDE_CDN)
    args = ap.parse_args()
    out = build(args.out, args.pyodide)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"built {out} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
