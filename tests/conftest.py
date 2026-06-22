import pytest

from fastapi_singleton import reset


@pytest.fixture(autouse=True)
def _reset_singleton_registry():
    reset()
    yield
    reset()
