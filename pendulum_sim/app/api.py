"""JSON API handlers: thin, validated adapters from request dicts to the engine.

Every handler is a plain function ``dict -> dict`` (or a job factory) so it
can be unit-tested without HTTP. Resource limits are explicit constants;
requests beyond them are rejected with a clear message instead of hanging
the machine.

Array encoding
--------------
* ``arr(...)``  : JSON list rounded to ``sig`` significant digits, NaN -> null.
* ``f32(...)``  : base64 little-endian float32 (used for large maps; NaN preserved).
"""

from __future__ import annotations

import base64
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace

import numpy as np

import pendulum_sim
from pendulum_sim.analysis import events as ev
from pendulum_sim.analysis import linear, lyapunov, poincare, spectral
from pendulum_sim.core import nlink, physics, pivot
from pendulum_sim.core.config import METHODS, Initial, Numerics, Physical, SimConfig
from pendulum_sim.core.integrators import integrate_rk4
from pendulum_sim.core.simulation import simulate as core_simulate
from pendulum_sim.experiments import art, challenges, ensemble, integrator_lab, maps, presets, sweeps

MAX_SAMPLES = 40_000  # stored samples returned by /simulate
MAX_RK4_STEPS = 2_000_000  # per single trajectory request
MAX_ENSEMBLE = 400  # members in the butterfly arena (high-performance mode)
MAX_ENSEMBLE_WORK = 4e7  # members x steps
MAX_SWEEP_WORK = 6e8  # points x steps for parameter sweeps
MAX_POINCARE_TRAJ = 24
MAX_POINCARE_T = 2000.0


class ApiError(ValueError):
    """Client error (HTTP 400)."""


# --------------------------------------------------------------------------
# Encoding helpers
# --------------------------------------------------------------------------


def arr(a, sig: int = 7) -> list:
    a = np.asarray(a, dtype=float)
    finite = np.isfinite(a)
    out = np.zeros_like(a)
    nz = finite & (a != 0)
    if np.any(nz):
        mag = np.floor(np.log10(np.abs(a[nz])))
        scale = 10.0 ** (sig - 1 - mag)
        out[nz] = np.round(a[nz] * scale) / scale
    if np.all(finite):
        return out.tolist()
    return np.where(finite, out, None).tolist()


def f32(a) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype="<f4").tobytes()).decode("ascii")


def _num(body: dict, key: str, default, lo=None, hi=None, kind=float):
    v = body.get(key, default)
    try:
        v = kind(v)
    except (TypeError, ValueError):
        raise ApiError(f"{key} must be a number") from None
    if kind is float and not math.isfinite(v):
        raise ApiError(f"{key} must be finite")
    if lo is not None and v < lo:
        raise ApiError(f"{key} must be >= {lo}")
    if hi is not None and v > hi:
        raise ApiError(f"{key} must be <= {hi}")
    return v


def parse_config(d) -> SimConfig:
    try:
        cfg = SimConfig.from_dict(d or {})
        cfg.validate()
    except (TypeError, ValueError, KeyError) as e:
        raise ApiError(f"invalid config: {e}") from None
    return cfg


def _check_budget(cfg: SimConfig, members: int = 1, limit: float = MAX_RK4_STEPS):
    num = cfg.numerics
    if num.method == "rk4" and members * num.t_max / num.dt > limit:
        raise ApiError(f"workload too large: {members} x {num.t_max / num.dt:.3g} RK4 steps exceeds {limit:.3g}")
    if num.t_max / num.output_dt > MAX_SAMPLES:
        raise ApiError(f"too many output samples (t_max/output_dt > {MAX_SAMPLES}); raise output_dt")


# --------------------------------------------------------------------------
# Meta / presets
# --------------------------------------------------------------------------


def meta(_body=None) -> dict:
    return {
        "version": pendulum_sim.__version__,
        "methods": list(METHODS),
        "map_observables": list(maps.OBSERVABLES),
        "sweep_observables": list(sweeps.OBSERVABLES),
        "sweep_keys": list(sweeps.PHYSICAL_KEYS + sweeps.INITIAL_KEYS + sweeps.DERIVED_KEYS),
        "art_objectives": list(art.OBJECTIVES),
        "butterfly_variables": list(ensemble.VARIABLES),
        "defaults": SimConfig().to_dict(),
        "limits": {
            "max_samples": MAX_SAMPLES,
            "max_rk4_steps": MAX_RK4_STEPS,
            "max_ensemble": MAX_ENSEMBLE,
            "max_map_pixels": maps.MAX_PIXELS,
        },
        "cpu_count": os.cpu_count(),
        "video": _video_support(),
    }


def _video_support() -> dict:
    try:
        import imageio_ffmpeg  # noqa: F401

        mp4 = True
    except ImportError:
        mp4 = False
    return {"gif": True, "mp4": mp4, "png": True}


def list_presets(_body=None) -> dict:
    return {"presets": [presets.to_json(p) for p in presets.PRESETS]}


# --------------------------------------------------------------------------
# Single trajectory
# --------------------------------------------------------------------------


def energy_diagnostic(res) -> tuple[np.ndarray, str]:
    """Dimensionless energy-error diagnostic that stays meaningful when E0 ≈ 0.

    * forced runs: energy-balance residual / E_char
    * |E0| >= 1e-3 E_char: (E - E0)/|E0|
    * otherwise (e.g. both rods horizontal at rest, E0 = 0): (E - E0)/E_char
    with E_char = (m1+m2) g L1 + m2 g L2.
    """
    p = res.config.physical
    E = res.energy["E"]
    scale = res.energy_scale
    if p.has_forcing:
        return np.asarray(res.relative_energy_error), "balance residual / E_char"
    if abs(E[0]) >= 1e-3 * scale:
        return (E - E[0]) / abs(E[0]), "(E-E0)/|E0|"
    return (E - E[0]) / scale, "(E-E0)/E_char (E0≈0)"


def simulate(body: dict) -> dict:
    """Integrate one config. Returns unwrapped angles, velocities, accelerations,
    energy components, the energy-error diagnostic, events and a summary."""
    cfg = parse_config(body.get("config"))
    _check_budget(cfg)
    t0 = time.perf_counter()
    res = core_simulate(cfg)
    if not res.success:
        raise ApiError(f"integration failed: {res.message}")
    sim_s = time.perf_counter() - t0
    y = res.y
    e = res.energy
    acc = res.accelerations
    p = cfg.physical
    _, _, vx2, vy2 = physics.velocities(y, p)
    err, err_kind = energy_diagnostic(res)
    out = {
        "config": cfg.to_dict(),
        "digest": cfg.digest(),
        "t": arr(res.t, 9),
        "theta1": arr(y[:, 0], 9),
        "theta2": arr(y[:, 1], 9),
        "omega1": arr(y[:, 2]),
        "omega2": arr(y[:, 3]),
        "alpha1": arr(acc[:, 0], 6),
        "alpha2": arr(acc[:, 1], 6),
        "T": arr(e["T"]),
        "V": arr(e["V"]),
        "E": arr(e["E"], 10),
        "energy_error": arr(err, 4),
        "energy_error_kind": err_kind,
        "speed2": arr(np.hypot(vx2, vy2), 6),
        "angular_momentum": arr(physics.angular_momentum(y, p), 6),
        "events": ev.detect_events(res),
        "summary": res.summary() | {"wall_s": sim_s, "max_abs_rel_energy_error": float(np.max(np.abs(err))),
                                    "final_rel_energy_error": float(err[-1]), "energy_error_kind": err_kind},
        "rotations": list(ev.rotation_counts(y)),
        "steps_per_second": (cfg.numerics.t_max / cfg.numerics.dt / max(res.runtime, 1e-9))
        if cfg.numerics.method == "rk4" else None,
    }
    if p.has_forcing:
        out["work"] = {
            k: arr(e[k], 6) for k in ("W_drive", "W_damp", "P_drive", "P_damp") if k in e
        }
        out["work"]["drive_torque"] = arr(physics.drive_torque(res.t, p) * np.ones_like(res.t), 6)
    return out


def export_csv(body: dict) -> tuple[str, str]:
    """Full-precision CSV of a simulation with a units header. Returns (filename, text)."""
    cfg = parse_config(body.get("config"))
    _check_budget(cfg)
    res = core_simulate(cfg)
    t0, t1 = float(body.get("t_start", 0.0)), float(body.get("t_end", res.t[-1]))
    m = (res.t >= t0 - 1e-12) & (res.t <= t1 + 1e-12)
    every = int(_num(body, "every", 1, 1, 10_000, int))
    y = res.y[m][::every]
    t = res.t[m][::every]
    p = cfg.physical
    x1, y1, x2, y2 = physics.positions(y, p)
    vx1, vy1, vx2, vy2 = physics.velocities(y, p)
    a1, a2 = physics.accelerations(t, y, p)
    T, V = physics.kinetic_energy(y, p), physics.potential_energy(y, p)
    E0 = float(physics.total_energy(np.array(cfg.initial.state()), p))
    cols = [
        ("t", "s", "physical time", t),
        ("theta1", "rad", "upper rod angle from downward vertical (unwrapped)", y[:, 0]),
        ("theta2", "rad", "lower rod angle from downward vertical (unwrapped)", y[:, 1]),
        ("omega1", "rad/s", "d theta1/dt", y[:, 2]),
        ("omega2", "rad/s", "d theta2/dt", y[:, 3]),
        ("alpha1", "rad/s^2", "d omega1/dt", a1),
        ("alpha2", "rad/s^2", "d omega2/dt", a2),
        ("x1", "m", "upper mass x (pivot at origin)", x1),
        ("y1", "m", "upper mass y (up positive)", y1),
        ("x2", "m", "lower mass x", x2),
        ("y2", "m", "lower mass y", y2),
        ("vx1", "m/s", "", vx1), ("vy1", "m/s", "", vy1), ("vx2", "m/s", "", vx2), ("vy2", "m/s", "", vy2),
        ("T", "J", "kinetic energy", T),
        ("V", "J", "potential energy (zero at pivot height)", V),
        ("E", "J", "total energy T+V", T + V),
        ("dE_rel", "1", "(E-E0)/|E0|", (T + V - E0) / abs(E0) if E0 else T + V - E0),
    ]
    lines = [
        f"# Double Pendulum Simulator {pendulum_sim.__version__} — simulation export",
        f"# config_digest: {cfg.digest()}",
        f"# config: {cfg.to_json(indent=None)}",
    ]
    lines += [f"# {n} [{u}] {d}".rstrip() for n, u, d, _ in cols]
    lines.append(",".join(n for n, *_ in cols))
    data = np.column_stack([c[-1] for c in cols])
    lines += [",".join(f"{v:.12g}" for v in row) for row in data]
    name = f"pendulum-sim-{cfg.digest()}.csv"
    return name, "\n".join(lines) + "\n"


def analysis(body: dict) -> dict:
    """Spectra and recurrence plot for one config (exploratory)."""
    cfg = parse_config(body.get("config"))
    _check_budget(cfg)
    res = core_simulate(cfg)
    dt = float(res.t[1] - res.t[0])
    out = {"dt": dt}
    for k, i in (("theta1", 0), ("theta2", 1)):
        s = spectral.spectrum(np.sin(res.y[:, i]), dt)
        fmax = float(body.get("fmax", 5.0))
        m = s["frequency_hz"] <= fmax
        out[f"spectrum_{k}"] = {"f": arr(s["frequency_hz"][m], 6), "amp": arr(s["amplitude"][m], 5)}
    thr = _num(body, "threshold", 0.3, 1e-4, 10)
    npts = int(_num(body, "points", 400, 50, 800, int))
    idx, R = spectral.recurrence_matrix(res.y, thr, physics.natural_time_scale(cfg.physical), npts)
    out["recurrence"] = {
        "n": int(len(idx)),
        "t": arr(res.t[idx], 6),
        "bits": base64.b64encode(np.packbits(R.astype(np.uint8), axis=None).tobytes()).decode(),
        "threshold": thr,
        "rate": float(R.mean()),
    }
    return out


# --------------------------------------------------------------------------
# Butterfly arena
# --------------------------------------------------------------------------


def butterfly(body: dict, ctx=None) -> dict:
    cfg = parse_config(body.get("config"))
    n = int(_num(body, "n", 10, 2, MAX_ENSEMBLE, int))
    _check_budget(cfg, n, MAX_ENSEMBLE_WORK)
    eps = _num(body, "epsilon", 1e-6)
    if eps == 0 or abs(eps) > 1:
        raise ApiError("epsilon must be non-zero with |epsilon| <= 1")
    variable = str(body.get("variable", "theta1"))
    if variable not in ensemble.VARIABLES:
        raise ApiError(f"variable must be one of {list(ensemble.VARIABLES)}")
    dist = str(body.get("distribution", "linear"))
    threshold = _num(body, "threshold", 0.5, 1e-6, 100)
    # Display sampling: keep the payload bounded for large ensembles.
    out_dt = max(cfg.numerics.output_dt, cfg.numerics.dt, 1 / 120 if n <= 20 else 1 / 60 if n <= 120 else 1 / 30)
    cfg = cfg.with_(**{"numerics.output_dt": out_dt})

    cb = None
    if ctx is not None:
        def cb(frac):
            ctx.progress(frac * 0.95)
            return ctx.cancelled()

    r = ensemble.butterfly(cfg, n=n, epsilon=eps, variable=variable, distribution=dist,
                           seed=int(_num(body, "seed", 0, 0, 2**31, int)), threshold=threshold,
                           numerical_control=bool(body.get("numerical_control", True)), callback=cb,
                           max_members=MAX_ENSEMBLE)
    if ctx is not None:
        ctx.check()
    Y = r["Y"]
    sep = r["separation"]
    with np.errstate(divide="ignore", invalid="ignore"):
        logsep = np.where(sep > 0, np.log10(np.where(sep > 0, sep, 1.0)), np.nan)
    # The wrapped angular difference of the lower arm, member vs reference
    dth2 = physics.wrap_angle(Y[:, :, 1] - Y[:, :1, 1])
    out = {
        "t": arr(r["t"], 7),
        "theta1": [arr(Y[:, k, 0], 6) for k in range(n)],
        "theta2": [arr(Y[:, k, 1], 6) for k in range(n)],
        "log10_separation": [arr(logsep[:, k], 4) for k in range(1, n)],
        "median_log10_separation": arr(np.nanmedian(np.where(np.isfinite(logsep[:, 1:]), logsep[:, 1:], np.nan), axis=1)
                                       if n > 1 else logsep[:, 0], 4),
        "angular_difference2": arr(np.median(np.abs(dth2[:, 1:]), axis=1), 4),
        "cartesian_separation_median": arr(np.median(r["cartesian_separation"][:, 1:], axis=1), 4),
        "divergence_times": r["divergence_times"],
        "threshold": threshold,
        "time_scale": r["time_scale"],
        "stats": r["stats"],
        "runtime_s": r["runtime_s"],
        "steps_per_second": r["steps_per_second"],
        "offsets": arr(Y[0, :, ensemble.VARIABLES[variable]] - Y[0, 0, ensemble.VARIABLES[variable]], 6),
        "metric": "||(wrap dθ1, wrap dθ2, τ dω1, τ dω2)||₂ with τ = sqrt(L1/g)",
    }
    if "numerical_control" in r:
        nc = r["numerical_control"]
        with np.errstate(divide="ignore", invalid="ignore"):
            out["numerical_control_log10"] = arr(np.where(nc > 0, np.log10(np.where(nc > 0, nc, 1.0)), np.nan), 4)
    return out


# --------------------------------------------------------------------------
# Lyapunov lab
# --------------------------------------------------------------------------


def lyapunov_run(body: dict, ctx=None) -> dict:
    cfg = parse_config(body.get("config"))
    t_max = _num(body, "t_max", 60.0, 1.0, 600.0)
    dt = _num(body, "dt", 2e-3, 1e-4, 0.01)
    if t_max / dt > 600_000:
        raise ApiError("t_max/dt too large (limit 6e5 steps)")
    iv = _num(body, "renorm_interval", 0.1, dt, 10.0)
    d0 = _num(body, "d0", 1e-8, 1e-14, 1e-2)
    method = str(body.get("method", "tangent"))
    if method not in ("tangent", "two_trajectory"):
        raise ApiError("method must be 'tangent' or 'two_trajectory'")
    cb = None
    if ctx is not None:
        def cb(frac):
            ctx.progress(frac)
            return ctx.cancelled()
    r = lyapunov.double_pendulum_lyapunov(cfg, t_max, dt=dt, renorm_interval=iv, d0=d0, method=method,
                                          transient=_num(body, "transient", 0.0, 0.0, 100.0), callback=cb)
    delta0 = _num(body, "delta0", 1e-6, 1e-15, 1.0)
    delta_max = _num(body, "delta_max", 0.5, 1e-6, 10.0)
    stride = max(1, len(r.t) // 3000)
    return {
        "t": arr(r.t[::stride], 7),
        "running": arr(r.running[::stride], 6),
        "local": arr(r.local[::stride], 5),
        "lambda": r.lam,
        "method": r.method,
        "dt": r.dt,
        "renorm_interval": r.renorm_interval,
        "d0": r.d0,
        "horizon": {"delta0": delta0, "delta_max": delta_max,
                    "T": r.predictability_horizon(delta0, delta_max)},
        "norm": "Euclidean in (θ1, θ2, τω1, τω2), τ = sqrt(L1/g), angle differences wrapped",
    }


def lyapunov_scan(body: dict, ctx=None) -> dict:
    cfg = parse_config(body.get("config"))
    t_max = _num(body, "t_max", 30.0, 1.0, 120.0)
    if ctx:
        ctx.progress(0.05, message="running estimator grid")
    r = lyapunov.sensitivity_scan(cfg, t_max)
    return r


def lyapunov_validate(_body=None, ctx=None) -> dict:
    """Validate the estimator on Lorenz-63 (reference λmax ≈ 0.9056)."""
    r = lyapunov.largest_lyapunov(lyapunov.lorenz, [1.0, 1.0, 1.0], 60.0, dt=0.005, renorm_interval=0.1,
                                  transient=10.0)
    return {"system": "Lorenz-63 (σ=10, ρ=28, β=8/3)", "estimate": r.lam, "reference": 0.9056,
            "t": arr(r.t[::5]), "running": arr(r.running[::5])}


# --------------------------------------------------------------------------
# Poincaré sections
# --------------------------------------------------------------------------


def poincare_run(body: dict, ctx=None) -> dict:
    cfg = parse_config(body.get("config") or {})
    p = cfg.physical
    if p.has_forcing:
        raise ApiError("Poincaré sections at fixed energy require a conservative system (no damping/driving)")
    t_max = _num(body, "t_max", 200.0, 1.0, MAX_POINCARE_T)
    if "energy" in body and body.get("energy") is not None:
        E = _num(body, "energy", -15.0)
        th2 = [float(v) for v in (body.get("theta2_values") or [0.1, 0.5, 1.0, 1.5])][:MAX_POINCARE_TRAJ]
        om2 = body.get("omega2_values")
        initials = poincare.fixed_energy_initials(p, E, th2, om2[: len(th2)] if om2 else None)
        if not initials:
            raise ApiError("no initial condition reaches that energy on the section (θ1=0, ω1>0)")
    else:
        initials = [list(map(float, y)) for y in (body.get("initials") or [cfg.initial.state()])][:MAX_POINCARE_TRAJ]
        E = None
    kw = {"rtol": _num(body, "rtol", 1e-10, 1e-14, 1e-4), "atol": _num(body, "rtol", 1e-10, 1e-14, 1e-4),
          "max_points": int(_num(body, "max_points", 4000, 10, 50_000, int))}
    jobs = [(p, y0, t_max, kw) for y0 in initials]
    results: list = [None] * len(jobs)
    workers = max(1, min(len(jobs), (os.cpu_count() or 2) - 1))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(poincare._section_job, j): i for i, j in enumerate(jobs)}
        done = 0
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()
            done += 1
            if ctx is not None:
                ctx.progress(done / len(jobs))
                if ctx.cancelled():
                    for f in futs:
                        f.cancel()
                    raise InterruptedError
    return {
        "energy": E,
        "surface": "θ1 = 0 (mod 2π), crossing with ω1 > 0; plotted (θ2 wrapped, ω2)",
        "sections": [
            {"initial": y0, "theta2": arr(r["theta2"], 6), "omega2": arr(r["omega2"], 6), "count": len(r["t"]),
             "energy": r["energy"], "energy_drift": r["energy_drift"], "runtime_s": r["runtime_s"]}
            for y0, r in zip(initials, results)
        ],
    }


# --------------------------------------------------------------------------
# Chaos maps
# --------------------------------------------------------------------------


def map_spec(body: dict) -> maps.MapSpec:
    cfg = parse_config(body.get("config") or {})
    spec = maps.MapSpec(
        observable=str(body.get("observable", "first_flip")),
        theta1_range=tuple(float(v) for v in body.get("theta1_range", (-180.0, 180.0))),
        theta2_range=tuple(float(v) for v in body.get("theta2_range", (-180.0, 180.0))),
        nx=int(_num(body, "nx", 160, 1, 2000, int)),
        ny=int(_num(body, "ny", 160, 1, 2000, int)),
        t_max=_num(body, "t_max", 10.0, 0.01, 200.0),
        dt=_num(body, "dt", 0.005, 1e-4, 0.05),
        omega1=_num(body, "omega1", 0.0),
        omega2=_num(body, "omega2", 0.0),
        physical=replace(cfg.physical),
    )
    if spec.physical.has_forcing:
        raise ApiError("chaos maps use the unforced model; remove damping/driving")
    try:
        spec.validate()
    except ValueError as e:
        raise ApiError(str(e)) from None
    if spec.theta1_range[0] >= spec.theta1_range[1] or spec.theta2_range[0] >= spec.theta2_range[1]:
        raise ApiError("ranges must be increasing")
    return spec


def chaos_map(body: dict, ctx=None) -> dict:
    spec = map_spec(body)
    t0 = time.perf_counter()

    def progress(frac, partial):
        if ctx is not None:
            ctx.progress(frac, {"data": f32(partial), "nx": spec.nx, "ny": spec.ny})

    data = maps.compute_map(spec, workers=body.get("workers"), progress=progress,
                            cancel=(ctx.cancelled if ctx else None), use_cache=bool(body.get("cache", True)))
    finite = data[np.isfinite(data)]
    return {
        "spec": spec.to_dict(),
        "digest": spec.digest(),
        "nx": spec.nx,
        "ny": spec.ny,
        "data": f32(data),
        "min": float(finite.min()) if finite.size else None,
        "max": float(finite.max()) if finite.size else None,
        "nan_fraction": float(1 - finite.size / data.size),
        "runtime_s": time.perf_counter() - t0,
        "axes": "x = θ1(0) [deg], y = θ2(0) [deg]; row 0 is the lowest θ2",
    }


# --------------------------------------------------------------------------
# Physics lab
# --------------------------------------------------------------------------


def integrators(body: dict, ctx=None) -> dict:
    cfg = parse_config(body.get("config"))
    t_max = _num(body, "t_max", 20.0, 0.5, 60.0)
    cfg = cfg.with_(**{"numerics.t_max": t_max, "numerics.output_dt": 1 / 60})
    settings = body.get("settings") or integrator_lab.DEFAULT_SETTINGS
    clean = []
    for s in settings[:8]:
        m = str(s.get("method"))
        if m not in METHODS:
            raise ApiError(f"unknown method {m}")
        d = {"method": m}
        if m == "rk4":
            d["dt"] = _num(s, "dt", 1e-3, 2e-5, 0.1)
            if t_max / d["dt"] > MAX_RK4_STEPS:
                raise ApiError("RK4 step too small for this horizon")
        else:
            d["rtol"] = _num(s, "rtol", 1e-8, 1e-13, 1e-2)
            d["atol"] = _num(s, "atol", 1e-10, 1e-14, 1e-2)
        clean.append(d)
    if ctx:
        ctx.progress(0.1, message="running reference DOP853 (rtol=atol=1e-13)")
    r = integrator_lab.compare(cfg, clean, keep_trajectories=True)
    traj = {}
    for label, tr in r["trajectories"].items():
        with np.errstate(divide="ignore"):
            traj[label] = {
                "t": arr(tr["t"], 6),
                "theta1": arr(tr["y"][:, 0], 6),
                "theta2": arr(tr["y"][:, 1], 6),
                "log10_energy_error": arr(np.log10(np.maximum(np.abs(tr["energy_error"]), 1e-17)), 4),
                "log10_distance": arr(np.log10(np.maximum(tr["distance"], 1e-17)), 4),
            }
    conv = integrator_lab.rk4_convergence(cfg)
    return {"rows": r["rows"], "reference_nfev": r["reference_nfev"], "trajectories": traj, "convergence": conv}


def modes(body: dict) -> dict:
    cfg = parse_config(body.get("config"))
    p = cfg.physical
    nm = linear.normal_modes(p)
    eq = linear.equilibria(p)
    for e in eq:
        e["theta1_deg"] = math.degrees(e["theta1"])
        e["theta2_deg"] = math.degrees(e["theta2"])
    # Linear vs nonlinear comparison for the requested initial state
    t_max = _num(body, "t_max", 20.0, 1.0, 120.0)
    c2 = cfg.with_(**{"numerics.t_max": t_max, "numerics.output_dt": 1 / 60, "numerics.method": "dop853",
                      "numerics.rtol": 1e-10, "numerics.atol": 1e-10})
    c2 = replace(c2, physical=replace(p, damping1=0.0, damping2=0.0, drive_amplitude=0.0))
    res = core_simulate(c2)
    lin = linear.linear_solution(c2.physical, c2.initial.state(), res.t)
    err = np.max(np.abs(lin[:, :2] - res.y[:, :2]), axis=1)
    thr = math.radians(_num(body, "breakdown_deg", 2.0, 0.01, 90))
    bad = np.nonzero(err > thr)[0]
    amp = float(np.max(np.abs(np.degrees(res.y[:, :2]))))
    return {
        "normal_modes": nm,
        "mode_states_deg": [[math.degrees(v) for v in linear.mode_initial_state(p, k, 3.0)[:2]] for k in (0, 1)],
        "equilibria": eq,
        "comparison": {
            "t": arr(res.t, 6),
            "theta1": arr(res.y[:, 0], 6), "theta2": arr(res.y[:, 1], 6),
            "theta1_linear": arr(lin[:, 0], 6), "theta2_linear": arr(lin[:, 1], 6),
            "max_abs_error": arr(err, 4),
            "breakdown_threshold_deg": math.degrees(thr),
            "breakdown_t": float(res.t[bad[0]]) if len(bad) else None,
            "max_amplitude_deg": amp,
        },
    }


def landscape(body: dict) -> dict:
    cfg = parse_config(body.get("config"))
    n = int(_num(body, "n", 121, 11, 401, int))
    a = np.linspace(-np.pi, np.pi, n)
    T1, T2 = np.meshgrid(a, a)
    y = np.stack([T1, T2, 0 * T1, 0 * T1], axis=-1)
    V = physics.potential_energy(y, cfg.physical)
    return {"n": n, "V": f32(V), "min": float(V.min()), "max": float(V.max()),
            "E0": float(physics.total_energy(np.array(cfg.initial.state()), cfg.physical)),
            "equilibria": [{k: e[k] for k in ("name", "theta1", "theta2", "potential_energy", "classification")}
                           for e in linear.equilibria(cfg.physical)]}


def sweep_run(body: dict, ctx=None) -> dict:
    cfg = parse_config(body.get("config"))
    xk = str(body.get("x_key", "theta1_deg"))
    yk = body.get("y_key") or None
    xr = body.get("x_range", [0, 180])
    nx = int(_num(body, "nx", 60, 2, 400, int))
    xv = np.linspace(float(xr[0]), float(xr[1]), nx)
    yv = None
    if yk:
        yr = body.get("y_range", [0, 180])
        ny = int(_num(body, "ny", 60, 2, 400, int))
        yv = np.linspace(float(yr[0]), float(yr[1]), ny)
    t_max = _num(body, "t_max", 10.0, 0.1, 120.0)
    dt = _num(body, "dt", 0.005, 1e-4, 0.05)
    pts = nx * (len(yv) if yv is not None else 1)
    if pts * t_max / dt > MAX_SWEEP_WORK:
        raise ApiError(f"sweep workload {pts * t_max / dt:.2g} point-steps exceeds {MAX_SWEEP_WORK:.2g}")
    obs = str(body.get("observable", "rotations"))
    if ctx:
        ctx.progress(0.05, message=f"{pts} points x {int(t_max / dt)} steps (vectorized RK4)")
    try:
        r = sweeps.sweep(cfg, xk, xv, yk, yv, observable=obs, t_max=t_max, dt=dt)
    except ValueError as e:
        raise ApiError(str(e)) from None
    vals = np.asarray(r["values"], dtype=float)
    return {"x_key": xk, "y_key": yk, "x": arr(xv), "y": arr(yv) if yv is not None else None,
            "observable": obs, "values": f32(vals), "shape": list(vals.shape),
            "runtime_s": r["runtime_s"], "t_max": t_max, "dt": dt,
            "min": float(np.nanmin(vals)) if np.isfinite(vals).any() else None,
            "max": float(np.nanmax(vals)) if np.isfinite(vals).any() else None}


def tolerance_sweep(body: dict, ctx=None) -> dict:
    cfg = parse_config(body.get("config"))
    cfg = cfg.with_(**{"numerics.t_max": _num(body, "t_max", 20.0, 1.0, 60.0)})
    return {"rows": sweeps.tolerance_sweep(cfg, str(body.get("method", "dop853")))}


# --------------------------------------------------------------------------
# Advanced models (isolated from the standard double pendulum)
# --------------------------------------------------------------------------


def nlink_run(body: dict) -> dict:
    masses = [float(v) for v in body.get("masses", [1, 1, 1])]
    lengths = [float(v) for v in body.get("lengths", [1, 1, 1])]
    if not 1 <= len(masses) <= 8:
        raise ApiError("1 to 8 links supported")
    try:
        p = nlink.NLinkParams(tuple(masses), tuple(lengths), _num(body, "g", 9.81, 1e-3, 1e3))
    except ValueError as e:
        raise ApiError(str(e)) from None
    th = [math.radians(float(v)) for v in body.get("theta_deg", [120, -10, 30])][: p.n]
    om = [float(v) for v in body.get("omega", [0] * p.n)][: p.n]
    if len(th) != p.n or len(om) != p.n:
        raise ApiError("theta_deg and omega must have one entry per link")
    t_max = _num(body, "t_max", 20.0, 0.1, 120.0)
    dt = _num(body, "dt", 5e-4, 1e-5, 0.01)
    if t_max / dt > MAX_RK4_STEPS / 2:
        raise ApiError("too many steps")
    every = max(1, int(round((1 / 120) / dt)))
    out = integrate_rk4(lambda t, y: nlink.derivatives(t, y, p), th + om, t_max, dt, output_every=every)
    if not out.success:
        raise ApiError(out.message)
    E = nlink.total_energy(out.y, p)
    return {"n": p.n, "masses": masses, "lengths": lengths, "t": arr(out.t, 7),
            "theta": [arr(out.y[:, i], 7) for i in range(p.n)],
            "energy_error": arr((E - E[0]) / max(abs(E[0]), 1e-9), 4), "runtime_s": out.runtime,
            "model": "generalized mass matrix M_ij = μ_ij L_i L_j cos(θi−θj), μ_ij = Σ_{k≥max(i,j)} m_k"}


def pivot_run(body: dict) -> dict:
    cfg = parse_config(body.get("config"))
    pm = pivot.PivotMotion(_num(body, "amp_x", 0.0, -1, 1), _num(body, "amp_y", 0.05, -1, 1),
                           _num(body, "omega", 30.0, 0, 500))
    dt = min(cfg.numerics.dt, 0.2 / max(pm.omega, 1e-9), 1e-3)
    t_max = min(cfg.numerics.t_max, 60.0)
    if t_max / dt > MAX_RK4_STEPS:
        raise ApiError("too many steps for this drive frequency")
    every = max(1, int(round((1 / 120) / dt)))
    p = replace(cfg.physical, damping1=0.0, damping2=0.0, drive_amplitude=0.0)
    out = integrate_rk4(lambda t, y: pivot.derivatives(t, y, p, pm), cfg.initial.state(), t_max, dt,
                        output_every=every)
    px, py = pm.position(out.t)
    return {"t": arr(out.t, 7), "theta1": arr(out.y[:, 0], 7), "theta2": arr(out.y[:, 1], 7),
            "pivot_x": arr(np.broadcast_to(px, out.t.shape), 6), "pivot_y": arr(np.broadcast_to(py, out.t.shape), 6),
            "dt": dt, "model": "fixed-pivot equations in the effective field g_eff = g − a_pivot(t)"}


# --------------------------------------------------------------------------
# Studio / challenges
# --------------------------------------------------------------------------


def art_search(body: dict, ctx=None) -> dict:
    cfg = parse_config(body.get("config") or {})
    objective = str(body.get("objective", "complexity"))
    n = int(_num(body, "n_candidates", 64, 1, 600, int))
    t_max = _num(body, "t_max", 30.0, 2.0, 60.0)
    if ctx:
        ctx.progress(0.05, message=f"evaluating {n} candidates (vectorized)")
    try:
        res = art.search(objective, n, int(_num(body, "top", 8, 1, 24, int)), int(_num(body, "seed", 0, 0, 2**31, int)),
                         t_max, physical=replace(cfg.physical, damping1=0.0, damping2=0.0, drive_amplitude=0.0),
                         randomize_physics=bool(body.get("randomize_physics", False)))
    except ValueError as e:
        raise ApiError(str(e)) from None
    out = []
    for k, r in enumerate(res):
        if ctx:
            ctx.check()
            ctx.progress(0.5 + 0.5 * k / len(res), message="tracing previews")
        c = r["config"].with_(**{"numerics.dt": 2e-3, "numerics.output_dt": 1 / 30})
        sim = core_simulate(c)
        _, _, x2, y2 = physics.positions(sim.y, c.physical)
        out.append({"score": r["score"], "metrics": r["metrics"], "config": r["config"].to_dict(),
                    "x2": arr(x2, 4), "y2": arr(y2, 4)})
    return {"objective": objective, "candidates": out,
            "note": "Scores are documented geometric heuristics for ranking, not measures of beauty."}


def challenge_list(_body=None) -> dict:
    return {"challenges": challenges.CHALLENGES}


def challenge_eval(cid: str, body: dict) -> dict:
    try:
        return challenges.evaluate(cid, body or {})
    except KeyError as e:
        raise ApiError(str(e)) from None
    except (TypeError, ValueError) as e:
        raise ApiError(f"invalid input: {e}") from None


def random_config(body: dict) -> dict:
    """Deterministic randomized experiment from a seed."""
    seed = int(_num(body, "seed", 0, 0, 2**31, int))
    rng = np.random.default_rng(seed)
    phys = Physical(m1=float(np.round(rng.uniform(0.5, 2.0), 3)), m2=float(np.round(rng.uniform(0.5, 2.0), 3)),
                    L1=float(np.round(rng.uniform(0.6, 1.4), 3)), L2=float(np.round(rng.uniform(0.6, 1.4), 3)))
    init = Initial(float(np.round(rng.uniform(-180, 180), 2)), float(np.round(rng.uniform(-180, 180), 2)),
                   float(np.round(rng.normal(0, 1), 3)), float(np.round(rng.normal(0, 1), 3)))
    base = parse_config(body.get("config") or {})
    return {"seed": seed, "config": SimConfig(phys, init, base.numerics, f"Random #{seed}").to_dict()}


def default_config(_body=None) -> dict:
    return {"config": SimConfig(numerics=Numerics()).to_dict()}
