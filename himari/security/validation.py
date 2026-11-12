"""Validation helpers for paths, commands and untrusted text."""

import os
from pathlib import Path

from ..development.test_runner import validate_command as _validate_command
from ..development.workspace import WorkspaceError
from .policies import (
    BLOCKED_FILE_NAMES,
    BLOCKED_FILE_SUFFIXES,
    BLOCKED_PATH_PARTS,
)


class ValidationError(RuntimeError):
    """An argument failed security validation."""


def validate_path(path, allowed_roots=None):
    """Resolve a path and enforce root confinement plus safe-file rules."""
    if path is None or str(path).strip() == "":
        raise ValidationError("No path provided.")
    resolved = Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve(strict=False)
    lowered = str(resolved).casefold()
    if any(part in lowered for part in BLOCKED_PATH_PARTS):
        raise ValidationError("Access to Windows system directories is not permitted.")
    name = resolved.name.casefold()
    if name in BLOCKED_FILE_NAMES or name.startswith(".env"):
        raise ValidationError("Sensitive credential files cannot be accessed.")
    if resolved.suffix.casefold() in BLOCKED_FILE_SUFFIXES:
        raise ValidationError("Private key and certificate files cannot be accessed.")
    if allowed_roots:
        roots = [
            Path(os.path.expandvars(os.path.expanduser(str(root)))).resolve(strict=False)
            for root in allowed_roots
        ]
        if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
            raise ValidationError("The path is outside the permitted folders.")
    return resolved


def validate_command(command):
    try:
        return _validate_command(command)
    except WorkspaceError as exc:
        raise ValidationError(str(exc)) from exc


def validate_text(value, field="value", max_length=20_000):
    if not isinstance(value, str):
        raise ValidationError(f"The {field} must be text.")
    if len(value) > max_length:
        raise ValidationError(f"The {field} is too long.")
    if any(character in value for character in "\x00"):
        raise ValidationError(f"The {field} contains invalid characters.")
    return value