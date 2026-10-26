"""Import tests/fixtures/synthetic/generate_fixtures.py as a module (it is a script)."""

import importlib.util
from functools import cache

from kpi_reference import FIXTURES_DIR


@cache
def generator():
    spec = importlib.util.spec_from_file_location(
        "generate_fixtures", FIXTURES_DIR / "generate_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
