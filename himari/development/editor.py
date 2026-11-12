"""Proposed code changes as unified diffs, applied only with approval."""

import difflib
from pathlib import Path

from .file_reader import read_source
from .workspace import WorkspaceError


class ChangeRejectedError(RuntimeError):
    """The user did not approve the proposed change."""


def propose_change(path, new_content):
    """Return the diff between the file on disk and the proposed content."""
    if not isinstance(new_content, str):
        raise WorkspaceError("New content must be a string.")
    original = read_source(path)
    target = Path(original["path"])
    original_text = original["content"].replace("\r\n", "\n")
    proposed_text = new_content.replace("\r\n", "\n")
    diff = difflib.unified_diff(
        original_text.splitlines(keepends=True),
        proposed_text.splitlines(keepends=True),
        fromfile=f"a/{target.name}",
        tofile=f"b/{target.name}",
    )
    return {
        "path": original["path"],
        "encoding": original["encoding"],
        "diff": "".join(diff),
        "changed": original_text != proposed_text,
    }


def apply_change(path, new_content, approve):
    """Apply a change only after the approval callback returns True."""
    change = propose_change(path, new_content)
    if not change["changed"]:
        return {**change, "applied": False, "message": "No changes to apply."}
    if approve is None or not approve(change):
        raise ChangeRejectedError("The proposed change was not approved.")
    Path(change["path"]).write_text(new_content, encoding=change["encoding"], newline="")
    return {**change, "applied": True, "message": f"Applied changes to {change['path']}."}