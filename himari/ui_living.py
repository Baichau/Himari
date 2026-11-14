"""Living-companion widgets shared by the chat and Companion screens."""

from __future__ import annotations

import math

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

TICK_MS = 55


class VoiceWaveform(QWidget):
    """A waveform driven by the real microphone level or the TTS speaking flag."""

    def __init__(self, colors=None, bars=26, parent=None):
        super().__init__(parent)
        self._colors = dict(colors or {})
        self._bars = max(6, int(bars))
        self._mode = "idle"
        self._level = 0.0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(36)

    @property
    def mode(self):
        return self._mode

    def set_mode(self, mode):
        normalized = str(mode or "idle").strip().lower()
        if normalized not in {"idle", "listening", "speaking"}:
            normalized = "idle"
        self._mode = normalized
        if normalized == "idle":
            self._timer.stop()
            self._level = 0.0
        elif self.isVisible():
            self._timer.start()
        self.update()

    def set_level(self, level):
        try:
            value = float(level)
        except (TypeError, ValueError):
            value = 0.0
        self._level = max(0.0, min(1.0, value))

    def showEvent(self, event):
        super().showEvent(event)
        if self._mode != "idle":
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self._phase = (self._phase + 0.34) % (math.pi * 2)
        if self._mode == "listening":
            self._level *= 0.94
        self.update()

    def _bar_height(self, index):
        if self._mode == "idle":
            return 3.0
        wave = math.sin(self._phase + index * 0.55) * 0.5 + 0.5
        lift = (wave * 0.55 + 0.25) if self._mode == "speaking" else (
            0.18 + 0.82 * self._level
        )
        envelope = math.sin(math.pi * (index + 0.5) / self._bars)
        return 4.0 + (self.height() - 10.0) * lift * (0.35 + 0.65 * envelope)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        accent = QColor(self._colors.get("accent") or "#ff7ebd")
        lavender = QColor(self._colors.get("accent_2") or "#b79cf5")
        if self._mode == "idle":
            accent.setAlpha(70)
        count = self._bars
        gap = 3.0
        width = max(2.0, (self.width() - gap * (count - 1)) / count)
        x = 0.0
        mid = self.height() / 2.0
        for index in range(count):
            blend = index / max(1, count - 1)
            color = QColor(
                int(accent.red() * (1 - blend) + lavender.red() * blend),
                int(accent.green() * (1 - blend) + lavender.green() * blend),
                int(accent.blue() * (1 - blend) + lavender.blue() * blend),
                200 if self._mode != "idle" else 70,
            )
            height = min(float(self.height()) - 2.0, self._bar_height(index))
            painter.setBrush(color)
            painter.drawRoundedRect(
                int(x), int(mid - height / 2.0), int(width), int(height), 3, 3
            )
            x += width + gap


class StatusDot(QWidget):
    """Small breathing dot used beside the companion status text."""

    def __init__(self, color="#ff7ebd", parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(12, 12)

    def set_color(self, color):
        value = QColor(color)
        if value.isValid():
            self._color = value
            self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self._phase = (self._phase + 0.12) % (math.pi * 2)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        breath = 0.5 + 0.5 * math.sin(self._phase)
        halo = QColor(self._color)
        halo.setAlpha(int(40 + 50 * breath))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(0, 0, self.width(), self.height())
        core = QColor(self._color)
        painter.setBrush(core)
        inset = 3.5 - 0.8 * breath
        painter.drawEllipse(
            int(inset), int(inset),
            int(self.width() - inset * 2), int(self.height() - inset * 2),
        )
