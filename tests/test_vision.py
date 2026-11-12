from types import SimpleNamespace

import pytest

from himari import vision


def test_text_only_vision_model_is_replaced_with_the_default():
    model, replaced = vision.resolve_vision_model(
        {"vision_model": "qwen3:8b", "chat_model": "qwen3:8b"}
    )

    assert model == vision.DEFAULT_VISION_MODEL
    assert replaced is True


def test_a_multimodal_model_is_kept():
    model, replaced = vision.resolve_vision_model(
        {"vision_model": "qwen2.5vl:3b", "chat_model": "qwen3:8b"}
    )

    assert model == "qwen2.5vl:3b"
    assert replaced is False


def test_an_unrelated_configured_model_falls_back():
    model, _ = vision.resolve_vision_model({"vision_model": "llama3:8b"})

    assert model == vision.DEFAULT_VISION_MODEL


def test_describe_images_sends_a_structured_prompt(monkeypatch):
    calls = {}

    class FakeLLM:
        def vision(self, images, prompt, model=None):
            calls["images"] = images
            calls["prompt"] = prompt
            calls["model"] = model
            return "A browser window shows an error dialog."

    monkeypatch.setattr(vision, "LLM", FakeLLM)
    monkeypatch.setattr(
        vision,
        "resolve_vision_model",
        lambda cfg=None: ("qwen2.5vl:3b", False),
    )

    text = vision.describe_images(
        [b"png-bytes"],
        question="What does the error mean?",
        context="Chrome — Settings",
    )

    assert text.startswith("A browser window")
    assert calls["images"] == ["cG5nLWJ5dGVz"]
    assert calls["model"] == "qwen2.5vl:3b"
    assert "What does the error mean?" in calls["prompt"]
    assert "Chrome — Settings" in calls["prompt"]
    assert "untrusted visual data" in calls["prompt"]


def test_missing_vision_model_gets_an_actionable_error(monkeypatch):
    class FakeLLM:
        def vision(self, *args, **kwargs):
            raise RuntimeError("model 'qwen2.5vl:3b' not found, try pulling it")

    monkeypatch.setattr(vision, "LLM", FakeLLM)
    monkeypatch.setattr(
        vision, "resolve_vision_model", lambda cfg=None: ("qwen2.5vl:3b", False)
    )

    with pytest.raises(vision.VisionError) as error:
        vision.describe_images([b"image"])

    assert "ollama pull qwen2.5vl:3b" in str(error.value)


def test_timeout_gets_a_retry_hint(monkeypatch):
    class FakeLLM:
        def vision(self, *args, **kwargs):
            raise RuntimeError("Read timed out after 300s")

    monkeypatch.setattr(vision, "LLM", FakeLLM)
    monkeypatch.setattr(
        vision, "resolve_vision_model", lambda cfg=None: ("qwen2.5vl:3b", False)
    )

    with pytest.raises(vision.VisionError) as error:
        vision.describe_images([b"image"])

    assert "Retry" in str(error.value)


def test_empty_vision_reply_is_an_error(monkeypatch):
    class FakeLLM:
        def vision(self, *args, **kwargs):
            return "   "

    monkeypatch.setattr(vision, "LLM", FakeLLM)
    monkeypatch.setattr(
        vision, "resolve_vision_model", lambda cfg=None: ("qwen2.5vl:3b", False)
    )

    with pytest.raises(vision.VisionError):
        vision.describe_images([b"image"])


def test_no_image_is_an_error():
    with pytest.raises(vision.VisionError):
        vision.describe_images([])


def test_vision_status_reports_a_missing_model(monkeypatch):
    monkeypatch.setattr(
        vision, "resolve_vision_model", lambda cfg=None: ("qwen2.5vl:3b", False)
    )
    monkeypatch.setattr(
        vision,
        "LLM",
        lambda: SimpleNamespace(
            model_status=lambda: (["qwen3:8b"], None)
        ),
    )

    ready, message = vision.vision_status()

    assert ready is False
    assert "ollama pull qwen2.5vl:3b" in message
