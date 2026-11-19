"""Tests for the static web demo: the in-browser API transport and the site build.

The browser transport is plain Python, so it is tested here under CPython; the
same code runs under Pyodide in the hosted demo.
"""

import base64
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

from pendulum_sim.app import api, browser
from pendulum_sim.core.config import SimConfig

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("PENDULUM_SIM_HOME", str(tmp_path / "home"))


def call(method, url, body=None):
    raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    status, ctype, out = browser.handle(method, url, raw)
    return status, ctype, (json.loads(out) if ctype == "application/json" else out)


def test_meta_and_presets():
    status, _, meta = call("GET", "/api/meta")
    assert status == 200 and meta["backend"] == "browser" and "rk4" in meta["methods"]
    status, _, presets = call("GET", "/api/presets")
    assert status == 200 and len(presets["presets"]) > 10


def test_simulate_matches_api():
    body = {"config": SimConfig().to_dict() | {"numerics": SimConfig().numerics.__dict__ | {"t_max": 2.0}}}
    status, _, out = call("POST", "/api/simulate", body)
    assert status == 200
    assert out["theta1"] == api.simulate(body)["theta1"]


def test_errors_map_to_http_status():
    assert call("POST", "/api/simulate", b"not json")[0] == 400
    assert call("POST", "/api/simulate", {"config": {"numerics": {"dt": -1}}})[0] == 400
    assert call("GET", "/api/experiments/0123456789ab")[0] == 404
    assert call("GET", "/api/nope")[0] == 404
    assert call("PATCH", "/api/meta")[0] == 404


def test_experiment_crud():
    cfg = SimConfig().to_dict()
    status, _, e = call("POST", "/api/experiments", {"name": "web", "config": cfg})
    assert status == 200
    assert [x["name"] for x in call("GET", "/api/experiments")[2]["experiments"]] == ["web"]
    assert call("PUT", f"/api/experiments/{e['id']}", e | {"favorite": True})[2]["favorite"] is True
    dup = call("POST", f"/api/experiments/{e['id']}/duplicate", {})[2]
    assert dup["id"] != e["id"]
    call("DELETE", f"/api/experiments/{e['id']}")
    assert [x["id"] for x in call("GET", "/api/experiments")[2]["experiments"]] == [dup["id"]]


def test_gallery_images_travel_inline():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "PNG")
    png = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    body = {"png": png, "config": SimConfig().to_dict(), "width": 8, "height": 8}
    status, _, rec = call("POST", "/api/gallery", body)
    assert status == 200
    arts = call("GET", "/api/gallery")[2]["artworks"]
    assert arts[0]["src"] == png
    status, ctype, data = call("GET", f"/api/gallery/{rec['id']}/image")
    assert status == 200 and ctype == "image/png" and data == buf.getvalue()


def test_csv_export():
    status, ctype, data = call("POST", "/api/export/csv", {"config": SimConfig().to_dict(), "t_start": 0, "t_end": 1})
    assert status == 200 and ctype.startswith("text/csv") and data.startswith(b"#")


def test_gif_encoder_roundtrip():
    from PIL import Image

    status, _, enc = call("POST", "/api/encode/start", {"format": "gif", "fps": 10, "width": 16, "height": 16})
    assert status == 200
    for color in ("black", "white"):
        buf = io.BytesIO()
        Image.new("RGB", (16, 16), color).save(buf, "PNG")
        assert call("POST", f"/api/encode/{enc['id']}/frame", buf.getvalue())[0] == 200
    assert call("POST", f"/api/encode/{enc['id']}/finish", {})[2]["frames"] == 2
    status, ctype, gif = call("GET", f"/api/encode/{enc['id']}/file")
    assert status == 200 and ctype == "image/gif" and gif.startswith(b"GIF8")
    call("DELETE", f"/api/encode/{enc['id']}")


def test_run_job_reports_progress_and_result():
    reports = []
    body = {"nx": 16, "ny": 16, "observable": "rotations", "t_max": 2, "cache": False}
    out = json.loads(browser.run_job("map", json.dumps(body), lambda f, p, m: reports.append((f, p))))
    assert out["status"] == "done" and out["result"]["nx"] == 16
    assert reports and reports[-1][0] == 1.0
    assert json.loads(reports[-1][1])["nx"] == 16  # partial maps are sent as JSON


def test_run_job_errors_are_reported_not_raised():
    out = json.loads(browser.run_job("map", json.dumps({"observable": "bogus"}), lambda *a: None))
    assert out["status"] == "error" and "observable" in out["message"]
    out = json.loads(browser.run_job("nope", "{}", lambda *a: None))
    assert out["status"] == "error" and "unknown job kind" in out["message"]


def test_poincare_runs_serially_without_process_pools(monkeypatch):
    monkeypatch.setattr(api, "CAN_FORK", False)
    out = json.loads(browser.run_job("poincare", json.dumps(
        {"config": SimConfig().to_dict(), "energy": -15, "theta2_values": [0.1, 0.5], "t_max": 20}), lambda *a: None))
    assert out["status"] == "done" and len(out["result"]["sections"]) == 2


def test_build_web_site(tmp_path):
    spec = importlib.util.spec_from_file_location("build_web", ROOT / "scripts" / "build_web.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.build(tmp_path / "site", "https://example.test/pyodide")
    html = (out / "index.html").read_text()
    assert '"pyodide": "https://example.test/pyodide/"' in html
    assert html.index("web/backend.js") < html.index("js/main.js")  # the shim must load first
    for f in ("web/backend.js", "web/pyworker.js", "js/main.js", "css/app.css", ".nojekyll"):
        assert (out / f).is_file(), f
    names = zipfile.ZipFile(out / "pendulum_sim.zip").namelist()
    assert "pendulum_sim/app/browser.py" in names
    assert not any("static/" in n or n.endswith(".pyc") for n in names)
