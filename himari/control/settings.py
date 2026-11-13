"""Validated, non-destructive settings updates.

Every change is validated before saving, only known keys are accepted, and
unrelated sections of the user's configuration are preserved.
"""

import copy

from ..config import load, save


class SettingsError(ValueError):
    pass


def _is_bool(value):
    return isinstance(value, bool)


def _is_text(value):
    return isinstance(value, str) and bool(value.strip())


def _is_text_list(value):
    return isinstance(value, list) and all(_is_text(item) for item in value)


def _number(minimum, maximum):
    def check(value):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and minimum <= float(value) <= maximum
        )
    return check


def _one_of(options):
    def check(value):
        return isinstance(value, str) and value.casefold() in options
    return check


def _screen_area(value):
    if not isinstance(value, str) or not value.strip():
        return False
    area = value.strip().casefold()
    return area in ("primary", "all", "active", "region") or area.isdigit()


def _region(value):
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    keys = ("left", "top", "width", "height")
    if set(value) != set(keys):
        return False
    if not all(
        isinstance(value[key], int) and not isinstance(value[key], bool)
        for key in keys
    ):
        return False
    return value["width"] > 0 and value["height"] > 0


SCHEMA = {
    "ollama": {
        "host": lambda value: _is_text(value) and value.startswith(("http://", "https://")),
        "chat_model": _is_text,
        "vision_model": _is_text,
        "vision_timeout_seconds": _number(10, 900),
        "temperature": _number(0, 2),
        "timeout_seconds": _number(5, 600),
        "stream_timeout_seconds": _number(5, 1800),
        "keep_alive": _is_text,
        "preload_model": _is_bool,
        "deep_reasoning": _is_bool,
    },
    "voice": {
        "stt_model": _is_text,
        "tts_voice": _is_text,
        "volume": _number(0, 1),
        "speak_replies": _is_bool,
        "push_to_talk_key": _is_text,
        "language": _is_text,
        "recognition_language": _is_text,
        "wake_word_enabled": _is_bool,
        "wake_word": _is_text,
        "microphone_device": lambda value: value is None
        or (isinstance(value, int) and not isinstance(value, bool) and value >= 0),
        "output_device": lambda value: value is None
        or (isinstance(value, int) and not isinstance(value, bool) and value >= 0),
        "sensitivity": _number(0.1, 1),
    },
    "screen": {
        "monitor": _screen_area,
        "capture_hotkey": _is_text,
        "region": _region,
    },
    "research": {
        "searx_url": lambda value: isinstance(value, str)
        and (not value.strip() or value.strip().startswith(("http://", "https://"))),
    },
    "memory": {
        "embedding_model": lambda value: isinstance(value, str),
    },
    "privacy": {
        "store_conversations": _is_bool,
        "auto_memory": _is_bool,
        "memory_enabled": _is_bool,
    },
    "permissions": {
        "allow_open_app": _is_bool,
        "allow_open_url": _is_bool,
        "allow_web_research": _is_bool,
        "allow_vision": _is_bool,
        "allow_volume": _is_bool,
        "allow_read_file": _is_bool,
        "allow_screen_capture": _is_bool,
        "allow_screen_control": _is_bool,
        "allow_active_window": _is_bool,
        "allow_media_control": _is_bool,
        "allow_run_command": _is_bool,
        "allow_write_file": _is_bool,
        "allow_browser_automation": _is_bool,
        "allowed_folders": _is_text_list,
    },
    "ui": {
        "theme": _is_text,
        "font_size": _number(9, 32),
        "always_on_top": _is_bool,
        "minimize_to_tray": _is_bool,
        "chat_engine": _one_of(("web", "classic")),
    },
    "development": {
        "workspaces": _is_text_list,
    },
    "personality": {
        "name": _is_text,
        "playfulness": _one_of(("low", "medium", "high")),
        "roleplay": _one_of(("none", "minimal", "moderate")),
    },
}


class SettingsService:
    def __init__(self, load_config=load, save_config=save):
        self._load = load_config
        self._save = save_config

    def snapshot(self):
        return copy.deepcopy(self._load())

    def validate(self, updates):
        if not isinstance(updates, dict):
            raise SettingsError("Settings updates must be an object.")
        errors = []
        cleaned = {}
        for section, values in updates.items():
            schema = SCHEMA.get(section)
            if schema is None:
                errors.append(f"Unknown settings section: {section}")
                continue
            if not isinstance(values, dict):
                errors.append(f"Section '{section}' must be an object.")
                continue
            prepared = {}
            for key, value in values.items():
                check = schema.get(key)
                if check is None:
                    errors.append(f"Unknown setting: {section}.{key}")
                    continue
                if not check(value):
                    errors.append(f"Invalid value for {section}.{key}")
                    continue
                prepared[key] = value
            cleaned[section] = prepared
        if errors:
            raise SettingsError("; ".join(errors))
        return cleaned

    def update(self, updates):
        cleaned = self.validate(updates)
        config = self.snapshot()
        for section, values in cleaned.items():
            current = config.get(section)
            if not isinstance(current, dict):
                current = {}
            current.update(values)
            config[section] = current
        self._save(config)
        return config

    def set(self, section, values):
        return self.update({section: values}).get(section, {})

    def set_permission(self, key, enabled):
        return self.set("permissions", {key: bool(enabled)})
