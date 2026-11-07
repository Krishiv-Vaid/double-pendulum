"""Chaos Lab Ultra — double pendulum physics, chaos analysis and visualization.

Two pendulums. Infinite possibilities. Explore the mathematics of chaos.
"""

__version__ = "0.2.0"

from chaos_lab.core.config import Initial, Numerics, Physical, SimConfig  # noqa: E402
from chaos_lab.core.simulation import Result, simulate  # noqa: E402

__all__ = ["Initial", "Numerics", "Physical", "SimConfig", "Result", "simulate", "__version__"]
