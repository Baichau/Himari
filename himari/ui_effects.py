"""Small, reusable Qt motion helpers.

Animations are deliberately short and quiet: a fade for new content, a pulse
for a status change, and a height transition for collapsible Settings groups.
Widgets that embed QtWebEngine are skipped by the tab fade because a graphics
effect can break their native compositing.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

QWIDGETSIZE_MAX = 16_777_215
_ANIMATION_ATTR = "_himari_animation"
_EFFECT_ATTR = "_himari_effect"


def _keep(widget, animation, effect=None):
    setattr(widget, _ANIMATION_ATTR, animation)
    if effect is not None:
        setattr(widget, _EFFECT_ATTR, effect)


def _drop_effect(widget, effect):
    try:
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
    except RuntimeError:
        pass


def _stop_previous(widget):
    previous = getattr(widget, _ANIMATION_ATTR, None)
    if previous is not None:
        try:
            previous.stop()
        except RuntimeError:
            pass


def fade_in(widget, duration=240, start=0.0, end=1.0, delay=0):
    """Fade a widget in without waiting for its layout to settle."""
    if widget is None:
        return None
    _stop_previous(widget)
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(float(start))
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(max(0, int(duration)))
    animation.setStartValue(float(start))
    animation.setEndValue(float(end))
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.finished.connect(lambda: _drop_effect(widget, effect))
    _keep(widget, animation, effect)
    if delay > 0:
        QTimer.singleShot(int(delay), animation.start)
    else:
        animation.start()
    return animation


def pulse(widget, duration=460, low=0.4):
    """Briefly dim a widget to draw attention without moving the layout."""
    if widget is None:
        return None
    _stop_previous(widget)
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(max(0, int(duration)))
    animation.setKeyValueAt(0.0, 1.0)
    animation.setKeyValueAt(0.35, float(low))
    animation.setKeyValueAt(1.0, 1.0)
    animation.setEasingCurve(QEasingCurve.Type.InOutSine)
    animation.finished.connect(lambda: _drop_effect(widget, effect))
    _keep(widget, animation, effect)
    animation.start()
    return animation


def fade_window(window, first_time=True):
    """Fade the main window in; later tray restores use a brisk short fade."""
    if window is None:
        return None
    start = 0.0 if first_time else 0.9
    duration = 300 if first_time else 140
    try:
        window.setWindowOpacity(start)
    except RuntimeError:
        return None
    animation = QPropertyAnimation(window, b"windowOpacity", window)
    animation.setDuration(duration)
    animation.setStartValue(start)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.finished.connect(lambda: window.setWindowOpacity(1.0))
    _keep(window, animation)
    animation.start()
    return animation


def _contains_web_view(widget):
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except Exception:  # pragma: no cover - depends on the Qt build
        return False
    try:
        return bool(widget.findChildren(QWebEngineView))
    except RuntimeError:
        return False


class AnimatedTabWidget(QTabWidget):
    """Tab widget that fades non-web pages when the active tab changes."""

    def __init__(self, parent=None, duration=210):
        super().__init__(parent)
        self._fade_duration = int(duration)
        self.currentChanged.connect(self._on_current_changed)

    def _on_current_changed(self, index):
        page = self.widget(index)
        if page is None or _contains_web_view(page):
            return
        fade_in(page, duration=self._fade_duration, start=0.55)


class CollapsibleSection(QFrame):
    """A Settings card whose body expands and collapses with a soft animation."""

    def __init__(self, title, parent=None, expanded=True, duration=190):
        super().__init__(parent)
        self.setObjectName("SettingsSection")
        self._title = str(title or "")
        self._expanded = bool(expanded)
        self._duration = int(duration)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.header = QPushButton(self)
        self.header.setObjectName("SectionHeader")
        self.header.setCheckable(True)
        self.header.setChecked(self._expanded)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.header.toggled.connect(self._on_toggled)
        layout.addWidget(self.header)

        self.body = QWidget(self)
        self.body.setObjectName("SectionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(14, 2, 14, 12)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)

        self._update_header()
        if not self._expanded:
            self.body.setMaximumHeight(0)
            self.body.setVisible(False)

    @property
    def expanded(self):
        return self._expanded

    def addWidget(self, widget):
        self.body_layout.addWidget(widget)
        return widget

    def addLayout(self, layout):
        self.body_layout.addLayout(layout)
        return layout

    def addHint(self, text):
        from PySide6.QtWidgets import QLabel

        label = QLabel(str(text), self.body)
        label.setObjectName("SectionHint")
        label.setWordWrap(True)
        self.body_layout.addWidget(label)
        return label

    def _update_header(self):
        arrow = "▾" if self._expanded else "▸"
        self.header.setText(f"{arrow}   {self._title}")

    def _on_toggled(self, expanded):
        self._expanded = bool(expanded)
        self._update_header()
        self._animate(expanded)

    def _animate(self, expanded):
        if self._duration <= 0:
            self.body.setVisible(expanded)
            self.body.setMaximumHeight(QWIDGETSIZE_MAX if expanded else 0)
            return
        previous = getattr(self, _ANIMATION_ATTR, None)
        if previous is not None:
            previous.stop()
        if expanded:
            self.body.setVisible(True)
            target = max(self.body.sizeHint().height(), 1)
            start = self.body.height()
        else:
            start = self.body.height() or self.body.sizeHint().height()
            target = 0
        animation = QPropertyAnimation(self.body, b"maximumHeight", self)
        animation.setDuration(self._duration)
        animation.setStartValue(max(0, int(start)))
        animation.setEndValue(int(target))
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        if expanded:
            animation.finished.connect(
                lambda: self.body.setMaximumHeight(QWIDGETSIZE_MAX)
            )
        else:
            animation.finished.connect(lambda: self.body.setVisible(False))
        _keep(self, animation)
        animation.start()
