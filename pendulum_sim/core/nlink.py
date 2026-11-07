"""Planar N-link pendulum (point masses on massless rods) — triple pendulum and beyond.

Generalized mass-matrix formulation (angles from the downward vertical):

    sum_j M_ij(theta) theta_j'' = -sum_j mu_ij L_i L_j sin(theta_i - theta_j) omega_j^2
                                  - mu_ii g L_i sin(theta_i)

with mu_ij = sum_{k >= max(i, j)} m_k  (total mass hanging at or below the
lower of the two joints) and M_ij = mu_ij L_i L_j cos(theta_i - theta_j).
These follow from the Euler–Lagrange equations of

    T = 1/2 sum_ij mu_ij L_i L_j cos(theta_i - theta_j) omega_i omega_j
    V = -g sum_i mu_ii L_i cos(theta_i).

For N = 2 the system reduces exactly to the double pendulum equations in
:mod:`pendulum_sim.core.physics` (verified in the test suite). This is a
separate model; the double pendulum code does not depend on it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class NLinkParams:
    masses: tuple[float, ...] = (1.0, 1.0, 1.0)
    lengths: tuple[float, ...] = (1.0, 1.0, 1.0)
    g: float = 9.81

    def __post_init__(self):
        if len(self.masses) != len(self.lengths) or len(self.masses) < 1:
            raise ValueError("masses and lengths must have the same non-zero length")
        if min(self.masses) <= 0 or min(self.lengths) <= 0 or self.g <= 0:
            raise ValueError("masses, lengths and g must be positive")

    @property
    def n(self) -> int:
        return len(self.masses)

    def mu(self) -> np.ndarray:
        m = np.asarray(self.masses, dtype=float)
        tail = np.cumsum(m[::-1])[::-1]  # tail[k] = sum_{j>=k} m_j
        idx = np.maximum.outer(np.arange(self.n), np.arange(self.n))
        return tail[idx]


def derivatives(t, y, p: NLinkParams):
    """dy/dt for state y = (theta_1..theta_N, omega_1..omega_N), shape (..., 2N)."""
    n = p.n
    y = np.asarray(y)
    th, om = y[..., :n], y[..., n:]
    L = np.asarray(p.lengths, dtype=float)
    mu = p.mu()
    d = th[..., :, None] - th[..., None, :]
    LL = np.outer(L, L)
    M = mu * LL * np.cos(d)
    rhs = -np.sum(mu * LL * np.sin(d) * om[..., None, :] ** 2, axis=-1) - np.diag(mu) * p.g * L * np.sin(th)
    alpha = np.linalg.solve(M, rhs[..., None])[..., 0]
    return np.concatenate([om, alpha], axis=-1)


def positions(y, p: NLinkParams):
    """Return arrays x, y of shape (..., N) with the Cartesian position of each mass."""
    th = np.asarray(y)[..., : p.n]
    L = np.asarray(p.lengths)
    return np.cumsum(L * np.sin(th), axis=-1), np.cumsum(-L * np.cos(th), axis=-1)


def total_energy(y, p: NLinkParams):
    n = p.n
    y = np.asarray(y)
    th, om = y[..., :n], y[..., n:]
    L = np.asarray(p.lengths)
    mu = p.mu()
    d = th[..., :, None] - th[..., None, :]
    T = 0.5 * np.einsum("...i,ij,...ij,...j->...", om * L, mu, np.cos(d), om * L)
    V = -p.g * np.sum(np.diag(mu) * L * np.cos(th), axis=-1)
    return T + V
