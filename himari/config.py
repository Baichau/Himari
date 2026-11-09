import copy
import json
import os
from pathlib import Path

from .paths import resource_dir, user_data_dir

APP_DIR = user_data_dir()
CFG = APP_DIR / "config.json"
RESOURCE_DIR = resource_dir()
DEFAULT_CONFIG_PATH = RESOURCE_DIR / "config.example.json"


class ConfigError(RuntimeError):
    pass


def _read_defaults():
    try:
        return json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(
            f"Could not load the packaged configuration template "
            f"'{DEFAULT_CONFIG_PATH}': {exc}"
        ) from exc


DEFAULT = _read_defaults()


def _merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if not CFG.exists():
        save(copy.deepcopy(DEFAULT))
    try:
        user = json.loads(CFG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not read settings file '{CFG}': {exc}") from exc
    if not isinstance(user, dict):
        raise ConfigError(f"Settings file '{CFG}' must contain a JSON object.")
    return _merge(copy.deepcopy(DEFAULT), user)


def save(cfg):
    if not isinstance(cfg, dict):
        raise TypeError("Settings must be a JSON object.")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = CFG.with_suffix(".json.tmp")
    try:
        temp_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        os.replace(temp_path, CFG)
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def get(*keys, default=None):
    config = load()
    for key in keys:
        if not isinstance(config, dict) or key not in config:
            return default
        config = config[key]
    return config


def set_value(keys, value):
    config = load()
    node = config
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value
    save(config)
