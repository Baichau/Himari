"""Dashboard snapshot for the Control Center.

``build_dashboard`` only reads local state. Nothing here touches the network
except an injected ``model_status`` callable, which the UI runs in a worker
thread so the interface never blocks.
"""

import threading
import time
from pathlib import Path

from ..config import APP_DIR, load
from ..integrations.registry import integration_status
from . import activity_view, memory_view
from .permissions_view import enabled_capabilities, permission_rows


def _avatar_info():
    directories = (APP_DIR / "avatar_assets", Path(__file__).resolve().parents[1] / "avatar_assets")
    files = []
    for directory in directories:
        if directory.is_dir():
            files.extend(sorted(path.stem for path in directory.glob("*.png")))
    return {
        "installed": bool(files),
        "expressions": sorted(set(files)),
        "directory": str(directories[0]),
    }


def build_dashboard(
    config=None,
    model_status=None,
    interactions=None,
    integration_loader=integration_status,
    activity_limit=8,
):
    config = load() if config is None else config
    ollama = config.get("ollama", {}) if isinstance(config, dict) else {}
    voice = config.get("voice", {}) if isinstance(config, dict) else {}

    models, error = [], ""
    connected = None
    if callable(model_status):
        try:
            models, error = model_status()
            connected = not error
        except Exception as exc:
            error = str(exc)
            connected = False

    interactions = interactions or {}
    try:
        integrations = integration_loader()
    except Exception as exc:
        integrations = []
        error = error or f"Integration status unavailable: {exc}"

    try:
        memory = memory_view.stats()
    except Exception as exc:
        memory = {"approved": 0, "suggestions": 0, "error": str(exc)}

    try:
        recent = activity_view.activity_rows(limit=activity_limit)
    except Exception:
        recent = []

    selected_model = ollama.get("chat_model", "qwen3:8b")
    return {
        "timestamp": time.time(),
        "ollama": {
            "host": ollama.get("host", ""),
            "model": selected_model,
            "connected": connected,
            "model_installed": None if connected is None else selected_model in models,
            "models": list(models),
            "error": error,
        },
        "voice": {
            "stt_model": voice.get("stt_model", ""),
            "tts_voice": voice.get("tts_voice", ""),
            "push_to_talk_key": voice.get("push_to_talk_key", ""),
            "wake_word_enabled": bool(voice.get("wake_word_enabled", False)),
            "recognition_language": voice.get("recognition_language", "en"),
        },
        "interaction": {
            "state": interactions.get("state", "idle"),
            "busy": bool(interactions.get("busy", False)),
            "current_task": interactions.get("current_task", ""),
        },
        "capabilities": permission_rows(config),
        "enabled_capabilities": enabled_capabilities(config),
        "integrations": [
            {
                "name": item.get("name", ""),
                "available": bool(item.get("available", False)),
                "running": bool(item.get("running", False)),
                "actions": item.get("actions", []),
            }
            for item in integrations
        ],
        "memory": memory,
        "recent_activity": recent,
        "avatar": _avatar_info(),
    }


def build_dashboard_async(on_done, **kwargs):
    """Run ``build_dashboard`` off the UI thread.

    ``on_done(snapshot, error)`` is called from the worker thread; Qt callers
    should hand the result to a signal before touching widgets.
    """

    def work():
        try:
            on_done(build_dashboard(**kwargs), None)
        except Exception as exc:
            on_done(None, exc)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread


def format_dashboard(snapshot):
    if not snapshot:
        return "No dashboard data."
    ollama = snapshot["ollama"]
    if ollama["connected"] is None:
        ollama_line = f"not checked ({ollama['host']})"
    elif ollama["connected"] and ollama["model_installed"]:
        ollama_line = f"connected; {ollama['model']} installed"
    elif ollama["connected"]:
        ollama_line = f"connected; {ollama['model']} is NOT installed"
    else:
        ollama_line = f"unreachable: {ollama['error']}"
    voice = snapshot["voice"]
    interaction = snapshot["interaction"]
    memory = snapshot["memory"]
    lines = [
        f"Ollama: {ollama_line}",
        f"Model: {ollama['model']}",
        f"Interaction: {interaction['state']}"
        + (f" — {interaction['current_task']}" if interaction["current_task"] else ""),
        f"Push-to-talk: {voice['push_to_talk_key'] or 'not set'}",
        f"Voice: {voice['tts_voice'] or 'not configured'} "
        f"(STT {voice['stt_model'] or 'not configured'})",
        "Enabled: " + (", ".join(snapshot["enabled_capabilities"]) or "none"),
        f"Memory: {memory.get('approved', 0)} saved, "
        f"{memory.get('suggestions', 0)} pending",
        f"Avatar art: {'installed' if snapshot['avatar']['installed'] else 'not installed'}",
    ]
    available = [item["name"] for item in snapshot["integrations"] if item["available"]]
    lines.append("Integrations: " + (", ".join(available) or "none detected"))
    return "\n".join(lines)
