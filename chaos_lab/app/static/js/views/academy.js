// Chaos Academy: guided lessons with links to live demonstrations.

import { applyPreset } from "../controls.js";
import { cloneDeep, setConfig, state } from "../state.js";
import { btn, h } from "../ui.js";

export const meta = { id: "academy" };

const eq = (s) => `<div class="eq">${s}</div>`;

const LESSONS = [
  {
    t: "What is a double pendulum?",
    body: `<p>Two point masses <i>m</i>₁, <i>m</i>₂ on massless rigid rods of length <i>L</i>₁, <i>L</i>₂, the second hanging from the first, swinging in a vertical plane under uniform gravity <i>g</i>. Nothing else: no friction unless you add it.</p>
<p>Despite that simplicity, released from a large angle it moves in a way that never repeats and is practically impossible to predict far ahead. It is one of the simplest mechanical systems that shows <b>deterministic chaos</b>.</p>`,
    demo: ["Watch the classic release", () => preset("classic")],
  },
  {
    t: "Why is it nonlinear?",
    body: `<p>The forces depend on sines and cosines of the angles, and the rods’ coupling depends on the angle <i>difference</i> Δ = θ₁ − θ₂. Doubling the starting angle does not simply double the motion.</p>
${eq("sin θ ≈ θ only when |θ| ≪ 1 rad")}
<p>For small swings the equations become linear and the motion is a sum of two simple harmonic <b>normal modes</b>. For large swings that approximation fails, which you can measure in the Physics Lab.</p>`,
    demo: ["Compare linear vs nonlinear", () => go("lab")],
  },
  {
    t: "What are generalized coordinates?",
    body: `<p>The two masses have four Cartesian coordinates, but the rigid rods impose two constraints. Two numbers describe every configuration: the angles θ₁, θ₂ from the downward vertical (counter-clockwise positive). These are <b>generalized coordinates</b>.</p>
${eq("x₁ = L₁ sin θ₁,&nbsp; y₁ = −L₁ cos θ₁,&nbsp;&nbsp; x₂ = x₁ + L₂ sin θ₂,&nbsp; y₂ = y₁ − L₂ cos θ₂")}
<p>With the angular velocities ω₁, ω₂ they form the four-dimensional <b>state</b> (θ₁, θ₂, ω₁, ω₂).</p>`,
    demo: ["Drag the masses to set angles", () => go("playground")],
  },
  {
    t: "What is a Lagrangian?",
    body: `<p>The Lagrangian is kinetic minus potential energy, ℒ = T − V. For the double pendulum:</p>
${eq("T = ½(m₁+m₂)L₁²ω₁² + ½m₂L₂²ω₂² + m₂L₁L₂ω₁ω₂ cos(θ₁−θ₂)")}
${eq("V = −(m₁+m₂) g L₁ cos θ₁ − m₂ g L₂ cos θ₂")}
<p>V is measured from the pivot height. The cross term in T couples the rods; it is why the kinetic energy is not separable.</p>`,
  },
  {
    t: "How do the equations of motion arise?",
    body: `<p>Applying the Euler–Lagrange equation d/dt(∂ℒ/∂θ̇ᵢ) − ∂ℒ/∂θᵢ = Qᵢ to each angle and dividing the rows by L₁ and m₂L₂ gives a linear system for the angular accelerations:</p>
${eq("[(m₁+m₂)L₁ &nbsp; m₂L₂ cos Δ ; &nbsp; L₁ cos Δ &nbsp; L₂] · [θ̈₁ ; θ̈₂] = [−m₂L₂ω₂² sin Δ − (m₁+m₂) g sin θ₁ ; &nbsp; L₁ω₁² sin Δ − g sin θ₂]")}
<p>The determinant L₁L₂(m₁ + m₂ sin²Δ) is always positive, so the system is always solvable. Chaos Lab solves it at every evaluation. Damping and driving enter as generalized torques Qᵢ.</p>`,
  },
  {
    t: "How does RK4 work?",
    body: `<p>The classical Runge–Kutta method advances the state by Δt using four slope evaluations:</p>
${eq("k₁ = f(t, y),&nbsp; k₂ = f(t+Δt/2, y+Δt k₁/2),&nbsp; k₃ = f(t+Δt/2, y+Δt k₂/2),&nbsp; k₄ = f(t+Δt, y+Δt k₃)")}
${eq("y(t+Δt) ≈ y + Δt (k₁ + 2k₂ + 2k₃ + k₄)/6")}
<p>Its global error scales like Δt⁴: halving the step should cut the error about 16×. The Physics Lab measures that order directly. RK45 and DOP853 pair two methods to estimate the error and adapt the step automatically.</p>`,
    demo: ["Run the convergence test", () => go("lab")],
  },
  {
    t: "What is numerical error?",
    body: `<p>A computer replaces the continuous flow by discrete steps (truncation error) in finite-precision arithmetic (round-off). Without friction or driving, total energy is exactly conserved, so the drift of E = T + V is a direct, physics-based measure of integration error.</p>
<p>Small energy error is <b>necessary</b> but not sufficient: a trajectory can conserve energy well and still drift in phase. Watch the energy-error panel while changing Δt.</p>`,
    demo: ["Try a coarse step", () => preset("integrator_challenge")],
  },
  {
    t: "What is sensitive dependence on initial conditions?",
    body: `<p>Start two pendulums a millionth of a radian apart. For a while they are indistinguishable; then the gap grows roughly exponentially until the motions are completely different. This is the <b>butterfly effect</b>.</p>
<p>It is a property of the equations, not of the computer: the Butterfly Arena plots a numerical-error control curve (the same run at Δt and Δt/2) that stays orders of magnitude below the physical divergence.</p>`,
    demo: ["Open the Butterfly Arena", () => { preset("butterfly"); go("butterfly"); }],
  },
  {
    t: "What is a Lyapunov exponent?",
    body: `<p>If small separations grow like d(t) ≈ d₀ e<sup>λt</sup>, then λ is the (largest) Lyapunov exponent. It is estimated by following a tiny perturbation and repeatedly renormalizing it (Benettin’s method), or by integrating the linearized “tangent” equations.</p>
${eq("λ ≈ (1/T) Σₖ ln(dₖ / d₀)")}
<p>Positive λ signals chaos. Any finite-time estimate depends on the averaging time, initial condition and norm, so the Lab shows convergence plots and a settings scan, and validates the estimator on the Lorenz system.</p>`,
    demo: ["Estimate λ", () => go("lab")],
  },
  {
    t: "What is phase space?",
    body: `<p>Phase space is the space of all states (θ₁, θ₂, ω₁, ω₂). Each state has exactly one future, so a motion is a curve that never crosses itself in 4D. Plots like θ₁–ω₁ are <b>projections</b>, which is why curves can appear to cross.</p>`,
    demo: ["Open the Phase-Space Observatory", () => go("phase")],
  },
  {
    t: "What is a Poincaré section?",
    body: `<p>Energy conservation confines motion to a 3D surface in 4D phase space. Slicing it with the plane θ₁ = 0 (crossed with ω₁ &gt; 0) and recording (θ₂, ω₂) at each exact crossing gives a 2D picture: the Poincaré section.</p>
<p>Regular motion leaves closed curves (“islands”); chaotic motion scatters points over a “sea”. Crossings must be located precisely (Chaos Lab root-finds on the solver’s dense output). Simply sampling states at regular times does not give a Poincaré section.</p>`,
    demo: ["Compute sections", () => go("phase")],
  },
  {
    t: "What does energy conservation tell us?",
    body: `<p>For the free, undamped pendulum, E = T + V is constant. That confines the motion (starting at rest, the masses can never rise above the starting potential energy) and gives a quality check on the integrator.</p>
<p>Angular momentum about the pivot is <i>not</i> conserved, because gravity exerts a torque about the pivot. The Playground displays it so you can see it change.</p>`,
    demo: ["Explore the energy landscape", () => go("lab")],
  },
  {
    t: "What makes motion regular or chaotic?",
    body: `<p>At low energy the motion stays near the normal modes and is regular (quasi-periodic). As energy rises, regular islands shrink and chaotic regions grow, but special initial conditions can remain regular even at high energy. The first-flip map and the Poincaré sections show this mixed structure.</p>`,
    demo: ["See the first-flip map", () => go("fractal")],
  },
  {
    t: "Why is long-term prediction difficult?",
    body: `<p>Any measurement has some uncertainty δ₀. With exponential growth at rate λ, that uncertainty reaches a tolerance δ_max after roughly</p>
${eq("T ≈ ln(δ_max / δ₀) / λ")}
<p>Because of the logarithm, a thousand times better measurement buys only ln(1000)/λ ≈ 7/λ more seconds. For the classic double pendulum λ is of order 1 s⁻¹, so useful prediction lasts tens of seconds at best: not because the laws are unknown, but because the dynamics amplify ignorance.</p>`,
    demo: ["Predictability horizon calculator", () => go("lab")],
  },
];

function go(view) { location.hash = `#/${view}`; }
function preset(id) {
  const p = state.presets.find((x) => x.id === id);
  if (p) applyPreset(p);
  else setConfig(cloneDeep(state.config));
  go("playground");
}

export function mount(root) {
  let current = 0;
  const list = h("div", { class: "lesson-list", role: "list" });
  const content = h("article", { class: "prose" });
  const render = () => {
    list.innerHTML = "";
    LESSONS.forEach((l, i) => {
      const b = h("button", { type: "button", "aria-current": String(i === current) }, h("span", { class: "n" }, String(i + 1)), l.t);
      b.addEventListener("click", () => { current = i; render(); });
      list.append(b);
    });
    const l = LESSONS[current];
    content.innerHTML = `<div class="eyebrow">Lesson ${current + 1} of ${LESSONS.length}</div><h2>${l.t}</h2>${l.body}`;
    content.append(h("div", { class: "btn-row", style: { marginTop: "16px" } },
      l.demo ? btn(l.demo[0], l.demo[1], { cls: "primary" }) : null,
      current > 0 ? btn("← Previous", () => { current--; render(); }, { cls: "ghost" }) : null,
      current < LESSONS.length - 1 ? btn("Next →", () => { current++; render(); }, { cls: "ghost" }) : null));
  };
  render();
  root.append(h("div", { class: "layout-2" }, h("div", { class: "panel" }, h("div", { class: "panel-body" }, h("div", { class: "eyebrow", style: { marginBottom: "8px" } }, "Chaos Academy"), list)),
    h("div", { class: "panel" }, h("div", { class: "panel-body", style: { padding: "22px 28px" } }, content))));
}
