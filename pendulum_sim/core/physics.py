"""Equations of motion and derived quantities for the planar double pendulum.

Conventions
-----------
* Angles ``theta1``, ``theta2`` are measured from the downward vertical,
  counter-clockwise positive; the pivot is at the origin with ``y`` pointing up.
* State vector ``y = (theta1, theta2, omega1, omega2)`` with ``omega = dtheta/dt``.
  Every function accepts arrays of shape ``(..., 4)`` and broadcasts, so one
  call can evaluate a single pendulum, an ensemble or a whole chaos map.
* SI units throughout: kg, m, s, rad, J.

Euler–Lagrange equations (with Delta = theta1 - theta2), after dividing the
first row by L1 and the second by m2*L2:

    [(m1+m2) L1      m2 L2 cosD] [a1]   [-m2 L2 w2^2 sinD - (m1+m2) g sin th1 + Q1/L1    ]
    [L1 cosD         L2        ] [a2] = [ L1 w1^2 sinD    - g sin th2         + Q2/(m2 L2)]

Q1, Q2 are non-conservative generalized forces (torques): viscous joint
damping and an optional sinusoidal torque applied at the pivot. The 2x2
system is solved with Cramer's rule; its determinant
L1 L2 (m1 + m2 sin^2 D) is strictly positive for positive masses/lengths.
"""

from __future__ import annotations

import numpy as np

from pendulum_sim.core.config import Physical


def _unpack(y):
    y = np.asarray(y)
    return y[..., 0], y[..., 1], y[..., 2], y[..., 3]


def generalized_forces(t, y, p: Physical):
    """Non-conservative generalized forces (Q1, Q2) in N*m.

    * Pivot joint: viscous torque ``-b1 * omega1`` on rod 1.
    * Elbow joint: viscous torque ``-b2 * (omega2 - omega1)`` on rod 2 and the
      equal and opposite torque on rod 1.
    * Drive: ``A cos(Omega t + phi)`` applied at the pivot on rod 1.
    """
    _, _, w1, w2 = _unpack(y)
    rel = w2 - w1
    q1 = -p.damping1 * w1 + p.damping2 * rel
    q2 = -p.damping2 * rel
    if np.any(np.asarray(p.drive_amplitude) != 0):
        q1 = q1 + drive_torque(t, p)
    return q1, q2


def drive_torque(t, p: Physical):
    return p.drive_amplitude * np.cos(p.drive_frequency * np.asarray(t) + p.drive_phase)


def solve_accelerations(th1, th2, w1, w2, p: Physical, gs1, gs2, q1=0.0, q2=0.0):
    """Solve the 2x2 Lagrangian system for (alpha1, alpha2).

    ``gs1``/``gs2`` are the gravity terms ``g sin(theta_i)``; they are passed in
    so that the isolated moving-pivot model can substitute an effective field.
    """
    d = th1 - th2
    c, s = np.cos(d), np.sin(d)
    a = (p.m1 + p.m2) * p.L1
    b = p.m2 * p.L2 * c
    cc = p.L1 * c
    dd = p.L2
    r1 = -p.m2 * p.L2 * w2**2 * s - (p.m1 + p.m2) * gs1 + q1 / p.L1
    r2 = p.L1 * w1**2 * s - gs2 + q2 / (p.m2 * p.L2)
    det = a * dd - b * cc  # = L1 L2 (m1 + m2 sin^2 D) > 0
    a1 = (r1 * dd - b * r2) / det
    a2 = (a * r2 - cc * r1) / det
    return a1, a2


def accelerations(t, y, p: Physical):
    th1, th2, w1, w2 = _unpack(y)
    if p.has_forcing:
        q1, q2 = generalized_forces(t, y, p)
    else:
        q1 = q2 = 0.0
    return solve_accelerations(th1, th2, w1, w2, p, p.g * np.sin(th1), p.g * np.sin(th2), q1, q2)


def derivatives(t, y, p: Physical):
    """dy/dt for state(s) y of shape (..., 4)."""
    th1, th2, w1, w2 = _unpack(y)
    a1, a2 = accelerations(t, y, p)
    return np.stack(np.broadcast_arrays(w1, w2, a1, a2), axis=-1)


# --------------------------------------------------------------------------
# Kinematics and energy
# --------------------------------------------------------------------------


def positions(y, p: Physical):
    """Cartesian positions (x1, y1, x2, y2) in metres."""
    th1, th2, _, _ = _unpack(y)
    x1 = p.L1 * np.sin(th1)
    y1 = -p.L1 * np.cos(th1)
    x2 = x1 + p.L2 * np.sin(th2)
    y2 = y1 - p.L2 * np.cos(th2)
    return x1, y1, x2, y2


def velocities(y, p: Physical):
    """Cartesian velocities (vx1, vy1, vx2, vy2) in m/s."""
    th1, th2, w1, w2 = _unpack(y)
    vx1 = p.L1 * np.cos(th1) * w1
    vy1 = p.L1 * np.sin(th1) * w1
    vx2 = vx1 + p.L2 * np.cos(th2) * w2
    vy2 = vy1 + p.L2 * np.sin(th2) * w2
    return vx1, vy1, vx2, vy2


def cartesian_accelerations(t, y, p: Physical):
    """Cartesian accelerations (ax1, ay1, ax2, ay2) in m/s^2."""
    th1, th2, w1, w2 = _unpack(y)
    a1, a2 = accelerations(t, y, p)
    ax1 = p.L1 * (np.cos(th1) * a1 - np.sin(th1) * w1**2)
    ay1 = p.L1 * (np.sin(th1) * a1 + np.cos(th1) * w1**2)
    ax2 = ax1 + p.L2 * (np.cos(th2) * a2 - np.sin(th2) * w2**2)
    ay2 = ay1 + p.L2 * (np.sin(th2) * a2 + np.cos(th2) * w2**2)
    return ax1, ay1, ax2, ay2


def kinetic_energy(y, p: Physical):
    th1, th2, w1, w2 = _unpack(y)
    return (
        0.5 * (p.m1 + p.m2) * p.L1**2 * w1**2
        + 0.5 * p.m2 * p.L2**2 * w2**2
        + p.m2 * p.L1 * p.L2 * w1 * w2 * np.cos(th1 - th2)
    )


def potential_energy(y, p: Physical):
    """Gravitational potential energy, zero at the pivot height."""
    th1, th2, _, _ = _unpack(y)
    return -(p.m1 + p.m2) * p.g * p.L1 * np.cos(th1) - p.m2 * p.g * p.L2 * np.cos(th2)


def total_energy(y, p: Physical):
    return kinetic_energy(y, p) + potential_energy(y, p)


def angular_momentum(y, p: Physical):
    """Angular momentum of both masses about the pivot (kg m^2/s).

    Not conserved in general: gravity exerts a torque about the pivot.
    """
    x1, y1, x2, y2 = positions(y, p)
    vx1, vy1, vx2, vy2 = velocities(y, p)
    return p.m1 * (x1 * vy1 - y1 * vx1) + p.m2 * (x2 * vy2 - y2 * vx2)


def center_of_mass(y, p: Physical):
    x1, y1, x2, y2 = positions(y, p)
    m = p.m1 + p.m2
    return (p.m1 * x1 + p.m2 * x2) / m, (p.m1 * y1 + p.m2 * y2) / m


def mechanical_power(t, y, p: Physical):
    """Rate of work done by non-conservative forces: dE/dt = Q . omega (W)."""
    _, _, w1, w2 = _unpack(y)
    q1, q2 = generalized_forces(t, y, p)
    return q1 * w1 + q2 * w2


def drive_power(t, y, p: Physical):
    _, _, w1, _ = _unpack(y)
    return drive_torque(t, p) * w1


def damping_power(y, p: Physical):
    """Power dissipated by viscous joint damping (W, non-negative)."""
    _, _, w1, w2 = _unpack(y)
    return p.damping1 * w1**2 + p.damping2 * (w2 - w1) ** 2


# --------------------------------------------------------------------------
# Angles and state-space geometry
# --------------------------------------------------------------------------


def wrap_angle(a):
    """Wrap angle(s) to [-pi, pi)."""
    return (np.asarray(a) + np.pi) % (2.0 * np.pi) - np.pi


def state_difference(ya, yb, time_scale: float = 1.0):
    """Difference ya - yb with wrapped angles and angular velocities scaled by
    ``time_scale`` (seconds), giving a dimensionless 4-vector."""
    ya = np.asarray(ya)
    yb = np.asarray(yb)
    d = np.array(ya - yb, dtype=float)
    d[..., 0] = wrap_angle(d[..., 0])
    d[..., 1] = wrap_angle(d[..., 1])
    d[..., 2] *= time_scale
    d[..., 3] *= time_scale
    return d


def state_distance(ya, yb, time_scale: float = 1.0):
    """Euclidean norm of :func:`state_difference` (dimensionless)."""
    d = state_difference(ya, yb, time_scale)
    return np.sqrt(np.sum(d**2, axis=-1))


def natural_time_scale(p: Physical) -> float:
    """sqrt(L1/g): the time unit used to non-dimensionalize angular velocities."""
    return float(np.sqrt(p.L1 / p.g))


def energy_for_omega1(theta1, theta2, omega2, energy, p: Physical):
    """Return the positive omega1 giving total energy ``energy``, or NaN if the
    requested energy is not reachable from (theta1, theta2, omega2)."""
    A = 0.5 * (p.m1 + p.m2) * p.L1**2
    B = p.m2 * p.L1 * p.L2 * omega2 * np.cos(theta1 - theta2)
    y = np.stack(np.broadcast_arrays(theta1, theta2, 0.0 * theta1, omega2), axis=-1)
    C = 0.5 * p.m2 * p.L2**2 * omega2**2 + potential_energy(y, p) - energy
    disc = B**2 - 4 * A * C
    with np.errstate(invalid="ignore"):
        return np.where(disc >= 0, (-B + np.sqrt(np.maximum(disc, 0))) / (2 * A), np.nan)


# --------------------------------------------------------------------------
# Jacobian (complex-step differentiation)
# --------------------------------------------------------------------------


def jvp(t, y, v, p: Physical, h: float = 1e-30):
    """Jacobian-vector product J(y) @ v of the vector field, exact to machine
    precision via complex-step differentiation (no subtractive cancellation).

    Works because every operation in :func:`derivatives` is complex-analytic.
    """
    yc = np.asarray(y, dtype=complex) + 1j * h * np.asarray(v, dtype=float)
    return np.imag(derivatives(t, yc, p)) / h


def jacobian(t, y, p: Physical):
    """4x4 Jacobian d f / d y at a single state ``y`` (complex-step)."""
    y = np.asarray(y, dtype=float)
    return np.stack([jvp(t, y, e, p) for e in np.eye(4)], axis=-1)


def jacobian_fd(t, y, p: Physical, h: float = 1e-6):
    """Central finite-difference Jacobian, used to validate :func:`jacobian`."""
    y = np.asarray(y, dtype=float)
    cols = []
    for e in np.eye(4):
        cols.append((derivatives(t, y + h * e, p) - derivatives(t, y - h * e, p)) / (2 * h))
    return np.stack(cols, axis=-1)
