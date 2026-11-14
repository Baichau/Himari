"""Continuity: remember what the user was doing and surface the current thread.

Activity memories are ordinary long-term memories in their own category, so
they follow the same privacy switch, dedupe and secret filtering. Project
context is assembled on demand and never raises when a permission is off.
"""

from ..development import active_project, discover_workspaces
from .common import bounded_text, permission

MAX_ACTIVITY_CHARS = 300
MAX_CONTEXT_LINES = 24


def _memory_manager():
    from ..memory import MemoryManager

    return MemoryManager()


def remember_activity(summary, kind="activity", project=None):
    """Store one short, user-approved activity note in local memory."""
    text = bounded_text(summary, MAX_ACTIVITY_CHARS)
    if not text:
        return "Tell me what you want remembered first."
    manager = _memory_manager()
    if not manager.enabled():
        return "Memory is disabled in Settings, so nothing was saved."
    label = bounded_text(kind, 40).casefold() or "activity"
    project_name = (bounded_text(project, 80) or None) if project else None
    record = manager.add(
        f"Activity ({label}): {text}",
        category="activity",
        project=project_name,
        source="himari",
    )
    if not record:
        return (
            "Nothing new was saved: it was already remembered, contained "
            "sensitive details, or looked temporary."
        )
    return f"Remembered: {text}"


def _vscode_lines():
    if not permission("allow_vscode_state"):
        return ["VS Code state: off (enable 'Read VS Code state' in Settings)."]
    try:
        from . import pair

        editors = pair.open_editors()
    except Exception as exc:
        return [f"VS Code state: unavailable ({exc})."]
    lines = []
    active = editors.get("active") or ""
    workspace = editors.get("workspace") or ""
    if active:
        lines.append(f"VS Code active file: {active}")
    if workspace:
        lines.append(f"VS Code workspace: {workspace}")
    files = editors.get("files") or []
    if files:
        shown = ", ".join(item.get("name") or item.get("path") for item in files[:5])
        lines.append(f"VS Code open editors ({len(files)}): {shown}")
    if not lines:
        lines.append("VS Code state: readable, but no editor is open.")
    return lines


def _watch_lines():
    try:
        from . import watch

        status = watch.session().status()
    except Exception as exc:
        return [f"Watch session: unavailable ({exc})."]
    if not status.get("running"):
        return ["Watch session: not running."]
    last = status.get("last") or {}
    subject = last.get("game") or last.get("application") or "unknown app"
    return [
        f"Watch session: running, one look every {status['interval_seconds']}s, "
        f"{status['remaining_text']} left. Last: {subject}."
    ]


def _memory_lines():
    try:
        manager = _memory_manager()
        if not manager.enabled():
            return []
        rows = []
        for category in ("projects", "activity", "workflows"):
            rows.extend(manager.list_memories(category=category, limit=3))
    except Exception:
        return []
    if not rows:
        return []
    rows.sort(key=lambda item: item.created or 0, reverse=True)
    return ["Recent memories: " + "; ".join(item.text for item in rows[:5])]


def project_context():
    """Summarize the active project, editor, watch session and recent memory."""
    lines = []
    project = active_project()
    if project is not None:
        lines.append(f"Active project: {project}")
    workspaces = discover_workspaces()
    if workspaces:
        lines.append(
            "Development workspaces: " + ", ".join(str(item) for item in workspaces[:5])
        )
    lines.extend(_vscode_lines())
    lines.extend(_watch_lines())
    lines.extend(_memory_lines())
    if not lines:
        return (
            "I have no project context yet. Open a folder in a development "
            "workspace or in VS Code and ask again."
        )
    return "\n".join(lines[:MAX_CONTEXT_LINES]) + (
        "\nThis context is read-only; nothing was changed."
    )


TOOLS = [
    {
        "name": "remember_activity",
        "confirm": False,
        "spec": {
            "type": "function",
            "function": {
                "name": "remember_activity",
                "description": (
                    "Save one short note about what the user is doing, such as a "
                    "game they are playing or a project they are on, so you can "
                    "continue the thread later. Only call it when the user asks to "
                    "remember something. Never pass secrets or passwords."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "One factual sentence, at most 300 characters.",
                        },
                        "kind": {
                            "type": "string",
                            "description": "Optional label such as gaming or coding.",
                        },
                        "project": {
                            "type": "string",
                            "description": "Optional project name.",
                        },
                    },
                    "required": ["summary"],
                },
            },
        },
        "fn": remember_activity,
    },
    {
        "name": "project_context",
        "confirm": False,
        "spec": {
            "type": "function",
            "function": {
                "name": "project_context",
                "description": (
                    "Report the current thread: active project, development "
                    "workspaces, the file open in VS Code, whether a watch session "
                    "is running, and a few recent memories. Read-only."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "fn": project_context,
    },
]
