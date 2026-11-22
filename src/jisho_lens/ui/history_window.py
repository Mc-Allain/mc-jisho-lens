"""History window: past captures, plus the OCR data tools (export / import / merge packs)."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QDateTime, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jisho_lens.core.history import HistoryStore
from jisho_lens.core.ocr_data import (
    OcrDataStore,
    PackError,
    export_pack,
    import_pack,
    merge_packs,
    select,
    to_test_set,
)
from jisho_lens.core.ocr_data.corrections import CorrectionStore
from jisho_lens.core.settings import Settings
from jisho_lens.core.storage import clear_all

_THUMB = QSize(220, 70)


def _thumb(path: Path) -> QIcon:
    pm = QPixmap(str(path))
    if pm.isNull():
        return QIcon()
    return QIcon(pm.scaled(_THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation))


class ExportPreview(QDialog):
    """Shows the crops that will be exported, so the user can spot names or chat first."""

    def __init__(self, store: OcrDataStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export OCR data pack")
        self.store = store
        self.which = QComboBox()
        self.which.addItem("Checked samples only (✓ or edited)", "checked")
        self.which.addItem("All samples", "all")
        self.game = QLineEdit()
        self.game.setPlaceholderText("All games")
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(_THUMB)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.count = QLabel()
        note = QLabel("Check the pictures before sharing: screenshots can contain player "
                      "names or chat. Game screenshots belong to the game's publisher, so "
                      "share packs privately.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #c9a25a;")
        buttons = QDialogButtonBox()
        self.save_btn = buttons.addButton("Save pack…", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(QLabel("Export"))
        row.addWidget(self.which, 1)
        row.addWidget(QLabel("Game"))
        row.addWidget(self.game, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.count)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.resize(760, 520)
        self.which.currentIndexChanged.connect(self.reload)
        self.game.textChanged.connect(self.reload)
        self.reload()

    def samples(self):
        return select(self.store, self.which.currentData(), self.game.text().strip() or None)

    def reload(self) -> None:
        self.list.clear()
        samples = self.samples()
        for s in samples[:500]:
            item = QListWidgetItem(_thumb(self.store.png_path(s.id)), (s.truth or s.ocr_text)[:30])
            self.list.addItem(item)
        more = " (showing 500)" if len(samples) > 500 else ""
        self.count.setText(f"{len(samples)} samples will be exported{more}.")
        self.save_btn.setEnabled(bool(samples))


class DeleteRangeDialog(QDialog):
    """Delete captures taken between two times (favorites are kept)."""

    def __init__(self, history: HistoryStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Delete a time range")
        self.history = history
        oldest = history.list(limit=1_000_000)
        start = QDateTime.fromSecsSinceEpoch(int(oldest[-1].created_at)) if oldest \
            else QDateTime.currentDateTime()
        self.start = QDateTimeEdit(start)
        self.end = QDateTimeEdit(QDateTime.currentDateTime().addSecs(60))
        for w in (self.start, self.end):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd HH:mm")
            w.dateTimeChanged.connect(self._update)
        self.info = QLabel()
        buttons = QDialogButtonBox()
        self.delete_btn = buttons.addButton("Delete", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow("From", self.start)
        form.addRow("To", self.end)
        form.addRow(self.info)
        form.addRow(buttons)
        self._update()

    def span(self) -> tuple[float, float]:
        # minutes are shown, so "To" includes the whole minute
        return (self.start.dateTime().toSecsSinceEpoch(),
                self.end.dateTime().toSecsSinceEpoch() + 59.999)

    def _update(self) -> None:
        start, end = self.span()
        if end < start:
            self.info.setText("“To” is before “From”.")
            self.delete_btn.setEnabled(False)
            return
        n, fav = self.history.count_range(start, end)
        text = f"{n} capture{'s' if n != 1 else ''} will be deleted."
        if fav:
            text += f" {fav} favorite{'s' if fav != 1 else ''} kept."
        self.info.setText(text)
        self.delete_btn.setEnabled(n > 0)


FILTERS = [("All", "all"), ("★ Favorites", "favorites"), ("Corrected", "corrected")]


class HistoryWindow(QWidget):
    open_requested = Signal(int)  # capture id
    changed = Signal()  # captures or collected data were deleted

    def __init__(self, history: HistoryStore, data: OcrDataStore, settings: Settings,
                 corrections: CorrectionStore | None = None) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("Jisho Lens — History")
        self.history, self.data, self.settings = history, data, settings
        self.corrections = corrections

        self.filter = QComboBox()
        for label, key in FILTERS:
            self.filter.addItem(label, key)
        self.filter.currentIndexChanged.connect(self.refresh)
        self.count = QLabel()
        self.count.setStyleSheet("color: #8a8f99;")
        top = QHBoxLayout()
        top.addWidget(QLabel("Show"))
        top.addWidget(self.filter)
        top.addStretch(1)
        top.addWidget(self.count)

        self.list = QListWidget()
        self.list.setIconSize(_THUMB)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(self._open)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.open_btn = QPushButton("Open")
        self.favorite_btn = QPushButton("☆ Favorite")
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setToolTip("Delete the selected captures (Ctrl/Shift-click to select "
                                   "several). Favorites are kept.")
        range_btn = QPushButton("Delete range…")
        range_btn.setToolTip("Delete captures taken between two times")
        clear_btn = QPushButton("Clear history…")
        clear_btn.setToolTip("Delete all captures from History; collected OCR data is kept")
        clear_all_btn = QPushButton("Clear all…")
        clear_all_btn.setToolTip("Delete History, collected OCR data and learned corrections")
        self.open_btn.clicked.connect(lambda: self._open(self.list.currentItem()))
        self.favorite_btn.clicked.connect(self._toggle_favorite)
        self.delete_btn.clicked.connect(self._delete)
        range_btn.clicked.connect(self._delete_range)
        clear_btn.clicked.connect(self._delete_all)
        clear_all_btn.clicked.connect(self._clear_all)
        buttons = QHBoxLayout()
        for b in (self.open_btn, self.favorite_btn, self.delete_btn, range_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(clear_btn)
        buttons.addWidget(clear_all_btn)

        # OCR data (opt-in collection, local only)
        self.data_box = QGroupBox("OCR data (kept only on this computer)")
        self.data_stats = QLabel()
        self.data_stats.setWordWrap(True)
        export_btn = QPushButton("Export pack…")
        import_btn = QPushButton("Import pack…")
        merge_btn = QPushButton("Merge packs…")
        testset_btn = QPushButton("Export as OCR test set…")
        export_btn.clicked.connect(self._export)
        import_btn.clicked.connect(self._import)
        merge_btn.clicked.connect(self._merge)
        testset_btn.clicked.connect(self._test_set)
        data_buttons = QHBoxLayout()
        for b in (export_btn, import_btn, merge_btn, testset_btn):
            data_buttons.addWidget(b)
        data_layout = QVBoxLayout(self.data_box)
        data_layout.addWidget(self.data_stats)
        data_layout.addLayout(data_buttons)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.data_box)
        self.resize(720, 620)

    # ---------- history ----------
    def refresh(self) -> None:
        self.list.clear()
        show = self.filter.currentData() or "all"
        captures = self.history.list(show=show)
        for c in captures:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(c.created_at))
            marks = ["★"] if c.favorite else []
            if c.edited_text is not None:
                marks.append("edited")
            sample = self.data.get(c.sample_id) if c.sample_id else None
            if sample is not None:
                marks.append("✓ checked" if sample.checked else "collected")
            head = f"{when}  ·  {c.engine or ''}" + (f"  ·  {', '.join(marks)}" if marks else "")
            preview = " / ".join(c.lines)[:80]
            if c.speaker:
                preview = f"{c.speaker}: {preview}"
            item = QListWidgetItem(_thumb(c.image_path), f"{head}\n{preview}")
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, c.favorite)
            self.list.addItem(item)
        total = self.history.count()
        self.count.setText(f"{len(captures)} shown · {total} in History · "
                           f"{self.history.favorite_count()} ★")
        self._selection_changed()
        self._refresh_data()

    def _selected(self) -> list[tuple[int, bool]]:
        return [(i.data(Qt.ItemDataRole.UserRole), bool(i.data(Qt.ItemDataRole.UserRole + 1)))
                for i in self.list.selectedItems()]

    def _selection_changed(self) -> None:
        sel = self._selected()
        self.open_btn.setEnabled(len(sel) == 1)
        self.favorite_btn.setEnabled(bool(sel))
        all_fav = bool(sel) and all(f for _, f in sel)
        self.favorite_btn.setText("★ Remove star" if all_fav else "☆ Favorite")
        deletable = [cid for cid, f in sel if not f]
        self.delete_btn.setEnabled(bool(deletable))
        self.delete_btn.setText(f"Delete ({len(deletable)})" if len(deletable) > 1
                                else "Delete")

    def _refresh_data(self) -> None:
        st = self.data.stats()
        state = {"yes": "on", "no": "off", "ask": "not set (you'll be asked)"}[
            self.settings.data.collect if self.settings.data.collect in ("yes", "no", "ask")
            else "ask"]
        mb = self.data.size_bytes() / 1024 / 1024
        limit = self.settings.data.max_mb
        text = (f"Collection is {state} (Settings → OCR data). {st['samples']} samples "
                f"({mb:.1f} MB{f' of {limit} MB' if limit else ''}), "
                f"{st['checked']} checked ({st['edited']} edited, {st['confirmed']} ✓). "
                "Checked samples are kept until you delete them.")
        if st["needs_review"]:
            text += f" {st['needs_review']} need review (different answers after merging)."
        self.data_stats.setText(text)

    def _current_id(self) -> int | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _open(self, item) -> None:
        if item is not None:
            self.open_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _toggle_favorite(self) -> None:
        sel = self._selected()
        if not sel:
            return
        favorite = not all(f for _, f in sel)
        for cid, _ in sel:
            self.history.set_favorite(cid, favorite)
        self.refresh()
        self.changed.emit()

    def _delete(self) -> None:
        sel = self._selected()
        ids = [cid for cid, f in sel if not f]
        if not ids:
            return
        if len(ids) > 1 and QMessageBox.question(
                self, "Delete", f"Delete {len(ids)} captures from History?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.history.delete_many(ids)
        self.refresh()
        self.changed.emit()

    def _delete_range(self) -> None:
        dlg = DeleteRangeDialog(self.history, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            gone = self.history.delete_range(*dlg.span())
            self.refresh()
            self.changed.emit()
            QMessageBox.information(self, "Delete a time range",
                                    f"Deleted {len(gone)} captures.")

    def _kept_note(self) -> str:
        fav = self.history.favorite_count()
        return (f"\n\n{fav} favorite{'s' if fav != 1 else ''} will be kept (remove the "
                "star first to delete them).") if fav else ""

    def _delete_all(self) -> None:
        if QMessageBox.question(
                self, "Clear history",
                "Delete all captures from History?\n\nCollected OCR data and learned "
                f"corrections are kept (use Clear all for those).{self._kept_note()}") \
                == QMessageBox.StandardButton.Yes:
            self.history.delete_all()
            self.refresh()
            self.changed.emit()

    def _clear_all(self) -> None:
        st = self.data.stats()
        if QMessageBox.question(
                self, "Clear all",
                f"Delete all History captures, all {st['samples']} collected OCR samples "
                f"(including {st['checked']} corrected or ✓ ones) and the learned "
                f"corrections from this computer?\n\nThis can't be undone."
                f"{self._kept_note()}",
                defaultButton=QMessageBox.StandardButton.No) \
                != QMessageBox.StandardButton.Yes:
            return
        captures, samples, kept = clear_all(self.history, self.data,
                                            self.corrections or CorrectionStore())
        self.refresh()
        self.changed.emit()
        QMessageBox.information(self, "Clear all",
                                f"Deleted {captures} captures and {samples} samples."
                                + (f" Kept {kept} favorites." if kept else ""))

    # ---------- data packs ----------
    def _export(self) -> None:
        dlg = ExportPreview(self.data, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        default = str(Path.home() / f"jisho-lens-ocr-pack-{time.strftime('%Y%m%d')}.zip")
        path, _ = QFileDialog.getSaveFileName(self, "Save OCR data pack", default,
                                              "OCR data pack (*.zip)")
        if path:
            n = export_pack(self.data, Path(path), dlg.samples())
            QMessageBox.information(self, "Export", f"Exported {n} samples to\n{path}")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import OCR data pack", str(Path.home()),
                                              "OCR data pack (*.zip)")
        if not path:
            return
        try:
            result = import_pack(self.data, Path(path))
        except PackError as exc:
            QMessageBox.warning(self, "Import", f"Not imported: {exc}")
            return
        QMessageBox.information(self, "Import", result.summary())
        self._refresh_data()

    def _merge(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose packs to merge", str(Path.home()),
                                                "OCR data pack (*.zip)")
        if len(paths) < 2:
            if paths:
                QMessageBox.information(self, "Merge", "Choose two or more packs.")
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "Save merged pack", str(Path.home() / "jisho-lens-ocr-merged.zip"),
            "OCR data pack (*.zip)")
        if not out:
            return
        try:
            count, result = merge_packs([Path(p) for p in paths], Path(out))
        except PackError as exc:
            QMessageBox.warning(self, "Merge", f"Not merged: {exc}")
            return
        QMessageBox.information(self, "Merge", f"Merged pack with {count} samples.\n"
                                                f"{result.summary()}")

    def _test_set(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Folder for the OCR test set",
                                                  str(Path.home()))
        if folder:
            n = to_test_set(self.data, Path(folder))
            QMessageBox.information(
                self, "OCR test set",
                f"Wrote {n} checked samples to\n{folder}\n\n"
                "Run: uv run python tools/ocr_bench.py \"<that folder>\"")
