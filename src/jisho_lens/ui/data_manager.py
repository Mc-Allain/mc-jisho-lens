"""Manage OCR data: every sample in your data with its source pack, category and status.

Filter by source pack, category, status or text; edit right answers; label a category or
remove it; delete samples. Changing or deleting a sample that came from a pack makes that
pack "(partial)" in the "Using:" label; a changed sample becomes your own data.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from jisho_lens.core.categories import clean_category
from jisho_lens.core.ocr_data.store import OcrDataStore, Sample
from jisho_lens.ui.pack_review import (
    _HTML,
    CategoryBox,
    _HtmlDelegate,
    plain_tooltip,
    sample_html,
)

THUMB = QSize(180, 50)
(COL_TICK, COL_PICTURE, COL_OCR, COL_ANSWER, COL_STATUS, COL_SOURCE, COL_CATEGORY,
 COL_CREATED, COL_HISTORY) = range(9)
ALL, OWN, NONE = None, "\x00own", "\x00none"
STATUS = {"edited": "Fixed with Edit", "same": "Same as OCR", "none": "Not checked"}


def _when(created: float) -> str:
    import time

    return time.strftime("%Y-%m-%d %H:%M", time.localtime(created))


def _status(s: Sample) -> str:
    """Fixed with Edit / Same as OCR (✓, or an Edit that changed nothing) / Not checked."""
    return STATUS[s.state]


class EditAnswersDialog(QDialog):
    """Edit the right text of several samples: ◀ Prev / Next ▶ go through them; nothing is
    saved until Save changes."""

    def __init__(self, store: OcrDataStore, samples: list[Sample], index: int = 0,
                 parent=None) -> None:
        super().__init__(parent)
        self.store, self.samples, self.index = store, samples, index
        # sample id -> (right text, speaker's name or None), for the samples you changed
        self.changes: dict[str, tuple[str, str | None]] = {}
        self.setWindowTitle("Edit answers")
        self.resize(760, 520)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setMinimumHeight(120)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.ocr = QLabel()
        self.ocr.setWordWrap(True)
        self.diff = QLabel()  # OCR read -> right text, the differences highlighted
        self.diff.setWordWrap(True)
        self.diff.setTextFormat(Qt.TextFormat.RichText)
        self.ocr.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.speaker_box = QLineEdit()
        self.speaker_box.setPlaceholderText("No speaker")
        self.speaker_box.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.editor = QPlainTextEdit()
        self.editor.setStyleSheet("font-size: 18px;")
        self.warning = QLabel()
        self.warning.setStyleSheet("color: #e0a030;")
        self.warning.setWordWrap(True)
        self.prev_btn = QPushButton("◀ Prev")
        self.next_btn = QPushButton("Next ▶")
        self.position = QLabel()
        self.prev_btn.clicked.connect(lambda: self._go(-1))
        self.next_btn.clicked.connect(lambda: self._go(1))
        save = QPushButton("Save changes")
        save.setDefault(True)
        cancel = QPushButton("Cancel")
        save.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        self.save_btn = save
        nav = QHBoxLayout()
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.position)
        nav.addWidget(self.next_btn)
        nav.addStretch(1)
        nav.addWidget(save)
        nav.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(self.picture)
        layout.addWidget(self.info)
        layout.addWidget(QLabel("OCR read:"))
        layout.addWidget(self.ocr)
        speaker_row = QHBoxLayout()
        speaker_row.addWidget(QLabel("Speaker:"))
        speaker_row.addWidget(self.speaker_box, 1)
        layout.addLayout(speaker_row)
        layout.addWidget(QLabel("Right text:"))
        layout.addWidget(self.editor, 1)
        layout.addWidget(QLabel("Differences (OCR read → right text):"))
        layout.addWidget(self.diff)
        layout.addWidget(self.warning)
        layout.addLayout(nav)
        self.editor.textChanged.connect(self._remember)
        self.speaker_box.textChanged.connect(self._remember)
        self._show()

    def _clean(self, text: str) -> str:
        return "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())

    def _remember(self) -> None:
        s = self.samples[self.index]
        text = self._clean(self.editor.toPlainText())
        speaker = " ".join(self.speaker_box.text().split()) or None
        current = "\n".join(s.answer_lines()) if s.truth else None
        if text and (text != current or speaker != (s.shown_speaker or None)):
            self.changes[s.id] = (text, speaker)
        else:
            self.changes.pop(s.id, None)
        self._update_labels()
        self._update_diff()

    def _update_diff(self) -> None:
        s = self.samples[self.index]
        speaker = " ".join(self.speaker_box.text().split()) or None
        before, after = sample_html(s, self._clean(self.editor.toPlainText()), speaker)
        self.diff.setText(f"<div style='font-size:16px'>{before}<br>→ {after}</div>")

    def _show(self) -> None:
        s = self.samples[self.index]
        pm = QPixmap(str(self.store.png_path(s.id)))
        if not pm.isNull():
            pm = pm.scaled(QSize(700, 140), Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        self.picture.setPixmap(pm)
        self.ocr.setText(s.ocr_text or "(nothing)")  # as OCR read it: name and dialogue
        self.editor.blockSignals(True)
        self.speaker_box.blockSignals(True)
        kept = self.changes.get(s.id)
        self.speaker_box.setText((kept[1] if kept else s.shown_speaker) or "")
        # without the speaker line: the window shows it separately
        start = "\n".join(s.answer_lines() if s.truth else s.ocr_lines())
        self.editor.setPlainText(kept[0] if kept else start)
        self.editor.blockSignals(False)
        self.speaker_box.blockSignals(False)
        self._update_labels()
        self._update_diff()
        self.editor.setFocus()

    def _update_labels(self) -> None:
        s = self.samples[self.index]
        n = len(self.samples)
        self.position.setText(f"{self.index + 1} of {n}")
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < n - 1)
        status = _status(s) + (" · changed (not saved yet)" if s.id in self.changes else "")
        self.info.setText(f"<b>{html.escape(s.source_label)}</b> · {status} · "
                          f"{html.escape(s.category or 'no category')} · "
                          f"added {html.escape(s.created.replace('T', ' ')[:16])}")
        self.warning.setText(f"This sample is from {s.source_pack}: changing it makes it your "
                             "own data and that pack (partial)." if s.source_pack_id else "")
        k = len(self.changes)
        self.save_btn.setText(f"Save changes ({k})" if k else "Save changes")
        self.save_btn.setEnabled(bool(k))

    def _go(self, step: int) -> None:
        self.index = max(0, min(len(self.samples) - 1, self.index + step))
        self._show()

    def _save(self) -> None:
        if self.changes:
            self.accept()


class DataManagerWindow(QDialog):
    changed = Signal()  # samples were edited, labelled or deleted

    def __init__(self, store: OcrDataStore, usage=lambda: {}, parent=None,
                 on_answer=lambda sid, text, speaker=None: 0) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage OCR data")
        self.resize(1180, 720)
        self.store = store
        # () -> {sample id: [(capture id, time, favorite)]}: History captures using each
        # sample; a sample used by a favorite capture can't be deleted
        self._usage_of = usage
        self._usage: dict = {}
        # (sample id, text, speaker): History captures show the new answer and name
        self._on_answer = on_answer
        self.samples: list[Sample] = []
        self._ticked: set[str] = set()  # sample ids ticked (kept across reloads)

        self.using = QLabel()
        self.using.setStyleSheet("color: #a9cfff;")
        self.using.setWordWrap(True)
        self.source_filter = QComboBox()
        self.category_filter = QComboBox()
        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", ALL)
        for key, label in (("edited", "Fixed with Edit"), ("same", "Same as OCR"),
                           ("none", "Not checked")):
            self.status_filter.addItem(label, key)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search text…")
        for box in (self.source_filter, self.category_filter, self.status_filter):
            box.currentIndexChanged.connect(self._filter)
        self.search.textChanged.connect(self._filter)
        all_btn = QPushButton("Select all")
        none_btn = QPushButton("Select none")
        all_btn.setToolTip("Tick every row shown")
        none_btn.setToolTip("Untick every row shown")
        all_btn.clicked.connect(lambda: self._tick_shown(True))
        none_btn.clicked.connect(lambda: self._tick_shown(False))
        bar = QHBoxLayout()
        for w in (QLabel("Show"), self.source_filter, self.category_filter,
                  self.status_filter):
            bar.addWidget(w)
        bar.addWidget(self.search, 1)
        bar.addWidget(all_btn)
        bar.addWidget(none_btn)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["", "Picture", "OCR read", "Right answer",
                                              "Status", "Source pack", "Category", "Added",
                                              "In History"])
        self.table.horizontalHeader().moveSection(COL_HISTORY, COL_STATUS + 1)
        self.table.setColumnWidth(COL_HISTORY, 120)
        self.table.setColumnWidth(COL_TICK, 32)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setItemDelegate(_HtmlDelegate(self.table))
        self.table.setIconSize(THUMB)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        for col in (COL_OCR, COL_ANSWER):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(COL_PICTURE, THUMB.width() + 8)
        self.table.setColumnWidth(COL_SOURCE, 150)
        self.table.setColumnWidth(COL_CATEGORY, 140)
        self.table.itemChanged.connect(self._item_changed)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(self._double_clicked)

        self.edit_btn = QPushButton("Edit answer…")
        self.edit_btn.setToolTip("Change the right text of the ticked rows, one after another "
                                 "(Prev / Next). A sample from a pack becomes your own data, and "
                                 "the pack shows as (partial).")
        self.edit_btn.clicked.connect(lambda _checked=False: self._edit())
        self.label_box = CategoryBox(store.categories())
        self.label_box.setToolTip("Pick a category, or type one and press Enter: the ticked rows "
                                  "(or the highlighted row, if none is ticked) get it right "
                                  "away.")
        self.label_box.activated.connect(lambda _=0: self._label())
        self.label_box.lineEdit().returnPressed.connect(self._label)
        self.remove_category_btn = QPushButton("Remove category")
        self.remove_category_btn.setToolTip("Take the category off the ticked rows (or the "
                                            "highlighted row): they get no category")
        self.remove_category_btn.clicked.connect(lambda _checked=False: self._label(""))
        self.delete_btn = QPushButton("Delete…")
        self.delete_btn.clicked.connect(lambda _checked=False: self._delete())
        for button, longest in ((self.edit_btn, "Edit answers (999)…"),
                                (self.delete_btn, "Delete ticked (999)…")):
            # wide enough for the longest text, so the row doesn't shift or cut it
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(longest) + 28)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        self.note = QLabel()
        self.note.setStyleSheet("color: #8a8f99;")
        actions = QHBoxLayout()
        actions.addWidget(self.edit_btn)
        actions.addWidget(QLabel("Label as"))
        actions.addWidget(self.label_box)
        actions.addWidget(self.remove_category_btn)
        actions.addWidget(self.delete_btn)
        actions.addWidget(self.note, 1)
        actions.addWidget(close)

        self.count = QLabel()
        layout = QVBoxLayout(self)
        layout.addWidget(self.using)
        layout.addLayout(bar)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.count)
        layout.addLayout(actions)
        self.reload()

    # ---------- data ----------
    def reload(self) -> None:
        self.samples = sorted(self.store.all(), key=lambda s: s.created, reverse=True)
        try:
            self._usage = self._usage_of() or {}
        except Exception:  # noqa: BLE001
            self._usage = {}
        label, _uses, _own = self.store.using()
        self.using.setText(f"<b>Using:</b> {html.escape(label)}")
        self.using.setToolTip(plain_tooltip(self.store.using_details()))
        self._fill_filters()
        self._ticked &= {s.id for s in self.samples}
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.samples))
        for i, s in enumerate(self.samples):
            self._fill_row(i, s)
        self.table.blockSignals(False)
        self.table.resizeRowsToContents()
        for i in range(len(self.samples)):
            self.table.setRowHeight(i, max(self.table.rowHeight(i), THUMB.height() + 8))
        self._filter()
        self._thumbs = 0
        QTimer.singleShot(0, self._load_thumbs)

    def _fill_filters(self) -> None:
        sources = sorted({s.source_label for s in self.samples if s.source_pack_id},
                         key=str.lower)
        cats = sorted({s.category for s in self.samples if s.category}, key=str.lower)
        self.label_box.set_names(cats)
        for box, first, extra, items in (
                (self.source_filter, "All sources", (OWN, "own data"), sources),
                (self.category_filter, "All categories", (NONE, "No category"), cats)):
            current = box.currentData()
            box.blockSignals(True)
            box.clear()
            box.addItem(first, ALL)
            if box is self.source_filter:
                box.addItem(*reversed(extra))
            for name in items:
                box.addItem(name, name)
            if box is self.category_filter:
                box.addItem(*reversed(extra))
            idx = box.findData(current)
            box.setCurrentIndex(idx if idx >= 0 else 0)
            box.blockSignals(False)

    def _fill_row(self, i: int, s: Sample) -> None:
        def item(text: str, tip: str = "") -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, s.id)
            if tip:
                it.setToolTip(plain_tooltip(tip))
            return it

        tick = item("")
        tick.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                      | Qt.ItemFlag.ItemIsSelectable)
        tick.setCheckState(Qt.CheckState.Checked if s.id in self._ticked
                           else Qt.CheckState.Unchecked)
        self.table.setItem(i, COL_TICK, tick)
        self.table.setItem(i, COL_PICTURE, item(""))
        ocr_item, answer_item = item(""), item("")
        # the speaker's name on the first line, the dialogue below (one cell each)
        ocr_html, answer_html = sample_html(s)
        ocr_item.setData(_HTML, ocr_html)
        answer_item.setData(_HTML, answer_html)
        self.table.setItem(i, COL_OCR, ocr_item)
        self.table.setItem(i, COL_ANSWER, answer_item)
        self.table.setItem(i, COL_STATUS, item(_status(s)))
        source = item(s.source_label)
        if not s.source_pack_id:
            source.setForeground(Qt.GlobalColor.gray)
        self.table.setItem(i, COL_SOURCE, source)
        self.table.setItem(i, COL_CATEGORY, item(s.category or "—"))
        self.table.setItem(i, COL_CREATED, item(s.created.replace("T", " ")[:16]))
        used = self._usage.get(s.id, [])
        favs = [u for u in used if u[2]]
        if favs:
            text = "★ favorite" + (f" (+{len(used) - 1})" if len(used) > 1 else "")
        else:
            text = f"{len(used)} capture{'s' if len(used) != 1 else ''}" if used else "—"
        tip = ("Used by these History captures (captures of the same sentence share one "
               "sample, so its picture can be from an earlier capture):\n"
               + "\n".join(f"{'★ ' if fav else ''}{_when(created)}"
                           + (" (favorite: this sample can't be deleted)" if fav else "")
                           for _cid, created, fav in used)
               if used else "Not used by any capture in History")
        self.table.setItem(i, COL_HISTORY, item(text, tip))

    def _load_thumbs(self) -> None:
        end = min(self._thumbs + 12, len(self.samples))
        for i in range(self._thumbs, end):
            pm = QPixmap(str(self.store.png_path(self.samples[i].id)))
            if not pm.isNull() and self.table.item(i, COL_PICTURE) is not None:
                self.table.item(i, COL_PICTURE).setData(
                    Qt.ItemDataRole.DecorationRole,
                    pm.scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation))
        self._thumbs = end
        if end < len(self.samples):
            QTimer.singleShot(0, self._load_thumbs)

    # ---------- filters ----------
    def _visible(self, s: Sample) -> bool:
        src, cat, status = (self.source_filter.currentData(), self.category_filter.currentData(),
                            self.status_filter.currentData())
        text = self.search.text().strip().lower()
        if src == OWN and s.source_pack_id or src not in (ALL, OWN) and s.source_label != src:
            return False
        if cat == NONE and s.category or cat not in (ALL, NONE) and s.category != cat:
            return False
        state = s.state
        if status is not None and state != status:
            return False
        return not text or text in (s.ocr_text + "\n" + (s.truth or "")).lower()

    def _filter(self) -> None:
        shown = 0
        for i, s in enumerate(self.samples):
            hide = not self._visible(s)
            self.table.setRowHidden(i, hide)
            shown += not hide
        self.count.setText(f"{shown} of {len(self.samples)} samples shown")
        self._selection_changed()

    # ---------- actions ----------
    def _selected(self) -> list[Sample]:
        """The ticked rows shown, in list order (latest first); with nothing ticked, the
        highlighted row(s)."""
        ticked = [s for i, s in enumerate(self.samples)
                  if s.id in self._ticked and not self.table.isRowHidden(i)]
        if ticked:
            return ticked
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return [self.samples[r] for r in rows if not self.table.isRowHidden(r)]

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != COL_TICK:
            return
        sid = self.samples[item.row()].id
        if item.checkState() == Qt.CheckState.Checked:
            self._ticked.add(sid)
        else:
            self._ticked.discard(sid)
        self._selection_changed()

    def _tick_shown(self, on: bool) -> None:
        self.table.blockSignals(True)
        for i, s in enumerate(self.samples):
            if self.table.isRowHidden(i):
                continue
            (self._ticked.add if on else self._ticked.discard)(s.id)
            self.table.item(i, COL_TICK).setCheckState(
                Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._selection_changed()

    def _selection_changed(self) -> None:
        sel = self._selected()
        n = len(sel)
        ticked_n = len([s for s in sel if s.id in self._ticked])
        self.edit_btn.setEnabled(bool(sel))
        self.edit_btn.setText(f"Edit answers ({n})…" if n > 1 else "Edit answer…")
        self.delete_btn.setEnabled(bool(sel))
        self.label_box.setEnabled(bool(sel))
        self.remove_category_btn.setEnabled(any(s.category for s in sel))
        what = "ticked" if self._ticked & {s.id for s in sel} else "selected"
        self.delete_btn.setText(f"Delete {what} ({n})…" if n > 1 else "Delete…")
        hidden = len(self._ticked) - ticked_n
        self.count.setText(self.count.text().split(" · ")[0]
                           + (f" · {ticked_n} ticked" if ticked_n else
                              (" · 1 selected" if n == 1 else f" · {n} selected" if n else ""))
                           + (f" ({hidden} more ticked but hidden by the filter)"
                              if hidden > 0 else ""))

    def _done(self, note: str) -> None:
        self.note.setText(note)
        self.reload()
        self.changed.emit()

    def _edit(self, start: Sample | None = None) -> None:
        """Edit the ticked records one after another (Prev / Next), starting at the first
        one in the list (the latest), or at `start`."""
        sel = self._selected()
        if not isinstance(start, Sample):
            start = None
        if start is not None and start not in sel:
            sel = [start]
        if not sel:
            return
        dlg = EditAnswersDialog(self.store, sel, sel.index(start) if start in sel else 0,
                                self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.changes:
            return
        packs = set()
        for sid, (text, speaker) in dlg.changes.items():
            s = self.store.get(sid)
            if s is None:
                continue
            if s.source_pack_id:
                packs.add(s.source_pack)
            if text != "\n".join(s.answer_lines()) or s.truth is None:
                self.store.set_truth(sid, text, "edited")
            if speaker != s.shown_speaker:
                self.store.set_speaker(sid, speaker)
            try:
                self._on_answer(sid, text, speaker)  # its History captures show it
            except Exception:  # noqa: BLE001
                pass
        n = len(dlg.changes)
        note = f"{n} answer{'s' if n != 1 else ''} changed"
        if packs:
            note += f" (now your own data; partial: {', '.join(sorted(packs))})"
        self._done(note)

    def _label(self, category: str | None = None) -> None:
        """Give the ticked (or highlighted) samples a category; "" removes it."""
        sel = self._selected()
        if not sel:
            return
        category = clean_category(self.label_box.text() if category is None else category)
        if not category:
            self.label_box.setEditText("")
        changed = [s for s in sel if s.category != category]
        for s in changed:
            self.store.set_category(s.id, category)
        n = len(changed)
        self._done(f"{n} labelled “{category}”" if category
                   else f"category removed from {n}" if n else "no category to remove")

    def _delete(self) -> None:
        sel = self._selected()
        if not sel:
            return
        self._usage = self._usage_of() or {}
        protected = {sid for sid, used in self._usage.items() if any(u[2] for u in used)}
        keep = [s for s in sel if s.id in protected]
        go = [s for s in sel if s.id not in protected]
        from_packs = sorted({s.source_pack for s in go if s.source_pack_id})
        text = f"Delete {len(go)} sample{'s' if len(go) != 1 else ''} from your OCR data?"
        if from_packs:
            text += f"\n\nThese packs will show as (partial): {', '.join(from_packs)}."
        if keep:
            when = ", ".join(_when(u[1]) for s in keep for u in self._usage.get(s.id, [])
                             if u[2])
            text += (f"\n\n{len(keep)} sample{'s' if len(keep) != 1 else ''} will be kept: "
                     f"used by a favorite capture in History ({when}). Captures of the same "
                     "sentence share one sample, so its picture can be from an earlier "
                     "capture. Remove the star in History first to delete it.")
        if not go:
            QMessageBox.information(self, "Delete", text)
            return
        if QMessageBox.question(self, "Delete", text + "\n\nThis can't be undone.",
                                defaultButton=QMessageBox.StandardButton.No) \
                != QMessageBox.StandardButton.Yes:
            return
        for s in go:
            self.store.delete(s.id)
        self._done(f"{len(go)} deleted")

    def _double_clicked(self, row: int, col: int) -> None:
        if col == COL_PICTURE:
            pm = QPixmap(str(self.store.png_path(self.samples[row].id)))
            if not pm.isNull():
                from jisho_lens.ui.pack_review import _ImageView

                _ImageView(pm, self.samples[row].truth or "", self).exec()
        elif col != COL_TICK:
            self._edit(self.samples[row])
