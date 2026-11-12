"""Workspace-restricted source file reading.

Sensitive files (.env, credentials, private keys) are refused by default.
"""

from pathlib import Path

from .workspace import WorkspaceError, workspace_for

MAX_FILE_BYTES = 1_000_000
_SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_ed25519", "credentials", "credentials.json",
    "secrets", "secrets.json", "ntds.dit",
}
_SENSITIVE_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".keystore", ".env", ".ppk"}
_TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "cp1251", "latin-1")


def is_sensitive(path):
    name = Path(path).name.casefold()
    if name in _SENSITIVE_NAMES or name.startswith(".env"):
        return True
    return Path(path).suffix.casefold() in _SENSITIVE_SUFFIXES


def read_source(path):
    root, target = workspace_for(path)
    if is_sensitive(target):
        raise PermissionError(f"Refusing to read sensitive file: {target.name}")
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {target}")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise WorkspaceError("File is too large to read safely.")
    data = target.read_bytes()
    for encoding in _TEXT_ENCODINGS:
        try:
            return {
                "path": str(target),
                "workspace": str(root),
                "encoding": encoding,
                "content": data.decode(encoding),
            }
        except UnicodeDecodeError:
            continue
    raise WorkspaceError("Could not decode the file as text.")