import math
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .ambient import reduced_motion_enabled
from .config import APP_DIR

_STATES = {
    "idle": "Idle",
    "listening": "Listening",
    "thinking": "Thinking",
    "speaking": "Speaking",
    "searching": "Searching",
    "working": "Working",
    "happy": "Happy",
    "confused": "Confused",
    "success": "Success",
    "sad": "Sad",
    "error": "Error",
}

# One accent per emotional state so the stage, name chip and floating avatar
# all agree on what Himari is doing.
STATE_COLORS = {
    "idle": "#b79cf5",
    "listening": "#8fd8ff",
    "thinking": "#b79cf5",
    "speaking": "#ff9ad5",
    "searching": "#8fd8ff",
    "working": "#ffbf8a",
    "happy": "#ffd48a",
    "confused": "#c9a6ff",
    "success": "#7fe3b0",
    "sad": "#8fa7d9",
    "error": "#ff8f9c",
}


def _asset_dirs():
    return (
        APP_DIR / "avatar_assets",
        Path(__file__).resolve().parent / "avatar_assets",
    )


class AvatarWidget(QLabel):
    clicked = Signal()

    def __init__(self, parent=None, asset_dirs=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(48, 48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QLabel { color: #bca9c8; background: transparent; }"
        )
        self._asset_dirs = tuple(Path(path) for path in (asset_dirs or _asset_dirs()))
        self._state = "idle"
        self._frames = []
        self._frame_index = 0
        self._pixmap = None
        self._animation = QTimer(self)
        self._animation.setInterval(180)
        self._animation.timeout.connect(self._advance_frame)
        self._blink = QTimer(self)
        self._blink.setInterval(4200)
        self._blink.timeout.connect(self._show_blink)
        self._restore_blink = QTimer(self)
        self._restore_blink.setSingleShot(True)
        self._restore_blink.setInterval(140)
        self._restore_blink.timeout.connect(self._restore_idle_frame)
        self._accent = None
        self._accent_animation = None
        self._breath = 0.0
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(60)
        self._breath_timer.timeout.connect(self._breathe)
        self._motion = not reduced_motion_enabled()
        if self._motion:
            self._breath_timer.start()
        self.set_state("idle")

    @property
    def state(self):
        return self._state

    def set_state(self, state):
        normalized = str(state or "idle").strip().lower()
        if normalized not in _STATES:
            normalized = "idle"
        self._state = normalized
        if self._accent_animation is not None:
            try:
                self._accent_animation.stop()
            except RuntimeError:
                pass
            self._accent_animation = None
        self._accent = QColor(STATE_COLORS.get(normalized, STATE_COLORS["idle"]))
        self._frames = self._find_frames(normalized)
        if not self._frames and normalized != "idle":
            # A state without dedicated art (for example "searching") should
            # still show Himari instead of the "art not installed" placeholder.
            self._frames = self._find_frames("thinking") or self._find_frames("idle")
        self._frame_index = 0
        self._animation.stop()
        self._restore_blink.stop()
        self._blink.stop()

        if self._frames:
            self.setToolTip(f"Himari — {_STATES[normalized]}")
            self._display_frame()
            if len(self._frames) > 1:
                self._animation.start()
            if normalized == "idle":
                self._blink.start()
        else:
            self._pixmap = None
            self.clear()
            self.setText("Avatar art not installed\nAdd PNGs to himari/avatar_assets")
            self.setToolTip(
                "Add original transparent PNG sprites to the avatar_assets folder."
            )

    def _find_frames(self, state):
        patterns = (
            ("speaking_*.png", "speaking.png")
            if state == "speaking"
            else (f"{state}_*.png", f"{state}.png")
        )
        for directory in self._asset_dirs:
            for pattern in patterns:
                frames = sorted(directory.glob(pattern))
                if frames:
                    return frames
        if state != "idle":
            return self._find_frames("idle")
        return []

    def _display_frame(self, frame=None):
        if not self._frames:
            return
        source = frame or self._frames[self._frame_index % len(self._frames)]
        from PySide6.QtGui import QPixmap

        pixmap = QPixmap(str(source))
        if pixmap.isNull():
            return
        self._pixmap = pixmap
        self.setPixmap(
            pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _advance_frame(self):
        if len(self._frames) < 2:
            return
        self._frame_index = (self._frame_index + 1) % len(self._frames)
        self._display_frame()

    def _show_blink(self):
        if self._state != "idle":
            return
        blink = next(
            (directory / "idle_blink.png" for directory in self._asset_dirs
             if (directory / "idle_blink.png").is_file()),
            None,
        )
        if blink is not None:
            self._display_frame(blink)
            self._restore_blink.start()

    def _restore_idle_frame(self):
        if self._state == "idle":
            self._display_frame()

    def _breathe(self):
        if not self._motion:
            return
        self._breath = (self._breath + 0.055) % 6.28318
        if self._pixmap is not None:
            self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._motion:
            self._breath_timer.start()

    def hideEvent(self, event):
        self._breath_timer.stop()
        super().hideEvent(event)

    def set_accent(self, color):
        """Blend a soft state-colored ring around the sprite."""
        target = QColor(color) if not isinstance(color, QColor) else QColor(color)
        if not target.isValid():
            return
        start = QColor(self._accent) if isinstance(self._accent, QColor) else QColor(target)
        if not self._accent_animation:
            start.setAlpha(0)
        else:
            try:
                self._accent_animation.stop()
            except RuntimeError:
                pass
        self._accent = target
        animation = QVariantAnimation(self)
        animation.setDuration(320)
        animation.setStartValue(start)
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        animation.valueChanged.connect(self._apply_accent)
        self._accent_animation = animation
        animation.start()

    def _apply_accent(self, color):
        self._accent = QColor(color)
        self.update()

    def paintEvent(self, event):
        if self._pixmap is not None and isinstance(self._accent, QColor):
            self._paint_aura()
        super().paintEvent(event)
        if not isinstance(self._accent, QColor) or self._pixmap is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(4, 4, -5, -5)
        glow = QColor(self._accent)
        glow.setAlpha(34)
        painter.setPen(QPen(glow, 7))
        painter.drawRoundedRect(rect, 22, 22)
        ring = QColor(self._accent)
        ring.setAlpha(120)
        painter.setPen(QPen(ring, 2))
        painter.drawRoundedRect(rect, 20, 20)

    def _paint_aura(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        breath = 0.5 + 0.5 * math.sin(self._breath)
        radius = min(self.width(), self.height()) * 0.52 + 6.0 * breath
        gradient = QRadialGradient(center, radius)
        inner = QColor(self._accent)
        inner.setAlpha(int(30 + 22 * breath))
        middle = QColor(self._accent)
        middle.setAlpha(int(12 + 10 * breath))
        gradient.setColorAt(0.0, inner)
        gradient.setColorAt(0.62, middle)
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(center, radius, radius)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap is not None:
            self.setPixmap(
                self._pixmap.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class FloatingAvatarWindow(QWidget):
    def __init__(self, parent=None, asset_dirs=None):
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Himari")
        self.resize(300, 430)
        self.avatar = AvatarWidget(self, asset_dirs=asset_dirs)
        self.avatar.setToolTip("Drag to move · click Himari to return to the app")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.addWidget(self.avatar)
        self.state_label = QLabel("Idle", self)
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label.setStyleSheet(
            "QLabel { color: #b79cf5; background-color: rgba(18,12,29,190);"
            " border: 1px solid rgba(183,156,245,110); border-radius: 11px;"
            " padding: 4px 14px; font-size: 11px; font-weight: 700; }"
        )
        layout.addWidget(self.state_label, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_state(self, state):
        self.avatar.set_state(state)
        name = _STATES.get(self.avatar.state, "Idle")
        color = QColor(STATE_COLORS.get(self.avatar.state, STATE_COLORS["idle"]))
        self.state_label.setText(name)
        self.state_label.setStyleSheet(
            f"QLabel {{ color: {color.name()}; background-color: rgba(18,12,29,190);"
            f" border: 1px solid rgba({color.red()},{color.green()},{color.blue()},120);"
            " border-radius: 11px; padding: 4px 14px; font-size: 11px;"
            " font-weight: 700; }"
        )

    def set_avatar_size(self, width, height):
        self.resize(max(96, int(width)), max(112, int(height)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "_drag_offset"):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
