"""Central registry of what Himari can actually do right now.

Tools stay where they are, but every tool gains the metadata the orchestration
layer needs: category, tags, risk, permission, verification strategy, and a
live availability probe. The chat path sends only the capabilities relevant to
the understood intent, which keeps small local models focused.
"""

import importlib.util
import os
import re
import time
from dataclasses import dataclass

from ..config import load
from ..security.policies import (
    confirmation_required_for,
    permission_key_for,
    risk_for,
    tool_is_known,
)
from ..tool_exec import timeout_for

MAX_CAPABILITIES = 16
AVAILABILITY_TTL_SECONDS = 30.0
CORE_TOOLS = (
    "open_app",
    "find_app",
    "active_window",
    "list_windows",
    "research_web",
    "media_control",
)

CATEGORY_TAGS = {
    "chat": set(),
    "information": {"information", "research", "browser"},
    "research": {"research", "web", "browser", "information", "video"},
    "music": {"music", "media", "spotify"},
    "weather": {"weather", "information"},
    "calendar": {"calendar", "schedule"},
    "app_control": {"app", "window", "discovery"},
    "system": {"system", "audio", "context"},
    "screen": {"screen", "ocr", "vision", "input", "context"},
    "file": {"file", "desktop"},
    "development": {"development", "file", "app"},
    "deep_work": {"research", "file", "development", "calendar"},
    "watch": {"watch", "screen", "gaming", "context", "ocr"},
    "coach": {"coach", "setup", "information"},
    "diagnostics": {"diagnostics", "system", "read"},
    "media": {"media", "video", "research", "web", "information"},
    "continuity": {"memory", "activity", "projects", "read", "development"},
}

# tool -> (category, tags, verification, mutates)
CAPABILITY_META = {
    "open_app": ("app", {"app", "launch"}, "app_running", True),
    "launch_game": ("app", {"app", "game", "launch"}, "app_running", True),
    "play_music": ("music", {"music", "media", "spotify", "playback"}, "media_playing", True),
    "spotify_search": ("music", {"music", "media", "spotify"}, "none", False),
    "now_playing": ("music", {"music", "media", "read", "context"}, "none", False),
    "media_control": ("music", {"music", "media", "system"}, "media_state", True),
    "open_url": ("browser", {"browser", "web"}, "none", True),
    "search_web": ("browser", {"browser", "web", "information"}, "none", True),
    "open_first_result": ("browser", {"browser", "web"}, "none", True),
    "browser_open": ("browser", {"browser", "web"}, "none", True),
    "browser_search": ("browser", {"browser", "web"}, "none", True),
    "browser_open_result": ("browser", {"browser", "web"}, "none", True),
    "browser_tabs": ("browser", {"browser", "web"}, "none", True),
    "browser_read": ("browser", {"browser", "web", "read"}, "none", False),
    "browser_close": ("browser", {"browser", "web"}, "none", True),
    "research_web": ("research", {"research", "web", "information"}, "none", False),
    "find_video": ("research", {"research", "web", "video"}, "none", False),
    "open_video": ("research", {"research", "web", "video", "browser"}, "none", True),
    "search_youtube": ("browser", {"browser", "web", "video"}, "none", True),
    "close_app": ("app", {"app", "lifecycle"}, "app_not_running", True),
    "list_project_files": ("development", {"development", "file", "read"}, "none", False),
    "search_code": ("development", {"development", "file", "read", "search"}, "none", False),
    "open_project": ("development", {"development", "app", "file"}, "none", True),
    "read_file": ("file", {"file", "read"}, "none", False),
    "scan_large_files": ("file", {"file", "read", "disk"}, "none", False),
    "write_file": ("file", {"file", "desktop", "write"}, "file_exists", True),
    "write_desktop_file": ("file", {"file", "desktop", "write"}, "file_exists", True),
    "set_volume": ("system", {"system", "audio"}, "none", True),
    "capture_screen_text": ("screen", {"screen", "ocr", "read"}, "none", False),
    "screen_scene": ("screen", {"screen", "ocr", "vision", "read"}, "none", False),
    "active_window": ("system", {"system", "screen", "context", "read"}, "none", False),
    "installed_apps": ("app", {"app", "discovery", "read"}, "none", False),
    "app_registry": ("app", {"app", "discovery", "read"}, "none", False),
    "inspect_app": ("app", {"app", "discovery", "uia", "read"}, "none", False),
    "list_windows": ("app", {"app", "window", "screen", "read", "context"}, "none", False),
    "running_processes": ("system", {"system", "read"}, "none", False),
    "find_app": ("app", {"app", "discovery", "read"}, "none", False),
    "focus_window": ("app", {"app", "window"}, "window_focused", True),
    "list_controls": ("screen", {"app", "screen", "uia", "read"}, "none", False),
    "click_control": ("screen", {"app", "screen", "uia", "input"}, "none", True),
    "set_control_text": ("screen", {"app", "screen", "uia", "input"}, "none", True),
    "type_text": ("screen", {"screen", "input"}, "none", True),
    "press_keys": ("screen", {"screen", "input"}, "none", True),
    "click_at": ("screen", {"screen", "input"}, "none", True),
    "scroll_screen": ("screen", {"screen", "input"}, "none", True),
    "run_command": ("system", {"system", "shell"}, "none", True),
    "weather_forecast": ("weather", {"weather", "information"}, "weather_data", False),
    "calendar_list": ("calendar", {"calendar", "schedule", "read"}, "none", False),
    "calendar_create": ("calendar", {"calendar", "schedule", "write"}, "calendar_event", True),
    "calendar_delete": ("calendar", {"calendar", "schedule", "delete"}, "calendar_absent", True),
    "calendar_export": ("calendar", {"calendar", "schedule", "export"}, "file_exists", True),
    "memory_add": ("memory", {"memory", "write"}, "none", True),
    "memory_search": ("memory", {"memory", "read"}, "none", False),
    "memory_delete": ("memory", {"memory", "delete"}, "none", True),
    "remember_activity": ("memory", {"memory", "activity", "write"}, "none", True),
    "project_context": ("memory", {"memory", "projects", "read", "development"}, "none", False),
    "watch_start": ("watch", {"watch", "screen", "gaming", "context"}, "watch_running", True),
    "watch_stop": ("watch", {"watch", "screen", "gaming"}, "watch_stopped", True),
    "watch_status": ("watch", {"watch", "screen", "gaming", "read"}, "none", False),
    "watch_observe": ("watch", {"watch", "screen", "gaming", "ocr"}, "none", False),
    "inspect_settings": ("coach", {"coach", "setup", "read"}, "none", False),
    "setup_guide": ("coach", {"coach", "setup", "information", "read"}, "none", False),
    "setup_verify": ("coach", {"coach", "setup", "verify", "read"}, "none", False),
    "setup_remember": ("coach", {"coach", "setup", "write"}, "none", True),
    "inspect_system": ("diagnostics", {"diagnostics", "system", "read", "health"}, "none", False),
    "diagnose_program": ("diagnostics", {"diagnostics", "system", "app", "read"}, "none", False),
    "vscode_editors": ("development", {"development", "vscode", "file", "read"}, "none", False),
    "vscode_read": ("development", {"development", "vscode", "file", "read"}, "none", False),
    "propose_change": ("development", {"development", "vscode", "file", "read", "diff"}, "none", False),
    "apply_change": ("development", {"development", "vscode", "file", "write"}, "file_exists", True),
    "run_tests": ("development", {"development", "test", "run"}, "test_result", True),
    "youtube_transcript": ("media", {"media", "video", "research", "web", "read"}, "none", False),
}

_RISK_ORDER = {"read": 0, "low": 1, "medium": 2, "high": 3}

HIMARI_BROWSER_REQUEST = re.compile(
    r"\b(?:himari(?:'s)? browser|your (?:own )?(?:browser|chrome|tabs?"
    r"|browser tabs)|the browser you opened|browser (?:window|tab|tabs)"
    r"|(?:close|switch|focus|list|next|previous) (?:the )?(?:tab|tabs)"
    r"|this tab|that tab|browser automation|playwright)\b",
    re.IGNORECASE,
)


def wants_himari_browser(intent):
    """True only when the request explicitly targets Himari's own browser."""
    if intent is None:
        return False
    required = [str(item).casefold() for item in getattr(intent, "required_capabilities", []) or []]
    if any(name.startswith("browser_") for name in required):
        return True
    text = " ".join(str(getattr(intent, "raw_text", "") or "").split())
    return bool(HIMARI_BROWSER_REQUEST.search(text))


def is_himari_browser_tool(name):
    return str(name or "").startswith("browser_")


@dataclass(frozen=True)
class Capability:
    tool: str
    category: str
    tags: tuple
    description: str
    risk: str
    permission: str
    verification: str
    mutates: bool
    timeout: float
    requires_confirmation: bool
    availability: str = "unknown"
    availability_detail: str = ""

    def to_dict(self):
        return {
            "tool": self.tool,
            "category": self.category,
            "description": self.description,
            "risk": self.risk,
            "permission": self.permission,
            "verification": self.verification,
            "mutates": self.mutates,
            "timeout_seconds": self.timeout,
            "requires_confirmation": self.requires_confirmation,
            "availability": self.availability,
            "availability_detail": self.availability_detail,
        }


def _spec_description(entry):
    function = ((entry.get("spec") or {}).get("function") or {})
    return " ".join(str(function.get("description") or "").split())


def _tags_for(name):
    meta = CAPABILITY_META.get(name)
    if meta:
        return meta[0], set(meta[1]), meta[2], meta[3]
    stems = {part for part in name.split("_") if part}
    return "other", stems, "none", False


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class CapabilityRegistry:
    def __init__(self, tools=None, config_loader=None, clock=None):
        if tools is None:
            from ..tools import TOOLS as tools
        self._entries = {
            entry.get("name"): entry
            for entry in tools or []
            if isinstance(entry, dict) and entry.get("name") and entry.get("spec")
        }
        self._config_loader = config_loader or load
        self._clock = clock or time.monotonic
        self._availability = {}
        self._checked_at = 0.0

    def tools(self):
        return [self._entries[name] for name in sorted(self._entries)]

    def has(self, tool):
        return tool in self._entries

    def entry(self, tool):
        return self._entries.get(tool)

    def _config(self):
        try:
            config = self._config_loader()
        except Exception:
            return {}
        return config if isinstance(config, dict) else {}

    def _probe(self, tool, config):
        permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
        permission = permission_key_for(tool)
        if permission and not permissions.get(permission, False):
            return "unavailable", f"Permission '{permission}' is disabled in Settings."
        if tool in {"play_music", "spotify_search", "now_playing"}:
            try:
                from ..applications import spotify

                if not spotify.installed():
                    return "unavailable", "Spotify is not installed."
                if not spotify.running():
                    return "available", "Spotify is installed but not running; it can be started."
            except Exception as exc:
                return "unknown", f"Spotify check failed: {exc}"
        if tool == "weather_forecast":
            return "available", ""
        if tool.startswith("calendar_"):
            return "available", "Local calendar."
        if tool in {"list_controls", "click_control", "set_control_text"}:
            if not _has_module("pywinauto"):
                return "unavailable", "pywinauto is not installed."
        if tool.startswith("browser_"):
            if not _has_module("playwright"):
                return "unavailable", "Playwright is not installed."
        if tool in {"now_playing", "media_control", "play_music"}:
            try:
                from ..windows import media_session

                if not media_session.available():
                    return (
                        "available",
                        "Playback control works, but verification needs "
                        "winrt-Windows.Media.Control.",
                    )
            except Exception:
                pass
        if tool.startswith("watch_"):
            if not permissions.get("allow_screen_capture", False):
                return "unavailable", "One-time screen capture is disabled in Settings."
            if os.name != "nt":
                return "unavailable", "The watch companion needs Windows."
        if tool in {"inspect_system", "diagnose_program"}:
            if not _has_module("psutil"):
                return "unavailable", "psutil is not installed."
        if tool.startswith("vscode_"):
            try:
                from ..skills import pair

                if not pair.state_root():
                    return "unavailable", "VS Code local state was not found."
            except Exception:
                pass
        return "available", ""

    def refresh_availability(self, force=False):
        now = self._clock()
        if not force and now - self._checked_at < AVAILABILITY_TTL_SECONDS and self._availability:
            return self._availability
        config = self._config()
        availability = {}
        for tool in self._entries:
            availability[tool] = self._probe(tool, config)
        self._availability = availability
        self._checked_at = now
        return availability

    def _availability_for(self, tool):
        if not self._availability:
            self.refresh_availability()
        return self._availability.get(tool, ("unknown", ""))

    def capability(self, tool):
        entry = self._entries.get(tool)
        if entry is None:
            return None
        category, tags, verification, mutates = _tags_for(tool)
        availability, detail = self._availability_for(tool)
        return Capability(
            tool=tool,
            category=category,
            tags=tuple(sorted(tags)),
            description=_spec_description(entry),
            risk=str(risk_for(tool)) if tool_is_known(tool) else "high",
            permission=permission_key_for(tool) or "",
            verification=verification,
            mutates=bool(mutates),
            timeout=timeout_for(entry),
            requires_confirmation=confirmation_required_for(tool)
            or str(risk_for(tool)) == "high",
            availability=availability,
            availability_detail=detail,
        )

    def all_capabilities(self):
        return [self.capability(tool) for tool in sorted(self._entries)]

    def select(self, intent=None, max_capabilities=MAX_CAPABILITIES):
        """Return the tool entries relevant to one intent."""
        self.refresh_availability()
        known_core = {tool for tool in CORE_TOOLS if tool in self._entries}
        if intent is None:
            names = set(known_core)
        else:
            wanted_tags = set(CATEGORY_TAGS.get(intent.category, set()))
            for capability in intent.required_capabilities:
                wanted_tags |= _tags_for(str(capability))[1]
            names = set()
            for tool in self._entries:
                if tool in CORE_TOOLS:
                    names.add(tool)
                    continue
                _, tags, _, _ = _tags_for(tool)
                if tags & wanted_tags:
                    names.add(tool)
            for tool in intent.required_capabilities:
                if tool in self._entries:
                    names.add(tool)
            if intent.category in {"chat", "information"}:
                names.update(known_core)
        ordered = []
        required = set(intent.required_capabilities) if intent else set()
        explicit_browser = wants_himari_browser(intent)
        for tool in sorted(names):
            if is_himari_browser_tool(tool) and not explicit_browser and tool not in required:
                continue
            availability, _ = self._availability_for(tool)
            if availability == "unavailable" and tool not in required:
                continue
            ordered.append(tool)
        ordered.sort(
            key=lambda tool: (
                tool not in required,
                tool not in CORE_TOOLS,
                _RISK_ORDER.get(str(risk_for(tool)) if tool_is_known(tool) else "high", 3),
                tool,
            )
        )
        limit = max(4, int(max_capabilities))
        return [self._entries[tool] for tool in ordered[:limit]]

    def specs(self, intent=None):
        return [entry["spec"] for entry in self.select(intent) if entry.get("spec")]

    def names(self, intent=None):
        return [entry["name"] for entry in self.select(intent)]

    def prompt_block(self, intent=None):
        """Compact capability inventory for the system prompt."""
        selected = self.select(intent)
        lines = []
        for entry in selected:
            capability = self.capability(entry["name"])
            if capability is None:
                continue
            note = ""
            if capability.availability != "available":
                note = f" [{capability.availability}: {capability.availability_detail}]"
            lines.append(
                f"- {capability.tool}: {capability.description}{note}"
            )
        return "\n".join(lines)

    def environment_notes(self):
        notes = []
        availability = self.refresh_availability()
        for tool in ("play_music", "now_playing", "weather_forecast"):
            if tool not in self._entries:
                continue
            state, detail = availability.get(tool, ("unknown", ""))
            if state != "available":
                notes.append(f"{tool}: {state} ({detail})" if detail else f"{tool}: {state}")
        return notes


_DEFAULT = None


def registry():
    """Process-wide registry; probes are cached, so sharing is safe."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = CapabilityRegistry()
    return _DEFAULT
