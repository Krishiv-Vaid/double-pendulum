"""Double Pendulum Simulator interactive web application.

A dependency-free (standard library) HTTP server exposes the ``pendulum_sim``
engine as a JSON API and serves a static single-page frontend that renders on
an HTML canvas. Numerical state lives on the server (simulations are pure
functions of a :class:`~pendulum_sim.core.config.SimConfig`); rendering state
(colours, trails, camera) lives entirely in the browser, so changing a visual
setting never re-runs an integration.

Launch with ``python -m pendulum_sim.app`` or ``pendulum-sim serve``.
"""
