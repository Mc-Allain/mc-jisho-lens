"""Merge packs: the list of packs to merge. Packs chosen in a file dialog are listed first;
Add brings more (from any folder), Remove takes the selected ones out, Merge goes on to the
review (two or more packs), Cancel merges nothing."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jisho_lens.core.ocr_data.packs import Pack, PackError, order_packs, read_pack
from jisho_lens.ui import file_dialogs

COL_PACK, COL_SAMPLES, COL_FILE = range(3)
PACK_FILTER = "OCR data pack (*.zip)"


def _key(pack: Pack) -> str:
    """The same pack (identical contents, e.g. a copy in another folder) has one key."""
    return pack.info.pack_id if pack.info else str(Path(pack.path).resolve())


class MergeListDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, folder: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Merge packs")
        self.resize(720, 360)
        self.packs: list[Pack] = []
        self.folder = folder or str(file_dialogs.downloads_dir())  # where Add opens
        layout = QVBoxLayout(self)
        intro = QLabel("Packs to merge. Add packs from any folder; Merge needs two or more.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Pack", "Samples fixed with Edit", "File"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_PACK, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_SAMPLES, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._update)
        layout.addWidget(self.table, 1)
        self.note = QLabel()  # what Add left out, and why
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #d0a040;")
        self.note.setVisible(False)
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        self.add_btn = QPushButton("Add…")
        self.add_btn.setToolTip("Choose more packs (you can pick several at once)")
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setToolTip("Take the selected packs out of the list (Delete)")
        self.requirement = QLabel()  # why Merge is disabled
        self.requirement.setStyleSheet("color: #8a8f99;")
        self.merge_btn = QPushButton("Merge…")
        self.merge_btn.setToolTip("Review the merge: choose the answers to keep")
        self.cancel_btn = QPushButton("Cancel")
        for b in (self.add_btn, self.remove_btn, self.merge_btn, self.cancel_btn):
            b.setAutoDefault(False)
        buttons.addWidget(self.add_btn)
        buttons.addWidget(self.remove_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.requirement)
        buttons.addWidget(self.merge_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)
        self.add_btn.clicked.connect(lambda _checked=False: self.choose())
        self.remove_btn.clicked.connect(lambda _checked=False: self.remove_selected())
        self.merge_btn.clicked.connect(lambda _checked=False: self.accept())
        self.cancel_btn.clicked.connect(lambda _checked=False: self.reject())
        self.table.installEventFilter(self)  # Delete removes the selected packs
        self._update()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if (obj is self.table and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Delete):
            self.remove_selected()
            return True
        return super().eventFilter(obj, event)

    # ---- adding
    def choose(self) -> int:
        """Add: a file dialog (several files at once); returns how many were added."""
        paths = file_dialogs.open_files(self, "Add packs to merge", self.folder, PACK_FILTER)
        return self.add_paths(paths)

    def add_paths(self, paths: list[str]) -> int:
        new, note = self.read_new(paths, self.packs)
        self.packs = order_packs(self.packs + new)
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self._fill()
        return len(new)

    def read_new(self, paths: list[str], current: list[Pack]) -> tuple[list[Pack], str]:
        """The packs in `paths` that aren't in `current` yet, and a note on what was left
        out (the same pack again, damaged files). The next Add opens where these were."""
        new, same, bad = [], [], []
        keys = {_key(p) for p in current}
        for path in paths:
            try:
                pack = read_pack(Path(path))
            except PackError as exc:
                bad.append(f"{Path(path).name} ({exc})")
                continue
            if _key(pack) in keys:
                same.append(Path(path).name)
                continue
            keys.add(_key(pack))
            new.append(pack)
        if paths:
            self.folder = str(Path(paths[-1]).parent)
        notes = []
        if same:
            notes.append(f"Already added (the same pack): {', '.join(same)}")
        if bad:
            notes.append(f"Not added: {'; '.join(bad)}")
        return new, "\n".join(notes)

    def pick_more(self, parent: QWidget, current: list[Pack]) -> tuple[list[Pack], str]:
        """Add packs… in the merge review: a file dialog over the review window."""
        paths = file_dialogs.open_files(parent, "Add packs to merge", self.folder, PACK_FILTER)
        return self.read_new(paths, current)

    def set_packs(self, packs: list[Pack]) -> None:
        """The review added or removed packs: the list shows the same ones."""
        self.packs = order_packs(list(packs))
        self.note.setVisible(False)
        self._fill()

    # ---- removing
    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        for row in rows:
            del self.packs[row]
        self.note.setVisible(False)
        self._fill()
        if self.packs:  # keep a selection near where the removed rows were
            self.table.selectRow(min(rows[-1], len(self.packs) - 1))

    # ---- view
    def _fill(self) -> None:
        self.table.setRowCount(len(self.packs))
        for row, pack in enumerate(self.packs):
            items = [QTableWidgetItem(pack.label), QTableWidgetItem(str(len(pack.samples))),
                     QTableWidgetItem(str(pack.path))]
            items[COL_SAMPLES].setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            items[COL_FILE].setToolTip(str(pack.path))
            if pack.info is not None:
                items[COL_PACK].setToolTip(pack.info.history_text())
            for col, item in enumerate(items):
                self.table.setItem(row, col, item)
        self._update()

    def _update(self) -> None:
        n = len(self.packs)
        self.remove_btn.setEnabled(bool(self.table.selectedIndexes()))
        self.merge_btn.setEnabled(n >= 2)
        self.requirement.setText("" if n >= 2 else
                                 f"Add {2 - n} more pack{'s' if 2 - n != 1 else ''} to merge")
