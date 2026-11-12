import subprocess
from unittest.mock import Mock

import pytest

from himari.development import (
    ChangeRejectedError,
    WorkspaceError,
    apply_change,
    discover_workspaces,
    propose_change,
    read_source,
    run_tests,
    search_code,
    validate_command,
)
from himari.development import code_search, editor, file_reader, test_runner, workspace


@pytest.fixture()
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n\"\"\"utf-8\"\"\"\n", encoding="utf-8")
    (root / "notes.txt").write_text("find me\nother line\nfind me again\n", encoding="utf-8")
    (root / "dist").mkdir()
    (root / "dist" / "bundle.js").write_text("find me in build output", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "lib.py").write_text("find me in venv", encoding="utf-8")
    (root / ".env").write_text("API_KEY=find-me-secret", encoding="utf-8")
    monkeypatch.setattr(workspace, "load_config", lambda: {"development": {"workspaces": [str(root)]}})
    return root


def test_discover_workspaces_filters_missing_paths(tmp_path, monkeypatch):
    existing = tmp_path / "ws"
    existing.mkdir()
    monkeypatch.setattr(workspace, "load_config", lambda: {"development": {"workspaces": [
        str(existing), str(tmp_path / "missing"), "", str(existing),
    ]}})

    assert discover_workspaces() == [existing.resolve()]


def test_paths_outside_workspaces_are_rejected(project, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(WorkspaceError):
        read_source(outside)
    with pytest.raises(WorkspaceError):
        search_code(outside.parent, "secret")


def test_read_source_returns_content_and_encoding(project):
    result = read_source(project / "notes.txt")

    assert result["encoding"] == "utf-8"
    assert "find me" in result["content"]
    assert result["workspace"] == str(project.resolve())


def test_read_source_blocks_sensitive_files(project):
    with pytest.raises(PermissionError):
        read_source(project / ".env")
    key = project / "server.key"
    key.write_text("private", encoding="utf-8")
    with pytest.raises(PermissionError):
        read_source(key)


def test_read_source_preserves_non_utf8_encodings(project):
    cyrillic = project / "cryllic.txt"
    cyrillic.write_bytes("привет мир".encode("cp1251"))

    result = read_source(cyrillic)

    assert result["content"] == "привет мир"
    assert result["encoding"] == "cp1251"


def test_search_skips_build_env_and_sensitive_files(project):
    results = search_code(project, "find me")
    paths = {item["path"] for item in results}

    assert "notes.txt" in paths
    assert not any(path.startswith("dist/") for path in paths)
    assert not any(".venv" in path for path in paths)
    assert not any(".env" in path for path in paths)
    assert {item["line"] for item in results if item["path"] == "notes.txt"} == {1, 3}


def test_search_is_bounded_and_rejects_empty_queries(project):
    result = search_code(project, "find me", max_results=1)

    assert len(result) == 1
    with pytest.raises(WorkspaceError):
        search_code(project, "  ")


def test_propose_change_returns_a_unified_diff(project):
    change = propose_change(project / "notes.txt", "find me\nchanged line\n")

    assert change["changed"] is True
    assert "--- a/notes.txt" in change["diff"]
    assert "+++ b/notes.txt" in change["diff"]
    assert "+changed line" in change["diff"]


def test_apply_change_requires_approval(project):
    path = project / "notes.txt"
    with pytest.raises(ChangeRejectedError):
        apply_change(path, "replacement", approve=None)
    with pytest.raises(ChangeRejectedError):
        apply_change(path, "replacement", approve=lambda change: False)
    assert "find me" in path.read_text(encoding="utf-8")

    result = apply_change(path, "replacement\n", approve=lambda change: True)

    assert result["applied"] is True
    assert path.read_text(encoding="utf-8") == "replacement\n"


def test_apply_change_reports_noop(project):
    path = project / "notes.txt"
    current = path.read_text(encoding="utf-8")

    result = apply_change(path, current, approve=Mock(side_effect=AssertionError("no approval needed")))

    assert result["applied"] is False


def test_apply_change_keeps_original_encoding(project):
    path = project / "cryllic.txt"
    path.write_bytes("старый текст".encode("cp1251"))

    apply_change(path, "новый текст", approve=lambda change: True)

    assert path.read_bytes().decode("cp1251") == "новый текст"


def test_validate_command_allows_only_known_programs():
    assert validate_command(["python", "-m", "pytest", "-q"]) == ["python", "-m", "pytest", "-q"]
    assert validate_command(["pytest", "-q"]) == ["pytest", "-q"]

    for bad in ([], "python -m pytest", ["cmd", "/c", "dir"], ["powershell", "-Command", "x"], [1, 2]):
        with pytest.raises(WorkspaceError):
            validate_command(bad)
    with pytest.raises(WorkspaceError):
        validate_command(["python", "line\nbreak"])


def test_run_tests_requires_approval_and_validates_cwd(project, tmp_path):
    with pytest.raises(PermissionError):
        run_tests(project)
    with pytest.raises(PermissionError):
        run_tests(project, approve=lambda request: False)
    with pytest.raises(WorkspaceError):
        run_tests(tmp_path / "outside", approve=lambda request: True)


def test_run_tests_executes_with_capture(project, monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess(["python"], 0, stdout="ok", stderr=""))
    monkeypatch.setattr(test_runner.subprocess, "run", run)
    approvals = []

    result = run_tests(project, approve=lambda request: approvals.append(request) or True, timeout=30)

    assert result["ok"] is True
    assert result["stdout"] == "ok"
    assert approvals[0]["command"] == ["python", "-m", "pytest", "-q"]
    assert run.call_args.kwargs["cwd"] == project.resolve()
    assert run.call_args.kwargs["timeout"] == 30
    assert "shell" not in run.call_args.kwargs


def test_run_tests_reports_timeout_and_os_errors(project, monkeypatch):
    monkeypatch.setattr(test_runner.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("python", 1)))

    result = run_tests(project, approve=lambda request: True, timeout=1)

    assert result["ok"] is False
    assert "timed out" in result["error"]

    monkeypatch.setattr(test_runner.subprocess, "run", Mock(side_effect=OSError("python missing")))

    result = run_tests(project, approve=lambda request: True)

    assert result["ok"] is False
    assert "python missing" in result["error"]


def test_run_tests_honors_cancellation(project):
    token = Mock()
    token.check.side_effect = RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        run_tests(project, approve=lambda request: True, token=token)