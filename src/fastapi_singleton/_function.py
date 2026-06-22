"""@singleton for plain functions.

A sync and an async wrapper class exist separately, rather than one wrapper
that internally awaits, because FastAPI decides how to invoke a dependency
(directly await it, or run it in a threadpool) based on whether the
callable itself is `async def` - so the wrapper's own sync/async-ness must
match the underlying provider's, not just delegate to it.

Deliberately does NOT use functools.wraps/update_wrapper on the raw
provider: that would set __wrapped__, and FastAPI's own generator detection
(fastapi.dependencies.models.Dependant.is_gen_callable) calls
inspect.unwrap() on whatever it's given, which would find the original
generator/async-generator function and misclassify our cached-value wrapper
as a live per-request resource. Identity (__name__/__doc__/__signature__) is
copied by hand instead.
"""

import asyncio
import inspect
import threading
import time
from collections.abc import Callable
from typing import Any

from . import _hooks, _registry, _signature
from ._provider import Provider

_UNSET = object()


class _BaseFunctionSingleton:
    def __init__(self, fn: Callable[..., Any], provider: Provider) -> None:
        self._fn = fn
        self._provider = provider
        self._created: float | None = None
        self._torn_down = False
        self._value: Any = _UNSET
        self._construction_kwargs: dict[str, Any] = {}
        self._hooks = _hooks.HookRegistry()
        self.__name__ = getattr(fn, "__name__", "singleton")
        self.__doc__ = fn.__doc__
        self.__module__ = fn.__module__
        self.__signature__ = inspect.signature(fn)
        setattr(self, _registry.MARKER, True)

    def before_start(self, hook: Callable[[], Any]) -> Callable[[], Any]:
        self._hooks.before_start.append(hook)
        return hook

    def before_end(self, hook: Callable[[], Any]) -> Callable[[], Any]:
        self._hooks.before_end.append(hook)
        return hook

    def after_end(self, hook: Callable[[], Any]) -> Callable[[], Any]:
        self._hooks.after_end.append(hook)
        return hook

    def _reset(self) -> None:
        self._provider = Provider(self._fn)
        self._created = None
        self._torn_down = False
        self._value = _UNSET
        self._construction_kwargs = {}

    def _existing(self, kwargs: dict[str, Any]) -> Any:
        """Returns the cached value if already created, else _UNSET.

        Shared between the sync and async fast-path/locked-path checks,
        which are otherwise identical aside from await placement.
        """
        if not self._created:
            return _UNSET
        _signature.check_no_conflict(
            repr(self), ((), self._construction_kwargs), ((), kwargs)
        )
        return self._value

    def _commit(self, value: Any, kwargs: dict[str, Any]) -> Any:
        self._value = value
        self._created = time.time()
        self._construction_kwargs = kwargs
        return value

    def _should_teardown(self) -> bool:
        if not self._created or self._torn_down:
            return False
        self._torn_down = True
        return True


class SyncFunctionSingleton(_BaseFunctionSingleton):
    def __init__(self, fn: Callable[..., Any], provider: Provider) -> None:
        super().__init__(fn, provider)
        self._lock = threading.Lock()

    def _reset(self) -> None:
        super()._reset()
        self._lock = threading.Lock()

    def __call__(self, **kwargs: Any) -> Any:
        existing = self._existing(kwargs)
        if existing is not _UNSET:
            return existing
        with self._lock:
            existing = self._existing(kwargs)
            if existing is not _UNSET:
                return existing
            if not kwargs:
                kwargs = _signature.self_resolve_kwargs(self._fn)
            _hooks.run_sync(self._hooks.before_start)
            value = self._provider.create(**kwargs)
            return self._commit(value, kwargs)

    def teardown(self) -> None:
        if not self._should_teardown():
            return
        _hooks.run_sync(self._hooks.before_end)
        self._provider.teardown()
        _hooks.run_sync(self._hooks.after_end)


class AsyncFunctionSingleton(_BaseFunctionSingleton):
    def __init__(self, fn: Callable[..., Any], provider: Provider) -> None:
        super().__init__(fn, provider)
        self._lock = asyncio.Lock()

    def _reset(self) -> None:
        super()._reset()
        self._lock = asyncio.Lock()

    async def __call__(self, **kwargs: Any) -> Any:
        existing = self._existing(kwargs)
        if existing is not _UNSET:
            return existing
        async with self._lock:
            existing = self._existing(kwargs)
            if existing is not _UNSET:
                return existing
            if not kwargs:
                kwargs = await _signature.async_self_resolve_kwargs(self._fn)
            await _hooks.run_async(self._hooks.before_start)
            value = await self._provider.create(**kwargs)
            return self._commit(value, kwargs)

    async def teardown(self) -> None:
        if not self._should_teardown():
            return
        await _hooks.run_async(self._hooks.before_end)
        result = self._provider.teardown()
        if inspect.isawaitable(result):
            await result
        await _hooks.run_async(self._hooks.after_end)


def make_function_singleton(
    fn: Callable[..., Any],
) -> SyncFunctionSingleton | AsyncFunctionSingleton:
    provider = Provider(fn)
    cls = AsyncFunctionSingleton if provider.is_async else SyncFunctionSingleton
    instance = cls(fn, provider)
    _registry.register(instance)
    return instance
