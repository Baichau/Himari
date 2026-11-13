"""Reusable input widgets for the desktop UI.

KeyCaptureButton turns a Qt key event into a chord understood by the
``keyboard`` package, so users can pick their own global shortcuts instead of
typing fragile key names by hand.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QPushButton

_MODIFIERS = (
    (Qt.KeyboardModifier.ControlModifier, "ctrl"),
    (Qt.KeyboardModifier.AltModifier, "alt"),
    (Qt.KeyboardModifier.ShiftModifier, "shift"),
    (Qt.KeyboardModifier.MetaModifier, "windows"),
)
_MODIFIER_KEYS = {
    Qt.Key.Key_Control,
    Qt.Key.Key_Shift,
    Qt.Key.Key_Alt,
    Qt.Key.Key_AltGr,
    Qt.Key.Key_Meta,
    Qt.Key.Key_CapsLock,
    Qt.Key.Key_NumLock,
    Qt.Key.Key_ScrollLock,
}
_NAMED_KEYS = {
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "page up",
    Qt.Key.Key_PageDown: "page down",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Pause: "pause",
    Qt.Key.Key_Print: "print screen",
    Qt.Key.Key_Menu: "apps",
}
_SAFE_PUNCTUATION = set("-=[];',./\\`")
_MODIFIER_ORDER = {"ctrl": 0, "alt": 1, "shift": 2, "windows": 3}


def normalize_chord(text):
    """Normalize a chord to lowercase, de-duplicated, modifier-first form."""
    parts = []
    for raw in str(text or "").replace(" ", "").split("+"):
        part = raw.strip().casefold()
        if part and part not in parts:
            parts.append(part)
    parts.sort(key=lambda part: _MODIFIER_ORDER.get(part, 99))
    return "+".join(parts)


def chord_from_key(key, modifiers, text=""):
    """Build a keyboard-package chord from a Qt key press, or None."""
    if key in _MODIFIER_KEYS or key == Qt.Key.Key_Escape or not key:
        return None
    name = None
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        name = chr(key).lower()
    elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        name = chr(key)
    elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        name = f"f{key - Qt.Key.Key_F1 + 1}"
    elif key in _NAMED_KEYS:
        name = _NAMED_KEYS[key]
    else:
        candidate = str(text or "").strip()
        if len(candidate) == 1 and candidate in _SAFE_PUNCTUATION:
            name = candidate
    if not name:
        return None
    parts = [label for flag, label in _MODIFIERS if modifiers & flag]
    parts.append(name)
    return "+".join(parts)


def _is_function_key(name):
    return (
        len(name) in (2, 3)
        and name.startswith("f")
        and name[1:].isdigit()
        and 1 <= int(name[1:]) <= 24
    )


def validate_chord(chord):
    """Return a human-readable problem, or None when the chord is safe."""
    normalized = normalize_chord(chord)
    if not normalized:
        return "Press a key combination, for example Ctrl + Alt + A."
    parts = normalized.split("+")
    if len(parts) == 1 and not _is_function_key(parts[0]):
        if parts[0].isdigit() or parts[0] in _SAFE_PUNCTUATION:
            return "Add Ctrl, Alt or Shift so typing does not trigger it."
        return "Use a modifier plus a key, or a function key such as F9."
    if not parts[-1] or parts[-1] in _MODIFIER_ORDER:
        return "The shortcut needs a normal key at the end."
    return None


def display_chord(chord):
    normalized = normalize_chord(chord)
    if not normalized:
        return "Not set"
    return " + ".join(part.upper() for part in normalized.split("+"))


class KeyCaptureButton(QPushButton):
    """A button that records the next keyboard shortcut the user presses."""

    chordChanged = Signal(str)
    captureStarted = Signal()
    captureFinished = Signal()

    def __init__(self, chord="", parent=None):
        super().__init__(parent)
        self._chord = normalize_chord(chord)
        self._capturing = False
        self._restore_text = ""
        self.setObjectName("KeyCaptureButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            "Click, then press the shortcut you want. Esc cancels; "
            "Backspace clears it."
        )
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.setInterval(1400)
        self._restore_timer.timeout.connect(self._restore_label)
        self.clicked.connect(self._begin_capture)
        self.setChord(self._chord, emit=False)

    def chord(self):
        return self._chord

    def currentChord(self):
        return self._chord

    def setChord(self, chord, emit=True):
        normalized = normalize_chord(chord)
        self._chord = normalized
        self.setText(display_chord(normalized))
        if emit:
            self.chordChanged.emit(normalized)

    def _set_capturing_style(self):
        self.setProperty("capturing", self._capturing)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def _begin_capture(self):
        if self._capturing:
            return
        self._capturing = True
        self._restore_text = self.text()
        self.setText("Press keys…")
        self._set_capturing_style()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        try:
            self.grabKeyboard()
        except RuntimeError:
            pass
        self.captureStarted.emit()

    def _end_capture(self):
        if not self._capturing:
            return
        self._capturing = False
        self._set_capturing_style()
        try:
            self.releaseKeyboard()
        except RuntimeError:
            pass
        if not self._chord:
            self.setText("Not set")
        self.captureFinished.emit()

    def _cancel_capture(self):
        if not self._capturing:
            return
        self._end_capture()
        self.setText(self._restore_text or display_chord(self._chord))

    def _flash_problem(self, message):
        self._end_capture()
        self.setText(str(message))
        self._restore_timer.start()

    def _restore_label(self):
        if not self._capturing:
            self.setText(display_chord(self._chord))

    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel_capture()
            event.accept()
            return
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self._end_capture()
            self.setChord("", emit=True)
            event.accept()
            return
        chord = chord_from_key(key, event.modifiers(), event.text())
        if chord is None:
            if key in _MODIFIER_KEYS or key in (
                Qt.Key.Key_Control,
                Qt.Key.Key_Shift,
                Qt.Key.Key_Alt,
                Qt.Key.Key_Meta,
            ):
                self.setText("Now press a key…")
            event.accept()
            return
        problem = validate_chord(chord)
        if problem:
            self._flash_problem(problem)
            event.accept()
            return
        self._end_capture()
        self.setChord(chord, emit=True)
        event.accept()

    def keyReleaseEvent(self, event):
        if self._capturing:
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        if self._capturing:
            self._cancel_capture()
            event.accept()
            return
        super().mousePressEvent(event)

    def focusOutEvent(self, event):
        self._cancel_capture()
        super().focusOutEvent(event)
