from types import SimpleNamespace

from himari.ui import UI


class _Widget:
    def __init__(self):
        self.text = ""
        self.visible = None
        self.enabled = None

    def setText(self, value):
        self.text = value

    def setPlainText(self, value):
        self.text = value

    def setVisible(self, visible):
        self.visible = visible

    def setEnabled(self, enabled):
        self.enabled = enabled


def _watch_window():
    return SimpleNamespace(
        watch_card=_Widget(),
        watch_left=_Widget(),
        companion_watch_btn=_Widget(),
        companion_watch_status=_Widget(),
    )


def test_watch_indicator_is_visible_while_watching():
    window = _watch_window()
    UI._apply_watch_status(
        window,
        {
            "running": True,
            "remaining_text": "12:00",
            "interval_seconds": 20,
            "limit_minutes": 30,
            "last": {"game": "Valorant"},
        },
    )
    assert window.watch_card.visible is True
    assert window.watch_left.text == "12:00"
    assert window.companion_watch_btn.text == "Stop watching"
    assert "Valorant" in window.companion_watch_status.text


def test_watch_indicator_hides_when_the_session_is_off():
    window = _watch_window()
    UI._apply_watch_status(
        window,
        {
            "running": False,
            "remaining_text": "",
            "interval_seconds": 20,
            "limit_minutes": 30,
            "last": None,
        },
    )
    assert window.watch_card.visible is False
    assert window.companion_watch_btn.text == "Watch with me"
    assert "Watch is off" in window.companion_watch_status.text


def test_coach_and_doctor_results_re_enable_their_buttons():
    coach_window = SimpleNamespace(coach_text=_Widget(), coach_verify_btn=_Widget())
    UI._apply_coach(coach_window, "Spotify is ready.")
    assert coach_window.coach_text.text == "Spotify is ready."
    assert coach_window.coach_verify_btn.enabled is True

    doctor_window = SimpleNamespace(
        doctor_text=_Widget(),
        doctor_system_btn=_Widget(),
        doctor_program_btn=_Widget(),
    )
    UI._apply_doctor(doctor_window, "System Doctor — read-only snapshot")
    assert "read-only" in doctor_window.doctor_text.text
    assert doctor_window.doctor_system_btn.enabled is True
    assert doctor_window.doctor_program_btn.enabled is True
