"""Permitted development workspaces.

Only directories listed under ``development.workspaces`` in Settings are
accessible. Workspace discovery is read-only and never creates folders.
"""

import logging
import os
from pathlib import Path

from ..config import load as load_config

log = logging.getLogger("himari.development")


class WorkspaceError(RuntimeError):
    """A path is outside the permitted workspaces or otherwise invalid."""


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