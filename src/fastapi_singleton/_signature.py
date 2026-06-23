"""Depends()-aware signature introspection and self-resolution.

Mirrors fastapi.dependencies.utils.analyze_param's two ways of finding a
Depends() marker on a parameter (bare default, or Annotated[...] metadata),
so @singleton-decorated callables can be resolved both by FastAPI itself
(during a real request) and by our own code (direct calls in plain Python,
and the eager lifespan startup walk).
"""

import contextlib
import contextvars
import inspect
import math
import typing
from collections.abc import Callable, Iterator
from typing import Any

from fastapi.params import Depends

from . import _registry


class UsageError(RuntimeError):
    """Raised when a singleton's dependency graph can't be resolved."""


#: ids of singletons currently under construction on this thread/task, used
#: to detect a singleton depending on itself, directly or transitively.
#: contextvars rather than a plain set: each thread gets its own context by
#: default, and the value propagates correctly across awaits within a single
#: asyncio task, so concurrent unrelated constructions never collide.
_constructing: contextvars.ContextVar[frozenset[int]] = contextvars.ContextVar(
    "_constructing", default=frozenset()
)


@contextlib.contextmanager
def guard_against_cycles(singleton: Any) -> Iterator[None]:
    """Raises UsageError if `singleton` is already being constructed further
    up the current call stack, instead of letting construction proceed into
    a re-acquire of its own non-reentrant lock, which would deadlock rather
    than fail."""
    current = _constructing.get()
    key = id(singleton)
    if key in current:
        raise UsageError(
            f"{singleton!r} depends on itself, directly or transitively. "
            "A singleton's dependency graph must be acyclic."
        )
    token = _constructing.set(current | {key})
    try:
        yield
    finally:
        _constructing.reset(token)


def _values_equal(a: Any, b: Any) -> bool:
    """Like `==`, but recurses into dicts/lists/tuples and treats two NaN
    floats as equal to each other.

    Covers the ways `==` alone is unreliable for argument values: NaN
    follows IEEE 754, where it's never equal to anything (including
    another NaN), and unhashable containers need their elements compared
    individually to catch a NaN nested inside them. Without this, a repeat
    call with semantically-unchanged arguments could look like a
    conflicting one."""
    if (
        isinstance(a, float)
        and isinstance(b, float)
        and math.isnan(a)
        and math.isnan(b)
    ):
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_values_equal(a[key], b[key]) for key in a)
    if (
        isinstance(a, (list, tuple))
        and isinstance(b, (list, tuple))
        and len(a) == len(b)
    ):
        return all(_values_equal(x, y) for x, y in zip(a, b))
    return a == b


def check_no_conflict(
    name: str,
    original: tuple[tuple[Any, ...], dict[str, Any]],
    attempted: tuple[tuple[Any, ...], dict[str, Any]],
) -> None:
    """A singleton is constructed once; calling it again with the same
    resolved args (e.g. FastAPI re-passing an already-cached nested
    singleton dependency on every request) is a no-op, but calling it again
    with genuinely different args is almost certainly a bug, not something
    to silently ignore."""
    attempted_args, attempted_kwargs = attempted
    if not attempted_args and not attempted_kwargs:
        return
    if _values_equal(attempted, original):
        return
    raise UsageError(
        f"{name} was already constructed with {original!r}; called again "
        f"with different arguments {attempted!r}. A singleton is "
        "constructed exactly once - if you need different configurations, "
        "use separate singletons."
    )


def depends_params(fn: Callable[..., Any]) -> dict[str, Callable[..., Any]]:
    signature = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except NameError:
        hints = {}
    found: dict[str, Callable[..., Any]] = {}
    for name, param in signature.parameters.items():
        if name == "self":
            continue
        depends = None
        if isinstance(param.default, Depends):
            depends = param.default
        else:
            annotation = hints.get(name, param.annotation)
            if typing.get_origin(annotation) is typing.Annotated:
                for meta in typing.get_args(annotation)[1:]:
                    if isinstance(meta, Depends):
                        depends = meta
        if depends is None:
            continue
        target = depends.dependency
        if target is None:
            target = hints.get(name, param.annotation)
        found[name] = target
    return found


def _check_target(fn: Callable[..., Any], target: Callable[..., Any]) -> None:
    if not _registry.is_singleton(target):
        raise UsageError(
            f"{fn!r} depends on {target!r} via Depends(), but {target!r} "
            "is not @singleton-wrapped. Singletons can only depend on "
            "other singletons, never on request-scoped data."
        )


def self_resolve_kwargs(fn: Callable[..., Any]) -> dict[str, Any]:
    """Sync resolution: raises if a dependency turns out to be async."""
    kwargs: dict[str, Any] = {}
    for name, target in depends_params(fn).items():
        _check_target(fn, target)
        result = target()
        if inspect.isawaitable(result):
            result.close()
            raise UsageError(
                f"{fn!r} depends on {target!r}, which is async. Resolve it "
                "from an async context instead - make this singleton's own "
                "provider `async def`, or rely on fastapi_singleton.lifespan "
                "for eager startup, rather than calling it directly."
            )
        kwargs[name] = result
    return kwargs


async def async_self_resolve_kwargs(fn: Callable[..., Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for name, target in depends_params(fn).items():
        _check_target(fn, target)
        result = target()
        if inspect.isawaitable(result):
            result = await result
        kwargs[name] = result
    return kwargs
