import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from himari.log_viewer import (
    LogViewerDialog,
    filter_log,
    level_of,
    read_log_tail,
)


def _app():
    return QApplication.instance() or QApplication([])


def test_level_of_parses_formatted_log_lines():
    assert level_of("2026-11-12 17:00:00,123 ERROR himari.llm: boom") == "ERROR"
    assert level_of('  File "x.py", line 1') == ""
    assert level_of("") == ""


def test_filter_log_uses_a_minimum_level_and_keeps_tracebacks():
    text = "\n".join([
        "2026-11-12 17:00:00,100 INFO himari.ui: started",
        "2026-11-12 17:00:01,100 WARNING himari.voice: mic missing",
        "2026-11-12 17:00:02,100 ERROR himari.llm: boom",
        "Traceback (most recent call last):",
        "RuntimeError: boom",
        "2026-11-12 17:00:03,100 INFO himari.ui: idle",
    ])

    visible = filter_log(text, "WARNING")

    assert "started" not in visible
    assert "mic missing" in visible
    assert "RuntimeError: boom" in visible
    assert "idle" not in visible


def test_filter_log_searches_case_insensitively():
    text = "2026-11-12 17:00:00,100 INFO himari.ui: Ollama started"

    assert "Ollama" in filter_log(text, query="ollama")
    assert filter_log(text, query="no such text") == ""


def test_read_log_tail_reads_the_end_and_skips_a_partial_line(tmp_path):
    path = tmp_path / "himari.log"
    path.write_bytes(b"old line\nnew line\n")

    text, error = read_log_tail(path, max_bytes=10)

    assert error == ""
    assert text == "new line\n"


def test_read_log_tail_keeps_the_line_when_the_tail_starts_at_a_boundary(tmp_path):
    path = tmp_path / "himari.log"
    path.write_bytes(b"first\nsecond\n")

    text, error = read_log_tail(path, max_bytes=7)

    assert error == ""
    assert text == "second\n"


def test_read_log_tail_reads_a_short_file_whole(tmp_path):
    path = tmp_path / "himari.log"
    path.write_bytes(b"only line\n")

    text, error = read_log_tail(path, max_bytes=10_000)

    assert error == ""
    assert text == "only line\n"


def test_read_log_tail_reports_a_missing_file(tmp_path):
    text, error = read_log_tail(tmp_path / "missing.log")

    assert text == ""
    assert "No log file yet" in error


def test_log_viewer_dialog_filters_and_copies(tmp_path):
    app = _app()
    path = tmp_path / "himari.log"
    path.write_text(
        "2026-11-12 10:00:00,000 INFO himari.ui: started\n"
        "2026-11-12 10:00:01,000 ERROR himari.llm: boom\n",
        encoding="utf-8",
    )

    dialog = LogViewerDialog(log_path=path)

    assert "started" in dialog.output.toPlainText()
    dialog.level.setCurrentText("ERROR")
    assert "started" not in dialog.output.toPlainText()
    assert "boom" in dialog.output.toPlainText()
    dialog._copy()
    assert "boom" in app.clipboard().text()
    dialog.deleteLater()


def test_log_viewer_dialog_reports_a_missing_log(tmp_path):
    _app()

    dialog = LogViewerDialog(log_path=tmp_path / "missing.log")

    assert "No log file yet" in dialog.info.text()
    assert dialog.output.toPlainText() == ""
    dialog.deleteLater()
