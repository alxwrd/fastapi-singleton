from typing import Annotated

import pytest
from fastapi import Depends

from fastapi_singleton import UsageError, singleton


def test_plain_function_is_cached_like_lru_cache_maxsize_1():
    @singleton
    def get_value():
        return object()

    assert get_value() is get_value()


def test_repeat_call_with_same_kwargs_is_a_noop():
    @singleton
    def get_value(option="default"):
        return object()

    a = get_value(option="first")
    b = get_value(option="first")
    assert a is b


def test_repeat_call_with_conflicting_kwargs_raises():
    @singleton
    def get_value(option="default"):
        return option

    get_value(option="first")
    with pytest.raises(UsageError):
        get_value(option="second")


def test_raises_when_an_unstable_dependency_resolves_differently_on_second_call():
    """A singleton is meant to be constructed once. If whatever's feeding
    its arguments isn't actually stable (e.g. it isn't itself a singleton,
    or is otherwise misused), a second invocation that resolves to a
    different value must raise rather than silently keep the first value or
    silently overwrite it with the second."""
    values = iter(["first-value", "second-value"])

    def get_unstable_value():
        return next(values)

    @singleton
    def get_thing(value=None):
        return value

    get_thing(value=get_unstable_value())
    with pytest.raises(UsageError):
        get_thing(value=get_unstable_value())


@pytest.mark.asyncio
async def test_async_repeat_call_with_conflicting_kwargs_raises():
    @singleton
    async def get_value(option="default"):
        return option

    await get_value(option="first")
    with pytest.raises(UsageError):
        await get_value(option="second")


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
async def test_async_singleton_self_resolves_an_async_singleton_dependency():
    @singleton
    async def get_other():
        return "other-value"

    @singleton
    async def get_thing(other: Annotated[str, Depends(get_other)]):
        return f"thing-with-{other}"

    assert await get_thing() == "thing-with-other-value"


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
