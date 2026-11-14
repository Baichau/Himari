"""Interactive setup coaching without ever exposing credentials.

The coach knows a few small playbooks (Spotify first), inspects only the
non-secret shape of the local config, verifies what is actually working, and
remembers completed steps by name — never their values.
"""

from __future__ import annotations

from .common import config_section, mask_mapping

PLAYBOOKS = {
    "spotify": {
        "title": "Spotify exact-track setup",
        "summary": (
            "Himari can already ask Spotify to play a song. These credentials let "
            "it resolve the exact track instead of a remix or cover."
        ),
        "docs": "https://developer.spotify.com/dashboard",
        "steps": [
            {
                "id": "open_dashboard",
                "title": "Open the Spotify Developer Dashboard",
                "detail": (
                    "Sign in with your normal Spotify account at "
                    "https://developer.spotify.com/dashboard. No payment or "
                    "premium plan is needed for search."
                ),
            },
            {
                "id": "create_app",
                "title": "Create an app",
                "detail": (
                    "Choose 'Create app', give it any name such as 'Himari Local', "
                    "and accept the terms. No redirect URI is needed because Himari "
                    "only uses Client Credentials search."
                ),
            },
            {
                "id": "client_id",
                "title": "Paste the Client ID into Settings",
                "detail": (
                    "Open the app, copy 'Client ID', then paste it into Settings → "
                    "Assistant & services → Spotify Client ID. It is stored only in "
                    "your local config.json."
                ),
                "check": "spotify.client_id",
            },
            {
                "id": "client_secret",
                "title": "Paste the Client Secret into Settings",
                "detail": (
                    "In the same app page choose 'View client secret', then paste it "
                    "into the Spotify Client Secret field. Himari masks it and never "
                    "writes it to logs or chat."
                ),
                "check": "spotify.client_secret",
            },
            {
                "id": "verify",
                "title": "Verify the connection",
                "detail": (
                    "Ask Himari to verify the Spotify setup. It requests a read-only "
                    "search token; nothing is played or changed."
                ),
                "check": "spotify.api",
            },
        ],
    },
    "vscode": {
        "title": "VS Code pair programmer setup",
        "summary": (
            "Himari can read the file that is actually open in VS Code, review it, "
            "and propose changes before writing anything."
        ),
        "steps": [
            {
                "id": "install",
                "title": "Install VS Code",
                "detail": "Install Visual Studio Code from https://code.visualstudio.com.",
                "check": "vscode.installed",
            },
            {
                "id": "permission",
                "title": "Allow reading VS Code's local editor state",
                "detail": (
                    "In Settings → Permissions enable 'Allow reading VS Code's local "
                    "editor state'. This is read-only and skips sensitive files."
                ),
                "check": "vscode.permission",
            },
            {
                "id": "workspaces",
                "title": "Add your project folders as development workspaces",
                "detail": (
                    "In Settings → Advanced add the folders you want Himari to read "
                    "and edit. Writes still ask for confirmation and show a diff."
                ),
                "check": "development.workspaces",
            },
            {
                "id": "tests",
                "title": "Allow project tests (optional)",
                "detail": (
                    "Enable 'Allow running project tests' to let Himari run an "
                    "allowlisted test command after you approve it."
                ),
                "check": "development.tests",
            },
        ],
    },
    "voice": {
        "title": "Voice setup",
        "summary": "Let Himari listen with your microphone and speak with a local voice.",
        "steps": [
            {
                "id": "microphone",
                "title": "Choose the microphone",
                "detail": "Settings → Voice & microphone → Microphone.",
            },
            {
                "id": "voice",
                "title": "Choose a local voice",
                "detail": (
                    "Pick a Piper voice. Himari never downloads a voice model "
                    "automatically; install one first if the list is empty."
                ),
                "check": "voice.model",
            },
            {
                "id": "hotkey",
                "title": "Set push-to-talk",
                "detail": "Click the push-to-talk button and press the key you want.",
                "check": "voice.hotkey",
            },
        ],
    },
    "ollama": {
        "title": "Local model setup",
        "summary": "Himari runs on Ollama on this PC. No cloud model is used.",
        "steps": [
            {
                "id": "running",
                "title": "Start Ollama",
                "detail": "Ollama must be running at the configured local address.",
            },
            {
                "id": "model",
                "title": "Install the chat model",
                "detail": "Run: ollama pull qwen3:8b (or choose a smaller installed model).",
                "check": "ollama.model",
            },
            {
                "id": "vision",
                "title": "Install a vision model (optional)",
                "detail": "Run: ollama pull qwen2.5vl:3b to read screenshots and photos.",
                "check": "ollama.vision",
            },
        ],
    },
    "browser": {
        "title": "Himari browser setup",
        "summary": (
            "Himari can open its own visible Chrome window for searching and reading "
            "pages, separate from your everyday profile."
        ),
        "steps": [
            {
                "id": "permission",
                "title": "Allow browser automation",
                "detail": "Settings → Permissions → Allow browser automation.",
                "check": "browser.permission",
            },
            {
                "id": "playwright",
                "title": "Install Playwright",
                "detail": "The packaged build already includes it; source installs need it.",
                "check": "browser.playwright",
            },
        ],
    },
    "watch": {
        "title": "Watch companion setup",
        "summary": (
            "An explicit watch session looks at the screen every few seconds while a "
            "visible indicator is shown. Nothing is recorded or saved."
        ),
        "steps": [
            {
                "id": "permission",
                "title": "Allow the watch companion",
                "detail": "Settings → Permissions → Allow the watch companion.",
                "check": "watch.permission",
            },
            {
                "id": "capture",
                "title": "Allow one-time screen capture",
                "detail": "Settings → Screen & shortcuts → Allow one-time screen capture.",
                "check": "watch.capture",
            },
            {
                "id": "active",
                "title": "Allow active-window capture (recommended)",
                "detail": (
                    "This keeps watch looks focused on the game window instead of "
                    "the whole desktop."
                ),
                "check": "watch.active",
            },
        ],
    },
}

TOPIC_ALIASES = {
    "vs code": "vscode",
    "visual studio code": "vscode",
    "developer": "vscode",
    "web": "browser",
    "chrome": "browser",
    "gaming": "watch",
    "game": "watch",
    "model": "ollama",
    "mic": "voice",
    "microphone": "voice",
    "tts": "voice",
}


def _config_value(path):
    node = config_section(path.split(".", 1)[0])
    for part in path.split(".")[1:]:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _check(key):
    """Return (done, detail) for one playbook check; done may be None."""
    if key == "spotify.installed":
        from ..applications import spotify

        installed = bool(spotify.installed())
        return installed, "Spotify is installed." if installed else "Spotify was not found."
    if key == "spotify.running":
        from ..applications import spotify

        running = bool(spotify.running())
        return running, "Spotify is running." if running else "Spotify is not running."
    if key == "spotify.api":
        values = config_section("spotify")
        ready = bool(str(values.get("client_id") or "").strip()) and bool(
            str(values.get("client_secret") or "").strip()
        )
        return ready, "Credentials are present (not verified online yet)." if ready else (
            "Client ID and secret are not both saved."
        )
    if key == "vscode.installed":
        from ..windows import installed_apps

        try:
            names = {item.name.casefold() for item in installed_apps()}
        except Exception:
            names = set()
        found = any("visual studio code" in name or name == "vs code" for name in names)
        return found, "VS Code is installed." if found else "VS Code was not found."
    if key == "vscode.permission":
        from .common import permission

        value = permission("allow_vscode_state")
        return value, "Editor-state reading is allowed." if value else (
            "Editor-state reading is disabled."
        )
    if key in {"development.workspaces", "development.tests"}:
        if key == "development.tests":
            from .common import permission

            value = permission("allow_run_tests")
            return value, "Test runs are allowed." if value else "Test runs are disabled."
        values = config_section("development").get("workspaces") or []
        return bool(values), (
            f"{len(values)} development workspace(s) configured."
            if values else "No development workspace is configured."
        )
    if key == "voice.model":
        try:
            from ..voice import TTS

            voices = TTS().available_voices()
        except Exception:
            voices = []
        return bool(voices), (
            f"{len(voices)} local voice(s) available." if voices else "No local voice found."
        )
    if key == "voice.hotkey":
        value = str(config_section("voice").get("push_to_talk_key") or "")
        return bool(value), f"Push-to-talk key: {value or 'not set'}."
    if key in {"ollama.model", "ollama.vision"}:
        section = "vision_model" if key.endswith("vision") else "chat_model"
        value = str(config_section("ollama").get(section) or "")
        return bool(value), f"{section.replace('_', ' ').title()}: {value or 'not set'}."
    if key == "browser.permission":
        from .common import permission

        value = permission("allow_browser_automation")
        return value, "Browser automation is allowed." if value else (
            "Browser automation is disabled."
        )
    if key == "browser.playwright":
        import importlib.util

        found = importlib.util.find_spec("playwright") is not None
        return found, "Playwright is available." if found else "Playwright is not installed."
    if key == "watch.permission":
        from .common import permission

        value = permission("allow_watch_mode")
        return value, "Watch sessions are allowed." if value else "Watch mode is disabled."
    if key == "watch.capture":
        from .common import permission

        value = permission("allow_screen_capture")
        return value, "Screen capture is allowed." if value else "Screen capture is disabled."
    if key == "watch.active":
        from .common import permission

        value = permission("allow_active_window")
        return value, "Active-window capture is allowed." if value else (
            "Active-window capture is disabled."
        )
    return None, ""


def resolve_topic(topic):
    value = str(topic or "").strip().casefold()
    if value in PLAYBOOKS:
        return value
    for alias, name in TOPIC_ALIASES.items():
        if alias in value:
            return name
    for name in PLAYBOOKS:
        if name in value:
            return name
    return "spotify"


def playbook_status(topic="spotify", remember=None):
    """Return a playbook with per-step status, safe for the UI and the model."""
    key = resolve_topic(topic)
    playbook = PLAYBOOKS[key]
    completed = set(remember if remember is not None else config_section("coach").get("completed", []))
    steps = []
    for step in playbook["steps"]:
        check = step.get("check")
        done = None
        detail = ""
        if check:
            try:
                done, detail = _check(check)
            except Exception as exc:
                done, detail = False, f"Check failed: {exc}"
        steps.append(
            {
                "id": step["id"],
                "title": step["title"],
                "detail": step["detail"],
                "check": check or "",
                "done": done,
                "detail_now": detail,
                "remembered": f"{key}.{step['id']}" in completed,
            }
        )
    next_step = next((step for step in steps if step["done"] is not True), None)
    done_count = sum(1 for step in steps if step["done"] is True)
    return {
        "topic": key,
        "title": playbook["title"],
        "summary": playbook["summary"],
        "docs": playbook.get("docs", ""),
        "steps": steps,
        "done": done_count,
        "total": len(steps),
        "next_step": next_step,
        "complete": next_step is None,
    }


def _format_status(status):
    lines = [status["title"], status["summary"], ""]
    for index, step in enumerate(status["steps"], 1):
        marker = "OK" if step["done"] is True else "--"
        lines.append(f"{index}. [{marker}] {step['title']}")
        lines.append(f"   {step['detail']}")
        if step["detail_now"]:
            lines.append(f"   Now: {step['detail_now']}")
    lines.append("")
    if status["complete"]:
        lines.append("Everything in this checklist is ready.")
    else:
        lines.append(f"Next step: {status['next_step']['title']}")
    if status.get("docs"):
        lines.append(f"Official page: {status['docs']}")
    return "\n".join(lines)


def inspect_settings(section=None):
    """Masked snapshot of local settings; secret values are replaced."""
    config = _snapshot()
    if section:
        name = str(section).strip()
        values = config.get(name)
        if values is None:
            return f"No settings section named '{name}'."
        data = {name: values}
    else:
        data = config
    safe = mask_mapping(data)
    lines = ["Local settings (masked; secret values are never shown):"]
    for name in sorted(safe):
        values = safe[name]
        if isinstance(values, dict):
            lines.append(f"{name}:")
            for key in sorted(values):
                value = values[key]
                if isinstance(value, dict):
                    value = "<nested object>"
                elif isinstance(value, (list, tuple)):
                    value = ", ".join(str(item) for item in value) or "(empty)"
                lines.append(f"  {key}: {value}")
        else:
            lines.append(f"{name}: {values}")
    return "\n".join(lines)[:5000]


def _snapshot():
    from ..control.settings import SettingsService

    try:
        return SettingsService().snapshot()
    except Exception:
        from ..config import load

        return load()


def setup_guide(topic="spotify"):
    return _format_status(playbook_status(topic))


def _verify_spotify():
    from ..applications import spotify

    result = playbook_status("spotify")
    notes = [
        f"Spotify installed: {'yes' if spotify.installed() else 'no'}",
        f"Spotify running: {'yes' if spotify.running() else 'no'}",
    ]
    if not result["steps"][2]["done"] or not result["steps"][3]["done"]:
        return (
            "Spotify credentials are not complete yet. "
            + " ".join(notes)
            + "\nNext: add the Client ID and Client Secret in Settings."
        )
    try:
        candidates = spotify.search_tracks("test", limit=1)
    except Exception as exc:
        return (
            "Spotify rejected a live test. "
            + " ".join(notes)
            + f"\nError: {exc}\nCheck the Client ID and secret, then try again."
        )
    if candidates:
        first = candidates[0]
        artist = ", ".join(getattr(first, "artists", ()) or ())
        return (
            "Spotify verified: a live read-only search succeeded. "
            + " ".join(notes)
            + f"\nExample result: {getattr(first, 'name', 'a track')}"
            + (f" — {artist}" if artist else "")
            + ". Nothing was played."
        )
    return (
        "Spotify accepted the credentials but returned no search result. "
        + " ".join(notes)
    )


def _verify_vscode():
    from . import pair

    status = playbook_status("vscode")
    lines = [_format_status(status)]
    try:
        editors = pair.open_editors()
    except Exception as exc:
        editors = {"active": "", "workspace": "", "files": [], "error": str(exc)}
    lines.append("")
    if editors.get("error"):
        lines.append(f"Editor state: {editors['error']}")
    else:
        lines.append(f"Active file: {editors.get('active') or 'none detected'}")
        lines.append(f"Workspace: {editors.get('workspace') or 'none detected'}")
        files = editors.get("files") or []
        lines.append(f"Open editors: {len(files)}")
        for item in files[:8]:
            lines.append(f"  - {item.get('path')}")
    return "\n".join(lines)


def setup_verify(topic="spotify"):
    key = resolve_topic(topic)
    if key == "spotify":
        return _verify_spotify()
    if key == "vscode":
        return _verify_vscode()
    status = playbook_status(key)
    if status["complete"]:
        return _format_status(status) + "\nEverything checked in this playbook is ready."
    return _format_status(status)


def setup_remember(topic="spotify", step=""):
    key = resolve_topic(topic)
    playbook = PLAYBOOKS[key]
    wanted = str(step or "").strip()
    valid = {item["id"] for item in playbook["steps"]}
    if wanted and wanted not in valid:
        return f"'{wanted}' is not a step in the {key} playbook: " + ", ".join(sorted(valid))
    entry = f"{key}.{wanted}" if wanted else key
    try:
        from ..control.settings import SettingsService

        service = SettingsService()
        current = list(service.snapshot().get("coach", {}).get("completed", []))
        if entry not in current:
            current.append(entry)
            service.set("coach", {"completed": current})
    except Exception as exc:
        return f"Could not remember that step: {exc}"
    return (
        f"Remembered '{entry}' as completed. Only the step name is stored; "
        "no credential value is saved."
    )


TOOLS = [
    {
        "name": "inspect_settings",
        "confirm": False,
        "spec": {
            "type": "function",
            "function": {
                "name": "inspect_settings",
                "description": (
                    "Read the local settings with every secret-looking value masked. "
                    "Use it to see what is already configured before coaching the "
                    "user. It never reveals passwords, tokens, client IDs or secrets."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "section": {
                            "type": "string",
                            "description": "Optional section such as spotify or permissions.",
                        },
                    },
                },
            },
        },
        "fn": inspect_settings,
    },
    {
        "name": "setup_guide",
        "confirm": False,
        "spec": {
            "type": "function",
            "function": {
                "name": "setup_guide",
                "description": (
                    "Return a step-by-step setup checklist for spotify, vscode, "
                    "voice, ollama, browser or watch, including what is already done. "
                    "Use it whenever the user does not know how to configure something."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "spotify, vscode, voice, ollama, browser or watch.",
                        },
                    },
                },
            },
        },
        "fn": setup_guide,
    },
    {
        "name": "setup_verify",
        "confirm": False,
        "spec": {
            "type": "function",
            "function": {
                "name": "setup_verify",
                "description": (
                    "Verify a setup for real. For Spotify it performs one read-only "
                    "search token request and search; for VS Code it reads the local "
                    "editor state. Never claims success without evidence."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "spotify, vscode, voice, ollama, browser or watch.",
                        },
                    },
                },
            },
        },
        "fn": setup_verify,
    },
    {
        "name": "setup_remember",
        "confirm": False,
        "spec": {
            "type": "function",
            "function": {
                "name": "setup_remember",
                "description": (
                    "Remember that one setup step was completed. Stores only the step "
                    "name in local config, never a credential value."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "step": {
                            "type": "string",
                            "description": "Step id from setup_guide.",
                        },
                    },
                    "required": ["topic", "step"],
                },
            },
        },
        "fn": setup_remember,
    },
]
