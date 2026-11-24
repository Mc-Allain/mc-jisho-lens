"""Review window for importing or merging data packs: nothing is written until confirmed.

One row per item in the pack(s): Include checkbox, picture (OCR packs), status, what OCR
read, Before (your answer) / After (theirs) with the changed characters highlighted, and for
"Different answer" rows what to do. Filters by status and contributor; Select all /
none act on the rows shown. Built on core.ocr_data.packs.ReviewRow; translation packs
(Phase 5) reuse it without the picture column.
"""

from __future__ import annotations

import html
from difflib import SequenceMatcher

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAbstractTextDocumentLayout, QPixmap, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jisho_lens.core.categories import category_suggestions, category_summary, clean_category
from jisho_lens.core.ocr_data.packs import (
    ALL_ANSWERS,
    DIFFERS,
    KEEP_ALTERNATIVE,
    KEEP_MINE,
    NEW,
    REMOVED,
    SAME,
    SAME_SENTENCE,
    STATUS_LABELS,
    USE_THEIRS,
    ReviewRow,
    carry_choices,
    label_rows,
    merge_contributions,
    order_packs,
)

THUMB = QSize(200, 56)
STATUS_COLORS = {NEW: "#5cbf6a", DIFFERS: "#e0a030", SAME_SENTENCE: "#6fb3e0", SAME: "#8a8f99",
                 REMOVED: "#c07070"}
COL_INCLUDE, COL_IMAGE, COL_STATUS, COL_OCR, COL_BEFORE, COL_AFTER, COL_CHOICE, COL_FROM, \
    COL_CATEGORY, COL_SOURCE = range(10)
NO_CATEGORY = "\x00none"  # filter value for rows without a category
_HTML = Qt.ItemDataRole.UserRole + 10


def _esc(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def diff_html(before: str | None, after: str) -> tuple[str, str]:
    """Before / after as HTML with removed characters (red) and added ones (green)."""
    if not before:
        return ("<span style='color:#8a8f99'>none</span>", _esc(after))
    a, b = [], []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, before, after,
                                              autojunk=False).get_opcodes():
        if tag == "equal":
            a.append(_esc(before[i1:i2]))
            b.append(_esc(after[j1:j2]))
            continue
        if i2 > i1:
            a.append(f"<span style='background:#6b2a2a;color:#ffd0d0'>"
                     f"{_esc(before[i1:i2])}</span>")
        if j2 > j1:
            b.append(f"<span style='background:#24552e;color:#d0ffd8'>"
                     f"{_esc(after[j1:j2])}</span>")
    return "".join(a), "".join(b)


def sample_html(sample, text: str | None = None, speaker=...) -> tuple[str, str]:
    """(OCR read, right answer) of a sample as HTML for one cell each: the speaker's name
    on the first line, the dialogue below, the differences highlighted in both. `text` /
    `speaker` replace the right answer / your name (e.g. while editing)."""
    read_speaker = sample.speaker or ""
    read_text = "\n".join(sample.ocr_lines())
    fixed_speaker = (sample.shown_speaker if speaker is ... else speaker) or ""
    fixed_text = "\n".join(sample.answer_lines()) if text is None else text
    if text is None and sample.truth is None:  # not checked: no right answer yet
        return (_speaker_line(_esc(read_speaker)) + _esc(read_text),
                "<span style='color:#8a8f99'>—</span>")
    text_before, text_after = diff_html(read_text, fixed_text) if read_text else (
        "", _esc(fixed_text))
    if read_speaker or fixed_speaker:
        name_before, name_after = (diff_html(read_speaker, fixed_speaker) if read_speaker
                                   else ("", _esc(fixed_speaker)))
        if not fixed_speaker:  # the name was removed
            name_after = "<span style='color:#8a8f99'>(no speaker)</span>"
    else:
        name_before = name_after = ""
    return (_speaker_line(name_before) + text_before, _speaker_line(name_after) + text_after)


def _speaker_line(name_html: str) -> str:
    return (f"<span style='color:#a9cfff;font-weight:bold'>{name_html}</span><br>"
            if name_html else "")


class _HtmlDelegate(QStyledItemDelegate):
    """Draws a cell's HTML (diff highlighting) instead of plain text."""

    def _doc(self, option, index) -> QTextDocument:
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDefaultStyleSheet("body { color: #e6e6e6; }")
        doc.setHtml(f"<body>{index.data(_HTML) or ''}</body>")
        doc.setTextWidth(max(80, option.rect.width() - 8))
        return doc

    def paint(self, painter, option, index) -> None:
        if index.data(_HTML) is None:
            super().paint(painter, option, index)
            return
        self.initStyleOption(option, index)
        option.text = ""
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option,
                                          painter, option.widget)
        doc = self._doc(option, index)
        painter.save()
        painter.translate(option.rect.left() + 4, option.rect.top() + 4)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        if index.data(_HTML) is None:
            return super().sizeHint(option, index)
        doc = self._doc(option, index)
        return QSize(int(doc.idealWidth()) + 8, int(doc.size().height()) + 8)


class _ImageView(QDialog):
    def __init__(self, pixmap: QPixmap, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        label = QLabel()
        label.setPixmap(pixmap)
        area = QScrollArea()
        area.setWidget(label)
        layout = QVBoxLayout(self)
        layout.addWidget(area)
        self.resize(min(pixmap.width() + 40, 1400), min(pixmap.height() + 60, 900))


def plain_tooltip(text: str) -> str:
    """Hover text shown exactly as written (text from packs must not act as formatting)."""
    return "<qt>" + _esc(text) + "</qt>"


class CategoryBox(QComboBox):
    """Type a category, or pick one: the defaults (Azur Promilia JP) and those in use."""

    def __init__(self, names=(), parent=None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.set_names(names)
        completer = QCompleter(self.model(), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.setCompleter(completer)
        self.lineEdit().setPlaceholderText("Category (blank = none)")
        self.setMinimumWidth(200)

    def set_names(self, names) -> None:
        text = self.currentText() if self.count() else ""
        self.clear()
        self.addItems(category_suggestions(*names))
        self.setEditText(text)

    def text(self) -> str:
        return clean_category(self.currentText())


class PackReviewDialog(QDialog):
    """mode: "import" (Before = your data), "merge" (rows where packs disagree) or
    "export" (your fixed samples: Before = what OCR read, After = your fix)."""

    def __init__(self, rows: list[ReviewRow], mode: str = "import", *, title: str = "",
                 skipped: int = 0, space: tuple[float, int] | None = None,
                 show_images: bool = True, learn_option: bool = True, packs=None,
                 preview=None, extra=None, on_change=None, rebuild=None, add_packs=None,
                 parent=None) -> None:
        """Merge: `rebuild(packs) -> rows` lets packs be removed here (and `add_packs(parent)
        -> packs to add` added); the rows update at once, keeping the choices made."""
        super().__init__(parent)
        self._rebuild, self._add_packs = rebuild, add_packs
        self.rows, self.mode = rows, mode
        self._space = space  # (MB used now, limit MB) for the footer
        self._preview = preview  # () -> ("Using:" now, after) — kept up to date
        self._packs = order_packs(list(packs)) if mode == "merge" and packs else (packs or [])
        self.changed_hooks = [on_change] if on_change else []  # called on any change
        # () -> "" or why the main button can't be pressed yet (e.g. no pack name)
        self.requirements: list = []
        self.setWindowTitle(title or {"import": "Review import", "merge": "Review merge",
                                      "export": "Review export"}[mode])
        self.resize(1180, 760)

        if mode == "export":
            intro = QLabel("Check what will be exported (only samples you fixed with "
                           "<b>Edit</b>). Untick anything you don't want to share, like "
                           "screenshots that show names or chat, and label them with a "
                           "category if you like. Nothing is saved until you press "
                           "<b>Export…</b>.")
        else:
            intro = QLabel(
                "Check what will be added. Nothing changes until you press "
                + ("<b>Import</b>." if mode == "import" else "<b>Save merged pack</b>.")
                + " Untick anything you don't trust, or screenshots that show names or chat.")
        intro.setWordWrap(True)
        self.status_filter = QComboBox()
        self.status_filter.addItem("All", None)
        self.who_filter = QComboBox()
        self._fill_filters()
        self.category_filter = QComboBox()
        for box in (self.status_filter, self.who_filter, self.category_filter):
            box.currentIndexChanged.connect(self._filter)
        all_btn = QPushButton("Select all")
        none_btn = QPushButton("Select none")
        all_btn.clicked.connect(lambda: self._select(True))
        none_btn.clicked.connect(lambda: self._select(False))
        bar = QHBoxLayout()
        for w in (QLabel("Show"), self.status_filter, self.who_filter, self.category_filter):
            bar.addWidget(w)
        self.status_filter.setVisible(mode != "export")
        self.who_filter.setVisible(mode != "export")
        bar.addStretch(1)
        bar.addWidget(all_btn)
        bar.addWidget(none_btn)

        # categories: tick / untick a whole category; label ticked rows (export, merge)
        self.quick_category = QComboBox()
        tick_btn = QPushButton("Tick")
        untick_btn = QPushButton("Untick")
        tick_btn.setToolTip("Tick every row of this category")
        untick_btn.setToolTip("Untick every row of this category")
        tick_btn.clicked.connect(lambda: self._tick_category(True))
        untick_btn.clicked.connect(lambda: self._tick_category(False))
        self.label_box = CategoryBox(self._row_categories())
        self.label_box.setToolTip("Pick a category, or type one and press Enter: the ticked "
                                  "rows shown get it right away. Clear it to remove it.")
        self._last_label: str | None = None  # last category applied from the box
        self.label_box.activated.connect(lambda _=0: self._label_ticked())
        self.label_box.lineEdit().editingFinished.connect(self._label_typed)
        self.label_note = QLabel()
        self.label_note.setStyleSheet("color: #8a8f99;")
        self.remove_category_btn = QPushButton("Remove category")
        self.remove_category_btn.setToolTip("Take the category off the ticked rows shown "
                                            "(they get no category)")
        self.remove_category_btn.clicked.connect(lambda _checked=False: self._unlabel_ticked())
        cat_bar = QHBoxLayout()
        cat_bar.addWidget(QLabel("Category"))
        cat_bar.addWidget(self.quick_category)
        cat_bar.addWidget(tick_btn)
        cat_bar.addWidget(untick_btn)
        cat_bar.addStretch(1)
        if mode in ("export", "merge"):
            cat_bar.addWidget(QLabel("Label ticked rows as"))
            cat_bar.addWidget(self.label_box)
            cat_bar.addWidget(self.remove_category_btn)
            cat_bar.addWidget(self.label_note)
        self.label_box.setVisible(mode in ("export", "merge"))
        self.remove_category_btn.setVisible(mode in ("export", "merge"))

        self.table = QTableWidget(len(rows), 10)
        self.table.setHorizontalHeaderLabels(
            ["Include", "Picture", "Status", "OCR read",
             {"import": "Before (yours)", "merge": "Before (first pack)",
              "export": "OCR read"}[mode],
             {"import": "After (theirs)", "merge": "After (other packs)",
              "export": "Your fix"}[mode],
             "Choice", "From", "Category", "Source pack"])
        self.table.setItemDelegate(_HtmlDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setIconSize(THUMB)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        for col in (COL_OCR, COL_BEFORE, COL_AFTER):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(COL_IMAGE, THUMB.width() + 8)
        self.table.setColumnHidden(COL_IMAGE, not show_images)
        self.table.setColumnHidden(COL_FROM, mode == "export" or (mode == "import" and len(
            {r.pack.name for r in rows}) <= 1))
        for col in (COL_STATUS, COL_OCR, COL_CHOICE):
            self.table.setColumnHidden(col, mode == "export" or self.table.isColumnHidden(col))
        header.moveSection(header.visualIndex(COL_CATEGORY), header.visualIndex(COL_AFTER) + 1)
        header.moveSection(header.visualIndex(COL_SOURCE), header.visualIndex(COL_CATEGORY) + 1)
        self.table.setColumnWidth(COL_CATEGORY, 150)
        self.table.setColumnWidth(COL_SOURCE, 150)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        self._fill()
        self.table.itemChanged.connect(self._item_changed)

        self.learn = QCheckBox("Also learn OCR fixes from these (applied to your future captures; "
                               "see Settings → Learned corrections)")
        self.learn.setVisible(mode == "import" and learn_option)
        self._refresh_categories()
        self.footer = QLabel()
        self.footer.setWordWrap(True)
        note = QLabel(f"{skipped} samples without an Edit fix were left out (only fixed "
                      "samples are shared)." if skipped else "")
        note.setStyleSheet("color: #8a8f99;")
        note.setVisible(bool(skipped))
        buttons = QDialogButtonBox()
        self.ok_btn = buttons.addButton({"import": "Import", "merge": "Save merged pack…",
                                         "export": "Export…"}[mode],
                                        QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.blocked = QLabel()  # why the main button is disabled
        self.blocked.setStyleSheet("color: #e0a030;")
        self.blocked.setWordWrap(True)
        bottom = QHBoxLayout()
        bottom.addWidget(self.blocked, 1)
        bottom.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        self._pack_labels: list = []  # (pack, label): merge shows what each pack brings
        self._packs_box = QWidget()  # the packs at the top (rebuilt when packs change)
        self._packs_layout = QVBoxLayout(self._packs_box)
        self._packs_layout.setContentsMargins(0, 0, 0, 0)
        # many packs scroll instead of making the window taller (up to PACKS_SHOWN rows)
        self.packs_scroll = QScrollArea()
        self.packs_scroll.setWidget(self._packs_box)
        self.packs_scroll.setWidgetResizable(True)
        self.packs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.packs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.packs_scroll)
        self.add_packs_btn = QPushButton("Add packs…")
        self.add_packs_btn.setToolTip("Add more packs to this merge (from any folder)")
        self.add_packs_btn.clicked.connect(lambda _checked=False: self._add())
        self.pack_note = QLabel()  # packs Add left out, and why
        self.pack_note.setWordWrap(True)
        self.pack_note.setStyleSheet("color: #d0a040;")
        self.pack_note.setVisible(False)
        if add_packs is not None:
            add_bar = QHBoxLayout()
            add_bar.addWidget(self.pack_note, 1)
            add_bar.addStretch(1)
            add_bar.addWidget(self.add_packs_btn)
            layout.addLayout(add_bar)
        self._show_packs()
        layout.addLayout(bar)
        layout.addLayout(cat_bar)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.learn)
        layout.addWidget(note)
        self.using = QLabel()
        self.using.setWordWrap(True)
        self.using.setStyleSheet("color: #a9cfff;")
        self.using.setVisible(preview is not None)
        layout.addWidget(self.using)
        if extra is not None:
            layout.addWidget(extra)
        layout.addWidget(self.footer)
        layout.addLayout(bottom)
        self._update_footer()
        self._thumbs_done = 0
        if show_images:
            QTimer.singleShot(0, self._load_thumbs)

    def _pack_header(self, pack) -> QHBoxLayout:
        """'RavenOCR v2 · by 58d34512 · 120 samples   [History…]'."""
        info = pack.info
        row = QHBoxLayout()
        who = f" · by {html.escape(info.contributor[:8])}" if info and info.contributor \
            else ""
        extra = "" if info and info.has_history else " · no history (older pack)"
        label = QLabel()
        label.setProperty("head", f"<b>{html.escape(pack.label)}</b>{who} · "
                          f"{len(pack.samples)} sample{'s' if len(pack.samples) != 1 else ''} · "
                          f"file {html.escape(pack.name)}{extra}")
        label.setText(label.property("head"))
        self._pack_labels.append((pack, label))
        row.addWidget(label, 1)
        if info and info.log:
            button = QPushButton("History…")
            button.setToolTip(plain_tooltip(info.history_text()))
            button.clicked.connect(lambda _=False, i=info: self._show_history(i))
            row.addWidget(button)
        if self._rebuild is not None:
            remove = QPushButton("Remove")
            remove.setToolTip("Take this pack out of the merge")
            remove.setObjectName("remove_pack")
            remove.setProperty("pack_label", pack.label)
            remove.clicked.connect(lambda _=False, p=pack: self.remove_pack(p))
            row.addWidget(remove)
        return row

    def _show_packs(self) -> None:
        """(Re)build the packs at the top."""
        while self._packs_layout.count():
            item = self._packs_layout.takeAt(0)
            holder = item.widget()
            if holder is not None:
                holder.setParent(None)  # gone from the window at once
                holder.deleteLater()
        self._pack_labels = []
        for pack in self._packs:
            holder = QWidget()
            line = self._pack_header(pack)
            line.setContentsMargins(0, 0, 0, 0)
            holder.setLayout(line)
            self._packs_layout.addWidget(holder)
        self._fit_packs_scroll()

    PACKS_SHOWN = 4  # pack rows visible before the list scrolls

    def _fit_packs_scroll(self) -> None:
        """As tall as the packs, up to PACKS_SHOWN of them; more packs scroll."""
        rows = [self._packs_layout.itemAt(i).widget()
                for i in range(self._packs_layout.count())]
        self.packs_scroll.setVisible(bool(rows))
        if not rows:
            return
        spacing = self._packs_layout.spacing()
        shown = rows[:self.PACKS_SHOWN]
        height = sum(r.sizeHint().height() for r in shown) + spacing * (len(shown) - 1)
        self.packs_scroll.setFixedHeight(height + 2)

    @property
    def packs(self) -> list:
        return list(self._packs)

    # ---------- packs added / removed here (merge)
    def remove_pack(self, pack) -> bool:
        from PySide6.QtWidgets import QMessageBox

        if QMessageBox.question(
                self, "Remove pack",
                f"Take {pack.label} out of this merge?\n\nIts rows go, and choices made on "
                "them are lost (add it again to start over).",
                defaultButton=QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        self.set_packs([p for p in self._packs if p is not pack])
        return True

    def _add(self) -> None:
        added, note = self._add_packs(self)
        self.pack_note.setText(note)
        self.pack_note.setVisible(bool(note))
        if added:
            self.set_packs(self._packs + list(added))

    def set_packs(self, packs: list) -> None:
        """The merge's packs changed: rebuild the rows, keeping the choices made."""
        packs = order_packs(list(packs))
        rows = self._rebuild(packs) if packs else []
        carry_choices(self.rows, rows)
        self._packs, self.rows = packs, rows
        self._show_packs()
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(len(rows))
        self._fill()
        self.table.blockSignals(False)
        self._fill_filters()
        self._refresh_categories()
        self._filter()  # also updates the footer, counts and the main button
        self._thumbs_done = 0
        if not self.table.isColumnHidden(COL_IMAGE):
            QTimer.singleShot(0, self._load_thumbs)

    def _fill_filters(self) -> None:
        """Status / contributor filters with counts (kept when still offered)."""
        for box in (self.status_filter, self.who_filter):
            box.blockSignals(True)
        status, who = self.status_filter.currentData(), self.who_filter.currentData()
        self.status_filter.clear()
        self.status_filter.addItem("All", None)
        for value in (NEW, DIFFERS, SAME_SENTENCE, REMOVED, SAME):
            n = sum(r.status == value for r in self.rows)
            if n:
                self.status_filter.addItem(f"{STATUS_LABELS[value]} ({n})", value)
        self.who_filter.clear()
        self.who_filter.addItem("All contributors", None)
        for c in sorted({r.contributor for r in self.rows if r.contributor}):
            self.who_filter.addItem(c[:8], c)
        for box, value in ((self.status_filter, status), (self.who_filter, who)):
            box.setCurrentIndex(max(0, box.findData(value)))
            box.blockSignals(False)

    def _show_history(self, info) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(f"History of {info.label}")
        text = QPlainTextEdit(info.history_text())
        text.setReadOnly(True)
        box = QVBoxLayout(dlg)
        box.addWidget(text)
        dlg.resize(760, 300)
        dlg.exec()

    # ---------- table ----------
    def _fill(self) -> None:
        for i, row in enumerate(self.rows):
            check = QTableWidgetItem()
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if row.status != SAME:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            check.setFlags(flags)
            check.setCheckState(Qt.CheckState.Checked if row.include
                                else Qt.CheckState.Unchecked)
            self.table.setItem(i, COL_INCLUDE, check)
            self.table.setItem(i, COL_IMAGE, QTableWidgetItem())
            status = QTableWidgetItem()
            label = (f"Removed in {row.removed_in}" if row.status == REMOVED
                     else STATUS_LABELS[row.status])
            status.setData(_HTML, f"<b style='color:{STATUS_COLORS[row.status]}'>"
                                  f"{html.escape(label)}</b>")
            status.setToolTip({
                NEW: "You don't have this picture (or have it without a right answer)",
                DIFFERS: "You have this picture with a different right answer",
                SAME_SENTENCE: "Another crop of a sentence you already have (skipped by "
                               "default to save space)",
                SAME: "Already identical in your data: nothing to import",
                REMOVED: "An older version of this pack has it, but its newer version in this "
                         "merge dropped it (unticked; tick it to bring it back)",
            }[row.status])
            self.table.setItem(i, COL_STATUS, status)
            ocr = QTableWidgetItem()
            ocr.setData(_HTML, f"<span style='color:#a9b0bb'>{_esc(row.ocr_text)}</span>")
            self.table.setItem(i, COL_OCR, ocr)
            before_item, after_item = QTableWidgetItem(), QTableWidgetItem()
            if self.mode == "merge" and row.status == DIFFERS:
                first = row.answers[0].truth
                before_item.setData(_HTML, f"{_esc(first)}<br><span style='color:#8a8f99'>"
                                           f"{html.escape(row.answers[0].pack)}</span>")
                parts = []
                for a in row.answers[1:]:
                    _, after = diff_html(first, a.truth)
                    parts.append(f"{after}<br><span style='color:#8a8f99'>"
                                 f"{html.escape(a.pack)}</span>")
                after_item.setData(_HTML, "<br>".join(parts))
            elif self.mode == "export":
                before, after = sample_html(row.sample)  # name + dialogue, one cell each
                before_item.setData(_HTML, before)
                after_item.setData(_HTML, after)
            else:
                before, after = diff_html(row.before, row.after)
                if self.mode == "merge" and row.before is None:
                    before = ""  # nothing to compare with in a merge
                before_item.setData(_HTML, before)
                extra = "".join(f"<br><span style='color:#8a8f99'>also:</span> {_esc(a.truth)}"
                                for a in row.answers[1:])
                after_item.setData(_HTML, after + extra)
            self.table.setItem(i, COL_BEFORE, before_item)
            self.table.setItem(i, COL_AFTER, after_item)
            self.table.setItem(i, COL_CHOICE, QTableWidgetItem())
            if row.status == DIFFERS:
                self.table.setCellWidget(i, COL_CHOICE, self._choice_box(row))
            self.table.setItem(i, COL_CATEGORY, QTableWidgetItem())
            self._show_category(i)
            source = QTableWidgetItem(self._source_of(row))
            self.table.setItem(i, COL_SOURCE, source)
            source = QTableWidgetItem(f"{row.pack.name}\n{row.contributor[:8]}")
            source.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(i, COL_FROM, source)
        self.table.resizeRowsToContents()
        for i in range(len(self.rows)):
            self.table.setRowHeight(i, max(self.table.rowHeight(i), THUMB.height() + 8))
        if any(r.status == DIFFERS for r in self.rows):
            widest = max(self.table.cellWidget(i, COL_CHOICE).sizeHint().width()
                         for i, r in enumerate(self.rows) if r.status == DIFFERS)
            self.table.setColumnWidth(COL_CHOICE, widest + 12)

    def _choice_box(self, row: ReviewRow) -> QComboBox:
        box = QComboBox()
        if self.mode == "import":
            options = [("Keep mine", KEEP_MINE), ("Use theirs", USE_THEIRS),
                       ("Keep as alternative", KEEP_ALTERNATIVE)]
        else:
            options = [("Keep all (first as the answer)", ALL_ANSWERS)]
            options += [(f"Use {a.pack}", i) for i, a in enumerate(row.answers)]
        for label, value in options:
            box.addItem(label, value)
        box.setCurrentIndex(max(0, box.findData(row.choice)))
        box.setToolTip({KEEP_MINE: "Your answer stays; theirs is not kept",
                        USE_THEIRS: "Their answer is used; yours is kept as an alternative",
                        KEEP_ALTERNATIVE: "Yours stays; theirs is kept as an alternative and "
                                          "the sample is marked for review"}
                       .get(row.choice, "Which answer the merged pack uses"))
        box.currentIndexChanged.connect(lambda _=0, r=row, b=box: self._choose(r, b))
        return box

    def _choose(self, row: ReviewRow, box: QComboBox) -> None:
        row.choice = box.currentData()
        self._update_footer()  # e.g. Keep mine makes the pack "(partial)"

    def _load_thumbs(self) -> None:
        """Pictures are read from the pack a few at a time, so big packs open quickly."""
        end = min(self._thumbs_done + 12, len(self.rows))
        for i in range(self._thumbs_done, end):
            row = self.rows[i]
            try:
                pm = QPixmap()
                pm.loadFromData(row.pack.image(row.sid), "PNG")
                self.table.item(i, COL_IMAGE).setData(
                    Qt.ItemDataRole.DecorationRole,
                    pm.scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation))
                self.table.item(i, COL_IMAGE).setToolTip("Double-click to see it full size")
            except Exception:  # noqa: BLE001
                self.table.item(i, COL_IMAGE).setText("(picture unavailable)")
        self._thumbs_done = end
        if end < len(self.rows):
            QTimer.singleShot(0, self._load_thumbs)

    def _double_clicked(self, i: int, col: int) -> None:
        if col != COL_IMAGE:
            return
        row = self.rows[i]
        pm = QPixmap()
        if pm.loadFromData(row.pack.image(row.sid), "PNG"):
            _ImageView(pm, row.after[:40], self).exec()

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == COL_INCLUDE:
            self.rows[item.row()].include = item.checkState() == Qt.CheckState.Checked
            self._update_footer()

    # ---------- filters ----------
    def _visible(self, row: ReviewRow) -> bool:
        status, who = self.status_filter.currentData(), self.who_filter.currentData()
        cat = self.category_filter.currentData()
        return ((status is None or row.status == status)
                and (who is None or row.contributor == who)
                and (cat is None or (row.category or NO_CATEGORY) == cat))

    def _source_of(self, row: ReviewRow) -> str:
        """Export: where your sample came from; import / merge: the pack(s) it comes from."""
        if self.mode == "export":
            return row.sample.source_label
        packs = [row.pack.label] + [a.source.label for a in row.answers
                                    if a.source is not None]
        return " / ".join(dict.fromkeys(packs))

    # ---------- categories ----------
    def _row_categories(self) -> list[str]:
        return sorted({r.category for r in self.rows if r.category}, key=str.lower)

    def _show_category(self, i: int) -> None:
        cat = self.rows[i].category
        item = self.table.item(i, COL_CATEGORY)
        item.setData(_HTML, html.escape(cat) if cat
                     else "<span style='color:#8a8f99'>—</span>")

    def _refresh_categories(self) -> None:
        """Category filter / quick-select lists with counts, after labelling."""
        counts: dict[str, int] = {}
        for r in self.rows:
            counts[r.category or NO_CATEGORY] = counts.get(r.category or NO_CATEGORY, 0) + 1
        names = self._row_categories()
        for box, first in ((self.category_filter, ("All categories", None)),
                           (self.quick_category, None)):
            current = box.currentData()
            box.blockSignals(True)
            box.clear()
            if first:
                box.addItem(*first)
            for name in names:
                box.addItem(f"{name} ({counts[name]})", name)
            if counts.get(NO_CATEGORY):
                box.addItem(f"No category ({counts[NO_CATEGORY]})", NO_CATEGORY)
            index = box.findData(current)
            box.setCurrentIndex(index if index >= 0 else 0)
            box.blockSignals(False)
        self.label_box.set_names(names)

    def _tick_category(self, on: bool) -> None:
        cat = self.quick_category.currentData()
        if cat is None:
            return
        self.table.blockSignals(True)
        for i, row in enumerate(self.rows):
            if row.status != SAME and (row.category or NO_CATEGORY) == cat:
                row.include = on
                self.table.item(i, COL_INCLUDE).setCheckState(
                    Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._update_footer()

    def _label_typed(self) -> None:
        """Enter or leaving the box: apply a typed category (only when it changed)."""
        if self.label_box.text() != (self._last_label or ""):
            self._label_ticked()

    def _unlabel_ticked(self) -> None:
        """Remove category: the ticked rows shown get no category."""
        self.label_box.setEditText("")
        self._label_ticked("")

    def _label_ticked(self, category: str | None = None) -> None:
        category = self.label_box.text() if category is None else category
        self._last_label = category
        rows = [r for i, r in enumerate(self.rows)
                if r.include and not self.table.isRowHidden(i)]
        label_rows(self.rows, category, only=rows)
        self.label_note.setText(f"{len(rows)} labelled “{category}”" if category
                                else f"category removed from {len(rows)}"
                                if rows else "no ticked rows shown")
        self.label_note.setMinimumWidth(self.label_note.sizeHint().width())
        for i, row in enumerate(self.rows):
            if row in rows:
                self._show_category(i)
        self._refresh_categories()
        self._filter()

    def _filter(self) -> None:
        for i, row in enumerate(self.rows):
            self.table.setRowHidden(i, not self._visible(row))
        self._update_footer()

    def _select(self, on: bool) -> None:
        self.table.blockSignals(True)
        for i, row in enumerate(self.rows):
            if row.status == SAME or self.table.isRowHidden(i):
                continue
            row.include = on
            self.table.item(i, COL_INCLUDE).setCheckState(
                Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._update_footer()

    def _update_footer(self) -> None:
        chosen = [r for r in self.rows if r.include and r.status != SAME]
        new = [r for r in chosen if r.status in (NEW, SAME_SENTENCE, REMOVED)]
        differs = sum(r.status == DIFFERS for r in chosen)
        mb = sum(r.size for r in new) / 1024 / 1024
        if self.mode == "export":
            mb = sum(r.size for r in chosen) / 1024 / 1024
            text = f"<b>{len(chosen)}</b> of {len(self.rows)} will be exported ({mb:.1f} MB)."
        else:
            text = (f"<b>{len(chosen)}</b> of {len(self.rows)} selected: {len(new)} new "
                    f"({mb:.1f} MB), {differs} with a different answer.")
        text += " " + html.escape(category_summary(r.category for r in chosen))
        if self.mode == "import" and self._space is not None:
            used, limit = self._space
            if limit:
                after = used + mb
                text += f" Your OCR data: {used:.1f} → {after:.1f} MB of {limit} MB."
                if after > limit:
                    text += (" <span style='color:#e0a030'>Over the limit: the oldest "
                             "unchecked samples will be removed (imported samples are fixed "
                             "ones and are kept).</span>")
        self.footer.setText(text)
        self._update_pack_counts()
        for hook in getattr(self, "changed_hooks", []):
            hook()
        self.refresh_ok()

    def pack_counts(self) -> dict[int, int]:
        """Merge: records each pack brings with the choices made now (by id(pack))."""
        return merge_contributions(self.rows)

    def _update_pack_counts(self) -> None:
        """Merge: 'N records in this merge' per pack; red when it brings nothing (it is
        then left out of the merged pack's sources and history log)."""
        if self.mode != "merge":
            return
        counts = self.pack_counts()
        for pack, label in getattr(self, "_pack_labels", []):
            n = counts.get(id(pack), 0)
            head = label.property("head")
            if n:
                label.setText(f"{head} · <b>{n} record{'s' if n != 1 else ''} in this "
                              "merge</b>")
                label.setStyleSheet("")
                label.setToolTip("")
            else:
                label.setText(f"{head} · <b>0 records in this merge</b> (not in the history "
                              "log)")
                label.setStyleSheet("color: #e05555;")
                label.setToolTip("Nothing from this pack is included (unticked, another "
                                 "pack's answer chosen, or the same as an earlier pack), so "
                                 "it isn't listed in the merged pack's history log.")

    def refresh_ok(self) -> None:
        """Enable the main button, or say why it can't be pressed yet."""
        if not hasattr(self, "blocked"):
            return
        verb = {"import": "import", "merge": "merge", "export": "export"}[self.mode]
        reasons = [] if any(r.include and r.status != SAME for r in self.rows) else [
            f"Tick at least one row to {verb}."]
        if self.mode == "merge" and self._rebuild is not None and len(self._packs) < 2:
            reasons = [f"A merge needs two or more packs ({len(self._packs)} here): add "
                       "one with Add packs…."]
        reasons += [r for r in (req() for req in self.requirements) if r]
        self.ok_btn.setEnabled(not reasons)
        text = " ".join(reasons)
        self.blocked.setText(f"⚠ {text}" if text else "")
        self.ok_btn.setToolTip(text)
        if self._preview is not None:
            now, after = self._preview()
            if self.mode == "import":
                self.using.setText(f"<b>Using now:</b> {html.escape(now)} &nbsp;→&nbsp; "
                                   f"<b>after import:</b> {html.escape(after)}")
            else:
                self.using.setText(f"<b>Merged pack made from:</b> {html.escape(after)}")

    @property
    def learn_fixes(self) -> bool:
        return self.learn.isVisible() and self.learn.isChecked()
