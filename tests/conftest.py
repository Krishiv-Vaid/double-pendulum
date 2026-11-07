import os

import matplotlib
import pytest

matplotlib.use("Agg")


@pytest.fixture(autouse=True, scope="session")
def _isolated_cache(tmp_path_factory):
    os.environ["PENDULUM_SIM_CACHE"] = str(tmp_path_factory.mktemp("cache"))
    from pathlib import Path

    import pendulum_sim.experiments.maps as maps

    maps.CACHE_DIR = Path(os.environ["PENDULUM_SIM_CACHE"]) / "maps"
