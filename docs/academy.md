# Chaos Academy

Fourteen short lessons. Each ends with a command that reproduces the
demonstration, so you can check every claim yourself. The equations are
derived in full in [physics.md](physics.md), and the methods in
[numerics.md](numerics.md).

---

### 1. What is a double pendulum?

A pendulum hangs from the end of another pendulum. It has two rigid rods and
two point masses, it moves in a plane, and nothing here involves friction
unless you add it. Two angles describe its configuration completely.

```bash
python -m chaos_lab render --preset classic --t-max 8 -o classic.gif --width 480 --height 480
```

### 2. Why is it nonlinear?

The restoring torques depend on $\sin\theta$, and the two arms are coupled
through $\cos(\theta_1 - \theta_2)$ and $\omega^2 \sin(\theta_1-\theta_2)$.
Doubling the starting angle does not just double the motion. At small angles
$\sin\theta \approx \theta$ and the system becomes linear: its motion is then
exactly a sum of two normal modes.

```bash
python -m chaos_lab modes            # the two small-angle frequencies and mode shapes
```

### 3. What are generalized coordinates?

Each mass has $(x, y)$, so the system has four Cartesian coordinates, but the
rigid rods impose two constraints. Two angles $(\theta_1, \theta_2)$ satisfy
the constraints automatically. These are generalized coordinates: the minimal
set that describes the configuration.

### 4. What is a Lagrangian?

$\mathcal L = T - V$, kinetic minus potential energy, written in the
generalized coordinates. Nature picks the path that makes the action
$\int \mathcal L\, dt$ stationary. You never need the rod tensions, because
constraint forces do no work.

### 5. How do the equations of motion arise?

From the Euler–Lagrange equations,
$\frac{d}{dt}\frac{\partial\mathcal L}{\partial\dot\theta_i} - \frac{\partial\mathcal L}{\partial\theta_i} = 0$.
For the double pendulum they give a 2×2 linear system for the angular
accelerations (see [physics.md](physics.md#euler–lagrange-equations)). The test
suite checks the implementation against a Lagrangian built independently from
Cartesian coordinates.

### 6. How does RK4 work?

RK4 samples the slope four times per step: at the start, twice at the midpoint
and once at the end. It combines them with weights 1:2:2:1. The error per unit
time scales as $\Delta t^4$.

```bash
for dt in 0.004 0.002 0.001; do python double_pendulum.py --no-show --dt $dt; done
```

The maximum energy error falls roughly 20× each time the step is halved: the 16× expected asymptotically for a 4th-order method, plus some pre-asymptotic variation.

### 7. What is numerical error?

It is the gap between the computed trajectory and the exact one. Watch the
energy, which should be constant without friction, and see what happens when
you refine the step.

```bash
python -m chaos_lab integrators --preset integrator_challenge
```

### 8. What is sensitive dependence on initial conditions?

Two starts that differ by $10^{-6}$ rad stay together for seconds, then
diverge completely. That is a property of the physics. The butterfly
experiment also runs a numerical control (the same start at dt and dt/2) to
show that the divergence is not an integration artefact.

```bash
python -m chaos_lab butterfly --preset butterfly --n 10 --epsilon 1e-6
```

### 9. What is a Lyapunov exponent?

It is the average exponential rate $\lambda$ at which nearby trajectories
separate: $d(t) \approx d_0 e^{\lambda t}$. A positive $\lambda$ is a hallmark
of chaos. Chaos Lab estimates a *finite-time* value. It depends on the run
length and the estimator settings, and `--scan` shows how much.

```bash
python -m chaos_lab lyapunov --preset classic --t-max 60 --scan
python -m chaos_lab lyapunov --preset near_equilibrium --t-max 60
```

### 10. What is phase space?

The state is four numbers $(\theta_1, \theta_2, \omega_1, \omega_2)$, a point
in a 4-dimensional space. A trajectory is a curve through that space. Every
2D or 3D plot of it is a projection, never the whole picture.

```bash
python -m chaos_lab figure --preset phase_space -o phase.png
```

### 11. What is a Poincaré section?

Instead of the whole 4D curve, record only the moments when the trajectory
pierces a surface: here $\theta_1 = 0$ with $\omega_1 > 0$. At fixed energy,
regular motion leaves points on closed curves, called islands. Chaotic motion
scatters points over a region.

```bash
python -m chaos_lab poincare --energy -15 --n 8 -o section.png
```

### 12. What does energy conservation tell us?

Without friction or driving, $E = T + V$ is exactly constant. Energy decides
what is *possible*: below a threshold, no arm can ever flip. The Make It Flip
challenge explains this when you try. In a simulation, energy drift measures
numerical error, but a small drift does not prove the trajectory is pointwise
accurate.

```bash
python -m chaos_lab challenge flip theta1_deg=40 theta2_deg=40
```

### 13. What makes motion regular or chaotic?

At low energy the motion is nearly linear and regular. At high energy, for
example rapid rotation, it can become more regular again. In between, regular
islands and chaotic seas coexist. Starting conditions matter: (60°, 40°) is
regular, (135°, −45°) is chaotic.

```bash
python scripts/generate_gallery.py --only regular-vs-chaotic
```

### 14. Why is long-term prediction difficult?

An uncertainty $\delta_0$ grows to $\delta_\text{max}$ in about
$T_p = \ln(\delta_\text{max}/\delta_0)/\lambda$. With $\lambda \approx 1$ s⁻¹,
improving the initial measurement 1000× buys only $\ln 1000 \approx 7$ more
seconds of prediction. Determinism does not imply predictability.

```bash
python -m chaos_lab lyapunov --preset classic     # prints a predictability horizon
```
