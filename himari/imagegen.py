"""Local image generation through an Automatic1111-compatible API.

Both stable-diffusion.cpp's ``sd-server`` and Automatic1111/Forge expose
``/sdapi/v1/txt2img``, so Himari can use either completely offline. Nothing is
sent to a hosted service, and generated files stay under the user's Himari
folder.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image

from . import imagegen_payload
from .config import load
from .paths import user_data_dir

log = logging.getLogger("himari.imagegen")

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
FALLBACK_BASE_URLS = ("http://127.0.0.1:7860",)
DEFAULT_NEGATIVE = "blurry, low quality, watermark, text, logo, deformed, extra limbs"
MAX_PROMPT_CHARS = 1200
MAX_IMAGES_PER_CALL = 2
DEFAULT_TIMEOUT = 600
START_WAIT_SECONDS = 180
_DATA_URI = re.compile(r"^data:image/[A-Za-z0-9.+-]+;base64,", re.I)
_SLUG = re.compile(r"[^a-z0-9]+")
_START_LOCK = threading.Lock()
_STARTED = False


class ImageGenError(RuntimeError):
    pass


def _settings():
    cfg = load().get("imagegen") or {}
    return cfg if isinstance(cfg, dict) else {}


def _clamp_dimension(value, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = int(default)
    number = max(256, min(1024, number))
    return number - (number % 8)


def _decode_images(payload):
    images = payload.get("images") if isinstance(payload, dict) else None
    if not isinstance(images, list) or not images:
        raise ImageGenError(
            "The image server returned no images. Check its log for a model "
            "loading or VRAM error."
        )
    decoded = []
    for raw in images[:MAX_IMAGES_PER_CALL]:
        if not isinstance(raw, str) or not raw.strip():
            continue
        data = _DATA_URI.sub("", raw.strip())
        try:
            binary = base64.b64decode(data, validate=False)
            with Image.open(io.BytesIO(binary)) as image:
                image.verify()
        except Exception as exc:
            raise ImageGenError("The image server returned unreadable image data.") from exc
        decoded.append(binary)
    if not decoded:
        raise ImageGenError("The image server returned no usable images.")
    return decoded


def _candidates():
    configured = str(_settings().get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    values = [configured, DEFAULT_BASE_URL, *FALLBACK_BASE_URLS]
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _output_dir():
    directory = user_data_dir() / "generated"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _slug(text):
    value = _SLUG.sub("-", str(text or "").casefold()).strip("-")
    return (value or "image")[:40]


def _save_images(images, prompt):
    directory = _output_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    paths = []
    for index, binary in enumerate(images, start=1):
        suffix = f"-{index}" if len(images) > 1 else ""
        path = directory / f"{stamp}-{_slug(prompt)}{suffix}.png"
        try:
            path.write_bytes(binary)
        except OSError as exc:
            raise ImageGenError(f"Could not save the generated image: {exc}") from exc
        paths.append(path)
    return paths


def probe(base_url=None):
    """Return (available, message) without generating anything."""
    candidates = [base_url.rstrip("/")] if base_url else _candidates()
    last_error = ""
    for candidate in candidates:
        try:
            response = httpx.get(
                f"{candidate}/sdapi/v1/options", timeout=6.0, trust_env=False
            )
            if response.status_code == 200:
                return True, f"Image server ready at {candidate}"
            last_error = f"HTTP {response.status_code}"
        except Exception as exc:
            last_error = str(exc)
    return False, (
        "No local image server answered. The portable app starts its bundled "
        "sd-server on the first image request; Automatic1111/Forge on port "
        f"7860 also works. Last error: {last_error}"
    )


def managed_server_paths():
    root = user_data_dir() / "imagegen"
    name = "sd-server.exe" if sys.platform == "win32" else "sd-server"
    return root / "server" / name, root / "models"


def _managed_model(models_dir):
    if not models_dir.is_dir():
        return None
    models = sorted(models_dir.glob("*.gguf"))
    if not models:
        return None
    for token in ("q8_0", "q8", "q6", "q5", "q4"):
        for model in models:
            if token in model.name.casefold():
                return model
    return models[0]


def _ensure_managed_assets(exe, models_dir):
    """Unpack the engine embedded in the packaged EXE on first use."""
    if exe.is_file() and _managed_model(models_dir) is not None:
        return True
    location = imagegen_payload.locate()
    if location is None:
        return False
    try:
        written = imagegen_payload.extract(user_data_dir() / "imagegen")
    except (imagegen_payload.PayloadError, OSError, zipfile.BadZipFile) as exc:
        log.warning("Could not unpack the bundled image engine: %s", exc)
        return False
    log.info("Unpacked %d bundled image engine file(s)", len(written))
    return exe.is_file() and _managed_model(models_dir) is not None


def _start_managed_server():
    global _STARTED
    with _START_LOCK:
        if _STARTED:
            return False
        exe, models_dir = managed_server_paths()
        if not _ensure_managed_assets(exe, models_dir):
            return False
        model = _managed_model(models_dir)
        if not exe.is_file() or model is None:
            return False
        log_path = user_data_dir() / "logs" / "sd-server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        command = [
            str(exe),
            "-m", str(model),
            "--model-dir", str(models_dir),
            "--listen-ip", "127.0.0.1",
            "--listen-port", "8080",
            "--vae-tiling",
        ]
        try:
            with open(log_path, "ab") as output:
                subprocess.Popen(
                    command,
                    cwd=str(exe.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                    close_fds=True,
                )
        except OSError as exc:
            log.warning("Could not start the local image server: %s", exc)
            return False
        _STARTED = True
        log.info("Started the local image server with model %s", model.name)
        return True


def _wait_for_server(timeout=START_WAIT_SECONDS):
    deadline = time.monotonic() + timeout
    while True:
        available, _ = probe()
        if available:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1.5)


def _auto_start():
    if not _settings().get("auto_start", False):
        return False
    if probe()[0]:
        return False
    if not _start_managed_server():
        return False
    return _wait_for_server()


def _release_ollama_vram():
    """Free GPU memory held by the chat model before Stable Diffusion runs."""
    cfg = load().get("ollama") or {}
    host = str(cfg.get("host") or "http://127.0.0.1:11434").rstrip("/")
    wanted = {
        str(name)
        for name in (cfg.get("chat_model"), cfg.get("vision_model"))
        if name
    }
    if not wanted:
        return []
    try:
        response = httpx.get(f"{host}/api/ps", timeout=5.0, trust_env=False)
        if response.status_code != 200:
            return []
        running = response.json().get("models", [])
    except Exception as exc:
        log.debug("Could not list loaded Ollama models: %s", exc)
        return []
    released = []
    for entry in running if isinstance(running, list) else []:
        name = str((entry or {}).get("model") or (entry or {}).get("name") or "")
        if name not in wanted:
            continue
        try:
            httpx.post(
                f"{host}/api/generate",
                json={"model": name, "keep_alive": 0},
                timeout=30.0,
                trust_env=False,
            )
        except Exception as exc:
            log.debug("Could not unload Ollama model %s: %s", name, exc)
            continue
        log.info("Released Ollama model %s before image generation", name)
        released.append(name)
    return released


def generate(
    prompt,
    negative_prompt=None,
    width=None,
    height=None,
    steps=None,
    seed=-1,
    batch=1,
):
    """Generate images locally and return their saved paths."""
    if not load().get("permissions", {}).get("allow_image_generation", True):
        raise ImageGenError(
            "Image generation is disabled in Settings."
        )
    prompt = str(prompt or "").strip()[:MAX_PROMPT_CHARS]
    if not prompt:
        raise ImageGenError("A prompt is required to generate an image.")
    settings = _settings()
    width = _clamp_dimension(width or settings.get("width", 768), 768)
    height = _clamp_dimension(height or settings.get("height", 768), 768)
    try:
        steps = int(steps if steps is not None else settings.get("steps", 28))
    except (TypeError, ValueError):
        steps = 28
    steps = max(4, min(60, steps))
    try:
        batch = max(1, min(MAX_IMAGES_PER_CALL, int(batch)))
    except (TypeError, ValueError):
        batch = 1
    negative = str(
        negative_prompt
        if negative_prompt is not None
        else settings.get("negative_prompt", DEFAULT_NEGATIVE)
    )[:MAX_PROMPT_CHARS]
    payload = {
        "prompt": prompt,
        "negative_prompt": negative,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": float(settings.get("cfg_scale", 7.0)),
        "sampler_name": str(settings.get("sampler", "Euler a")),
        "batch_size": batch,
        "n_iter": 1,
        "seed": int(seed) if isinstance(seed, int) else -1,
    }
    timeout = float(settings.get("timeout_seconds", DEFAULT_TIMEOUT))
    if settings.get("free_ollama_vram", False):
        _release_ollama_vram()
    if _auto_start():
        log.info("Local image server is ready")
    last_error = None
    for base_url in _candidates():
        try:
            response = httpx.post(
                f"{base_url}/sdapi/v1/txt2img",
                json=payload,
                timeout=timeout,
                trust_env=False,
            )
        except Exception as exc:
            last_error = exc
            continue
        if response.status_code == 404:
            last_error = ImageGenError(
                f"{base_url} does not expose the txt2img API. Use "
                "stable-diffusion.cpp's sd-server or Automatic1111/Forge."
            )
            continue
        if response.status_code >= 400:
            detail = response.text[:300].strip()
            last_error = ImageGenError(
                f"The image server returned HTTP {response.status_code}: {detail}"
            )
            continue
        try:
            data = response.json()
            images = _decode_images(data)
            paths = _save_images(images, prompt)
        except ImageGenError as exc:
            last_error = exc
            continue
        except ValueError as exc:
            last_error = ImageGenError(
                f"The image server returned invalid JSON: {exc}"
            )
            continue
        log.info("Generated %d image(s) at %dx%d", len(paths), width, height)
        return paths
    message = str(last_error or "No local image server answered.")
    raise ImageGenError(
        "Could not generate an image locally. The image server may still be "
        "loading or unreachable; check the server URL in Settings and the "
        f"sd-server log. Details: {message}"
    )


def _prompt_with_style(prompt, style):
    text = str(prompt or "").strip()
    value = str(style or "").strip()
    if value and value.casefold() not in text.casefold():
        text = f"{text}, {value}" if text else value
    return text


def generate_image_tool(
    prompt,
    negative_prompt=None,
    width=None,
    height=None,
    steps=None,
    style=None,
    seed=None,
    batch_size=None,
    **extra,
):
    if extra:
        log.debug(
            "Ignoring unsupported generate_image arguments: %s",
            ", ".join(sorted(extra)),
        )
    prompt = _prompt_with_style(prompt, style)
    try:
        paths = generate(
            prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            seed=seed if isinstance(seed, int) else -1,
            batch=batch_size if isinstance(batch_size, int) else 1,
        )
    except ImageGenError as exc:
        return f"Image generation is unavailable: {exc}"
    lines = [f"Generated {len(paths)} image(s) locally."]
    lines.extend(f"IMAGE_PATH:{path}" for path in paths)
    lines.append(f"Prompt: {str(prompt)[:300]}")
    return "\n".join(lines)
