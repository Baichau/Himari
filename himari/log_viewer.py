"""In-app application log viewer.

Reads a bounded tail of the rotating log file so opening the viewer never
loads a multi-megabyte file onto the UI thread.
"""

import os
import re
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .logging_setup import log_file_path

LOG_TAIL_BYTES = 200_000

_SEVERITY = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 40}
_LEVEL_LINE = re.compile(r"^\S+\s+\S+\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s")


def level_of(line):
    """Return the log level token of a formatted line, or an empty string."""
    match = _LEVEL_LINE.match(str(line or ""))
    return match.group(1) if match else ""


def read_log_tail(path=None, max_bytes=LOG_TAIL_BYTES):
    """Return ``(text, error)`` for the last ``max_bytes`` of the log file."""
    path = Path(path) if path is not None else log_file_path()
    limit = max(1, int(max_bytes))
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            start = max(0, handle.tell() - limit)
            previous = b""
            if start > 0:
                handle.seek(start - 1)
                previous = handle.read(1)
            handle.seek(start)
            data = handle.read()
    except FileNotFoundError:
        return "", f"No log file yet at {path}."
    except OSError as exc:
        return "", f"Could not read {path}: {exc}"
    text = data.decode("utf-8", errors="replace")
    if start > 0 and previous != b"\n":
        newline = text.find("\n")
        text = "" if newline < 0 else text[newline + 1:]
    return text, ""


def filter_log(text, level="", query=""):
    """Filter a log tail by minimum level and a case-insensitive query.

    Unleveled continuation lines (tracebacks) stay with the entry above them.
    """
    wanted = str(level or "").strip().upper()
    threshold = _SEVERITY.get(wanted)
    needle = str(query or "").strip().casefold()
    kept = []
    include = True
    for line in str(text or "").splitlines():
        line_level = level_of(line)
        if line_level:
            include = threshold is None or _SEVERITY.get(line_level, 0) >= threshold
        if not include:
            continue
        if needle and needle not in line.casefold():
            continue
        kept.append(line)
    return "\n".join(kept)


class LogViewerDialog(QDialog):
    """Read-only snapshot of the log with level and text filters."""

    def __init__(self, parent=None, log_path=None, max_bytes=LOG_TAIL_BYTES):
        super().__init__(parent)
        self.setObjectName("LogViewer")
        self.setWindowTitle("Application log")
        self.resize(920, 620)
        self._log_path = Path(log_path) if log_path is not None else log_file_path()
        self._max_bytes = max(1, int(max_bytes))
        self._text = ""

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Level:"))
        self.level = QComboBox()
        self.level.addItems(["All", "DEBUG", "INFO", "WARNING", "ERROR"])
        controls.addWidget(self.level)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter text…")
        self.search.setClearButtonEnabled(True)
        controls.addWidget(self.search, 1)
        self.refresh_button = QPushButton("Refresh")
        self.copy_button = QPushButton("Copy")
        self.folder_button = QPushButton("Open folder")
        for button in (self.refresh_button, self.copy_button, self.folder_button):
            controls.addWidget(button)
        layout.addLayout(controls)

        self.info = QLabel()
        self.info.setObjectName("MutedLine")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.output = QPlainTextEdit()
        self.output.setObjectName("LogOutput")
        self.output.setReadOnly(True)
        font = QFont("Cascadia Mono", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.output.setFont(font)
        layout.addWidget(self.output, 1)

        self.level.currentTextChanged.connect(self._render)
        self.search.textChanged.connect(self._render)
        self.refresh_button.clicked.connect(self.refresh)
        self.copy_button.clicked.connect(self._copy)
        self.folder_button.clicked.connect(self._open_folder)

        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._reset_copy_label)
        self.refresh()

    def refresh(self):
        self._text, error = read_log_tail(self._log_path, self._max_bytes)
        if error:
            self.info.setText(error)
        else:
            self.info.setText(
                f"{self._log_path} · last {self._max_bytes // 1000} KB snapshot. "
                "Press Refresh to update."
            )
        self._render()

    def _render(self):
        visible = filter_log(
            self._text, self.level.currentText(), self.search.text()
        )
        self.output.setPlainText(visible)
        scroll = self.output.verticalScrollBar()
        scroll.setValue(scroll.maximum())

    def _copy(self):
        QApplication.clipboard().setText(self.output.toPlainText())
        self.copy_button.setText("Copied")
        self._copy_timer.start(1200)

    def _reset_copy_label(self):
        self.copy_button.setText("Copy")

    def _open_folder(self):
        folder = self._log_path.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.info.setText(f"Could not open the log folder: {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
