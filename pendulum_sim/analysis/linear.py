"""Linearized dynamics: small-angle normal modes and equilibrium stability.

Small-angle model about the hanging equilibrium (theta1 = theta2 = 0):

    M0 theta'' + K0 theta = 0,
    M0 = [[(m1+m2) L1^2, m2 L1 L2], [m2 L1 L2, m2 L2^2]],
    K0 = diag((m1+m2) g L1, m2 g L2).

The generalized eigenproblem K0 phi = omega^2 M0 phi gives the two normal-mode
angular frequencies and mode shapes. For m1 = m2, L1 = L2 = L:
omega^2 = (2 -+ sqrt 2) g / L.
"""

from __future__ import annotations

import numpy as np
from scipy.linalg import eigh

from pendulum_sim.core import physics
from pendulum_sim.core.config import Physical


def linear_matrices(p: Physical):
    M = np.array([[(p.m1 + p.m2) * p.L1**2, p.m2 * p.L1 * p.L2], [p.m2 * p.L1 * p.L2, p.m2 * p.L2**2]])
    K = np.diag([(p.m1 + p.m2) * p.g * p.L1, p.m2 * p.g * p.L2])
    return M, K


def normal_modes(p: Physical) -> dict:
    """Frequencies (rad/s, ascending), periods (s) and mass-normalized mode shapes (columns)."""
    M, K = linear_matrices(p)
    w2, phi = eigh(K, M)  # phi.T @ M @ phi = I
    omega = np.sqrt(w2)
    shapes = phi / phi[0]  # normalize so theta1 component = 1 for display
    return {
        "omega": omega.tolist(),
        "frequency_hz": (omega / (2 * np.pi)).tolist(),
        "period_s": (2 * np.pi / omega).tolist(),
        "shape_ratio_theta2_over_theta1": shapes[1].tolist(),
        "phi": phi.tolist(),
    }


def mode_initial_state(p: Physical, mode: int, amplitude_deg: float = 3.0) -> list[float]:
    """Initial state exciting a single normal mode (index 0 = slow, 1 = fast),
    with theta1 amplitude ``amplitude_deg``, starting from rest."""
    r = normal_modes(p)["shape_ratio_theta2_over_theta1"][mode]
    a = np.radians(amplitude_deg)
    return [float(a), float(a * r), 0.0, 0.0]


def linear_solution(p: Physical, y0, t) -> np.ndarray:
    """Exact solution of the linearized equations, returned as states (n, 4)."""
    M, K = linear_matrices(p)
    w2, phi = eigh(K, M)
    w = np.sqrt(w2)
    th0 = np.asarray(y0[:2], dtype=float)
    om0 = np.asarray(y0[2:], dtype=float)
    q0 = phi.T @ M @ th0
    qd0 = phi.T @ M @ om0
    t = np.asarray(t)[:, None]
    q = q0 * np.cos(w * t) + qd0 / w * np.sin(w * t)
    qd = -q0 * w * np.sin(w * t) + qd0 * np.cos(w * t)
    return np.concatenate([q @ phi.T, qd @ phi.T], axis=1)


EQUILIBRIA = {
    "down-down": (0.0, 0.0),
    "down-up": (0.0, np.pi),
    "up-down": (np.pi, 0.0),
    "up-up": (np.pi, np.pi),
}


def equilibria(p: Physical) -> list[dict]:
    """The four vertical equilibria (mod 2 pi) with linear stability classification.

    For conservative dynamics eigenvalues come in +-pairs: purely imaginary
    pairs are elliptic (neutrally stable to linear order); each real positive
    eigenvalue is an unstable direction. With damping, all Re < 0 means
    asymptotically stable.
    """
    out = []
    for name, (a, b) in EQUILIBRIA.items():
        y = np.array([a, b, 0.0, 0.0])
        J = physics.jacobian(0.0, y, p)
        ev = np.linalg.eigvals(J)
        n_unstable = int(np.sum(ev.real > 1e-9))
        if n_unstable:
            kind = f"unstable ({n_unstable} unstable direction{'s' if n_unstable > 1 else ''})"
        elif np.all(ev.real < -1e-9):
            kind = "asymptotically stable"
        else:
            kind = "linearly stable (elliptic)"
        out.append({
            "name": name,
            "theta1": a,
            "theta2": b,
            "potential_energy": float(physics.potential_energy(y, p)),
            "eigenvalues": [[float(e.real), float(e.imag)] for e in ev],
            "classification": kind,
        })
    return out
