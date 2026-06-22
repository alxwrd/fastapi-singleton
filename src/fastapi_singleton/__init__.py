"""Application-scoped dependencies for FastAPI.

See README.md for the full guide. Public API:

    from fastapi_singleton import singleton, lifespan
"""

import inspect
from typing import Any

from ._class import make_class_singleton
from ._function import make_function_singleton
from ._lifespan import lifespan
from ._registry import reset
from ._signature import UsageError


def singleton(obj: Any) -> Any:
    if inspect.isclass(obj):
        return make_class_singleton(obj)
    return make_function_singleton(obj)


__all__ = [
    "singleton",
    "lifespan",
    "reset",
    "UsageError",
]
