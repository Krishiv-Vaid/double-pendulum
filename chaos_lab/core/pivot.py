"""Double pendulum with a prescribed (moving) suspension point — an isolated
advanced experiment that does not modify the standard fixed-pivot model.

Pivot motion: x_p(t) = Ax cos(Omega t),  y_p(t) = Ay cos(Omega t).

Derivation. In the frame translating with the pivot each mass feels the
fictitious force -m a_p, so the dynamics are those of a fixed-pivot pendulum
in the uniform effective field g_eff = (-x_p'', -g - y_p''). The potential
V = -sum m_i (g_x x_i + g_y y_i) turns the fixed-pivot gravity term
g sin(theta) into

    x_p'' cos(theta) + (g + y_p'') sin(theta),

and the remaining Euler–Lagrange terms are unchanged. (A vertically driven
pivot with Ax = 0 gives the Kapitza-type parametric pendulum.) Energy is not
conserved: the pivot does work on the system.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from chaos_lab.core.config import Physical
from chaos_lab.core.physics import solve_accelerations


@dataclass(frozen=True)
class PivotMotion:
    amp_x: float = 0.0  # m
    amp_y: float = 0.05  # m
    omega: float = 30.0  # rad/s

    def position(self, t):
        c = np.cos(self.omega * np.asarray(t))
        return self.amp_x * c, self.amp_y * c

    def acceleration(self, t):
        c = np.cos(self.omega * np.asarray(t))
        return -self.amp_x * self.omega**2 * c, -self.amp_y * self.omega**2 * c


def derivatives(t, y, p: Physical, pivot: PivotMotion):
    y = np.asarray(y)
    th1, th2, w1, w2 = y[..., 0], y[..., 1], y[..., 2], y[..., 3]
    ax, ay = pivot.acceleration(t)
    gs1 = ax * np.cos(th1) + (p.g + ay) * np.sin(th1)
    gs2 = ax * np.cos(th2) + (p.g + ay) * np.sin(th2)
    a1, a2 = solve_accelerations(th1, th2, w1, w2, p, gs1, gs2)
    return np.stack(np.broadcast_arrays(w1, w2, a1, a2), axis=-1)
