# Numerical Methods

## Integrators

| Method | Type | Where it is used |
|---|---|---|
| **RK4** | classical 4th-order Runge–Kutta, fixed step | animation, ensembles, chaos maps, sweeps |
| **RK45** | Dormand–Prince 5(4), adaptive, dense output (SciPy) | comparisons |
| **DOP853** | Dormand–Prince 8(5,3), adaptive, dense output (SciPy) | references, Poincaré sections, slow motion |

**Why fixed-step RK4 by default.** Animation needs states on a uniform time
grid. RK4 is 4th order: the error falls about 16× when the step is halved. The
observed order is 4.05; see `benchmarks/results.md`. RK4 is cheap per step and
vectorizes trivially across thousands of pendulums.

**Why not a symplectic integrator.** Simple explicit symplectic schemes such as
leapfrog/Verlet require a separable Hamiltonian $H = T(p) + V(q)$. Here $T$
depends on $\cos(\theta_1 - \theta_2)$, so a symplectic method would have to be
implicit. RK4 and the Dormand–Prince pairs are not symplectic, so energy drifts
slowly. Chaos Lab measures that drift and shows it rather than hiding it.

**Physical time vs output vs playback.** `Numerics.dt` is the integration step
and `Numerics.output_dt` the spacing of stored samples, both in simulated
seconds. For RK4 the output spacing is rounded to a whole number of steps;
adaptive methods sample their dense output. Playback speed is applied only at
render time and is always labelled.

**Performance paths.**

* A single trajectory uses a pure-float RK4 loop
  (`integrate_rk4_double_pendulum`). NumPy's per-call overhead dominates on a
  4-element state, and the measured speed-up is about 20×. A test pins it to
  the vectorized implementation to 10⁻¹¹.
* Batches (ensembles, maps, sweeps) use the vectorized `physics.derivatives`
  over arrays of shape `(..., 4)`. Physical parameters may themselves be
  arrays, which is how parameter sweeps run as a single batch.

## Accuracy diagnostics

* **Conservative runs:** relative energy error $(E - E_0)/|E_0|$. A small
  energy error is **necessary but not sufficient**. Phase errors along the
  trajectory do not show up in the energy.
* **Forced runs:** the residual of $E(t) - E_0 = W_\text{drive} - W_\text{damp}$,
  with the works integrated by the trapezoid rule on the output grid. It is
  divided by the characteristic energy $(m_1+m_2)gL_1 + m_2 gL_2$.
* **Convergence:** the energy error and short-horizon trajectory error must
  shrink as the step or tolerance is refined (tested).
* **Chaotic divergence is not an integrator bug.** Two accurate integrators
  give trajectories that separate exponentially after a few Lyapunov times.
  Compare runs over horizons shorter than the predictability time.

## Event detection

* **Flips.** An arm flips when its *unwrapped* angle crosses an odd multiple
  of π. Crossing times are linearly interpolated between samples, so the
  output spacing must resolve the motion.
* **Poincaré crossings.** These use SciPy event location on the solver's
  dense output for $g(y) = \sin\theta_1$ with positive direction. Crossings at
  $\theta_1 = \pi$ are rejected by requiring $\cos\theta_1 > 0$. The tests
  re-integrate to each crossing time and check that $\theta_1 \equiv 0$ to
  10⁻⁶.

## Lyapunov exponents

The largest finite-time exponent follows Benettin et al. (1980):

```math
\lambda_T = \frac{1}{T}\sum_{k} \ln\frac{d_k}{d_0}
```

* **Tangent method (default).** The variational equation $\dot v = J(y)\,v$ is
  integrated alongside the trajectory. Jacobian–vector products come from
  complex-step differentiation, so there are no finite-perturbation saturation
  effects. $v$ is renormalized every `renorm_interval`.
* **Two-trajectory method.** A twin trajectory starts $d_0$ away and is
  rescaled back to $d_0$ at each interval. Angular differences are wrapped to
  $[-\pi, \pi)$.
* **Norm.** Euclidean in $(\theta_1, \theta_2, \tau\omega_1, \tau\omega_2)$ with
  $\tau = \sqrt{L_1/g}$, which makes the state space dimensionless.
* **Validation.** The Lorenz system gives λ = 0.906 ± 0.06, against the
  literature value 0.9056. A linear oscillator gives λ ≈ 0. The two methods
  agree within 10% on the double pendulum.
* **Interpretation.** Finite-time values depend on $T$, the norm, the start
  and the estimator settings. `sensitivity_scan` reports that spread. The
  predictability horizon $T_p = \ln(\delta_\text{max}/\delta_0)/\lambda$
  assumes uniform exponential growth, so it is an order-of-magnitude guide.

## Initial-condition maps

Every pixel is integrated with vectorized RK4: dt = 0.005 s by default and up
to `t_max`. Pixels whose energy is below the minimum potential energy of any
flipped configuration are marked "no flip" without integrating. That shortcut
is exact, because of energy conservation.

Work is split into chunks of about 20,000 pixels to amortize NumPy overhead.
Maps of 120,000 pixels or more use a process pool. Results are cached by a hash
of the full specification. Fine-scale structure is limited by the step and the
horizon. Intricate boundaries indicate sensitivity; they are not a proof that a
set is fractal.

## Known limitations

* RK4 maps at dt = 0.005 s are accurate enough for the large-scale structure.
  Deep zooms resolve detail that depends on the step size, so recompute with a
  smaller dt to check robustness.
* Recorded states are played back in reverse; time-reversed dynamics are not
  re-integrated.
* The 3D view (dashboard) is a presentation of planar motion only.
