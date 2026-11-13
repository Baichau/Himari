"""Pick a reusable screen-capture region.

The picker photographs the primary monitor first, then dims that picture and
lets the user drag a rectangle over it. Working from the picture means the
saved coordinates are exact physical pixels even when Windows uses display
scaling, because the mapping is done between the picture and its on-screen
representation.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog

from .theme import palette as theme_palette

MIN_REGION_PIXELS = 12


def normalized_rect(x1, y1, x2, y2):
    left = min(int(x1), int(x2))
    top = min(int(y1), int(y2))
    return left, top, abs(int(x2) - int(x1)), abs(int(y2) - int(y1))


def fit_rect(container_width, container_height, image_width, image_height):
    """Return (x, y, width, height) of an image scaled to fit and centered."""
    container_width = max(1, int(container_width))
    container_height = max(1, int(container_height))
    image_width = max(1, int(image_width))
    image_height = max(1, int(image_height))
    scale = min(container_width / image_width, container_height / image_height)
    width = max(1, round(image_width * scale))
    height = max(1, round(image_height * scale))
    return (container_width - width) // 2, (container_height - height) // 2, width, height


def map_selection(selection, display, image_size, monitor_box, min_size=MIN_REGION_PIXELS):
    """Map a widget-space selection to absolute desktop pixels, or None."""
    sx, sy, sw, sh = (int(value) for value in selection)
    dx, dy, dw, dh = (int(value) for value in display)
    image_width, image_height = (int(value) for value in image_size)
    if dw <= 0 or dh <= 0 or image_width <= 0 or image_height <= 0:
        return None
    left = max(sx, dx)
    top = max(sy, dy)
    right = min(sx + sw, dx + dw)
    bottom = min(sy + sh, dy + dh)
    width = right - left
    height = bottom - top
    if width < min_size or height < min_size:
        return None
    scale_x = image_width / dw
    scale_y = image_height / dh
    image_left = min(max(0, round((left - dx) * scale_x)), image_width - 1)
    image_top = min(max(0, round((top - dy) * scale_y)), image_height - 1)
    image_right = min(image_width, max(image_left + 1, round((right - dx) * scale_x)))
    image_bottom = min(image_height, max(image_top + 1, round((bottom - dy) * scale_y)))
    return {
        "left": int(monitor_box.get("left", 0)) + image_left,
        "top": int(monitor_box.get("top", 0)) + image_top,
        "width": int(image_right - image_left),
        "height": int(image_bottom - image_top),
    }


def describe_region(region):
    if not region:
        return "No custom region selected"
    return (
        f"Custom region · {int(region['width'])} × {int(region['height'])} "
        f"at ({int(region['left'])}, {int(region['top'])})"
    )


def _primary_capture():
    import mss

    with mss.mss() as screen:
        monitors = list(screen.monitors)
        box = dict(monitors[1] if len(monitors) > 1 else monitors[0])
        shot = screen.grab(box)
        image = QImage(
            shot.rgb, shot.width, shot.height, QImage.Format.Format_RGB888
        ).copy()
    return image, box


class RegionSelector(QDialog):
    """Full-screen overlay that returns one absolute desktop rectangle."""

    def __init__(self, pixmap, monitor_box, screen, parent=None, accent="#e08bb5"):
        super().__init__(parent)
        self._pixmap = pixmap
        self._monitor_box = dict(monitor_box)
        self._screen_geometry = screen.geometry()
        self._accent = QColor(accent)
        self._anchor = None
        self._current = None
        self._hint = ""
        self._result = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(self._screen_geometry)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._display = fit_rect(
            self.width(), self.height(), pixmap.width(), pixmap.height()
        )

    def region(self):
        return self._result

    def _selection_rect(self):
        if self._anchor is None or self._current is None:
            return None
        left, top, width, height = normalized_rect(
            self._anchor.x(), self._anchor.y(), self._current.x(), self._current.y()
        )
        bounded = QRect(left, top, width, height).intersected(
            QRect(*self._display)
        )
        if bounded.width() <= 0 or bounded.height() <= 0:
            return None
        return bounded

    def _source_rect(self, selection):
        dx, dy, dw, dh = self._display
        scale_x = self._pixmap.width() / max(1, dw)
        scale_y = self._pixmap.height() / max(1, dh)
        source = QRect(
            round((selection.left() - dx) * scale_x),
            round((selection.top() - dy) * scale_y),
            max(1, round(selection.width() * scale_x)),
            max(1, round(selection.height() * scale_y)),
        )
        return source.intersected(
            QRect(0, 0, self._pixmap.width(), self._pixmap.height())
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(QRect(*self._display), self._pixmap)
        painter.fillRect(self.rect(), QColor(10, 8, 14, 150))

        selection = self._selection_rect()
        if selection is not None:
            painter.drawPixmap(selection, self._pixmap, self._source_rect(selection))
            pen = QPen(self._accent, 2)
            painter.setPen(pen)
            painter.drawRect(selection.adjusted(0, 0, -1, -1))
            size_text = f"{selection.width()} × {selection.height()}"
            label_rect = QRect(
                selection.left(),
                max(8, selection.top() - 30),
                max(120, selection.width()),
                24,
            )
            painter.fillRect(label_rect, QColor(18, 12, 22, 210))
            painter.setPen(QColor("#f3eaf6"))
            painter.drawText(
                label_rect.adjusted(8, 0, -8, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                size_text,
            )

        message = self._hint or (
            "Drag to select the area Himari should capture   ·   Esc to cancel"
        )
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(message)
        band = QRect(
            max(16, (self.width() - text_width - 44) // 2),
            22,
            text_width + 44,
            40,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(18, 12, 22, 225))
        painter.drawRoundedRect(band, 12, 12)
        painter.setPen(QColor("#f3eaf6"))
        painter.drawText(band, Qt.AlignmentFlag.AlignCenter, message)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.reject()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._anchor = event.position().toPoint()
            self._current = self._anchor
            self._hint = ""
            self.update()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._anchor is not None:
            self._current = event.position().toPoint()
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._anchor is None:
            return
        self._current = event.position().toPoint()
        selection = self._selection_rect()
        region = None
        if selection is not None:
            region = map_selection(
                (
                    selection.left(),
                    selection.top(),
                    selection.width(),
                    selection.height(),
                ),
                self._display,
                (self._pixmap.width(), self._pixmap.height()),
                self._monitor_box,
            )
        if region is None:
            self._anchor = None
            self._current = None
            self._hint = "Select a larger rectangle"
            self.update()
            return
        self._result = region
        self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


def select_region(parent=None, theme_name="dark"):
    """Capture the primary monitor, let the user drag a rectangle, return it."""
    try:
        image, monitor_box = _primary_capture()
    except Exception as exc:
        return None, f"Could not read the screen: {exc}"
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None, "Windows did not report a primary screen."
    pixmap = QPixmap.fromImage(image)
    if pixmap.isNull():
        return None, "The captured screen could not be displayed."
    colors = theme_palette(theme_name)
    dialog = RegionSelector(
        pixmap,
        monitor_box,
        screen,
        parent,
        accent=colors.get("accent", "#e08bb5"),
    )
    dialog.exec()
    region = dialog.region()
    dialog.deleteLater()
    if region is None:
        return None, None
    return region, None
