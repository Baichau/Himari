"""Permitted development workspaces.

Only directories listed under ``development.workspaces`` in Settings are
accessible. Workspace discovery is read-only and never creates folders.
"""

import logging
import os
import threading
from pathlib import Path

from ..config import load as load_config

log = logging.getLogger("himari.development")

_active_project = None
_active_lock = threading.Lock()


class WorkspaceError(RuntimeError):
    """A path is outside the permitted workspaces or otherwise invalid."""


def set_active_project(path):
    """Remember the project folder the user just opened.

    Only a folder inside a configured workspace is accepted, so later relative
    reads can never escape the allow-list.
    """
    global _active_project
    if path is None:
        with _active_lock:
            _active_project = None
        return None
    _, resolved = workspace_for(path)
    if not resolved.is_dir():
        raise WorkspaceError(f"'{resolved}' is not a project folder.")
    with _active_lock:
        _active_project = resolved
    return resolved


def active_project():
    with _active_lock:
        return _active_project


def discover_workspaces():
    config = load_config()
    section = config.get("development", {}) if isinstance(config, dict) else {}
    entries = section.get("workspaces", [])
    if not isinstance(entries, (list, tuple)):
        return []
    workspaces = []
    for entry in entries:
        if not entry:
            continue
        path = Path(os.path.expandvars(os.path.expanduser(str(entry)))).resolve(strict=False)
        if path.is_dir() and path not in workspaces:
            workspaces.append(path)
    return workspaces


def workspace_for(path):
    """Return (workspace_root, resolved_path) after enforcing the allow-list."""
    requested = Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve(strict=False)
    for root in discover_workspaces():
        if requested == root or requested.is_relative_to(root):
            return root, requested
    raise WorkspaceError("This path is outside the configured development workspaces.")