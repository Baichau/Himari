import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from himari import imagegen


def _png_bytes(size=(32, 32), color=(220, 120, 160)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _config(**overrides):
    config = {
        "permissions": {"allow_image_generation": True},
        "imagegen": {
            "base_url": "http://127.0.0.1:8080",
            "timeout_seconds": 30,
            "steps": 20,
            "width": 512,
            "height": 512,
            "cfg_scale": 7.0,
            "sampler": "Euler a",
            "negative_prompt": "blurry",
        },
    }
    for key, value in overrides.items():
        config[key] = value
    return config


def test_dimensions_are_clamped_to_a_supported_range():
    assert imagegen._clamp_dimension(100, 512) == 256
    assert imagegen._clamp_dimension(9000, 512) == 1024
    assert imagegen._clamp_dimension(513, 512) == 512
    assert imagegen._clamp_dimension("bad", 768) == 768


def test_generate_saves_returned_images(monkeypatch, tmp_path):
    payload = {"images": [base64.b64encode(_png_bytes()).decode("ascii")]}
    calls = {}

    def fake_post(url, json, timeout, trust_env):
        calls["url"] = url
        calls["json"] = json
        calls["timeout"] = timeout
        calls["trust_env"] = trust_env
        return SimpleNamespace(status_code=200, json=lambda: payload, text="")

    monkeypatch.setattr(imagegen, "load", lambda: _config())
    monkeypatch.setattr(imagegen, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(imagegen.httpx, "post", fake_post)

    paths = imagegen.generate("a rainy Tokyo street", width=400, height=300, steps=99)

    assert len(paths) == 1
    assert paths[0].is_file()
    assert paths[0].parent == tmp_path / "generated"
    assert "rainy-tokyo-street" in paths[0].name
    assert calls["url"].endswith("/sdapi/v1/txt2img")
    assert calls["json"]["width"] == 400
    assert calls["json"]["height"] == 296
    assert calls["json"]["steps"] == 60
    assert calls["json"]["negative_prompt"] == "blurry"
    assert calls["trust_env"] is False


def test_data_uri_images_are_decoded(monkeypatch, tmp_path):
    encoded = base64.b64encode(_png_bytes()).decode("ascii")
    payload = {"images": [f"data:image/png;base64,{encoded}"]}

    monkeypatch.setattr(imagegen, "load", lambda: _config())
    monkeypatch.setattr(imagegen, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        imagegen.httpx,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200, json=lambda: payload, text=""
        ),
    )

    paths = imagegen.generate("a cat")

    assert paths and paths[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_generation_respects_the_permission_setting(monkeypatch):
    monkeypatch.setattr(
        imagegen,
        "load",
        lambda: {"permissions": {"allow_image_generation": False}, "imagegen": {}},
    )

    with pytest.raises(imagegen.ImageGenError) as error:
        imagegen.generate("anything")

    assert "disabled in Settings" in str(error.value)


def test_blank_prompt_is_rejected(monkeypatch):
    monkeypatch.setattr(imagegen, "load", lambda: _config())

    with pytest.raises(imagegen.ImageGenError) as error:
        imagegen.generate("   ")

    assert "prompt is required" in str(error.value)


def test_missing_txt2img_endpoint_explains_the_server(monkeypatch):
    monkeypatch.setattr(imagegen, "load", lambda: _config())
    monkeypatch.setattr(
        imagegen.httpx,
        "post",
        lambda *args, **kwargs: SimpleNamespace(status_code=404, text="", json=dict),
    )

    with pytest.raises(imagegen.ImageGenError) as error:
        imagegen.generate("a cat")

    assert "txt2img" in str(error.value)


def test_invalid_json_is_reported_clearly(monkeypatch):
    def invalid():
        raise ValueError("Expecting value")

    monkeypatch.setattr(imagegen, "load", lambda: _config())
    monkeypatch.setattr(
        imagegen.httpx,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200, json=invalid, text=""
        ),
    )

    with pytest.raises(imagegen.ImageGenError) as error:
        imagegen.generate("a cat")

    assert "invalid JSON" in str(error.value)


def test_probe_reports_a_running_server(monkeypatch):
    monkeypatch.setattr(
        imagegen.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200),
    )

    ready, message = imagegen.probe("http://127.0.0.1:8080/")

    assert ready is True
    assert "http://127.0.0.1:8080" in message


def test_probe_reports_no_server(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(imagegen.httpx, "get", refuse)

    ready, message = imagegen.probe("http://127.0.0.1:8080")

    assert ready is False
    assert "sd-server" in message


def test_tool_result_lists_saved_image_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        imagegen, "generate", lambda *args, **kwargs: [tmp_path / "one.png"]
    )

    result = imagegen.generate_image_tool("a lighthouse", width=512)

    assert result.startswith("Generated 1 image(s) locally.")
    assert f"IMAGE_PATH:{tmp_path / 'one.png'}" in result
    assert "a lighthouse" in result


def test_tool_result_explains_failures(monkeypatch):
    def fail(*args, **kwargs):
        raise imagegen.ImageGenError("server offline")

    monkeypatch.setattr(imagegen, "generate", fail)

    result = imagegen.generate_image_tool("a lighthouse")

    assert result.startswith("Image generation is unavailable: server offline")


def test_tool_folds_style_and_ignores_unknown_arguments(monkeypatch, tmp_path):
    calls = {}

    def fake_generate(prompt, **kwargs):
        calls["prompt"] = prompt
        calls.update(kwargs)
        return [tmp_path / "one.png"]

    monkeypatch.setattr(imagegen, "generate", fake_generate)

    result = imagegen.generate_image_tool(
        "GTA 6 city", style="neon cinematic", aspect_ratio="16:9", quality="high"
    )

    assert "IMAGE_PATH" in result
    assert calls["prompt"] == "GTA 6 city, neon cinematic"


def test_unknown_arguments_never_raise_a_type_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        imagegen, "generate", lambda *args, **kwargs: [tmp_path / "one.png"]
    )

    result = imagegen.generate_image_tool("a chair", style="", palette="warm")

    assert result.startswith("Generated 1 image(s) locally.")


def test_ollama_models_are_released_before_image_generation(monkeypatch):
    config = _config()
    config["ollama"] = {
        "host": "http://127.0.0.1:11434",
        "chat_model": "qwen3:8b",
        "vision_model": "qwen2.5vl:3b",
    }
    posts = []

    monkeypatch.setattr(imagegen, "load", lambda: config)
    monkeypatch.setattr(
        imagegen.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            json=lambda: {
                "models": [
                    {"model": "qwen3:8b"},
                    {"model": "qwen2.5vl:3b"},
                    {"model": "other:1b"},
                ]
            },
        ),
    )
    monkeypatch.setattr(
        imagegen.httpx,
        "post",
        lambda url, json, timeout, trust_env: posts.append((url, json)),
    )

    released = imagegen._release_ollama_vram()

    assert released == ["qwen3:8b", "qwen2.5vl:3b"]
    assert posts == [
        ("http://127.0.0.1:11434/api/generate", {"model": "qwen3:8b", "keep_alive": 0}),
        ("http://127.0.0.1:11434/api/generate", {"model": "qwen2.5vl:3b", "keep_alive": 0}),
    ]


def test_ollama_release_is_quiet_when_nothing_is_loaded(monkeypatch):
    config = _config()
    config["ollama"] = {"host": "http://127.0.0.1:11434", "chat_model": "qwen3:8b"}
    posts = []

    monkeypatch.setattr(imagegen, "load", lambda: config)
    monkeypatch.setattr(
        imagegen.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200, json=lambda: {"models": []}
        ),
    )
    monkeypatch.setattr(
        imagegen.httpx,
        "post",
        lambda *args, **kwargs: posts.append(args),
    )

    assert imagegen._release_ollama_vram() == []
    assert posts == []


def test_ollama_release_never_breaks_generation(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("ollama is offline")

    monkeypatch.setattr(imagegen.httpx, "get", refuse)

    assert imagegen._release_ollama_vram() == []


def test_bundled_engine_is_unpacked_before_the_server_starts(monkeypatch, tmp_path):
    monkeypatch.setattr(imagegen, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(imagegen, "_STARTED", False)
    monkeypatch.setattr(
        imagegen.imagegen_payload, "locate", lambda *args: (1, 1)
    )
    extracted = {}

    def fake_extract(root):
        extracted["root"] = root
        exe = root / "server" / "sd-server.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"bin")
        model = root / "models" / "stable-diffusion-v1-5-Q8_0.gguf"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"weights")
        return [exe, model]

    monkeypatch.setattr(imagegen.imagegen_payload, "extract", fake_extract)
    monkeypatch.setattr(
        imagegen.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace()
    )

    assert imagegen._start_managed_server() is True
    assert extracted["root"] == tmp_path / "imagegen"
    assert (tmp_path / "imagegen" / "server" / "sd-server.exe").is_file()


def test_managed_server_launch_uses_the_installed_model(monkeypatch, tmp_path):
    monkeypatch.setattr(imagegen, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(imagegen, "_STARTED", False)
    exe = tmp_path / "imagegen" / "server" / "sd-server.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"bin")
    model = tmp_path / "imagegen" / "models" / "stable-diffusion-v1-5-Q8_0.gguf"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"weights")
    launched = {}

    def fake_popen(command, **kwargs):
        launched["command"] = command
        launched["kwargs"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr(imagegen.subprocess, "Popen", fake_popen)

    assert imagegen._start_managed_server() is True
    assert imagegen._start_managed_server() is False
    assert launched["command"][0] == str(exe)
    assert str(model) in launched["command"]
    assert "8080" in launched["command"]
    assert "--vae-tiling" in launched["command"]
    assert launched["kwargs"]["cwd"] == str(exe.parent)
    assert (tmp_path / "logs" / "sd-server.log").is_file()


def test_managed_server_requires_an_installed_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(imagegen, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(imagegen, "_STARTED", False)

    assert imagegen._start_managed_server() is False


def test_auto_start_is_off_without_the_setting(monkeypatch):
    monkeypatch.setattr(imagegen, "_settings", lambda: {})
    monkeypatch.setattr(imagegen, "probe", lambda: (False, "down"))
    started = []
    monkeypatch.setattr(
        imagegen, "_start_managed_server", lambda: started.append(True)
    )

    assert imagegen._auto_start() is False
    assert started == []


def test_auto_start_does_not_duplicate_a_running_server(monkeypatch):
    monkeypatch.setattr(imagegen, "_settings", lambda: {"auto_start": True})
    monkeypatch.setattr(imagegen, "probe", lambda: (True, "ready"))
    started = []
    monkeypatch.setattr(
        imagegen, "_start_managed_server", lambda: started.append(True)
    )

    assert imagegen._auto_start() is False
    assert started == []


def test_auto_start_waits_for_the_new_server(monkeypatch):
    monkeypatch.setattr(imagegen, "_settings", lambda: {"auto_start": True})
    monkeypatch.setattr(imagegen, "probe", lambda: (False, "down"))
    monkeypatch.setattr(imagegen, "_start_managed_server", lambda: True)
    monkeypatch.setattr(imagegen, "_wait_for_server", lambda: True)

    assert imagegen._auto_start() is True
