from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.dependencies.utils import get_dependant

from fastapi_singleton import UsageError, singleton


def test_class_is_a_value_singleton():
    @singleton
    class Thing:
        def __init__(self):
            self.id = object()

    a = Thing()
    b = Thing()
    assert a is b


def test_class_self_resolves_init_depends():
    @singleton
    def get_other():
        return "other-value"

    @singleton
    class Connection:
        def __init__(self, other: Annotated[str, Depends(get_other)]):
            self.other = other

    conn = Connection()
    assert conn.other == "other-value"


def test_class_depends_on_other_class_resolves():
    @singleton
    class Other:
        def __init__(self):
            self.value = "other-value"

    @singleton
    class Connection:
        def __init__(self, other: Annotated[str, Depends(Other)]):
            self.other = other

    conn = Connection()
    assert conn.other.value == "other-value"


def test_class_repeat_construction_with_same_args_is_a_noop():
    @singleton
    class Thing:
        def __init__(self, value="default"):
            self.value = value

    a = Thing(value="first")
    b = Thing(value="first")
    assert a is b


def test_class_raises_on_conflicting_repeat_construction():
    @singleton
    class Thing:
        def __init__(self, value="default"):
            self.value = value

    Thing(value="first")
    with pytest.raises(UsageError):
        Thing(value="second")


def test_class_raises_when_an_unstable_dependency_resolves_differently():
    values = iter(["first-value", "second-value"])

    def get_unstable_value():
        return next(values)

    @singleton
    class Thing:
        def __init__(self, value=None):
            self.value = value

    Thing(value=get_unstable_value())
    with pytest.raises(UsageError):
        Thing(value=get_unstable_value())


def test_class_singleton_is_a_plain_sync_dependency_to_fastapi():
    """A class singleton's __init__ can never be async (Python doesn't
    support it), so Depends(SomeClass) should behave exactly like any other
    FastAPI class-based dependency: a plain, synchronously-called
    constructor, never awaited, never treated as a generator."""

    @singleton
    class Thing:
        def __init__(self):
            pass

    dependant = get_dependant(path="/x", call=Thing)

    assert dependant.is_gen_callable is False
    assert dependant.is_async_gen_callable is False
    assert dependant.is_coroutine_callable is False
