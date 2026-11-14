"""Painted ambient backdrop: midnight glow, sakura petals and motes.

The backdrop is intentionally cheap: one cached gradient pixmap per resize and
a small fixed pool of moving particles. It stops animating when hidden and
falls back to a still frame when the OS asks for reduced motion.
"""

from __future__ import annotations

import ctypes
import math
import os
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

FRAME_MS = 40
PETAL_COUNT = 22
MOTE_COUNT = 16
SPI_GETCLIENTAREAANIMATION = 0x1042


def reduced_motion_enabled():
    override = str(os.environ.get("HIMARI_REDUCED_MOTION", "")).strip().casefold()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    if os.name == "nt":
        try:
            enabled = ctypes.c_int(0)
            ok = ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
            )
            if ok:
                return not bool(enabled.value)
        except (AttributeError, OSError):
            pass
    return False


@dataclass
class _Petal:
    x: float
    y: float
    size: float
    speed: float
    sway: float
    phase: float
    spin: float
    color: QColor


@dataclass
class _Mote:
    x: float
    y: float
    radius: float
    speed: float
    phase: float
    color: QColor


class AmbientBackground(QWidget):
    """Draws the living background behind every page."""

    def __init__(self, colors=None, parent=None, animate=None, seed=7):
        super().__init__(parent)
        self.setObjectName("AmbientBackground")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._colors = dict(colors or {})
        self._seed = int(seed)
        self._animate = (not reduced_motion_enabled()) if animate is None else bool(animate)
        self._phase = 0.0
        self._backdrop = None
        self._petals = []
        self._motes = []
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._advance)
        self._populate()

    @property
    def animating(self):
        return self._timer.isActive()

    def set_reduced_motion(self, reduced):
        self._animate = not bool(reduced)
        if self._animate and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _color(self, key, fallback, alpha=255):
        value = QColor(self._colors.get(key) or fallback)
        value.setAlpha(alpha)
        return value

    def _populate(self):
        rng = random.Random(self._seed)
        palette = (
            self._color("accent", "#ff7ebd", 190),
            self._color("accent_strong", "#ffa6d2", 150),
            self._color("accent_2", "#b79cf5", 160),
            self._color("text", "#f6eefb", 120),
        )
        self._petals = [
            _Petal(
                x=rng.random(),
                y=rng.random(),
                size=rng.uniform(5.0, 13.0),
                speed=rng.uniform(0.010, 0.030),
                sway=rng.uniform(0.010, 0.030),
                phase=rng.uniform(0, math.tau),
                spin=rng.uniform(-0.9, 0.9),
                color=rng.choice(palette),
            )
            for _ in range(PETAL_COUNT)
        ]
        self._motes = [
            _Mote(
                x=rng.random(),
                y=rng.random(),
                radius=rng.uniform(0.8, 2.0),
                speed=rng.uniform(0.002, 0.007),
                phase=rng.uniform(0, math.tau),
                color=self._color(
                    "accent_2", "#b79cf5", rng.randint(40, 110)
                ),
            )
            for _ in range(MOTE_COUNT)
        ]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._backdrop = None
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._animate:
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self):
        self._phase += FRAME_MS / 1000.0
        for petal in self._petals:
            petal.y += petal.speed * FRAME_MS / 1000.0
            petal.phase += FRAME_MS / 1000.0 * 0.7
            if petal.y > 1.08:
                petal.y = -0.08
                petal.x = random.random()
        for mote in self._motes:
            mote.y -= mote.speed * FRAME_MS / 1000.0
            mote.phase += FRAME_MS / 1000.0
            if mote.y < -0.05:
                mote.y = 1.05
                mote.x = random.random()
        self.update()

    def _build_backdrop(self):
        size = self.size()
        if size.width() <= 0 or size.height() <= 0:
            return None
        pixmap = QPixmap(size)
        pixmap.fill(QColor(self._colors.get("bg") or "#0a0611"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width, height = size.width(), size.height()

        top = QLinearGradient(0, 0, 0, height)
        top.setColorAt(0.0, QColor(self._colors.get("surface") or "#120c1d"))
        top.setColorAt(0.45, QColor(self._colors.get("bg") or "#0a0611"))
        top.setColorAt(1.0, QColor(self._colors.get("bg") or "#0a0611"))
        painter.fillRect(0, 0, width, height, top)

        glow_a = QRadialGradient(width * 0.18, height * 0.08, max(width, height) * 0.7)
        glow_a.setColorAt(0.0, self._color("accent_2", "#b79cf5", 46))
        glow_a.setColorAt(0.55, self._color("accent_2", "#b79cf5", 10))
        glow_a.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, width, height, glow_a)

        glow_b = QRadialGradient(width * 0.92, height * 0.9, max(width, height) * 0.75)
        glow_b.setColorAt(0.0, self._color("accent", "#ff7ebd", 40))
        glow_b.setColorAt(0.6, self._color("accent", "#ff7ebd", 8))
        glow_b.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, width, height, glow_b)
        painter.end()
        return pixmap

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._backdrop is None:
            self._backdrop = self._build_backdrop()
        if self._backdrop is not None:
            painter.drawPixmap(0, 0, self._backdrop)
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0:
            return
        self._paint_motes(painter, width, height)
        self._paint_petals(painter, width, height)

    def _paint_motes(self, painter, width, height):
        for mote in self._motes:
            x = (mote.x + 0.012 * math.sin(mote.phase)) * width
            y = mote.y * height
            glow = QColor(mote.color)
            glow.setAlpha(min(180, glow.alpha()))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(x, y), mote.radius, mote.radius)

    def _paint_petals(self, painter, width, height):
        for petal in self._petals:
            x = (petal.x + petal.sway * math.sin(petal.phase)) * width
            y = petal.y * height
            size = petal.size
            painter.save()
            painter.translate(x, y)
            painter.rotate(math.degrees(petal.phase * 0.6) * petal.spin)
            path = QPainterPath(QPointF(0, -size))
            path.cubicTo(size * 0.9, -size * 0.6, size * 0.75, size * 0.5, 0, size)
            path.cubicTo(-size * 0.75, size * 0.5, -size * 0.9, -size * 0.6, 0, -size)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(petal.color)
            painter.drawPath(path)
            painter.restore()


class AuroraDivider(QWidget):
    """Thin gradient separator used between hero rows and content."""

    def __init__(self, colors=None, parent=None):
        super().__init__(parent)
        self._colors = dict(colors or {})
        self.setFixedHeight(2)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(0.5, self._color("accent", "#ff7ebd", 120))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(QPen(QBrush(gradient), 1))
        painter.drawLine(0, 1, self.width(), 1)

    def _color(self, key, fallback, alpha=255):
        value = QColor(self._colors.get(key) or fallback)
        value.setAlpha(alpha)
        return value
