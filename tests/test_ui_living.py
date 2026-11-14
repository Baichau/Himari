import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from himari.ui_living import StatusDot, VoiceWaveform


def _app():
    return QApplication.instance() or QApplication([])


def test_waveform_modes_are_limited_to_real_voice_states():
    app = _app()
    wave = VoiceWaveform({}, bars=10)

    wave.set_mode("listening")
    assert wave.mode == "listening"
    wave.set_mode("speaking")
    assert wave.mode == "speaking"
    wave.set_mode("something-else")
    assert wave.mode == "idle"

    wave.set_mode("listening")
    wave.show()
    assert wave._timer.isActive()
    wave.set_mode("idle")
    assert not wave._timer.isActive()
    app.processEvents()


def test_waveform_level_is_clamped():
    _app()
    wave = VoiceWaveform({}, bars=10)

    wave.set_level(4.2)
    assert wave._level == 1.0
    wave.set_level(-3)
    assert wave._level == 0.0
    wave.set_level("not-a-number")
    assert wave._level == 0.0


def test_status_dot_ignores_invalid_colors():
    app = _app()
    dot = StatusDot("#ff7ebd")
    before = dot._color.name()

    dot.set_color("definitely-not-a-color")
    assert dot._color.name() == before

    dot.set_color("#7fe3b0")
    assert dot._color.name() == "#7fe3b0"
    app.processEvents()
