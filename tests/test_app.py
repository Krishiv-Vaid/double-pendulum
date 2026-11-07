"""Tests for the dashboard backend: API handlers, jobs, storage and HTTP server."""

import base64
import io
import json
import threading
import urllib.request

import numpy as np
import pytest

from pendulum_sim.app import api, store
from pendulum_sim.app.jobs import JobLimitError, JobManager
from pendulum_sim.core.config import SimConfig


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("PENDULUM_SIM_HOME", str(tmp_path / "home"))


def cfg(**changes):
    c = SimConfig().to_dict()
    for k, v in changes.items():
        sec, key = k.split(".")
        c[sec][key] = v
    return c


def test_arr_rounding_and_nan():
    out = api.arr([1.23456789, np.nan, 0.0, -1e-9], sig=3)
    assert out == [1.23, None, 0.0, -1e-9]
    assert api.arr(np.array([[1.0, np.inf]])) == [[1.0, None]]
    json.dumps(out, allow_nan=False)


def test_f32_roundtrip():
    a = np.array([1.5, np.nan, -2.25], dtype=np.float32)
    b = np.frombuffer(base64.b64decode(api.f32(a)), dtype="<f4")
    assert np.allclose(a, b, equal_nan=True)


def test_simulate_payload_matches_engine():
    r = api.simulate({"config": cfg(**{"numerics.t_max": 2.0})})
    json.dumps(r, allow_nan=False)
    assert len(r["t"]) == len(r["theta1"]) == len(r["E"])
    assert r["t"][-1] == pytest.approx(2.0)
    assert r["theta1"][0] == pytest.approx(np.radians(120))
    assert r["energy_error_kind"] == "(E-E0)/|E0|"
    assert r["summary"]["max_abs_rel_energy_error"] < 1e-6


def test_energy_diagnostic_when_E0_is_zero():
    # Both rods horizontal at rest: V = 0, T = 0, so E0 = 0 exactly in theory.
    r = api.simulate({"config": cfg(**{"initial.theta1_deg": 90.0, "initial.theta2_deg": 90.0, "numerics.t_max": 5.0})})
    assert "E_char" in r["energy_error_kind"]
    assert r["summary"]["max_abs_rel_energy_error"] < 1e-5  # well resolved, not divided by ~0


def test_forced_run_reports_work():
    r = api.simulate({"config": cfg(**{"physical.damping1": 0.1, "numerics.t_max": 3.0})})
    assert "W_damp" in r["work"]
    assert r["work"]["W_damp"][-1] > 0
    assert "balance" in r["energy_error_kind"]


@pytest.mark.parametrize("bad", [
    {"physical": {"m1": -1}},
    {"physical": {"bogus": 1}},
    {"numerics": {"method": "euler"}},
])
def test_invalid_config_rejected(bad):
    with pytest.raises(api.ApiError):
        api.simulate({"config": bad})


def test_budget_limits():
    with pytest.raises(api.ApiError):
        api.simulate({"config": cfg(**{"numerics.dt": 1e-5, "numerics.t_max": 100.0})})
    with pytest.raises(api.ApiError):
        api.butterfly({"config": cfg(), "n": 10_000})


def test_csv_export_has_units_and_matches_range():
    name, text = api.export_csv({"config": cfg(**{"numerics.t_max": 1.0}), "t_start": 0.5, "t_end": 1.0})
    assert name.endswith(".csv")
    lines = text.splitlines()
    assert any(line.startswith("# theta1 [rad]") for line in lines)
    header = next(line for line in lines if not line.startswith("#"))
    rows = [line for line in lines if line and not line.startswith("#")][1:]
    assert header.split(",")[0] == "t"
    t = [float(r.split(",")[0]) for r in rows]
    assert min(t) >= 0.5 - 1e-9 and max(t) <= 1.0 + 1e-9


def test_butterfly_separation_is_wrapped_and_grows():
    r = api.butterfly({"config": cfg(**{"numerics.t_max": 15.0}), "n": 4, "epsilon": 1e-6})
    sep = np.array(r["median_log10_separation"], dtype=float)
    assert sep[0] < -6 and sep[-1] > -2  # exponential growth for the chaotic start
    assert r["numerical_control_log10"][0] is None  # zero difference at t=0 -> NaN, not -300
    assert len(r["theta1"]) == 4


def test_modes_equal_masses():
    r = api.modes({"config": cfg(**{"initial.theta1_deg": 2.0, "initial.theta2_deg": 2.8}), "t_max": 5})
    w = r["normal_modes"]["omega"]
    g = 9.81
    assert w[0] == pytest.approx(np.sqrt((2 - np.sqrt(2)) * g), rel=1e-9)
    assert w[1] == pytest.approx(np.sqrt((2 + np.sqrt(2)) * g), rel=1e-9)
    assert len(r["equilibria"]) == 4


def test_landscape_and_random_are_deterministic():
    a = api.random_config({"seed": 42})
    b = api.random_config({"seed": 42})
    assert a == b
    SimConfig.from_dict(a["config"]).validate()
    L = api.landscape({"config": cfg(), "n": 21})
    V = np.frombuffer(base64.b64decode(L["V"]), dtype="<f4")
    assert V.min() == pytest.approx(-(2 * 9.81 + 9.81), rel=1e-5)


def test_nlink_reduces_and_conserves():
    r = api.nlink_run({"masses": [1, 1, 1], "lengths": [1, 1, 1], "theta_deg": [30, -20, 10], "t_max": 2, "dt": 5e-4})
    assert max(abs(v) for v in r["energy_error"]) < 1e-6


def test_job_manager_progress_cancel_and_limit():
    jm = JobManager(max_running=1)
    ev = threading.Event()

    def slow(ctx):
        while not ctx.cancelled():
            ctx.progress(0.5)
            ev.wait(0.01)
        raise InterruptedError

    j = jm.submit("slow", slow)
    with pytest.raises(JobLimitError):
        jm.submit("other", lambda ctx: 1)
    jm.cancel(j.id)
    assert jm.wait(j.id).status == "cancelled"
    j2 = jm.submit("ok", lambda ctx: {"x": 1})
    assert jm.wait(j2.id).info()["result"] == {"x": 1}
    j3 = jm.submit("bad", lambda ctx: 1 / 0)
    assert jm.wait(j3.id).status == "error"


def test_experiment_store_roundtrip():
    e = store.save_experiment({"name": "A", "tags": ["x"], "config": cfg(), "notes": "hi"})
    assert store.get_experiment(e["id"])["notes"] == "hi"
    d = store.duplicate_experiment(e["id"])
    assert d["id"] != e["id"] and d["name"] == "A (copy)"
    assert len(store.list_experiments()) == 2
    store.delete_experiment(e["id"])
    assert len(store.list_experiments()) == 1
    with pytest.raises(ValueError):
        store.get_experiment("../../etc")
    with pytest.raises(ValueError):
        store.save_experiment({"config": {"physical": {"m1": 0}}})


def test_artwork_store_requires_png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG")
    rec = store.save_artwork(buf.getvalue(), {"config": cfg(), "width": 4, "height": 4})
    assert store.artwork_path(rec["id"]).exists()
    with pytest.raises(ValueError):
        store.save_artwork(b"GIF89a", {"config": cfg()})


# ---------------------------------------------------------------- HTTP


@pytest.fixture(scope="module")
def server():
    from pendulum_sim.app.server import make_server

    httpd = make_server("127.0.0.1", 0, quiet=True)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def _req(url, data=None, method=None, raw=False):
    body = None if data is None else (data if isinstance(data, bytes) else json.dumps(data).encode())
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            content = r.read()
            return r.status, content if raw else json.loads(content)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_static_and_meta(server):
    status, html = _req(server + "/", raw=True)
    assert status == 200 and b"Double Pendulum Simulator" in html
    status, js = _req(server + "/js/main.js", raw=True)
    assert status == 200 and b"VIEWS" in js
    status, _ = _req(server + "/../../etc/passwd", raw=True)  # traversal falls back to index
    assert status == 200
    status, meta = _req(server + "/api/meta")
    assert meta["methods"] == ["rk4", "rk45", "dop853"]
    status, pre = _req(server + "/api/presets")
    assert len(pre["presets"]) >= 25


def test_http_simulate_errors_and_jobs(server):
    status, r = _req(server + "/api/simulate", {"config": cfg(**{"numerics.t_max": 1.0})})
    assert status == 200 and len(r["t"]) > 100
    status, r = _req(server + "/api/simulate", {"config": {"physical": {"L1": -1}}})
    assert status == 400 and "L1" in r["error"]
    body = {"config": cfg(), "nx": 8, "ny": 8, "t_max": 1, "cache": False, "workers": 1}
    status, job = _req(server + "/api/jobs/map", body)
    assert status == 202
    import time

    for _ in range(300):
        _, info = _req(f"{server}/api/jobs/{job['id']}")
        if info["status"] != "running":
            break
        time.sleep(0.05)
    assert info["status"] == "done"
    data = np.frombuffer(base64.b64decode(info["result"]["data"]), dtype="<f4")
    assert data.size == 64
    status, _ = _req(server + "/api/jobs/nope", {})
    assert status == 400


def test_http_encoder_gif(server):
    from PIL import Image

    status, enc = _req(server + "/api/encode/start", {"format": "gif", "fps": 10, "width": 32, "height": 32})
    assert status == 200
    for k in range(3):
        buf = io.BytesIO()
        Image.new("RGB", (32, 32), (k * 80, 0, 0)).save(buf, "PNG")
        status, r = _req(f"{server}/api/encode/{enc['id']}/frame", buf.getvalue())
        assert status == 200 and r["frames"] == k + 1
    status, info = _req(f"{server}/api/encode/{enc['id']}/finish", {})
    assert info["frames"] == 3
    status, gif = _req(f"{server}/api/encode/{enc['id']}/file", raw=True)
    assert gif[:6] in (b"GIF89a", b"GIF87a")
    assert Image.open(io.BytesIO(gif)).n_frames == 3


def test_http_experiments_crud(server):
    status, e = _req(server + "/api/experiments", {"name": "web", "config": cfg()})
    assert status == 200
    status, lst = _req(server + "/api/experiments")
    assert any(x["id"] == e["id"] for x in lst["experiments"])
    status, _ = _req(f"{server}/api/experiments/{e['id']}", method="DELETE")
    assert status == 200


def test_cli_serve_forwards_options(monkeypatch):
    import pendulum_sim.app.server as server
    from pendulum_sim import cli

    seen = {}
    monkeypatch.setattr(server, "main", lambda argv=None: seen.setdefault("argv", argv))
    cli.main(["serve", "--port", "9999", "--no-browser"])
    assert seen["argv"] == ["--port", "9999", "--no-browser"]


def test_frontend_is_strictly_monochrome():
    """Design rule: no hue anywhere in the dashboard. Every hex/rgb colour
    literal in the static assets must be a grey (r == g == b)."""
    import re
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "pendulum_sim" / "app" / "static"
    offenders = []
    for f in static.rglob("*"):
        if f.suffix not in {".js", ".css", ".html"}:
            continue
        text = f.read_text()
        for m in re.finditer(r"(?:#|%23)([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", text):
            h = m.group(1)
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            if not (r == g == b):
                offenders.append(f"{f.name}: #{m.group(1)}")
        for m in re.finditer(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text):
            r, g, b = map(int, m.groups())
            if not (r == g == b):
                offenders.append(f"{f.name}: {m.group(0)}")
    assert not offenders, offenders
