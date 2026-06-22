"""Depends()-aware signature introspection and self-resolution.

Mirrors fastapi.dependencies.utils.analyze_param's two ways of finding a
Depends() marker on a parameter (bare default, or Annotated[...] metadata),
so @singleton-decorated callables can be resolved both by FastAPI itself
(during a real request) and by our own code (direct calls in plain Python,
and the eager lifespan startup walk).
"""

import inspect
import typing
from collections.abc import Callable
from typing import Any

from fastapi.params import Depends

from . import _registry


class UsageError(RuntimeError):
    """Raised when a singleton's dependency graph can't be resolved."""


def depends_params(fn: Callable[..., Any]) -> dict[str, Callable[..., Any]]:
    signature = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:
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
