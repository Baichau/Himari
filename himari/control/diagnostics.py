"""Local diagnostics for the Control Center.

Checks are fail-soft: a broken check reports the error and never stops the
remaining checks. Network and Windows discovery are optional inputs so the
caller can keep diagnostics fast and off the UI thread.
"""

import importlib.util
import platform
import sys
import threading
from pathlib import Path

from .. import db
from ..config import APP_DIR, load
from .permissions_view import enabled_capabilities


def _check(name, func):
    try:
        ok, detail = func()
    except Exception as exc:
        return {"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    return {"name": name, "ok": bool(ok), "detail": str(detail)}


def _python_check():
    version = sys.version.split()[0]
    return sys.version_info >= (3, 10), version


CORE_SECTIONS = ("ollama", "voice", "permissions", "privacy", "ui")


def _config_check(config):
    def check():
        missing = [key for key in CORE_SECTIONS if key not in config]
        if missing:
            return False, "Missing sections: " + ", ".join(missing)
        return True, "All expected sections present."
    return check


def _database_check():
    def check():
        with db.conn() as connection:
            connection.execute("SELECT 1").fetchone()
        return True, str(APP_DIR / "himari.db")
    return check


def _ollama_check(model_status, config):
    def check():
        if not callable(model_status):
            return True, "Skipped (status not requested)."
        models, error = model_status()
        if error:
            return False, error
        model = config.get("ollama", {}).get("chat_model", "")
        if model not in models:
            return False, f"'{model}' is not installed. Run: ollama pull {model}"
        return True, f"{model} available."
    return check


def _playwright_check():
    def check():
        if importlib.util.find_spec("playwright") is None:
            return False, "playwright is not installed; browser automation is unavailable."
        return True, "playwright installed. Browser automation permission is separate."
    return check


def _avatar_check():
    def check():
        directory = APP_DIR / "avatar_assets"
        files = list(directory.glob("*.png")) if directory.is_dir() else []
        if not files:
            return True, "No avatar art installed; placeholder is shown."
        return True, f"{len(files)} PNG file(s) in {directory}"
    return check


def _windows_check():
    def check():
        from ..windows import installed_apps

        apps = installed_apps()
        return True, f"{len(apps)} installed apps discovered."
    return check


def _speech_check(config):
    def check():
        voice = config.get("voice", {})
        return True, (
            f"STT model '{voice.get('stt_model', 'unset')}', "
            f"TTS voice '{voice.get('tts_voice', 'unset')}'. "
            "Models load from local storage only."
        )
    return check


def _vision_check(model_status, config):
    def check():
        from ..vision import resolve_vision_model

        model, replaced = resolve_vision_model(config.get("ollama", {}))
        note = " (configured model was text-only)" if replaced else ""
        if not callable(model_status):
            return True, f"Vision model: {model}{note}."
        models, error = model_status()
        if error:
            return False, error
        families = {name.split(":")[0] for name in models or []}
        if model in models or model.split(":")[0] in families:
            return True, f"Vision model ready: {model}{note}."
        return False, f"Vision model missing. Run: ollama pull {model}"
    return check


def _image_server_check(config, probe=None):
    def check():
        from .. import imagegen

        base_url = str(
            config.get("imagegen", {}).get("base_url")
            or imagegen.DEFAULT_BASE_URL
        )
        runner = probe or imagegen.probe
        ready, message = runner(base_url)
        return ready, message
    return check


def _chat_engine_check(config):
    def check():
        engine = str(config.get("ui", {}).get("chat_engine", "web")).strip()
        assets = Path(__file__).resolve().parent.parent / "web_assets"
        if engine == "classic":
            return True, "Classic text view selected in Settings."
        if importlib.util.find_spec("PySide6.QtWebEngineWidgets") is None:
            return False, (
                "QtWebEngine is not installed, so Himari falls back to the "
                "classic chat view. Use the packaged build for math and diagrams."
            )
        missing = [
            name
            for name in (
                "katex/katex.min.js",
                "katex/katex.min.css",
                "mermaid.min.js",
                "himari-chat.js",
            )
            if not (assets / name).is_file()
        ]
        if missing:
            return False, "Bundled chat assets missing: " + ", ".join(missing)
        return True, "Rich chat view ready (Markdown, KaTeX, Mermaid)."
    return check


def run_diagnostics(
    config=None,
    model_status=None,
    include_windows=False,
    include_ollama=True,
    image_probe=None,
    include_image_server=True,
):
    config = load() if config is None else config
    checks = [
        _check("Python", _python_check),
        _check("Configuration", _config_check(config)),
        _check("Database", _database_check()),
        _check("Avatar assets", _avatar_check()),
        _check("Speech configuration", _speech_check(config)),
        _check("Chat rendering", _chat_engine_check(config)),
        _check("Playwright", _playwright_check()),
    ]
    if include_ollama:
        checks.append(_check("Ollama", _ollama_check(model_status, config)))
        checks.append(_check("Vision", _vision_check(model_status, config)))
    if include_image_server and isinstance(config.get("imagegen"), dict):
        checks.append(
            _check("Image generation", _image_server_check(config, image_probe))
        )
    if include_windows:
        checks.append(_check("Windows discovery", _windows_check()))
    checks.append(_check("Platform", lambda: (platform.system() == "Windows", platform.platform())))
    return checks


def diagnostics_async(on_done, **kwargs):
    """Run diagnostics in a worker thread; ``on_done(checks, error)``."""

    def work():
        try:
            on_done(run_diagnostics(**kwargs), None)
        except Exception as exc:
            on_done(None, exc)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread


def format_diagnostics(checks):
    if not checks:
        return "No diagnostics available."
    lines = []
    for item in checks:
        marker = "OK" if item["ok"] else "FAIL"
        lines.append(f"[{marker}] {item['name']}: {item['detail']}")
    return "\n".join(lines)


def summary(checks):
    return {
        "total": len(checks),
        "passed": sum(1 for item in checks if item["ok"]),
        "failed": sum(1 for item in checks if not item["ok"]),
    }
