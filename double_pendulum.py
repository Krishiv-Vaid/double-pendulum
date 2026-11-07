"""Double pendulum simulation with RK4 integration and energy tracking.

State vector: y = [theta1, theta2, omega1, omega2], angles measured from the
downward vertical. Equations of motion come from the Lagrangian
L = T - V and are solved each step as a 2x2 linear system M @ alpha = b.

Usage:
    python double_pendulum.py                 # animate
    python double_pendulum.py --t-max 60 --dt 0.0005
    python double_pendulum.py --save out.mp4  # or out.gif
    python double_pendulum.py --no-show       # just print energy stats
"""

import argparse
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation


@dataclass
class Params:
    m1: float = 1.0
    m2: float = 1.0
    L1: float = 1.0
    L2: float = 1.0
    g: float = 9.81


def derivatives(y: np.ndarray, p: Params) -> np.ndarray:
    """Return dy/dt for state y = [th1, th2, w1, w2]."""
    th1, th2, w1, w2 = y
    d = th1 - th2
    c, s = np.cos(d), np.sin(d)
    M = np.array([
        [(p.m1 + p.m2) * p.L1, p.m2 * p.L2 * c],
        [p.L1 * c,             p.L2],
    ])
    b = np.array([
        -p.m2 * p.L2 * w2**2 * s - (p.m1 + p.m2) * p.g * np.sin(th1),
        p.L1 * w1**2 * s - p.g * np.sin(th2),
    ])
    a1, a2 = np.linalg.solve(M, b)
    return np.array([w1, w2, a1, a2])


def rk4_step(y: np.ndarray, dt: float, p: Params) -> np.ndarray:
    k1 = derivatives(y, p)
    k2 = derivatives(y + 0.5 * dt * k1, p)
    k3 = derivatives(y + 0.5 * dt * k2, p)
    k4 = derivatives(y + dt * k3, p)
    return y + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)


def total_energy(Y: np.ndarray, p: Params) -> np.ndarray:
    """Total mechanical energy T + V for an array of states (N, 4)."""
    th1, th2, w1, w2 = Y.T
    T = (0.5 * (p.m1 + p.m2) * p.L1**2 * w1**2
         + 0.5 * p.m2 * p.L2**2 * w2**2
         + p.m2 * p.L1 * p.L2 * w1 * w2 * np.cos(th1 - th2))
    V = (-(p.m1 + p.m2) * p.g * p.L1 * np.cos(th1)
         - p.m2 * p.g * p.L2 * np.cos(th2))
    return T + V


def simulate(y0, t_max: float, dt: float, p: Params):
    n = int(round(t_max / dt))
    t = np.linspace(0.0, n * dt, n + 1)
    Y = np.empty((n + 1, 4))
    Y[0] = y0
    for i in range(n):
        Y[i + 1] = rk4_step(Y[i], dt, p)
    return t, Y


def positions(Y: np.ndarray, p: Params):
    th1, th2 = Y[:, 0], Y[:, 1]
    x1 = p.L1 * np.sin(th1)
    y1 = -p.L1 * np.cos(th1)
    x2 = x1 + p.L2 * np.sin(th2)
    y2 = y1 - p.L2 * np.cos(th2)
    return x1, y1, x2, y2


def animate(t, Y, E, p: Params, fps: int, trail_seconds: float, save: str | None, show: bool,
            dpi: int = 100):
    dt = t[1] - t[0]
    stride = max(1, int(round(1.0 / (fps * dt))))  # sim steps per frame
    frames = range(0, len(t), stride)
    trail_len = int(trail_seconds / dt)

    x1, y1, x2, y2 = positions(Y, p)
    E0 = E[0]
    rel_err = (E - E0) / abs(E0) if E0 != 0 else E - E0

    fig, (ax, axE) = plt.subplots(1, 2, figsize=(12, 6),
                                  gridspec_kw={"width_ratios": [1, 1.2]})
    R = (p.L1 + p.L2) * 1.1
    ax.set_xlim(-R, R)
    ax.set_ylim(-R, R)
    ax.set_aspect("equal")
    ax.set_title("Double pendulum (RK4)")
    ax.grid(alpha=0.3)
    trail, = ax.plot([], [], "-", lw=1, color="tab:orange", alpha=0.6)
    rods, = ax.plot([], [], "o-", lw=2, color="tab:blue", markersize=8,
                    markerfacecolor="tab:red")
    time_text = ax.text(0.03, 0.97, "", transform=ax.transAxes, va="top", ha="left",
                        family="monospace", fontsize=10,
                        bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="0.7", alpha=0.85))

    axE.set_title(r"Relative energy error  $(E - E_0)\,/\,|E_0|$")
    axE.set_xlabel("time [s]")
    axE.set_xlim(t[0], t[-1])
    span = max(np.max(np.abs(rel_err)), 1e-16) * 1.1
    axE.set_ylim(-span, span)
    axE.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
    axE.grid(alpha=0.3)
    axE.plot(t, rel_err, color="lightgray", lw=1)  # full curve as backdrop
    e_line, = axE.plot([], [], color="tab:green", lw=1.5)

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
        writer = "pillow" if save.lower().endswith(".gif") else None
        anim.save(save, writer=writer, fps=fps, dpi=dpi)
    if show:
        plt.show()
    return anim


def main():
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
    ap.add_argument("--dt", type=float, default=1e-3, help="RK4 step [s]")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--trail", type=float, default=2.0, help="trail length [s]")
    ap.add_argument("--save", type=str, default=None, help="save to .mp4 or .gif")
    ap.add_argument("--dpi", type=int, default=100, help="resolution when saving")
    ap.add_argument("--no-show", action="store_true", help="don't open a window")
    args = ap.parse_args()

    p = Params(args.m1, args.m2, args.L1, args.L2, args.g)
    y0 = np.array([np.radians(args.theta1), np.radians(args.theta2),
                   args.omega1, args.omega2])

    t, Y = simulate(y0, args.t_max, args.dt, p)
    E = total_energy(Y, p)
    rel = (E - E[0]) / abs(E[0])
    print(f"Steps: {len(t) - 1}, dt = {args.dt}")
    print(f"E0 = {E[0]:.10f} J")
    print(f"Max |ΔE/E0| = {np.max(np.abs(rel)):.3e}")
    print(f"Final ΔE/E0 = {rel[-1]:+.3e}")

    if args.save or not args.no_show:
        animate(t, Y, E, p, args.fps, args.trail, args.save,
                show=not args.no_show, dpi=args.dpi)


if __name__ == "__main__":
    main()
