import pytest

from fastapi_singleton import singleton
from fastapi_singleton._hooks import AsyncHookError


def test_before_start_hooks_run_in_registration_order_before_creation():
    events = []

    @singleton
    def get_value():
        events.append("create")
        return "value"

    @get_value.before_start
    def hook_one():
        events.append("hook-1")

    @get_value.before_start
    def hook_two():
        events.append("hook-2")

    get_value()
    assert events == ["hook-1", "hook-2", "create"]


def test_hooks_fire_exactly_once_not_per_call():
    events = []

    @singleton
    def get_value():
        return "value"

    @get_value.before_start
    def hook():
        events.append("hook")

    get_value()
    get_value()
    get_value()
    assert events == ["hook"]


def test_before_end_and_after_end_run_around_teardown():
    events = []

    @singleton
    def get_value():
        yield "value"
        events.append("teardown")

    @get_value.before_end
    def before():
        events.append("before-end")

    @get_value.after_end
    def after():
        events.append("after-end")

    get_value()
    get_value.teardown()
    assert events == ["before-end", "teardown", "after-end"]


def test_sync_hook_path_rejects_async_hooks():
    @singleton
    def get_value():
        return "value"

    @get_value.before_start
    async def async_hook():
        pass

    with pytest.raises(AsyncHookError):
        get_value()


@pytest.mark.asyncio
async def test_async_singleton_supports_async_hooks():
    events = []

    @singleton
    async def get_value():
        events.append("create")
        return "value"

    @get_value.before_start
    async def hook():
        events.append("hook")

    await get_value()
    assert events == ["hook", "create"]


def test_class_singleton_hooks_attach_to_the_wrapper():
    events = []

    @singleton
    class Thing:
        def __init__(self):
            pass

    @Thing.before_start
    def hook():
        events.append("hook")

    Thing()
    assert events == ["hook"]


def test_before_end_hook_failure_still_runs_teardown_and_after_end():
    events = []

    @singleton
    def get_value():
        yield "value"
        events.append("provider-teardown")

    @get_value.before_end
    def boom():
        raise RuntimeError("boom")

    @get_value.after_end
    def after():
        events.append("after-end")

    get_value()
    with pytest.raises(RuntimeError):
        get_value.teardown()

    assert events == ["provider-teardown", "after-end"]
