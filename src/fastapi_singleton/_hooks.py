"""before_start/before_end/after_end lifecycle hooks.

Hooks run in registration order. A hook may be sync or async, but firing an
async hook requires an await-capable path (an async provider, or the
lifespan context manager) - firing one from a purely sync path raises a
clear error rather than silently dropping it or blocking on the coroutine.
"""

import inspect
from collections.abc import Callable
from typing import Any


class AsyncHookError(RuntimeError):
    """Raised when an async hook fires on a purely sync lifecycle path."""


class HookRegistry:
    def __init__(self) -> None:
        self.before_start: list[Callable[[], Any]] = []
        self.before_end: list[Callable[[], Any]] = []
        self.after_end: list[Callable[[], Any]] = []


def run_sync(hooks: list[Callable[[], Any]]) -> None:
    for hook in hooks:
        result = hook()
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if close is not None:
                close()
            raise AsyncHookError(
                f"{hook!r} is an async hook but fired on a sync singleton "
                "lifecycle path. Use fastapi_singleton.lifespan, or make "
                "the singleton's provider async, to run async hooks."
            )


async def run_async(hooks: list[Callable[[], Any]]) -> None:
    for hook in hooks:
        result = hook()
        if inspect.isawaitable(result):
            await result
