import os

import matplotlib
import pytest

matplotlib.use("Agg")


@pytest.fixture(autouse=True, scope="session")
def _isolated_cache(tmp_path_factory):
    os.environ["CHAOS_LAB_CACHE"] = str(tmp_path_factory.mktemp("cache"))
    from pathlib import Path

    import chaos_lab.experiments.maps as maps

    maps.CACHE_DIR = Path(os.environ["CHAOS_LAB_CACHE"]) / "maps"
