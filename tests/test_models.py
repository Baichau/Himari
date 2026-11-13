from unittest.mock import Mock

import pytest

from himari import models


@pytest.fixture(autouse=True)
def _clear_capability_cache():
    models.clear_cache()
    yield
    models.clear_cache()


def test_capabilities_are_read_and_cached():
    client = Mock()
    client.show.return_value = {
        "capabilities": ["completion", "tools", "thinking"],
    }

    first = models.model_capabilities("qwen3:8b", client=client)
    second = models.model_capabilities("qwen3:8b", client=client)

    assert first == frozenset({"completion", "tools", "thinking"})
    assert second is first
    assert client.show.call_count == 1


def test_supports_is_tri_state():
    client = Mock()
    client.show.return_value = {"capabilities": ["completion", "tools"]}

    assert models.supports("tools", "qwen3:8b", client=client) is True
    assert models.supports("vision", "qwen3:8b", client=client) is False

    broken = Mock()
    broken.show.side_effect = RuntimeError("ollama unavailable")
    assert models.supports("tools", "other:1b", client=broken) is None


def test_missing_capability_list_is_unknown():
    client = Mock()
    client.show.return_value = {"details": {"family": "qwen3"}}

    assert models.model_capabilities("qwen3:8b", client=client) is None


def test_capability_lookup_never_raises():
    client = Mock()
    client.show.side_effect = ConnectionError("down")

    assert models.model_capabilities("qwen3:8b", client=client) is None
