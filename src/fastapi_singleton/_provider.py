"""Normalizes the four sync/async x plain/generator dependency shapes that
FastAPI itself supports into a single create-once/teardown-once interface.

Detection runs on the raw function the user wrote, never on a wrapper we
hand to FastAPI - see _function.py and _class.py for why that distinction
matters.
"""

import inspect
from collections.abc import Callable
from typing import Any

_UNSET = object()


class MultipleYieldError(RuntimeError):
    """Raised when a generator-based provider yields more than once."""


class Provider:
    """Drives a single sync/async, plain/generator callable exactly once."""

    def __init__(self, fn: Callable[..., Any]) -> None:
        self._fn = fn
        self._is_gen = inspect.isgeneratorfunction(fn)
        self._is_async_gen = inspect.isasyncgenfunction(fn)
        self._is_coroutine = inspect.iscoroutinefunction(fn)
        self.is_async = self._is_async_gen or self._is_coroutine
        self._generator: Any = _UNSET

    def create(self, **kwargs: Any) -> Any:
        if self._is_async_gen:
            return self._acreate(**kwargs)
        if self._is_coroutine:
            return self._fn(**kwargs)
        if self._is_gen:
            generator = self._fn(**kwargs)
            value = next(generator)
            self._generator = generator
            return value
        return self._fn(**kwargs)

    async def _acreate(self, **kwargs: Any) -> Any:
        generator = self._fn(**kwargs)
        value = await anext(generator)
        self._generator = generator
        return value

    def teardown(self) -> Any:
        if self._generator is _UNSET:
            return None
        if self._is_async_gen:
            return self._ateardown()
        generator = self._generator
        sentinel = _UNSET
        result = next(generator, sentinel)
        if result is not sentinel:
            raise MultipleYieldError(
                f"{self._fn!r} yielded more than once; "
                "singleton providers must yield exactly once"
            )
        return None

    async def _ateardown(self) -> None:
        generator = self._generator
        sentinel = _UNSET
        result = await anext(generator, sentinel)
        if result is not sentinel:
            raise MultipleYieldError(
                f"{self._fn!r} yielded more than once; "
                "singleton providers must yield exactly once"
            )
