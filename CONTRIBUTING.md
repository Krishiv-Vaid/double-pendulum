# Contributing to Double Pendulum Simulator

Thanks for helping! The project has one non-negotiable rule: **scientific
correctness comes before aesthetics.**

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q && ruff check .
```

## Guidelines

* **Physics changes need a test that fails if the physics is wrong.** Prefer
  independent checks to re-deriving the same formula: energy conservation and
  its convergence, the Euler–Lagrange residual in `tests/test_physics.py`,
  analytic limits, and conservation or balance laws.
* **Keep it monochrome.** Use the tokens in `rendering/palettes.py` (greys only). Distinguish
  series by tone and dash pattern, never by hue; a test enforces that every token is grey.
* **Never present visuals as physics.** Glow, particles, camera motion,
  cross-fades and colour mappings must not feed back into the simulation, and
  must be labelled when they could be mistaken for dynamics.
* **Time is physical.** Store simulated seconds; apply playback speed only when
  rendering, and label it whenever it is not 1×.
* **No invented numbers.** Benchmarks come from `python -m pendulum_sim bench`.
  Gallery parameters come from sidecar files
  (`python scripts/build_gallery_docs.py`).
* **Presets make claims; claims are tested.** If you add a preset with a
  behavioural description, add a `checks` entry that `tests/test_presets.py`
  can verify.
* **Keep heavy work bounded.** New long-running features need validation
  limits, progress callbacks and cancellation.
* **Media.** Keep README GIFs small (see the `write()` budget in
  `scripts/generate_gallery.py`). Longer material goes in MP4.

## Regenerating assets

```bash
python scripts/generate_gallery.py            # all GIFs + MP4 (~4 min)
python scripts/generate_gallery.py --only hero-chaos
python scripts/build_gallery_docs.py          # refresh docs/gallery.md
python -m pendulum_sim bench                     # refresh benchmarks/results.{json,md}
```
