from fastapi_singleton import _registry, singleton


def test_registering_a_singleton_adds_it_to_the_registry():
    before = len(_registry.all_singletons())

    @singleton
    def get_value():
        return object()

    assert len(_registry.all_singletons()) == before + 1
    assert get_value in _registry.all_singletons()


def test_creation_order_is_empty_until_first_creation():
    @singleton
    def get_value():
        return object()

    assert get_value not in _registry.creation_order()
    get_value()
    assert get_value in _registry.creation_order()


def test_reset_clears_registry_and_instance_state():
    @singleton
    def get_value():
        return object()

    value = get_value()
    _registry.reset()

    assert _registry.all_singletons() == ()
    assert _registry.creation_order() == ()
    assert get_value._created is False
    assert get_value() is not value


def test_is_singleton_recognizes_function_and_class_singletons():
    @singleton
    def get_value():
        return object()

    @singleton
    class Plain:
        def __init__(self):
            pass

    @singleton
    class WithCall:
        def __init__(self):
            pass

        def __call__(self):
            yield object()

    assert _registry.is_singleton(get_value)
    assert _registry.is_singleton(Plain)
    assert _registry.is_singleton(WithCall)
    assert not _registry.is_singleton(object())
