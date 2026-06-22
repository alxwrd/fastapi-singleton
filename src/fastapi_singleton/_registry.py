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
    #: unix timestamp set when the singleton is created, None until then.
    #: Doubles as the creation-order sort key, so no separate list of
    #: created singletons needs to be maintained.
    _created: float | None

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
    def teardown(self) -> Any: ...
    def _reset(self) -> None: ...


_singletons: list[_Lifecycle] = []


def register(singleton: _Lifecycle) -> None:
    _singletons.append(singleton)


def all_singletons() -> tuple[_Lifecycle, ...]:
    return tuple(_singletons)


def creation_order() -> tuple[_Lifecycle, ...]:
    created = [s for s in _singletons if s._created is not None]
    created.sort(key=lambda s: s._created)
    return tuple(created)


def is_singleton(obj: Any) -> bool:
    return getattr(obj, MARKER, False) is True


def reset() -> None:
    for singleton in _singletons:
        singleton._reset()
    _singletons.clear()
