<div align="center">
    <h1><code>fastapi-singleton</code></h1>
    <p align="center"><i>
        Application-scoped dependencies for <code>fastapi</code>
    </i></p>
    <img width="256px" src=".github/assets/three-card-trickster-768.png">
    <div align="center">
        <a href="https://github.com/alxwrd/fastapi-singleton/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/alxwrd/fastapi-singleton/test.yml?branch=main&label=main"></a>
        <a href="https://pypi.python.org/pypi/fastapi-singleton"><img src="https://img.shields.io/pypi/v/fastapi-singleton.svg"></a>
        <a href="https://github.com/alxwrd/fastapi-singleton/blob/main/LICENCE"><img src="https://img.shields.io/pypi/l/fastapi-singleton.svg?"></a>
    </div>

Every dependency resolved through FastAPI's `Depends` is request-scoped:
created on each request and discarded once the response is sent. That's the
right default for most things, but it's the wrong default for connection
pools, HTTP clients, and anything else that's expensive to create and safe to
share.

`fastapi-singleton` gives you a `@singleton` decorator that turns any
dependency, function or class, into one shared instance per process, with
proper startup and shutdown hooks wired into FastAPI's `lifespan`, instead of
leaving it to whatever a `SIGTERM` does to a `@lru_cache`d object.
</div>

## Example

```python
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi_singleton import singleton, lifespan


@singleton
class Settings:
    def __init__(self):
        self.dsn = "postgresql://localhost/app"


@singleton
async def get_pool(settings: Annotated[Settings, Depends(Settings)]):
    pool = await create_pool(settings.dsn)
    yield pool
    await pool.close()


@get_pool.before_start
def log_pool_starting():
    logger.info("opening connection pool")


@get_pool.after_end
def log_pool_closed():
    logger.info("connection pool closed")


app = FastAPI(lifespan=lifespan)


@app.get("/users/{user_id}")
def read_user(pool: Annotated[Pool, Depends(get_pool)], user_id: int):
    return pool.fetch_user(user_id)
```

```plain
$ uvicorn app:app

INFO:     opening connection pool
INFO:     Application startup complete.
...
INFO:     Shutting down
INFO:     connection pool closed
INFO:     Application shutdown complete.
```

## Installation

```shell
uv add fastapi-singleton
```

## Defining a singleton

`@singleton` wraps a function or a class so that it's only ever called once
per process; every dependant that resolves it via `Depends` receives the
exact same instance, the same guarantee `@lru_cache(maxsize=1)` gives you,
but tracked in a registry so its lifecycle can be managed instead of left to
the garbage collector.

```python
@singleton
def get_other():
    return Other()
```

Singletons can depend on other singletons the same way any FastAPI
dependency does, by declaring them with `Depends` in the constructor or
function signature:

```python
@singleton
class Connection:
    def __init__(self, other: Annotated[Other, Depends(get_other)]):
        self.other = other
```

A class singleton's `__init__` is the constructor, plain and simple -
`Depends(Connection)` calls it exactly once, the same way any FastAPI
class-based dependency works. `__init__` can never be `async def` in
Python, so a class singleton can't do real async setup itself - if you need
that (an async connection pool, an `await`-based client, anything with
teardown), write it as a function singleton instead and have your class
depend on it, the same way `Connection` depends on `get_other` above.

A singleton can't depend on a regular, request-scoped dependency - there's
no request to resolve it from when the singleton is constructed eagerly at
startup, or directly in plain Python. `@singleton`-ing something that
depends on non-singleton `Depends(...)` raises an error rather than silently
resolving it once and reusing stale data on every later request.

A singleton is also constructed exactly once: calling it again with the
same arguments it was first constructed with is a no-op (this is what lets
FastAPI re-resolve a singleton's own `Depends`-declared dependencies on
every request without recreating anything), but calling it again with
genuinely different arguments raises rather than silently ignoring them.

## Teardown with generators

If a singleton needs to release what it acquired, write it as a generator,
exactly like a request-scoped `yield` dependency in FastAPI. The code before
`yield` runs once, on creation; the code after `yield` runs once, on
shutdown.

```python
@singleton
def get_other():
    other = Other()
    yield other
    other.close()
```

## Lifecycle hooks

Sometimes the setup or teardown you need isn't part of constructing the
resource itself, things like metrics, logging, or cache warming. Each
singleton exposes hooks you can register without touching its body:

```python
@Connection.before_start
def before_start():
    ...  # runs immediately before Connection is constructed


@get_other.before_end
def before_end():
    ...  # runs immediately before get_other's teardown executes


@get_other.after_end
def after_end():
    ...  # runs immediately after get_other's teardown completes
```

| Hook | Runs |
|---|---|
| `before_start` | Immediately before the singleton is constructed |
| `before_end` | Immediately before the singleton's teardown executes |
| `after_end` | Immediately after the singleton's teardown completes |

A singleton can register any number of hooks for each event; they run in
registration order.

## Wiring up the lifespan

Singletons are created lazily by default, on first resolution, the same as
`@lru_cache`. To get deterministic startup and shutdown instead, pass
`fastapi_singleton.lifespan` to your `FastAPI` app:

```python
from fastapi_singleton import lifespan

app = FastAPI(lifespan=lifespan)
```

On startup, every registered singleton is constructed eagerly, in dependency
order, so a connection pool is open and ready before the app accepts its
first request. On shutdown, each singleton is torn down in reverse order,
running any `before_end` hooks, its own post-`yield` teardown, then any
`after_end` hooks, like a stack of context managers being unwound.

If you already have a `lifespan` of your own, compose them:

```python
from contextlib import asynccontextmanager

from fastapi_singleton import lifespan as singleton_lifespan


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with singleton_lifespan(app):
        # your own startup
        yield
        # your own shutdown


app = FastAPI(lifespan=lifespan)
```

Without the lifespan wired up, singletons still work, lazily, on first call,
like a plain `@lru_cache`, but nothing guarantees their teardown code runs;
register the lifespan whenever a singleton's cleanup actually matters.

## One process, one app

Singletons live in a process-global registry, the same way `@lru_cache`d
state does. That makes `fastapi-singleton` a fit for one `FastAPI` app per
process; running two `FastAPI(lifespan=lifespan)` apps side by side in the
same process means they'd share singleton state, including teardown. If
you're testing code that uses singletons, reset the registry between tests:

```python
from fastapi_singleton import reset


@pytest.fixture(autouse=True)
def reset_singletons():
    reset()
```
