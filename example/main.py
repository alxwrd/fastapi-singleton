"""Run with:

    uv run uvicorn example.main:app --reload

Watch the console: the connection pool is opened once, before the server
accepts its first request, and closed once, on shutdown - not per request.
"""

import logging
from typing import Annotated

from fastapi import Depends, FastAPI

from fastapi_singleton import lifespan, singleton

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("example")


@singleton
class Settings:
    def __init__(self) -> None:
        self.dsn = "postgresql://localhost/example"


class Pool:
    """Stands in for something like an asyncpg.Pool."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def fetch_user(self, user_id: int) -> dict:
        return {"id": user_id, "fetched_with": self.dsn}

    async def close(self) -> None:
        pass


@singleton
async def get_pool(settings: Annotated[Settings, Depends(Settings)]):
    pool = Pool(dsn=settings.dsn)  # stands in for `await asyncpg.create_pool(...)`
    yield pool
    await pool.close()


@get_pool.before_start
def log_pool_starting():
    logger.info("opening connection pool")


@get_pool.after_end
def log_pool_closed():
    logger.info("connection pool closed")


app = FastAPI(lifespan=lifespan)

PoolDependency = Annotated[Pool, Depends(get_pool)]


@app.get("/users/{user_id}")
def read_user(pool: PoolDependency, user_id: int):
    return pool.fetch_user(user_id)


@app.get("/pool-identity")
def read_pool_identity(pool: PoolDependency):
    """Hit this twice and compare - the id() is identical across requests,
    proving the pool is shared, not recreated per request."""
    return {"id": id(pool)}
