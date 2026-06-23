import inspect
from typing import Annotated

import pytest
from fastapi import Depends

from fastapi_singleton import UsageError, singleton
from fastapi_singleton._provider import Provider


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


@pytest.mark.parametrize(
    "value_factory",
    [
        pytest.param(lambda: float("nan"), id="nan"),
        pytest.param(lambda: [1, 2, 3], id="list"),
        pytest.param(lambda: {"a": 1, "b": 2}, id="dict"),
        pytest.param(lambda: [1, float("nan")], id="list-containing-nan"),
        pytest.param(lambda: {"a": float("nan")}, id="dict-containing-nan"),
    ],
)
def test_repeat_call_with_equal_but_distinct_value_is_not_treated_as_a_conflict(
    value_factory,
):
    @singleton
    def get_value(value=None):
        return value

    # value_factory() is called twice so each call gets its own distinct
    # object - the point is that equal-but-not-identical values shouldn't be
    # treated as a conflict, whether or not they're hashable or contain NaN.
    get_value(value=value_factory())
    get_value(value=value_factory())


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


def test_calling_a_singleton_after_teardown_raises_instead_of_returning_stale_value():
    @singleton
    def get_value():
        yield "value"

    get_value()
    get_value.teardown()

    with pytest.raises(UsageError):
        get_value()


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


def test_self_dependent_singleton_raises_instead_of_deadlocking():
    """A singleton depending on itself would otherwise try to re-acquire
    its own non-reentrant lock mid-construction and hang forever; it must
    raise instead. Constructed via monkeypatching because a genuine direct
    self-reference can't be written with `Depends(get_a)` inside `get_a`'s
    own definition - the name doesn't exist yet at that point."""

    @singleton
    def get_a(a=None):
        return "a"

    def self_referencing(a: Annotated[str | None, Depends(get_a)] = None):
        return "a"

    get_a._fn = self_referencing
    get_a._provider = Provider(self_referencing)
    get_a.__signature__ = inspect.signature(self_referencing)

    with pytest.raises(UsageError, match="depends on itself"):
        get_a()


def test_mutually_dependent_singletons_raise_instead_of_deadlocking():
    @singleton
    def get_a(b=None):
        return "a"

    @singleton
    def get_b(a: Annotated[str | None, Depends(get_a)] = None):
        return "b"

    def a_depends_on_b(b: Annotated[str | None, Depends(get_b)] = None):
        return "a"

    get_a._fn = a_depends_on_b
    get_a._provider = Provider(a_depends_on_b)
    get_a.__signature__ = inspect.signature(a_depends_on_b)

    with pytest.raises(UsageError, match="depends on itself"):
        get_a()


@pytest.mark.asyncio
async def test_async_mutually_dependent_singletons_raise_instead_of_deadlocking():
    @singleton
    async def get_a(b=None):
        return "a"

    @singleton
    async def get_b(a: Annotated[str | None, Depends(get_a)] = None):
        return "b"

    async def a_depends_on_b(b: Annotated[str | None, Depends(get_b)] = None):
        return "a"

    get_a._fn = a_depends_on_b
    get_a._provider = Provider(a_depends_on_b)
    get_a.__signature__ = inspect.signature(a_depends_on_b)

    with pytest.raises(UsageError, match="depends on itself"):
        await get_a()


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
