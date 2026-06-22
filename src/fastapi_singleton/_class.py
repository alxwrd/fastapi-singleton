"""@singleton for classes.

Classes are always a sync, `__init__`-only "value singleton": `__init__`
can never be `async def` in Python, so there's no mechanism by which a
class-based dependency could do real async resource setup (`await
asyncpg.create_pool(...)` and friends) - FastAPI itself never awaits a
class's constructor either, for the same reason. If a singleton needs async
construction or generator-based teardown, write it as a function (see
_function.py); a class singleton can still depend on one via `Depends` in
its `__init__` the same way any other dependency does.

Because `@singleton class Foo` only ever constructs via `__init__`, calling
it is exactly "call the constructor" - the same mental model as a plain
FastAPI class-based dependency (`Depends(Foo)`), just memoized.
"""

import inspect
import threading
import time
from collections.abc import Callable
from typing import Any

from . import _hooks, _registry, _signature

_UNSET = object()


class _ClassSingleton:
    def __init__(self, cls: type) -> None:
        self._cls = cls
        self._hooks = _hooks.HookRegistry()
        self.__name__ = cls.__name__
        self.__doc__ = cls.__doc__
        self.__module__ = cls.__module__
        init_signature = inspect.signature(cls.__init__)
        params = [p for name, p in init_signature.parameters.items() if name != "self"]
        self.__signature__ = init_signature.replace(parameters=params)
        setattr(self, _registry.MARKER, True)
        self._created: float | None = None
        self._torn_down = False
        self._value: Any = _UNSET
        self._construction_args: tuple[Any, ...] = ()
        self._construction_kwargs: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _existing(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        if not self._created:
            return _UNSET
        _signature.check_no_conflict(
            repr(self),
            (self._construction_args, self._construction_kwargs),
            (args, kwargs),
        )
        return self._value

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        existing = self._existing(args, kwargs)
        if existing is not _UNSET:
            return existing
        with self._lock:
            existing = self._existing(args, kwargs)
            if existing is not _UNSET:
                return existing
            if not args and not kwargs:
                kwargs = _signature.self_resolve_kwargs(self._cls.__init__)
            _hooks.run_sync(self._hooks.before_start)
            self._value = self._cls(*args, **kwargs)
            self._created = time.time()
            self._construction_args = args
            self._construction_kwargs = kwargs
            return self._value

    def teardown(self) -> None:
        if not self._created or self._torn_down:
            return
        self._torn_down = True
        _hooks.run_sync(self._hooks.before_end)
        _hooks.run_sync(self._hooks.after_end)

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
        self._created = None
        self._torn_down = False
        self._value = _UNSET
        self._construction_args = ()
        self._construction_kwargs = {}
        self._lock = threading.Lock()


def make_class_singleton(cls: type) -> _ClassSingleton:
    instance = _ClassSingleton(cls)
    _registry.register(instance)
    return instance
