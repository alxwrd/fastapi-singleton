"""The `lifespan` async context manager: eager startup, reverse-order
teardown.

No explicit topological sort is needed: calling every registered singleton
once is enough, because self-resolution (see _signature.py) recursively
constructs a singleton's own dependencies before it finishes constructing
itself. Each singleton's `_created` timestamp is therefore set in a valid
dependency order (deps before dependents) for free, and sorting by it -
see registry.creation_order() - then reversing is a valid teardown order,
exactly like unwinding a stack of context managers.
"""

import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from . import _registry


@asynccontextmanager
async def lifespan(app: Any) -> AsyncIterator[None]:
    for singleton in _registry.all_singletons():
        if singleton._created:
            continue
        result = singleton()
        if inspect.isawaitable(result):
            await result
    try:
        yield
    finally:
        for singleton in reversed(_registry.creation_order()):
            result = singleton.teardown()
            if inspect.isawaitable(result):
                await result
