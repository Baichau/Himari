"""VS Code pair programmer: read what is actually open, review, then propose.

VS Code is only read through its local state database (read-only SQLite) and
window titles. Code edits are shown as a unified diff first; applying them
requires the normal security confirmation, and tests are allowlisted and
timeout-bounded.
"""

from __future__ import annotations

import difflib
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..development import (
    WorkspaceError,
    active_project,
    discover_workspaces,
    is_sensitive,
    run_tests,
    validate_command,
    workspace_for,
)
from ..windows import list_windows
from .common import permission

MAX_FILES = 20
MAX_FILE_BYTES = 1_000_000
MAX_DIFF_CHARS = 9000
MAX_STATE_ROWS = 40
TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "cp1251", "latin-1")
CODE_PROCESSES = ("code.exe", "code - insiders.exe", "vscodium.exe")


class PairError(RuntimeError):
    """VS Code state is disabled, missing, or the file is not safely readable."""


class PairPermissionError(PermissionError):
    """The VS Code editor-state permission is off."""


def _user_roots():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    base = Path(appdata)
    return [
        base / "Code" / "User",
        base / "Code - Insiders" / "User",
        base / "VSCodium" / "User",
    ]


def state_root():
    """Return the first existing VS Code user directory, or None."""
    for root in _user_roots():
        if (root / "workspaceStorage").is_dir():
            return root
    return None


def _uri_to_path(uri):
    if not isinstance(uri, str) or not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme and parsed.scheme.casefold() != "file":
        return None
    value = unquote(parsed.path or "")
    if parsed.netloc:
        value = f"//{parsed.netloc}{value}"
    if value.startswith("/") and len(value) > 2 and value[2] == ":":
        value = value[1:]
    if not value:
        return None
    return Path(value)


def _workspace_entries():
    root = state_root()
    if root is None:
        return []
    storage = root / "workspaceStorage"
    entries = []
    try:
        folders = sorted(
            (item for item in storage.iterdir() if item.is_dir()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []
    for folder in folders[:12]:
        workspace = folder / "workspace.json"
        target = None
        try:
            payload = json.loads(workspace.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                target = _uri_to_path(payload.get("folder") or payload.get("workspace"))
        except (OSError, ValueError):
            target = None
        entries.append({"directory": folder, "workspace": target})
    return entries


def _walk_uris(node, found, budget):
    if budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(node, str):
        if node.startswith("file://"):
            found.append(node)
        return
    if isinstance(node, dict):
        for value in node.values():
            _walk_uris(value, found, budget)
    elif isinstance(node, list):
        for value in node:
            _walk_uris(value, found, budget)


def _state_uris(directory):
    database = directory / "state.vscdb"
    if not database.is_file():
        return []
    connection = None
    try:
        connection = sqlite3.connect(
            f"file:{database.as_posix()}?mode=ro", uri=True, timeout=2.0
        )
        rows = connection.execute(
            "SELECT value FROM ItemTable WHERE key LIKE '%openEditor%' "
            "OR key LIKE '%recentlyOpened%' OR key LIKE '%editors.files%' "
            "LIMIT ?",
            (MAX_STATE_ROWS,),
        ).fetchall()
    except (sqlite3.Error, OSError):
        return []
    finally:
        if connection is not None:
            connection.close()
    found = []
    for row in rows:
        raw = row[0]
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
        if not isinstance(raw, str):
            continue
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        _walk_uris(payload, found, [20000])
    return found


def _code_window():
    try:
        windows = list_windows()
    except Exception:
        return None
    for window in windows:
        if str(window.process_name or "").casefold() in CODE_PROCESSES:
            return window
    return None


def _title_parts(title):
    value = str(title or "").strip()
    for suffix in (
        " - Visual Studio Code",
        " - Code - Insiders",
        " - VSCodium",
    ):
        if value.endswith(suffix):
            value = value[: -len(suffix)].strip()
            break
    parts = [part.strip() for part in value.split(" - ") if part.strip()]
    if not parts:
        return "", ""
    file_name = parts[0].removeprefix("● ").strip()
    folder = parts[1] if len(parts) > 1 else ""
    return file_name, folder


def _normalize(value):
    try:
        return str(Path(value).resolve(strict=False)).casefold()
    except (OSError, ValueError):
        return str(value or "").casefold()


def open_editors():
    """Return active file, workspace and open/recent editor paths (read-only)."""
    if not permission("allow_vscode_state"):
        raise PairPermissionError(
            "Permission denied: 'allow_vscode_state' is disabled in Settings."
        )
    entries = _workspace_entries()
    active = _code_window()
    active_file = Path()
    workspace = Path()
    title = ""
    if active is not None:
        title = str(active.title or "")
        file_name, folder_name = _title_parts(title)
        workspace = entries[0]["workspace"] if entries and entries[0]["workspace"] else Path()
        if not workspace and folder_name:
            workspace = Path(folder_name)
        if file_name and workspace:
            candidate = workspace / file_name
            if candidate.is_file():
                active_file = candidate
    if not workspace and entries:
        workspace = entries[0]["workspace"] or Path()

    seen = {}
    for entry in entries[:4]:
        folder = entry["workspace"]
        for uri in _state_uris(entry["directory"]):
            path = _uri_to_path(uri)
            if path is None or not path.is_file():
                continue
            if is_sensitive(path):
                continue
            seen.setdefault(_normalize(path), path)
            if len(seen) >= MAX_FILES:
                break
        if active_file.is_file() and not is_sensitive(active_file):
            seen.setdefault(_normalize(active_file), active_file)
        if len(seen) >= MAX_FILES:
            break

    files = [
        {
            "path": str(path),
            "name": path.name,
            "workspace": str(workspace) if workspace else "",
        }
        for path in seen.values()
    ]
    return {
        "active": str(active_file) if active_file.is_file() else "",
        "workspace": str(workspace) if workspace else "",
        "window": title,
        "files": files,
        "error": "",
    }


def _all_open_paths():
    listing = open_editors()
    paths = {}
    if listing.get("active"):
        paths[_normalize(listing["active"])] = Path(listing["active"])
    for item in listing.get("files") or []:
        value = item.get("path")
        if value:
            paths[_normalize(value)] = Path(value)
    return listing, paths


def _editable_path(requested):
    """Resolve a path only if it is in a workspace or currently open in VS Code."""
    raw = str(requested or "").strip()
    if not raw:
        raise PairError("No file path was provided.")
    candidate = Path(os.path.expandvars(os.path.expanduser(raw)))
    try:
        _, resolved = workspace_for(candidate)
        if is_sensitive(resolved):
            raise PermissionError(f"Refusing to touch sensitive file: {resolved.name}")
        return resolved
    except WorkspaceError:
        pass
    if not permission("allow_vscode_state"):
        raise PairError(
            "This file is outside the configured development workspaces and VS Code "
            "editor-state reading is disabled."
        )
    _, open_paths = _all_open_paths()
    resolved = open_paths.get(_normalize(candidate))
    if resolved is None:
        raise PairError(
            "This file is not inside a development workspace or open in VS Code. "
            "Add its folder in Settings → Advanced first."
        )
    if is_sensitive(resolved):
        raise PermissionError(f"Refusing to touch sensitive file: {resolved.name}")
    return resolved


def _read_text(path):
    target = Path(path)
    if not target.is_file():
        raise PairError(f"File not found: {target}")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise PairError("File is too large to read safely.")
    data = target.read_bytes()
    for encoding in TEXT_ENCODINGS:
        try:
            return {
                "path": target,
                "encoding": encoding,
                "content": data.decode(encoding),
            }
        except UnicodeDecodeError:
            continue
    raise PairError("Could not decode the file as text.")


def read_open_file(path=None):
    if not permission("allow_vscode_state"):
        raise PairPermissionError(
            "Permission denied: 'allow_vscode_state' is disabled in Settings."
        )
    listing = open_editors()
    requested = str(path or "").strip() or listing.get("active") or ""
    if not requested:
        raise PairError(
            "No file is open in VS Code right now. Open the file you want me to "
            "read, or give a path inside a development workspace."
        )
    try:
        target = _editable_path(requested)
        source = _read_text(target)
    except (WorkspaceError, PairError) as exc:
        if listing.get("active") and not path:
            raise PairError(f"{exc} Active file: {listing['active']}") from exc
        raise
    return {
        "path": str(source["path"]),
        "encoding": source["encoding"],
        "content": source["content"],
        "workspace": listing.get("workspace", ""),
        "open_files": [item.get("path") for item in listing.get("files") or []][:MAX_FILES],
    }


def propose_change(path, new_content):
    if not isinstance(new_content, str):
        raise PairError("New content must be a string.")
    target = _editable_path(path)
    source = _read_text(target)
    original = source["content"].replace("\r\n", "\n")
    proposed = new_content.replace("\r\n", "\n")
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile=f"a/{target.name}",
            tofile=f"b/{target.name}",
        )
    )
    return {
        "path": str(target),
        "encoding": source["encoding"],
        "diff": diff,
        "changed": original != proposed,
    }


def apply_change(path, new_content):
    change = propose_change(path, new_content)
    if not change["changed"]:
        return {**change, "applied": False, "message": "No changes to apply."}
    target = Path(change["path"])
    target.write_text(new_content, encoding=change["encoding"], newline="")
    return {
        **change,
        "applied": True,
        "message": f"Applied the approved changes to {target}.",
    }


def _default_test_root():
    project = active_project()
    if project is not None:
        return project
    workspaces = discover_workspaces()
    if workspaces:
        return workspaces[0]
    raise PairError(
        "No development workspace is configured. Add one in Settings → Advanced."
    )


def run_project_tests(path=None, command=None):
    root = _default_test_root() if not path else workspace_for(path)[1]
    if command is not None:
        command = validate_command(command)
    result = run_tests(root, command or ["python", "-m", "pytest", "-q"])
    lines = [
        f"Tests {'passed' if result.get('ok') else 'failed'} "
        f"in {result.get('workspace', root)}.",
        "Command: " + " ".join(result.get("command") or []),
    ]
    if result.get("error"):
        lines.append("Error: " + str(result["error"]))
    if result.get("returncode") is not None:
        lines.append(f"Exit code: {result['returncode']}")
    stdout = (result.get("stdout") or "").strip()
    stderr = (result.get("stderr") or "").strip()
    if stdout:
        lines.append("Output:\n" + stdout[-5000:])
    if stderr:
        lines.append("Errors:\n" + stderr[-3000:])
    return "\n".join(lines)


def vscode_editors():
    try:
        listing = open_editors()
    except PairPermissionError as exc:
        return str(exc)
    lines = ["VS Code editor state (read-only):"]
    lines.append("Active file: " + (listing.get("active") or "none detected"))
    lines.append("Workspace: " + (listing.get("workspace") or "none detected"))
    files = listing.get("files") or []
    lines.append(f"Open or recent editors: {len(files)}")
    for item in files:
        lines.append(f"  - {item.get('path')}")
    if not files:
        lines.append(
            "No editor paths were found. Open the file in VS Code, or add the "
            "project folder as a development workspace."
        )
    return "\n".join(lines)


def vscode_read(path=None):
    try:
        source = read_open_file(path)
    except (PairPermissionError, PairError, WorkspaceError, PermissionError) as exc:
        return f"Could not read the VS Code file: {exc}"
    content = source["content"]
    return (
        f"File: {source['path']} (encoding {source['encoding']})\n"
        f"Workspace: {source.get('workspace') or 'not detected'}\n\n"
        + content[:12000]
        + ("\n\n[truncated]" if len(content) > 12000 else "")
    )


def propose_change_tool(path, new_content):
    try:
        change = propose_change(path, new_content)
    except (PairPermissionError, PairError, WorkspaceError, PermissionError) as exc:
        return f"Could not prepare the change: {exc}"
    if not change["changed"]:
        return f"No changes would be made to {change['path']}."
    diff = change["diff"]
    return (
        f"Proposed diff for {change['path']}. Nothing has been written yet.\n\n"
        + diff[:MAX_DIFF_CHARS]
        + ("\n\n[diff truncated; ask for a smaller change]" if len(diff) > MAX_DIFF_CHARS else "")
        + "\n\nIf the user approves, call apply_change with the exact new content."
    )


def apply_change_tool(path, new_content):
    try:
        result = apply_change(path, new_content)
    except (PairPermissionError, PairError, WorkspaceError, PermissionError) as exc:
        return f"Change not applied: {exc}"
    if not result.get("applied"):
        return result.get("message") or "No changes were applied."
    return f"{result['message']} The file was verified after writing."


def run_tests_tool(path=None, command=None):
    try:
        return run_project_tests(path, command)
    except (PairError, WorkspaceError, PermissionError) as exc:
        return f"Tests not run: {exc}"


TOOLS = [
    {
        "name": "vscode_editors",
        "confirm": False,
        "timeout_seconds": 30,
        "spec": {
            "type": "function",
            "function": {
                "name": "vscode_editors",
                "description": (
                    "List the file that is actually active in VS Code plus open or "
                    "recent editors, read from VS Code's local state. Read-only; "
                    "sensitive files are skipped. Use it before reviewing code."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "fn": vscode_editors,
    },
    {
        "name": "vscode_read",
        "confirm": True,
        "confirm_message": "Allow Himari to read the file that is open in VS Code?",
        "timeout_seconds": 30,
        "spec": {
            "type": "function",
            "function": {
                "name": "vscode_read",
                "description": (
                    "Read one file that is open in VS Code (or inside a development "
                    "workspace). Omit path to read the active file. Refuses sensitive "
                    "files and files larger than 1 MB."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Optional full path; omit for the active editor.",
                        },
                    },
                },
            },
        },
        "fn": vscode_read,
    },
    {
        "name": "propose_change",
        "confirm": True,
        "confirm_message": (
            "Allow Himari to read this file and prepare a diff? Nothing will be written."
        ),
        "timeout_seconds": 30,
        "spec": {
            "type": "function",
            "function": {
                "name": "propose_change",
                "description": (
                    "Return a unified diff between the file on disk and proposed new "
                    "content. Read-only. Always show the user the diff before calling "
                    "apply_change."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "new_content": {
                            "type": "string",
                            "description": "The complete proposed file content.",
                        },
                    },
                    "required": ["path", "new_content"],
                },
            },
        },
        "fn": propose_change_tool,
    },
    {
        "name": "apply_change",
        "confirm": True,
        "confirm_message": (
            "Apply this approved change to the file? The diff must already have been "
            "shown to the user."
        ),
        "timeout_seconds": 30,
        "spec": {
            "type": "function",
            "function": {
                "name": "apply_change",
                "description": (
                    "Write the approved new content to a workspace or open VS Code "
                    "file. Requires confirmation and refuses sensitive files. Use "
                    "propose_change first."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "new_content": {"type": "string"},
                    },
                    "required": ["path", "new_content"],
                },
            },
        },
        "fn": apply_change_tool,
    },
    {
        "name": "run_tests",
        "confirm": True,
        "confirm_message": (
            "Allow Himari to run the project's allowlisted test command?"
        ),
        "timeout_seconds": 300,
        "spec": {
            "type": "function",
            "function": {
                "name": "run_tests",
                "description": (
                    "Run project tests inside a configured development workspace. "
                    "Only allowlisted executables are accepted, output is bounded, "
                    "and the run has a timeout. Reports the real exit code."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Optional project folder; defaults to the active project.",
                        },
                        "command": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional command list, e.g. ['python','-m','pytest','-q'].",
                        },
                    },
                },
            },
        },
        "fn": run_tests_tool,
    },
]
