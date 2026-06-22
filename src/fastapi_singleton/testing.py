"""Test-only helpers. Not part of the main public API.

`fastapi_singleton`'s registry is process-global (one app per process, by
design - matching @lru_cache(maxsize=1) semantics). Tests that create
singletons need a way to reset that global state between test functions.
"""

from ._registry import reset

__all__ = ["reset"]
