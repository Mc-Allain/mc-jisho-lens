"""Frozen, dimmed full-screen overlay for selecting a capture region.

One borderless window is opened per monitor, each showing that monitor's part of a screenshot
taken *before* the overlay appeared. Mouse positions are converted to physical pixels per monitor,
so selection works at any Windows scaling and on mixed-DPI setups.
"""

from __future__ import annotations

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from jisho_lens.core.capture import DesktopShot, Rect
from jisho_lens.core.displays import Display

_DIM = QColor(0, 0, 0, 110)
_BORDER = QColor(80, 170, 255)
_MIN_SIZE = 4


class _MonitorOverlay(QWidget):
    selected = Signal(object)  # Rect | None

    def __init__(self, display: Display, pixmap: QPixmap, screen) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.display = display
        self.pixmap = pixmap
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self._start: QPoint | None = None
        self._end: QPoint | None = None

    # widget coords (logical) -> physical pixels on the virtual desktop
    def _to_physical(self, p: QPoint) -> tuple[int, int]:
        sx = self.display.width / max(1, self.width())
        sy = self.display.height / max(1, self.height())
        return self.display.left + round(p.x() * sx), self.display.top + round(p.y() * sy)

    def _selection(self) -> QRect | None:
        """Selection in widget coords. Uses (x, y, w, h) so the size is end - start, not +1
        (QRect(QPoint, QPoint) is inclusive of both corners)."""
        if self._start is None or self._end is None:
            return None
        x0, x1 = sorted((self._start.x(), self._end.x()))
        y0, y1 = sorted((self._start.y(), self._end.y()))
        return QRect(x0, y0, x1 - x0, y1 - y0)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.pixmap)
        painter.fillRect(self.rect(), _DIM)
        sel = self._selection()
        if sel is not None:
            src = QRect(
                round(sel.x() * self.pixmap.width() / self.width()),
                round(sel.y() * self.pixmap.height() / self.height()),
                round(sel.width() * self.pixmap.width() / self.width()),
                round(sel.height() * self.pixmap.height() / self.height()),
            )
            painter.drawPixmap(sel, self.pixmap, src)
            painter.setPen(QPen(_BORDER, 2))
            painter.drawRect(sel)
            x0, y0 = self._to_physical(sel.topLeft())
            x1, y1 = self._to_physical(sel.topLeft() + QPoint(sel.width(), sel.height()))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(sel.left(), max(14, sel.top() - 6), f"{x1 - x0} x {y1 - y0}")
        painter.end()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = self._end = e.position().toPoint()
            self.update()
        elif e.button() == Qt.MouseButton.RightButton:
            self.selected.emit(None)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._start is not None:
            self._end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._end = e.position().toPoint()
        sel = self._selection()
        x0, y0 = self._to_physical(sel.topLeft())
        x1, y1 = self._to_physical(sel.topLeft() + QPoint(sel.width(), sel.height()))
        rect = Rect(x0, y0, x1 - x0, y1 - y0)
        if rect.width < _MIN_SIZE or rect.height < _MIN_SIZE:
            self._start = self._end = None
            self.update()
            return
        self.selected.emit(rect)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.selected.emit(None)


class CaptureOverlay:
    """Shows the overlay on every monitor; calls on_done(Rect | None) once."""

    def __init__(self, shot: DesktopShot, on_done) -> None:
        self._on_done = on_done
        self._windows: list[_MonitorOverlay] = []
        screens = {s.name(): s for s in QGuiApplication.screens()}
        for display in shot.displays:
            screen = screens.get(display.device)
            if screen is None:  # fall back to geometry order
                screen = QGuiApplication.primaryScreen()
            pixmap = QPixmap.fromImage(ImageQt(shot.display_image(display)))
            w = _MonitorOverlay(display, pixmap, screen)
            w.selected.connect(self._finish)
            self._windows.append(w)

    def show(self) -> None:
        for w in self._windows:
            w.showFullScreen()
            w.raise_()
            w.activateWindow()

    def _finish(self, rect: Rect | None) -> None:
        for w in self._windows:
            w.close()
        windows, self._windows = self._windows, []
        for w in windows:
            w.deleteLater()
        if self._on_done is not None:
            cb, self._on_done = self._on_done, None
            cb(rect)
