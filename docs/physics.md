# Physics of the Double Pendulum

This is the reference for every equation used in Double Pendulum Simulator. Each result
here is implemented in `pendulum_sim/core/physics.py` and checked by the test
suite (see [Validation](#validation)).

## Model and conventions

Two point masses $m_1, m_2$ hang from massless rigid rods of lengths
$L_1, L_2$ in a uniform gravitational field $g$. The pivot is fixed at the
origin, $y$ points **up**, and the angles $\theta_1, \theta_2$ are measured
from the **downward vertical**, counter-clockwise positive. The state is
$(\theta_1, \theta_2, \omega_1, \omega_2)$ with $\omega_i = \dot\theta_i$.
SI units throughout: kg, m, s, rad, J.

## Kinematics

```math
x_1 = L_1 \sin\theta_1, \qquad y_1 = -L_1 \cos\theta_1
```

```math
x_2 = L_1 \sin\theta_1 + L_2 \sin\theta_2, \qquad y_2 = -L_1 \cos\theta_1 - L_2 \cos\theta_2
```

Differentiating,

```math
\dot x_1 = L_1 \omega_1 \cos\theta_1, \qquad \dot y_1 = L_1 \omega_1 \sin\theta_1
```

```math
\dot x_2 = \dot x_1 + L_2 \omega_2 \cos\theta_2, \qquad \dot y_2 = \dot y_1 + L_2 \omega_2 \sin\theta_2
```

## Energy

Using $\cos\theta_1\cos\theta_2 + \sin\theta_1\sin\theta_2 = \cos(\theta_1 - \theta_2)$:

```math
T = \tfrac12 (m_1 + m_2) L_1^2 \omega_1^2 + \tfrac12 m_2 L_2^2 \omega_2^2 + m_2 L_1 L_2\, \omega_1 \omega_2 \cos(\theta_1 - \theta_2)
```

```math
V = m_1 g y_1 + m_2 g y_2 = -(m_1 + m_2)\, g L_1 \cos\theta_1 - m_2\, g L_2 \cos\theta_2
```

```math
E = T + V
```

$V$ is zero at the height of the pivot, so the hanging equilibrium has
$E = -(m_1 + m_2) g L_1 - m_2 g L_2$ (−29.43 J for unit masses and lengths with
$g = 9.81$ m/s²).

## Euler–Lagrange equations

With $\mathcal{L} = T - V$ and $\Delta = \theta_1 - \theta_2$:

```math
\frac{\partial \mathcal L}{\partial \omega_1} = (m_1 + m_2) L_1^2 \omega_1 + m_2 L_1 L_2 \omega_2 \cos\Delta,
\qquad
\frac{\partial \mathcal L}{\partial \theta_1} = -m_2 L_1 L_2 \omega_1 \omega_2 \sin\Delta - (m_1 + m_2) g L_1 \sin\theta_1
```

```math
\frac{\partial \mathcal L}{\partial \omega_2} = m_2 L_2^2 \omega_2 + m_2 L_1 L_2 \omega_1 \cos\Delta,
\qquad
\frac{\partial \mathcal L}{\partial \theta_2} = m_2 L_1 L_2 \omega_1 \omega_2 \sin\Delta - m_2 g L_2 \sin\theta_2
```

In $\tfrac{d}{dt}\partial\mathcal L/\partial\omega_i - \partial\mathcal L/\partial\theta_i = 0$
the $\omega_1\omega_2\sin\Delta$ terms cancel, leaving

```math
(m_1 + m_2) L_1^2 \ddot\theta_1 + m_2 L_1 L_2 \cos\Delta\, \ddot\theta_2 + m_2 L_1 L_2\, \omega_2^2 \sin\Delta + (m_1 + m_2) g L_1 \sin\theta_1 = 0
```

```math
m_2 L_1 L_2 \cos\Delta\, \ddot\theta_1 + m_2 L_2^2\, \ddot\theta_2 - m_2 L_1 L_2\, \omega_1^2 \sin\Delta + m_2 g L_2 \sin\theta_2 = 0
```

Dividing the first equation by $L_1$ and the second by $m_2 L_2$ gives the
normalized matrix form used in the code:

```math
\begin{pmatrix}
(m_1+m_2)L_1 & m_2 L_2\cos\Delta \\
L_1\cos\Delta & L_2
\end{pmatrix}
\begin{pmatrix}
\ddot\theta_1 \\
\ddot\theta_2
\end{pmatrix}
=
\begin{pmatrix}
-m_2 L_2\omega_2^2\sin\Delta - (m_1+m_2)g\sin\theta_1 \\
L_1\omega_1^2\sin\Delta - g\sin\theta_2
\end{pmatrix}
```

The determinant is $L_1 L_2 (m_1 + m_2 \sin^2\Delta) > 0$ for positive masses
and lengths, so the system always has a unique solution; the code solves it
with Cramer's rule, vectorized over any number of states.

## Damping and driving

Non-conservative effects enter as generalized forces $Q_1, Q_2$ (torques) on
the right-hand side of the unnormalized equations, i.e. $+Q_1/L_1$ and
$+Q_2/(m_2 L_2)$ after normalization:

* viscous torque at the pivot, $-b_1\omega_1$, on rod 1;
* viscous torque at the elbow, $-b_2(\omega_2 - \omega_1)$, on rod 2 and its
  reaction on rod 1;
* a sinusoidal torque $A\cos(\Omega t + \varphi)$ applied at the pivot on rod 1.

```math
Q_1 = -b_1\omega_1 + b_2(\omega_2 - \omega_1) + A\cos(\Omega t + \varphi), \qquad Q_2 = -b_2(\omega_2 - \omega_1)
```

The energy balance is $\dot E = Q_1\omega_1 + Q_2\omega_2$, so

```math
E(t) - E(0) = W_\text{drive}(t) - W_\text{damp}(t), \qquad
W_\text{damp} = \int_0^t \left[b_1\omega_1^2 + b_2(\omega_2-\omega_1)^2\right] dt' \ge 0 .
```

Double Pendulum Simulator integrates both works along the trajectory and reports the residual
of this balance as the accuracy diagnostic for forced runs.

## Angular momentum

The angular momentum of the two masses about the pivot is
$L_z = \sum_i m_i (x_i \dot y_i - y_i \dot x_i)$. It is **not** conserved:
gravity exerts a torque about the pivot,

```math
\frac{dL_z}{dt} = -g\,(m_1 x_1 + m_2 x_2).
```

(The rod tensions pass through the pivot or are internal, so they contribute no
net torque about the pivot.)

## Small oscillations and normal modes

Linearizing about $\theta_1 = \theta_2 = 0$:

```math
M_0\,\ddot{\boldsymbol\theta} + K_0\,\boldsymbol\theta = 0, \qquad
M_0 = \begin{pmatrix} (m_1+m_2)L_1^2 & m_2 L_1 L_2 \\ m_2 L_1 L_2 & m_2 L_2^2 \end{pmatrix}, \qquad
K_0 = \begin{pmatrix} (m_1+m_2) g L_1 & 0 \\ 0 & m_2 g L_2 \end{pmatrix}
```

The normal-mode frequencies solve $\det(K_0 - \omega^2 M_0) = 0$. For
$m_1 = m_2$ and $L_1 = L_2 = L$:

```math
\omega^2 = (2 \mp \sqrt2)\,\frac{g}{L}, \qquad \frac{\theta_2}{\theta_1} = \pm\sqrt2 ,
```

i.e. 2.397 rad/s (in phase) and 5.787 rad/s (anti-phase) for $L = 1$ m. The
linear solution is the exact superposition of the two modes;
`analysis/linear.py` compares it with the nonlinear motion.

## Equilibria

Modulo $2\pi$ there are four vertical equilibria. Their stability follows from
the eigenvalues of the 4×4 Jacobian of the state-space vector field:

| Configuration | $(\theta_1, \theta_2)$ | Linear stability (undamped) |
|---|---|---|
| down–down | $(0, 0)$ | elliptic (neutrally stable to linear order) |
| down–up | $(0, \pi)$ | unstable, 1 unstable direction |
| up–down | $(\pi, 0)$ | unstable, 1 unstable direction |
| up–up | $(\pi, \pi)$ | unstable, 2 unstable directions |

With damping the down–down state becomes asymptotically stable. The Jacobian is
computed by complex-step differentiation (exact to rounding) and checked against
finite differences.

## Extensions (separate models)

### Moving pivot (`core/pivot.py`)

For a prescribed pivot motion $(x_p(t), y_p(t))$, the dynamics in the frame of
the pivot are those of a fixed pivot in the effective field
$\mathbf g_\text{eff} = (-\ddot x_p,\ -g - \ddot y_p)$. Each gravity term
$g\sin\theta_i$ becomes

```math
\ddot x_p \cos\theta_i + (g + \ddot y_p)\sin\theta_i ,
```

and everything else is unchanged. A vertically oscillating pivot gives a
Kapitza-type parametric pendulum. Energy is not conserved, because the pivot
does work on the system.

### N-link pendulum (`core/nlink.py`)

For $N$ point masses, let $\mu_{ij} = \sum_{k \ge \max(i,j)} m_k$. Then

```math
T = \tfrac12 \sum_{i,j} \mu_{ij} L_i L_j \cos(\theta_i - \theta_j)\,\omega_i\omega_j, \qquad
V = -g \sum_i \mu_{ii} L_i \cos\theta_i,
```

and the Euler–Lagrange equations are

```math
\sum_j \mu_{ij} L_i L_j \cos(\theta_i - \theta_j)\,\ddot\theta_j
= -\sum_j \mu_{ij} L_i L_j \sin(\theta_i - \theta_j)\,\omega_j^2 - \mu_{ii}\, g L_i \sin\theta_i .
```

For $N = 2$ this reproduces the double pendulum exactly, which the tests check.
$N = 3$ is the triple pendulum.

## Validation

The test suite checks the physics independently of the derivation above:

* **Euler–Lagrange residual.** A Lagrangian is built from Cartesian positions
  only, using numerical differentiation and none of the derived equations.
  Computed trajectories satisfy its Euler–Lagrange equations, and the residual
  converges to zero as $O(\Delta t^2)$ as the sampling is refined. A
  deliberately wrong model fails the same test. This is checked for two
  parameter sets and for the moving-pivot model.
* The matrix equation shown above, solved with `numpy.linalg.solve`, equals the
  Cramer's-rule implementation.
* Positions, velocities and energies match hand calculations.
* $dL_z/dt$ equals the gravitational torque along a trajectory.
* Cartesian accelerations match numerical derivatives of the velocities.
* Normal-mode frequencies, mode shapes and the linear solution match the
  analytic results.
* Damped and driven runs close their energy balance.
* The two-link N-link model equals the double pendulum.
