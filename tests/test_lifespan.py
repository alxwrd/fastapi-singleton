from contextlib import asynccontextmanager
from typing import Annotated

import pytest
from fastapi import Depends

from fastapi_singleton import lifespan, singleton


@pytest.mark.asyncio
async def test_eager_startup_constructs_dependencies_before_dependents():
    events = []

    @singleton
    def get_a():
        events.append("a")
        return "a-value"

    @singleton
    def get_b(a: Annotated[str, Depends(get_a)]):
        events.append("b")
        return "b-value"

    async with lifespan(None):
        assert events == ["a", "b"]


@pytest.mark.asyncio
async def test_teardown_runs_in_reverse_creation_order():
    events = []

    @singleton
    def get_a():
        yield "a-value"
        events.append("a-teardown")

    @singleton
    def get_b(a: Annotated[str, Depends(get_a)]):
        yield "b-value"
        events.append("b-teardown")

    async with lifespan(None):
        pass

    assert events == ["b-teardown", "a-teardown"]


@pytest.mark.asyncio
async def test_already_created_singleton_is_not_recreated_on_startup():
    events = []

    @singleton
    def get_value():
        events.append("create")
        return "value"

    get_value()
    assert events == ["create"]

    async with lifespan(None):
        pass

    assert events == ["create"]


@pytest.mark.asyncio
async def test_teardown_runs_even_if_app_body_raises():
    events = []

    @singleton
    def get_value():
        yield "value"
        events.append("teardown")

    with pytest.raises(RuntimeError):
        async with lifespan(None):
            raise RuntimeError("boom")

    assert events == ["teardown"]


@pytest.mark.asyncio
async def test_composes_with_a_user_defined_lifespan():
    events = []

    @singleton
    def get_value():
        events.append("singleton-create")
        yield "value"
        events.append("singleton-teardown")

    @asynccontextmanager
    async def app_lifespan(app):
        async with lifespan(app):
            events.append("user-startup")
            yield
            events.append("user-shutdown")

    async with app_lifespan(None):
        pass

    assert events == [
        "singleton-create",
        "user-startup",
        "user-shutdown",
        "singleton-teardown",
    ]
