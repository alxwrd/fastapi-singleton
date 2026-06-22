"""Application-scoped dependencies for FastAPI.

See README.md for the full guide. Public API:

    from fastapi_singleton import singleton, lifespan
"""

import inspect
from typing import Any

from ._class import _ClassSingleton
from ._function import make_function_singleton
from ._lifespan import lifespan
from ._signature import UsageError


def singleton(obj: Any) -> Any:
    if inspect.isclass(obj):
        return _ClassSingleton(obj)
    return make_function_singleton(obj)


__all__ = ["singleton", "lifespan", "UsageError"]
