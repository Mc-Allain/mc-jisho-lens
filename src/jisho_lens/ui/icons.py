"""App icon drawn in code (no image files needed yet)."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


def app_icon(busy: bool = False) -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#e08a2e") if busy else QColor("#3d7dd8"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRect(0, 0, size, size), size * 0.22, size * 0.22)
        font = QFont("Yu Gothic UI")
        font.setBold(True)
        font.setPixelSize(int(size * 0.72))
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "字")
        p.end()
        icon.addPixmap(pm)
    return icon
