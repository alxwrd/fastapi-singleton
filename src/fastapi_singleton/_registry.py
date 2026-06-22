"""Process-global registry of every @singleton-wrapped object.

This package is single-FastAPI-app-per-process by design: singleton state
lives at module scope, the same way @lru_cache(maxsize=1) does. reset() is
provided for tests, where leaking state across test functions would
otherwise be a footgun.
"""

from typing import Any, Protocol, runtime_checkable

#: marker attribute used by is_singleton() to recognize anything @singleton
#: produces, including objects (like _InstanceProxy) that don't themselves
#: own a create/teardown lifecycle but stand in for one.
MARKER = "__fastapi_singleton__"


@runtime_checkable
class _Lifecycle(Protocol):
    _created: bool

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
    def teardown(self) -> Any: ...
    def _reset(self) -> None: ...


_singletons: list[_Lifecycle] = []
_creation_order: list[_Lifecycle] = []


def register(singleton: _Lifecycle) -> None:
    _singletons.append(singleton)


def note_created(singleton: _Lifecycle) -> None:
    _creation_order.append(singleton)


def all_singletons() -> tuple[_Lifecycle, ...]:
    return tuple(_singletons)


def creation_order() -> tuple[_Lifecycle, ...]:
    return tuple(_creation_order)


def is_singleton(obj: Any) -> bool:
    return getattr(obj, MARKER, False) is True


def reset() -> None:
    for singleton in _singletons:
        singleton._reset()
    _singletons.clear()
    _creation_order.clear()
