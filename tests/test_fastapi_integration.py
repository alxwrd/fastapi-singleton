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


def test_eager_creation_class_form_and_teardown_order():
    events = []

    @singleton
    def get_settings():
        events.append("settings-create")
        yield {"dsn": "x"}
        events.append("settings-teardown")

    @singleton
    class ConnectionPool:
        def __init__(self, settings: Annotated[dict, Depends(get_settings)]):
            self.settings = settings
            events.append("pool-init")

        def __call__(self):
            events.append("pool-pre-yield")
            yield self
            events.append("pool-post-yield")

    @ConnectionPool.before_start
    def before_start():
        events.append("hook:before_start")

    @ConnectionPool.after_end
    def after_end():
        events.append("hook:after_end")

    app = FastAPI(lifespan=lifespan)
    pool_dependency = Annotated[ConnectionPool, Depends(ConnectionPool())]

    @app.get("/id")
    def read_id(pool: pool_dependency):
        return {"id": id(pool)}

    with TestClient(app) as client:
        assert events == [
            "settings-create",
            "hook:before_start",
            "pool-init",
            "pool-pre-yield",
        ]
        r1 = client.get("/id")
        r2 = client.get("/id")
        assert r1.json() == r2.json()

    assert events == [
        "settings-create",
        "hook:before_start",
        "pool-init",
        "pool-pre-yield",
        "pool-post-yield",
        "hook:after_end",
        "settings-teardown",
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
