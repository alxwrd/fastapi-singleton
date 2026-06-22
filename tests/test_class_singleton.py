from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.dependencies.utils import get_dependant

from fastapi_singleton import singleton


def test_class_without_call_is_a_value_singleton():
    @singleton
    class Thing:
        def __init__(self):
            self.id = object()

    a = Thing()
    b = Thing()
    assert a is b


def test_class_without_call_self_resolves_init_depends():
    @singleton
    def get_other():
        return "other-value"

    @singleton
    class Connection:
        def __init__(self, other: Annotated[str, Depends(get_other)]):
            self.other = other

    conn = Connection()
    assert conn.other == "other-value"


def test_class_without_call_ignores_args_on_repeat_construction():
    @singleton
    class Thing:
        def __init__(self, value="default"):
            self.value = value

    a = Thing(value="first")
    b = Thing(value="second")
    assert a is b
    assert a.value == "first"


@pytest.mark.asyncio
async def test_class_with_call_yields_once_and_caches_value():
    events = []

    @singleton
    class Pool:
        def __init__(self):
            events.append("init")

        def __call__(self):
            events.append("pre-yield")
            yield self
            events.append("post-yield")

    proxy = Pool()
    v1 = await proxy()
    v2 = await proxy()
    assert v1 is v2
    assert events == ["init", "pre-yield"]

    await proxy.teardown()
    assert events == ["init", "pre-yield", "post-yield"]


def test_class_with_call_returns_same_proxy_on_repeat_calls():
    @singleton
    class Pool:
        def __init__(self):
            pass

        def __call__(self):
            yield self

    assert Pool() is Pool()


@pytest.mark.asyncio
async def test_class_with_async_generator_call():
    events = []

    @singleton
    class Pool:
        def __init__(self):
            pass

        async def __call__(self):
            events.append("pre-yield")
            yield self
            events.append("post-yield")

    proxy = Pool()
    await proxy()
    await proxy()
    await proxy.teardown()
    assert events == ["pre-yield", "post-yield"]


@pytest.mark.asyncio
async def test_proxy_is_not_detected_as_a_generator_dependency_by_fastapi():
    """Regression test for the core risk this package has to defeat: if
    FastAPI thinks the proxy is a live generator dependency, it will
    recreate/close the resource on every request instead of once."""

    @singleton
    class Pool:
        def __init__(self):
            pass

        def __call__(self):
            yield self

    proxy = Pool()
    dependant = get_dependant(path="/x", call=proxy)

    assert dependant.is_gen_callable is False
    assert dependant.is_async_gen_callable is False
    assert dependant.is_coroutine_callable is True


def test_class_with_call_self_resolves_init_depends_async():
    @singleton
    def get_other():
        return "other-value"

    @singleton
    class Pool:
        def __init__(self, other: Annotated[str, Depends(get_other)]):
            self.other = other

        def __call__(self):
            yield self

    import asyncio

    proxy = Pool()
    value = asyncio.run(proxy())
    assert value.other == "other-value"
