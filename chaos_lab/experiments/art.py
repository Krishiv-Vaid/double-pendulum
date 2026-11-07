"""Chaos Art Generator: random search for visually interesting trajectories.

Aesthetics cannot be measured objectively. These are explicit, documented
heuristics computed from the lower bob's path (x2, y2) over the run, used only
to *rank candidates for a human to review*:

* coverage    fraction of a 64x64 grid over the reachable disc that the path visits
* symmetry    correlation between the visit histogram and its left-right mirror
* loops       total absolute turning angle of the path / 2 pi
* complexity  coverage x log(1 + loops)
* sparse      high loops with low coverage: loops / (1 + 40 coverage)
* swirl       mean |angular velocity of the bob about the pivot|, normalised

Objectives map to scores: "coverage", "symmetry", "dense" (swirl x coverage),
"loops", "complexity", "sparse", "exposure" (coverage x symmetry^0.5).
"""

from __future__ import annotations

import numpy as np

from chaos_lab.core import physics
from chaos_lab.core.config import Initial, Numerics, Physical, SimConfig
from chaos_lab.experiments.ensemble import integrate_batch

OBJECTIVES = ("coverage", "symmetry", "dense", "loops", "complexity", "sparse", "exposure")


def path_metrics(x, y, R, bins: int = 64) -> dict:
    H, _, _ = np.histogram2d(x, y, bins=bins, range=[[-R, R], [-R, R]])
    c = (np.arange(bins) + 0.5) / bins * 2 * R - R
    X, Y = np.meshgrid(c, c, indexing="ij")
    disc = (X**2 + Y**2) <= R**2
    occ = (H > 0) & disc
    cov = float(occ.sum() / disc.sum())
    a = (H > 0).astype(float).ravel()
    b = (H[::-1, :] > 0).astype(float).ravel()
    sym = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 else 0.0
    dx, dy = np.diff(x), np.diff(y)
    heading = np.unwrap(np.arctan2(dy, dx))
    loops = float(np.sum(np.abs(np.diff(heading))) / (2 * np.pi))
    phi = np.unwrap(np.arctan2(x, -y))
    swirl = float(np.mean(np.abs(np.diff(phi))) * len(x) / (2 * np.pi * 100))
    return {"coverage": cov, "symmetry": sym, "loops": loops, "complexity": cov * np.log1p(loops),
            "sparse": loops / (1 + 40 * cov), "swirl": swirl}


def score(m: dict, objective: str) -> float:
    return {
        "coverage": m["coverage"],
        "symmetry": max(m["symmetry"], 0) * (0.2 + m["coverage"]),
        "dense": m["swirl"] * m["coverage"],
        "loops": m["loops"],
        "complexity": m["complexity"],
        "sparse": m["sparse"],
        "exposure": m["coverage"] * max(m["symmetry"], 0) ** 0.5,
    }[objective]


def search(objective: str = "complexity", n_candidates: int = 64, top: int = 8, seed: int = 0, t_max: float = 30.0,
           physical: Physical | None = None, randomize_physics: bool = False, dt: float = 2e-3) -> list[dict]:
    """Evaluate ``n_candidates`` random starts (vectorized) and return the best ``top``."""
    if objective not in OBJECTIVES:
        raise ValueError(f"objective must be one of {OBJECTIVES}")
    if not 1 <= n_candidates <= 2000:
        raise ValueError("n_candidates must be in [1, 2000]")
    rng = np.random.default_rng(seed)
    base = physical or Physical()
    th = rng.uniform(-np.pi, np.pi, (n_candidates, 2))
    w = rng.normal(0, 1.0, (n_candidates, 2)) * (rng.random((n_candidates, 1)) < 0.3)
    y0 = np.concatenate([th, w], axis=1)
    if randomize_physics:
        m2 = rng.uniform(0.3, 2.0, n_candidates)
        L2 = rng.uniform(0.4, 1.4, n_candidates)
        from dataclasses import replace
        p = replace(base, m2=m2, L2=L2)
    else:
        m2 = np.full(n_candidates, base.m2)
        L2 = np.full(n_candidates, base.L2)
        p = base
    t, Y = integrate_batch(p, y0, t_max, dt, 1 / 60)
    _, _, x2, y2 = physics.positions(Y, p)
    results = []
    for k in range(n_candidates):
        R = base.L1 + L2[k]
        m = path_metrics(x2[:, k], y2[:, k], R)
        phys = Physical(base.m1, float(m2[k]), base.L1, float(L2[k]), base.g)
        cfg = SimConfig(phys, Initial(float(np.degrees(th[k, 0])), float(np.degrees(th[k, 1])),
                                      float(w[k, 0]), float(w[k, 1])),
                        Numerics(t_max=t_max), f"Art candidate {k} (seed {seed})")
        results.append({"score": float(score(m, objective)), "metrics": m, "config": cfg})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top]
