from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fastapi_singleton import UsageError, lifespan, singleton


def test_eager_creation_function_form_and_shared_instance_across_requests():
    events = []

    @singleton
    def get_settings():
        events.append("settings")
        return {"dsn": "x"}

    @singleton
    def get_client(settings: Annotated[dict, Depends(get_settings)]):
        events.append("client")
        return {"settings": settings, "id": object()}

    app = FastAPI(lifespan=lifespan)

    @app.get("/id")
    def read_id(client: Annotated[dict, Depends(get_client)]):
        return {"id": id(client["id"])}

    with TestClient(app) as client:
        assert events == ["settings", "client"]  # eager, before any request
        r1 = client.get("/id")
        r2 = client.get("/id")
        assert r1.json() == r2.json()


def test_eager_creation_class_depending_on_async_pool_and_teardown_order():
    """A class singleton (sync, __init__-only) depending on an async,
    teardown-capable function singleton - the recommended composition for
    a connection pool: the class holds config, the function does the real
    (possibly async) resource setup and teardown."""
    events = []

    @singleton
    class Settings:
        def __init__(self):
            events.append("settings-init")
            self.dsn = "x"

    @singleton
    async def get_pool(settings: Annotated[Settings, Depends(Settings)]):
        events.append("pool-pre-yield")
        yield {"dsn": settings.dsn}
        events.append("pool-post-yield")

    @get_pool.before_start
    def before_start():
        events.append("hook:before_start")

    @get_pool.after_end
    def after_end():
        events.append("hook:after_end")

    app = FastAPI(lifespan=lifespan)
    pool_dependency = Annotated[dict, Depends(get_pool)]

    @app.get("/id")
    def read_id(pool: pool_dependency):
        return {"id": id(pool)}

    with TestClient(app) as client:
        assert events == [
            "settings-init",
            "hook:before_start",
            "pool-pre-yield",
        ]
        r1 = client.get("/id")
        r2 = client.get("/id")
        assert r1.json() == r2.json()

    assert events == [
        "settings-init",
        "hook:before_start",
        "pool-pre-yield",
        "pool-post-yield",
        "hook:after_end",
    ]


def test_singleton_depending_on_non_singleton_raises_usage_error():
    def get_request_scoped():
        return "request-data"

    @singleton
    def get_thing(value: Annotated[str, Depends(get_request_scoped)]):
        return value

    app = FastAPI(lifespan=lifespan)

    @app.get("/thing")
    def read_thing(thing: Annotated[str, Depends(get_thing)]):
        return {"thing": thing}

    with pytest.raises(UsageError):
        with TestClient(app):
            pass
