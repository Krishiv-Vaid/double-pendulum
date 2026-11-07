"""Double Pendulum Simulator — double pendulum physics, chaos analysis and visualization.

Simulate, analyze and render the chaotic motion of a double pendulum.
"""

__version__ = "0.2.0"

from pendulum_sim.core.config import Initial, Numerics, Physical, SimConfig  # noqa: E402
from pendulum_sim.core.simulation import Result, simulate  # noqa: E402

__all__ = ["Initial", "Numerics", "Physical", "SimConfig", "Result", "simulate", "__version__"]
