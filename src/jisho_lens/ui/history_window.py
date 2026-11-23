"""History window: past captures, plus the OCR data tools (export / import / merge packs)."""

from __future__ import annotations

import html
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
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jisho_lens.core.categories import category_summary
from jisho_lens.core.history import HistoryStore
from jisho_lens.core.ocr_data import (
    OcrDataStore,
    PackError,
    apply_export,
    apply_import,
    apply_merge,
    read_pack,
    review_export,
    review_import,
    review_merge,
    to_test_set,
)
from jisho_lens.core.ocr_data.corrections import CorrectionStore
from jisho_lens.core.ocr_data.packs import merge_sources, preview_import_label
from jisho_lens.core.ocr_data.provenance import clean_name, file_name, merge_logs
from jisho_lens.core.settings import Settings
from jisho_lens.core.storage import clear_all
from jisho_lens.ui.file_dialogs import (
    downloads_dir,
    open_file,
    open_files,
    pick_folder,
    save_file,
)
from jisho_lens.ui.pack_review import PackReviewDialog

_THUMB = QSize(220, 70)


def _thumb(path: Path) -> QIcon:
    pm = QPixmap(str(path))
    if pm.isNull():
        return QIcon()
    return QIcon(pm.scaled(_THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation))


class ExportNamePanel(QWidget):
    """Pack name (remembered), the version it will be saved as, and its history log."""

    def __init__(self, store: OcrDataStore, rows, parent=None) -> None:
        super().__init__(parent)
        self.store, self.rows = store, rows
        self.name = QLineEdit(store.provenance.last_name())
        self.name.setPlaceholderText("Your pack name, e.g. RavenOCR")
        self.name.setMaxLength(40)
        self.version_label = QLabel()
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setMaximumHeight(80)
        note = QLabel("Check the pictures before sharing: screenshots can contain player "
                      "names or chat. Game screenshots belong to the game's publisher, so "
                      "share packs privately.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #c9a25a;")
        row = QHBoxLayout()
        row.addWidget(QLabel("Pack name"))
        row.addWidget(self.name, 1)
        row.addWidget(self.version_label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(QLabel("History log of this pack (since its first version):"))
        layout.addWidget(self.history)
        layout.addWidget(note)
        self.name.textChanged.connect(self.update)

    def pack_name(self) -> str:
        return clean_name(self.name.text())

    def update(self) -> None:  # noqa: D102 (also refreshes after labelling)
        name = self.pack_name()
        prov = self.store.provenance
        if not name:
            self.version_label.setText("")
            self.history.setPlainText("Choose a name that identifies your packs, e.g. "
                                      "RavenOCR. Each export adds a version: v1, v2, …")
            return
        version = prov.next_version(name)
        self.version_label.setText(f"→ <b>{html.escape(name)} v{version}</b>")
        label, _uses, _own = self.store.using()
        chosen = [r.category for r in self.rows if r.include]
        cats = category_summary(chosen)
        new = (f"{name} v{version} · today · by {self.store.contributor()[:8]} · exported: "
               f"{label} · {len(chosen)} samples" + (f" · {cats}" if cats else ""))
        ids = {s.id for s in self.store.all()}
        old = [e.line() for e in merge_logs(prov.series_log(name), prov.used_logs(ids))]
        self.history.setPlainText("\n".join([new + "  (this export)"] + old))


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
        self.data_using = QLabel()
        self.data_using.setWordWrap(True)
        self.data_using.setStyleSheet("color: #a9cfff;")
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
        data_layout.addWidget(self.data_using)
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
        label, _uses, _own = self.data.using()
        self.data_using.setText(f"<b>Using:</b> {html.escape(label)}")
        self.data_using.setToolTip(self.data.using_details())

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
        rows = review_export(self.data)
        if not rows:
            QMessageBox.information(self, "Export", "No samples fixed with Edit yet: nothing "
                                    "to export. (Samples OCR read right, or never checked, "
                                    "stay on this computer.)")
            return
        panel = ExportNamePanel(self.data, rows)
        dlg = PackReviewDialog(rows, "export", title="Review export", extra=panel,
                               on_change=panel.update, parent=self)
        dlg.requirements.append(lambda: "" if panel.pack_name() else
                                "Enter a pack name in the Pack name box to export.")
        panel.name.textChanged.connect(lambda _=0: dlg.refresh_ok())
        panel.update()
        dlg.refresh_ok()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = panel.pack_name()
        version = self.data.provenance.next_version(name)
        default = str(downloads_dir() / file_name(name, version))
        path = save_file(self, "Save OCR data pack", default, "OCR data pack (*.zip)")
        if path:
            n = apply_export(self.data, rows, Path(path), name)
            QMessageBox.information(self, "Export", f"Exported {name} v{version}: {n} samples "
                                                    f"to\n{path}")

    def _import(self) -> None:
        path = open_file(self, "Import OCR data pack", str(downloads_dir()),
                         "OCR data pack (*.zip)")
        if not path:
            return
        try:
            pack = read_pack(Path(path))
            rows = review_import(self.data, pack)
        except PackError as exc:
            QMessageBox.warning(self, "Import", f"Not imported: {exc}")
            return
        if not rows:
            QMessageBox.information(self, "Import", "Nothing to import: the pack has no samples "
                                    f"fixed with Edit ({pack.skipped} others left out).")
            return
        used = self.data.size_bytes() / 1024 / 1024
        dlg = PackReviewDialog(rows, "import", title=f"Review import — {pack.label}",
                               skipped=pack.skipped, space=(used, self.settings.data.max_mb),
                               packs=[pack],
                               preview=lambda: preview_import_label(self.data, rows),
                               parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            result = apply_import(self.data, rows,
                                  self.corrections if dlg.learn_fixes else None)
        except PackError as exc:
            QMessageBox.warning(self, "Import", f"Import stopped: {exc}")
            return
        QMessageBox.information(self, "Import", result.summary())
        self._refresh_data()
        self.changed.emit()

    def _merge(self) -> None:
        paths = open_files(self, "Choose packs to merge (two or more)", str(downloads_dir()),
                           "OCR data pack (*.zip)")
        if len(paths) < 2:
            if paths:
                QMessageBox.information(self, "Merge", "Choose two or more packs.")
            return
        try:
            packs = [read_pack(Path(p)) for p in paths]
        except PackError as exc:
            QMessageBox.warning(self, "Merge", f"Not merged: {exc}")
            return
        rows = review_merge(packs)
        skipped = sum(p.skipped for p in packs)
        if not rows:
            QMessageBox.information(self, "Merge", "Nothing to merge: the packs have no "
                                    "samples fixed with Edit.")
            return
        dlg = PackReviewDialog(rows, "merge", title=f"Review merge — {len(packs)} packs",
                               skipped=skipped, packs=packs,
                               preview=lambda: ("", merge_sources(rows)), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, ok = QInputDialog.getText(
            self, "Merged pack name",
            "Your pack name (identifies your packs; each release adds a version):",
            text=self.data.provenance.last_name())
        name = clean_name(name)
        if not ok or not name:
            return
        version = self.data.provenance.next_version(name)
        out = save_file(self, f"Save merged pack {name} v{version}",
                        str(downloads_dir() / file_name(name, version)), "OCR data pack (*.zip)")
        if not out:
            return
        try:
            count = apply_merge(rows, Path(out), self.data.contributor(), name, self.data)
        except PackError as exc:
            QMessageBox.warning(self, "Merge", f"Not merged: {exc}")
            return
        QMessageBox.information(self, "Merge", f"Merged {name} v{version}: {count} samples "
                                                f"saved to\n{out}")

    def _test_set(self) -> None:
        folder = pick_folder(self, "Folder for the OCR test set", str(downloads_dir()))
        if folder:
            n = to_test_set(self.data, Path(folder))
            QMessageBox.information(
                self, "OCR test set",
                f"Wrote {n} checked samples to\n{folder}\n\n"
                "Run: uv run python tools/ocr_bench.py \"<that folder>\"")
