"""Approved, validated project test runs with timeouts and cancellation."""

import subprocess
from pathlib import Path

from .workspace import WorkspaceError, workspace_for

ALLOWED_EXECUTABLES = {
    "python", "python.exe", "py", "py.exe",
    "pytest", "pytest.exe", "npm", "npm.cmd", "node", "node.exe",
}
DEFAULT_TIMEOUT_SECONDS = 300
OUTPUT_LIMIT = 8000


def validate_command(command):
    if not isinstance(command, (list, tuple)) or not command:
        raise WorkspaceError("A test command must be a list of program and arguments.")
    program = Path(str(command[0])).name.casefold()
    if program not in ALLOWED_EXECUTABLES:
        raise WorkspaceError(f"Executable '{program}' is not allowed for test runs.")
    validated = []
    for argument in command:
        if not isinstance(argument, str):
            raise WorkspaceError("Command arguments must be strings.")
        if any(character in argument for character in "\r\n\x00"):
            raise WorkspaceError("The command contains invalid control characters.")
        validated.append(argument)
    return validated


def run_tests(path, command=None, approve=None, timeout=DEFAULT_TIMEOUT_SECONDS, token=None):
    """Run project tests through subprocess with a validated argument list."""
    root, start = workspace_for(path)
    if not start.is_dir():
        raise WorkspaceError("The test workspace must be a directory.")
    validated = validate_command(command or ["python", "-m", "pytest", "-q"])
    if approve is None or not approve({"workspace": str(start), "command": validated}):
        raise PermissionError("Running project tests requires explicit approval.")
    if token is not None:
        token.check()
    try:
        result = subprocess.run(
            validated,
            cwd=start,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"Test run timed out after {timeout} seconds.",
            "command": validated,
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc), "command": validated}
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "command": validated,
        "workspace": str(root),
        "stdout": (result.stdout or "")[-OUTPUT_LIMIT:],
        "stderr": (result.stderr or "")[-OUTPUT_LIMIT:],
    }