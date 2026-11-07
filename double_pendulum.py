"""Double pendulum simulation with RK4 integration and energy tracking.

This is the original Double Pendulum Simulator entry point. It keeps its documented CLI and
output, and now runs on the ``pendulum_sim`` physics engine.

State vector: y = [theta1, theta2, omega1, omega2], angles measured from the
downward vertical. Equations of motion come from the Lagrangian
L = T - V and are solved each step as a 2x2 linear system M @ alpha = b.

Usage:
    python double_pendulum.py                 # animate
    python double_pendulum.py --t-max 60 --dt 0.0005
    python double_pendulum.py --save out.mp4  # or out.gif
    python double_pendulum.py --no-show       # just print energy stats
    python double_pendulum.py --method dop853 # adaptive integrator
    python double_pendulum.py --style dark    # white on black

For the full interactive lab run ``python -m pendulum_sim serve``.
"""

import argparse

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation

from pendulum_sim.core import physics
from pendulum_sim.core.config import Initial, Numerics, Physical, SimConfig
from pendulum_sim.core.integrators import rk4_step as _rk4_step
from pendulum_sim.core.simulation import simulate as _simulate

# --------------------------------------------------------------------------
# Backwards-compatible API (thin wrappers over pendulum_sim)
# --------------------------------------------------------------------------
Params = Physical


def derivatives(y: np.ndarray, p: Params) -> np.ndarray:
    """Return dy/dt for state y = [th1, th2, w1, w2]."""
    return physics.derivatives(0.0, y, p)


def rk4_step(y: np.ndarray, dt: float, p: Params) -> np.ndarray:
    return _rk4_step(lambda t, s: physics.derivatives(t, s, p), 0.0, y, dt)


def total_energy(Y: np.ndarray, p: Params) -> np.ndarray:
    """Total mechanical energy T + V for an array of states (N, 4)."""
    return physics.total_energy(Y, p)


def positions(Y: np.ndarray, p: Params):
    return physics.positions(Y, p)


def simulate(y0, t_max: float, dt: float, p: Params, method: str = "rk4"):
    """Integrate from y0 and return (t, Y) sampled every dt."""
    y0 = np.asarray(y0, dtype=float)
    init = Initial(np.degrees(y0[0]), np.degrees(y0[1]), y0[2], y0[3])
    cfg = SimConfig(p, init, Numerics(method=method, dt=dt, t_max=t_max, output_dt=dt))
    res = _simulate(cfg, y0=y0)
    if not res.success:
        raise RuntimeError(f"integration failed: {res.message}")
    return res.t, res.y


# --------------------------------------------------------------------------
# Animation
# --------------------------------------------------------------------------
STYLES = {
    "classic": dict(bg=None, fg=None, rod="tab:blue", mass="tab:red", trail="tab:orange",
                    energy="tab:green", backdrop="lightgray", box_fc="white", box_ec="0.7", grid=0.3),
    "dark": dict(bg="#000000", fg="#F2F2F2", rod="#B0B0B0", mass="#FFFFFF", trail="#FFFFFF",
                 energy="#FFFFFF", backdrop="#2E2E2E", box_fc="#0E0E0E", box_ec="#262626", grid=0.10),
}


def animate(t, Y, E, p: Params, fps: int, trail_seconds: float, save: str | None, show: bool,
            dpi: int = 100, style: str = "classic", method: str = "rk4"):
    st = STYLES[style]
    dt = t[1] - t[0]
    stride = max(1, int(round(1.0 / (fps * dt))))  # sim steps per frame
    frames = range(0, len(t), stride)
    trail_len = int(trail_seconds / dt)

    x1, y1, x2, y2 = positions(Y, p)
    E0 = E[0]
    rel_err = (E - E0) / abs(E0) if E0 != 0 else E - E0

    fig, (ax, axE) = plt.subplots(1, 2, figsize=(12, 6),
                                  gridspec_kw={"width_ratios": [1, 1.2]})
    if st["bg"]:
        fig.patch.set_facecolor(st["bg"])
        for a in (ax, axE):
            a.set_facecolor(st["bg"])
            a.tick_params(colors=st["fg"])
            for s in a.spines.values():
                s.set_color(st["backdrop"])
            a.title.set_color(st["fg"])
            a.xaxis.label.set_color(st["fg"])
            a.yaxis.get_offset_text().set_color(st["fg"])
    R = (p.L1 + p.L2) * 1.1
    ax.set_xlim(-R, R)
    ax.set_ylim(-R, R)
    ax.set_aspect("equal")
    ax.set_title(f"Double pendulum ({method.upper()})")
    ax.grid(alpha=st["grid"])
    trail, = ax.plot([], [], "-", lw=1, color=st["trail"], alpha=0.6)
    rods, = ax.plot([], [], "o-", lw=2, color=st["rod"], markersize=8,
                    markerfacecolor=st["mass"], markeredgecolor=st["mass"] if st["bg"] else None)
    time_text = ax.text(0.03, 0.97, "", transform=ax.transAxes, va="top", ha="left",
                        family="monospace", fontsize=10, color=st["fg"] or "black",
                        bbox=dict(boxstyle="round,pad=0.4", fc=st["box_fc"], ec=st["box_ec"], alpha=0.85))

    axE.set_title(r"Relative energy error  $(E - E_0)\,/\,|E_0|$")
    axE.set_xlabel("time [s]")
    axE.set_xlim(t[0], t[-1])
    span = max(np.max(np.abs(rel_err)), 1e-16) * 1.1
    axE.set_ylim(-span, span)
    axE.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
    axE.grid(alpha=st["grid"])
    axE.plot(t, rel_err, color=st["backdrop"], lw=1)  # full curve as backdrop
    e_line, = axE.plot([], [], color=st["energy"], lw=1.5)

    def update(i):
        rods.set_data([0, x1[i], x2[i]], [0, y1[i], y2[i]])
        j = max(0, i - trail_len)
        trail.set_data(x2[j:i + 1], y2[j:i + 1])
        e_line.set_data(t[:i + 1], rel_err[:i + 1])
        time_text.set_text(f"t = {t[i]:.2f} s\n"
                           rf"$\Delta E/E_0$ = {rel_err[i]:+.2e}")
        return rods, trail, e_line, time_text

    anim = FuncAnimation(fig, update, frames=frames, interval=1000 / fps, blit=True)
    fig.tight_layout()

    if save:
        print(f"Saving animation to {save} ...")
        if save.lower().endswith(".gif"):
            writer = "pillow"
        else:
            writer = None
            _use_bundled_ffmpeg()
        anim.save(save, writer=writer, fps=fps, dpi=dpi,
                  savefig_kwargs={"facecolor": fig.get_facecolor()})
    if show:
        plt.show()
    return anim


def _use_bundled_ffmpeg():
    """Point matplotlib at imageio-ffmpeg's bundled binary if no system ffmpeg exists."""
    import shutil

    if shutil.which(plt.rcParams["animation.ffmpeg_path"]):
        return
    try:
        import imageio_ffmpeg

        plt.rcParams["animation.ffmpeg_path"] = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--theta1", type=float, default=120.0, help="initial θ1 [deg]")
    ap.add_argument("--theta2", type=float, default=-10.0, help="initial θ2 [deg]")
    ap.add_argument("--omega1", type=float, default=0.0, help="initial ω1 [rad/s]")
    ap.add_argument("--omega2", type=float, default=0.0, help="initial ω2 [rad/s]")
    ap.add_argument("--m1", type=float, default=1.0)
    ap.add_argument("--m2", type=float, default=1.0)
    ap.add_argument("--L1", type=float, default=1.0)
    ap.add_argument("--L2", type=float, default=1.0)
    ap.add_argument("--g", type=float, default=9.81)
    ap.add_argument("--t-max", type=float, default=30.0, help="simulated time [s]")
    ap.add_argument("--dt", type=float, default=1e-3, help="RK4 step / output spacing [s]")
    ap.add_argument("--method", choices=["rk4", "rk45", "dop853"], default="rk4",
                    help="integrator (default rk4)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--trail", type=float, default=2.0, help="trail length [s]")
    ap.add_argument("--style", choices=sorted(STYLES), default="classic", help="plot theme")
    ap.add_argument("--save", type=str, default=None, help="save to .mp4 or .gif")
    ap.add_argument("--dpi", type=int, default=100, help="resolution when saving")
    ap.add_argument("--no-show", action="store_true", help="don't open a window")
    args = ap.parse_args(argv)

    p = Params(args.m1, args.m2, args.L1, args.L2, args.g)
    try:
        p.validate()
    except ValueError as e:
        ap.error(str(e))
    y0 = np.array([np.radians(args.theta1), np.radians(args.theta2),
                   args.omega1, args.omega2])

    t, Y = simulate(y0, args.t_max, args.dt, p, method=args.method)
    E = total_energy(Y, p)
    rel = (E - E[0]) / abs(E[0])
    print(f"Steps: {len(t) - 1}, dt = {args.dt}")
    print(f"E0 = {E[0]:.10f} J")
    print(f"Max |ΔE/E0| = {np.max(np.abs(rel)):.3e}")
    print(f"Final ΔE/E0 = {rel[-1]:+.3e}")

    if args.save or not args.no_show:
        animate(t, Y, E, p, args.fps, args.trail, args.save, show=not args.no_show,
                dpi=args.dpi, style=args.style, method=args.method)


if __name__ == "__main__":
    main()
