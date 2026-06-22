"""@singleton for classes.

Two distinct shapes, matching the two patterns in the README:

* No `__call__` defined: the class itself has nothing to tear down (an
  `__init__` can't yield), so `@singleton class Connection: ...` behaves
  like a "value singleton" - calling/`Depends`-ing the wrapper directly
  constructs once (synchronously - construction can't be deferred into an
  async context here) and forever returns the same instance.

* `__call__` defined as a (sync or async, plain or generator) method: this
  is the teardown-capable shape (`ConnectionPool` in the README). Calling
  `ConnectionPool()` must stay synchronous (it's typically evaluated inline
  in `Depends(ConnectionPool())` at route-definition time, not inside an
  async function), so it can't trigger real construction itself. Instead it
  returns a stable `_InstanceProxy` - a plain object whose own `__call__` is
  always `async def` and does the real (possibly async) construction lazily,
  exactly once, on first invocation. FastAPI inspects `instance.__call__`
  for generator-ness when given a callable instance (see
  fastapi.dependencies.models.Dependant.is_gen_callable): because
  `_InstanceProxy.__call__` is hand-written as an ordinary coroutine
  function (never a generator, never built via functools.wraps over the
  user's real generator `__call__`), FastAPI treats it as a normal
  once-per-request dependency rather than a live per-request resource - the
  user's actual generator body is captured separately and driven manually,
  once, by this module and by _lifespan.py.
"""

import inspect
from collections.abc import Callable
from typing import Any

from . import _hooks, _registry, _signature
from ._provider import Provider

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

        self._call_fn: Any | None = cls.__dict__.get("__call__")
        self._has_call = self._call_fn is not None

        if self._has_call:
            self._proxy: "_InstanceProxy | None" = None
        else:
            self._created = False
            self._torn_down = False
            self._value: Any = _UNSET
            _registry.register(self)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._has_call:
            if self._proxy is None:
                self._proxy = _InstanceProxy(self, args, kwargs)
                _registry.register(self._proxy)
            return self._proxy
        if self._created:
            return self._value
        if not args and not kwargs:
            kwargs = _signature.self_resolve_kwargs(self._cls.__init__)
        _hooks.run_sync(self._hooks.before_start)
        self._value = self._cls(*args, **kwargs)
        self._created = True
        _registry.note_created(self)
        return self._value

    def teardown(self) -> None:
        """Only meaningful for the no-`__call__` shape; an `__init__` can't
        yield, so there's nothing to tear down beyond running hooks."""
        if self._has_call:
            return
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
        if self._has_call:
            self._proxy = None
        else:
            self._created = False
            self._torn_down = False
            self._value = _UNSET


class _InstanceProxy:
    """What `ConnectionPool()` returns - the actual `Depends(...)` target."""

    def __init__(
        self, owner: _ClassSingleton, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        self._owner = owner
        self._args = args
        self._kwargs = kwargs
        self._created = False
        self._torn_down = False
        self._value: Any = _UNSET
        self._call_provider: Provider | None = None
        setattr(self, _registry.MARKER, True)

    async def __call__(self) -> Any:
        if self._created:
            return self._value
        args, kwargs = self._args, self._kwargs
        if not args and not kwargs:
            kwargs = await _signature.async_self_resolve_kwargs(
                self._owner._cls.__init__
            )
        await _hooks.run_async(self._owner._hooks.before_start)
        instance = self._owner._cls(*args, **kwargs)
        call_fn = self._owner._call_fn
        if call_fn is not None:
            bound = call_fn.__get__(instance, type(instance))
            provider = Provider(bound)
            value = provider.create()
            if inspect.isawaitable(value):
                value = await value
            self._call_provider = provider
        else:
            value = instance
        self._value = value
        self._created = True
        _registry.note_created(self)
        return self._value

    async def teardown(self) -> None:
        if not self._created or self._torn_down:
            return
        self._torn_down = True
        await _hooks.run_async(self._owner._hooks.before_end)
        if self._call_provider is not None:
            result = self._call_provider.teardown()
            if inspect.isawaitable(result):
                await result
        await _hooks.run_async(self._owner._hooks.after_end)

    def _reset(self) -> None:
        self._created = False
        self._torn_down = False
        self._value = _UNSET
        self._call_provider = None
