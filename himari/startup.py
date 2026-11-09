import importlib
import logging
import sys

log = logging.getLogger("himari.startup")

_REQUIRED_MODULES = (
    "PySide6",
    "ollama",
    "faster_whisper",
    "piper",
    "sounddevice",
    "numpy",
    "mss",
    "PIL",
    "keyboard",
    "winrt.windows.graphics.imaging",
    "winrt.windows.media.ocr",
    "winrt.windows.storage.streams",
)


def _verify_python_modules():
    missing = []
    for module_name in _REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            missing.append(f"{module_name}: {exc}")
    if missing:
        raise RuntimeError(
            "Required runtime dependencies could not be loaded:\n"
            + "\n".join(missing)
        )


def _verify_speech_assets():
    from .config import load
    from .voice import TTS, _preferred_stt_model

    model_path = None
    try:
        model_path = _preferred_stt_model()
        log.info("Local speech recognition model: %s", model_path)
    except Exception as exc:
        log.warning("Speech recognition is unavailable: %s", exc)

    voice = load()["voice"].get("tts_voice", "en_US-amy-medium")
    available = TTS().available_voices()
    if available:
        log.info("Local Piper voices: %s", ", ".join(available))
    else:
        message = (
            f"No Piper voice was found. Add the configured '{voice}.onnx' "
            "and its .onnx.json file to the user-data voices folder."
        )
        log.warning(message)
    return model_path, available


def self_test(open_gui=False, require_ollama=False):
    failures = []
    try:
        _verify_python_modules()
        from .config import APP_DIR, DEFAULT_CONFIG_PATH, load

        APP_DIR.mkdir(parents=True, exist_ok=True)
        config = load()
        if not DEFAULT_CONFIG_PATH.is_file():
            raise RuntimeError(f"Configuration template is missing: {DEFAULT_CONFIG_PATH}")
        log.info("Configuration and user-data directory verified: %s", APP_DIR)
        model_path, voices = _verify_speech_assets()

        from .voice import STT, TTS

        if model_path:
            try:
                recognizer = STT()
                log.info("Speech recognition model loaded: %s", recognizer.model_name)
                del recognizer
            except Exception as exc:
                message = f"Speech recognition model failed to load: {exc}"
                log.exception(message)
                failures.append(message)

        if voices:
            from piper import PiperVoice

            voice_path = TTS()._find_voice_file(
                config["voice"].get("tts_voice", "en_US-amy-medium")
            )
            if voice_path is None:
                voice_path = TTS()._find_voice_file(voices[0])
            if voice_path is None:
                failures.append("No usable Piper voice model was found.")
            else:
                try:
                    PiperVoice.load(voice_path)
                    log.info("Piper voice model loaded: %s", voice_path)
                except Exception as exc:
                    message = f"Piper voice model failed to load: {exc}"
                    log.exception(message)
                    failures.append(message)

        from .llm import LLM

        models, error = LLM().model_status()
        configured_model = config["ollama"]["chat_model"]
        if error:
            message = f"Ollama is not reachable: {error}"
            log.warning(message)
            if require_ollama:
                failures.append(message)
        elif configured_model not in models:
            message = (
                f"Ollama is reachable, but '{configured_model}' is not installed. "
                f"Install it manually with: ollama pull {configured_model}"
            )
            log.warning(message)
            if require_ollama:
                failures.append(message)
        else:
            log.info("Ollama model available: %s", configured_model)

        if open_gui:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication

            from .ui import UI

            app = QApplication.instance() or QApplication(sys.argv[:1])
            window = UI()
            window.cb_minimize_to_tray.setChecked(False)
            window.show()

            def close_test_window():
                window._allow_quit = True
                window.close()
                app.quit()

            QTimer.singleShot(1500, close_test_window)
            app.exec()
            log.info("Packaged main-window smoke test completed.")
    except Exception as exc:
        message = f"Packaged runtime self-test failed: {exc}"
        log.exception(message)
        failures.append(message)

    if failures:
        for failure in failures:
            log.error("SELF-TEST: %s", failure)
        return 1
    log.info("SELF-TEST: packaged runtime checks passed.")
    return 0
