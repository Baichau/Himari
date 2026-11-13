"""Development assistant: workspace-restricted reading, search, edits, tests."""

from .code_search import search_code
from .editor import ChangeRejectedError, apply_change, propose_change
from .file_reader import is_sensitive, read_source
from .launcher import (
    EditorNotFoundError,
    create_project,
    find_project,
    open_in_editor,
    safe_folder_name,
)
from .test_runner import run_tests, validate_command
from .workspace import WorkspaceError, discover_workspaces, workspace_for

__all__ = [
    "WorkspaceError",
    "ChangeRejectedError",
    "EditorNotFoundError",
    "discover_workspaces",
    "workspace_for",
    "read_source",
    "is_sensitive",
    "search_code",
    "propose_change",
    "apply_change",
    "run_tests",
    "validate_command",
    "find_project",
    "create_project",
    "open_in_editor",
    "safe_folder_name",
]