import pytest

from fastapi_singleton import testing


@pytest.fixture(autouse=True)
def _reset_singleton_registry():
    testing.reset()
    yield
    testing.reset()
