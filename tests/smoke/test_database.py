"""Smoke tests against the running PostgreSQL container.

Start it first:  docker compose up -d
Run only these:  pytest -m smoke
"""

import pytest

from druksmart_common import healthchecks
from druksmart_common.config import load_settings

pytestmark = pytest.mark.smoke


@pytest.fixture(scope="module")
def settings():
    return load_settings()


@pytest.mark.parametrize("check", healthchecks.ALL_CHECKS, ids=lambda c: c.__name__)
def test_database_check(settings, check):
    result = check(settings)

    assert result.passed, result.detail
