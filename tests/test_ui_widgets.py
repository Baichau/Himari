from PySide6.QtCore import Qt

from himari.ui_widgets import (
    chord_from_key,
    display_chord,
    normalize_chord,
    validate_chord,
)


def test_normalize_chord_is_lowercase_modifier_first_and_unique():
    assert normalize_chord("  SHIFT + Ctrl +A ") == "ctrl+shift+a"
    assert normalize_chord("Alt+alt+Space") == "alt+space"
    assert normalize_chord("") == ""


def test_chord_from_key_builds_keyboard_package_names():
    assert chord_from_key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier, "a") == "ctrl+a"
    assert chord_from_key(Qt.Key.Key_7, Qt.KeyboardModifier.NoModifier, "7") == "7"
    assert chord_from_key(Qt.Key.Key_F9, Qt.KeyboardModifier.NoModifier) == "f9"
    assert chord_from_key(Qt.Key.Key_Space, Qt.KeyboardModifier.AltModifier) == "alt+space"
    assert chord_from_key(
        Qt.Key.Key_S,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        "S",
    ) == "ctrl+shift+s"


def test_chord_from_key_ignores_modifier_presses_escape_and_unsafe_text():
    assert chord_from_key(Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier) is None
    assert chord_from_key(Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier) is None
    assert chord_from_key(Qt.Key(0), Qt.KeyboardModifier.NoModifier, "<") is None


def test_validate_chord_requires_a_real_shortcut():
    assert validate_chord("f9") is None
    assert validate_chord("ctrl+alt+a") is None
    assert "modifier" in validate_chord("a")
    assert "modifier" in validate_chord("f")
    assert "Ctrl" in validate_chord("7")
    assert "Ctrl" in validate_chord("-")
    assert "normal key" in validate_chord("ctrl+shift")
    assert "Press a key" in validate_chord("")


def test_display_chord_is_readable():
    assert display_chord("ctrl+shift+a") == "CTRL + SHIFT + A"
    assert display_chord("") == "Not set"
