"""Bounded text search inside permitted workspaces."""

from .file_reader import MAX_FILE_BYTES, _TEXT_ENCODINGS, is_sensitive
from .workspace import WorkspaceError, workspace_for

IGNORED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    "build", "dist", ".pytest_cache", ".mypy_cache", ".idea",
}
MAX_RESULTS = 200


def _iter_files(start):
    if start.is_file():
        if not is_sensitive(start):
            yield start
        return
    for child in sorted(start.rglob("*")):
        if any(part in IGNORED_DIRS for part in child.relative_to(start).parts):
            continue
        if child.is_file() and not is_sensitive(child):
            yield child


def _decode(data):
    for encoding in _TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def search_code(path, query, max_results=MAX_RESULTS):
    if not isinstance(query, str) or not query.strip():
        raise WorkspaceError("Provide text to search for.")
    root, start = workspace_for(path)
    needle = query.casefold()
    results = []
    for file in _iter_files(start):
        try:
            data = file.read_bytes()
        except OSError:
            continue
        if len(data) > MAX_FILE_BYTES:
            continue
        text = _decode(data)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.casefold():
                results.append({
                    "path": str(file.relative_to(root)).replace("\\", "/"),
                    "line": number,
                    "text": line.strip()[:300],
                })
                if len(results) >= max_results:
                    return results
    return results