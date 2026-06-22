from typing import Annotated

import pytest
from fastapi import Depends

from fastapi_singleton import UsageError, singleton


def test_plain_function_is_cached_like_lru_cache_maxsize_1():
    @singleton
    def get_value():
        return object()

    assert get_value() is get_value()


def test_generator_function_yields_once_then_caches_value():
    events = []

    @singleton
    def get_value():
        events.append("create")
        yield "value"
        events.append("teardown")

    assert get_value() == "value"
    assert get_value() == "value"
    assert events == ["create"]

    get_value.teardown()
    assert events == ["create", "teardown"]


def test_teardown_is_idempotent():
    events = []

    @singleton
    def get_value():
        yield "value"
        events.append("teardown")

    get_value()
    get_value.teardown()
    get_value.teardown()
    assert events == ["teardown"]


def test_teardown_before_creation_is_a_noop():
    @singleton
    def get_value():
        yield "value"

    get_value.teardown()  # should not raise


def test_generator_yielding_twice_raises_on_teardown():
    @singleton
    def get_value():
        yield "a"
        yield "b"

    get_value()
    with pytest.raises(Exception):
        get_value.teardown()


@pytest.mark.asyncio
async def test_async_plain_function_is_cached():
    @singleton
    async def get_value():
        return object()

    a = await get_value()
    b = await get_value()
    assert a is b


@pytest.mark.asyncio
async def test_async_generator_function_yields_once_then_caches_value():
    events = []

    @singleton
    async def get_value():
        events.append("create")
        yield "value"
        events.append("teardown")

    assert await get_value() == "value"
    assert await get_value() == "value"
    assert events == ["create"]

    await get_value.teardown()
    assert events == ["create", "teardown"]


def test_self_resolution_of_singleton_dependency_chain_with_zero_args():
    @singleton
    def get_other():
        return "other-value"

    @singleton
    def get_thing(other: Annotated[str, Depends(get_other)]):
        return f"thing-with-{other}"

    assert get_thing() == "thing-with-other-value"


def test_self_resolution_rejects_non_singleton_dependency():
    def get_request_scoped():
        return "request-data"

    @singleton
    def get_thing(other: Annotated[str, Depends(get_request_scoped)]):
        return other

    with pytest.raises(UsageError):
        get_thing()


@pytest.mark.asyncio
async def test_sync_singleton_cannot_self_resolve_an_async_singleton_dependency():
    @singleton
    async def get_other():
        return "other-value"

    @singleton
    def get_thing(other: Annotated[str, Depends(get_other)]):
        return other

    with pytest.raises(UsageError):
        get_thing()
