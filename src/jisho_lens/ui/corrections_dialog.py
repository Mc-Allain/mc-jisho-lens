"""Settings → OCR data → Learned corrections: review and delete fixes learned from Edit."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from jisho_lens.core.ocr_data.corrections import LINE, CorrectionStore


def _show(s: str) -> str:
    return s.replace(LINE, "⏎")


class CorrectionsDialog(QDialog):
    def __init__(self, store: CorrectionStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Learned corrections")
        self.resize(520, 380)
        self.store = store
        note = QLabel("When you fix OCR with Edit, the change is remembered with the characters "
                      "around it and applied to later captures. Delete one here if it's wrong. "
                      "⏎ means the start or end of a line.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #8a8f99;")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["OCR reads", "Fixed to", "Learned", "Applied"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.delete_btn = QPushButton("Delete")
        self.delete_all_btn = QPushButton("Delete all…")
        close = QPushButton("Close")
        self.delete_btn.clicked.connect(self._delete)
        self.delete_all_btn.clicked.connect(self._delete_all)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.delete_btn)
        buttons.addWidget(self.delete_all_btn)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(note)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        rules = sorted(self.store.all(), key=lambda r: r.created, reverse=True)
        self.table.setRowCount(len(rules))
        for row, r in enumerate(rules):
            for col, value in enumerate((_show(r.wrong), _show(r.right),
                                         f"{r.count}×", f"{r.used}×")):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, r.wrong)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.delete_btn.setEnabled(bool(rules))
        self.delete_all_btn.setEnabled(bool(rules))

    def _delete(self) -> None:
        rows = {i.row() for i in self.table.selectedItems()}
        for row in rows:
            self.store.delete(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))
        self.refresh()

    def _delete_all(self) -> None:
        if QMessageBox.question(self, "Learned corrections",
                                "Delete all learned corrections?") \
                == QMessageBox.StandardButton.Yes:
            self.store.delete_all()
            self.refresh()
