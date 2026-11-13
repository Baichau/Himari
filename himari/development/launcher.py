"""Find or create a project folder inside a permitted workspace, then open it in VS Code."""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from .workspace import WorkspaceError, discover_workspaces, workspace_for

log = logging.getLogger("himari.development")

EDITOR_NAME = "Visual Studio Code"
_INVALID_NAME_CHARS = set('<>:"/\\|?*')
_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class EditorNotFoundError(RuntimeError):
    """Visual Studio Code is not installed or not discoverable."""


def editor_executable():
    for candidate in _editor_candidates():
        if candidate.is_file():
            return candidate
    on_path = shutil.which("code")
    return Path(on_path) if on_path else None


def _editor_candidates():
    candidates = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "Microsoft VS Code" / "Code.exe")
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "Microsoft VS Code" / "Code.exe")
    return candidates


def safe_folder_name(name):
    candidate = str(name or "").strip()
    if not candidate or candidate in {".", ".."}:
        return False
    if any(character in _INVALID_NAME_CHARS for character in candidate):
        return False
    return candidate.casefold() not in _RESERVED_NAMES


def find_project(name):
    """Return the single project folder matching ``name`` inside a workspace root."""
    roots = discover_workspaces()
    if not roots:
        raise WorkspaceError(
            "No development workspaces are configured in Settings. Add a folder "
            "under development workspaces first."
        )
    requested = str(name or "").strip()
    if not requested:
        raise WorkspaceError("Tell me which project to open.")

    if _looks_like_path(requested):
        root, folder = workspace_for(requested)
        if not folder.exists():
            raise WorkspaceError(f'"{folder}" does not exist inside the workspace "{root}".')
        if not folder.is_dir():
            raise WorkspaceError(f'"{folder}" is not a folder.')
        return folder

    key = requested.casefold()
    matches = [root for root in roots if root.name.casefold() == key]
    matches.extend(
        child
        for root in roots
        for child in _child_folders(root)
        if child.name.casefold() == key
    )
    if not matches:
        matches = [
            child
            for root in roots
            for child in _child_folders(root)
            if key in child.name.casefold() and not child.name.startswith(".")
        ]
    if not matches:
        raise WorkspaceError(f'No project folder named "{requested}" was found in the workspaces.')
    unique = []
    for match in matches:
        if match not in unique:
            unique.append(match)
    if len(unique) > 1:
        listing = "\n".join(f"- {match}" for match in unique[:8])
        raise WorkspaceError(
            f'{len(unique)} project folders match "{requested}". Ask the user which one:\n{listing}'
        )
    return unique[0]


def create_project(name):
    """Create a new project folder under the first configured workspace root."""
    roots = discover_workspaces()
    if not roots:
        raise WorkspaceError(
            "No development workspaces are configured in Settings, so there is no "
            "safe place to create a project."
        )
    if not safe_folder_name(name):
        raise WorkspaceError(
            "Use a simple project name without path separators or reserved characters."
        )
    folder = workspace_for(roots[0] / str(name).strip())[1]
    if folder.exists():
        if folder.is_dir():
            return folder
        raise WorkspaceError(f'"{folder}" already exists and is not a folder.')
    folder.mkdir()
    return folder


def open_in_editor(folder):
    executable = editor_executable()
    if executable is None:
        raise EditorNotFoundError(
            f"{EDITOR_NAME} was not found. Install it or add the 'code' command to PATH."
        )
    subprocess.Popen([str(executable), str(folder)])
    return executable


def _child_folders(root):
    try:
        return sorted(child for child in root.iterdir() if child.is_dir())
    except OSError as exc:
        log.debug("Could not list workspace %s: %s", root, exc)
        return []


def _looks_like_path(name):
    return (
        os.path.isabs(name)
        or name.startswith(("~", "."))
        or "\\" in name
        or "/" in name
    )
