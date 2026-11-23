"""Review window for importing or merging data packs: nothing is written until confirmed.

One row per item in the pack(s): Include checkbox, picture (OCR packs), status, what OCR
read, Before (your answer) / After (theirs) with the changed characters highlighted, and for
"Different answer" rows what to do. Filters by status, game and contributor; Select all /
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
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from jisho_lens.core.ocr_data.packs import (
    ALL_ANSWERS,
    DIFFERS,
    KEEP_ALTERNATIVE,
    KEEP_MINE,
    NEW,
    SAME,
    SAME_SENTENCE,
    STATUS_LABELS,
    USE_THEIRS,
    ReviewRow,
)

THUMB = QSize(200, 56)
STATUS_COLORS = {NEW: "#5cbf6a", DIFFERS: "#e0a030", SAME_SENTENCE: "#6fb3e0", SAME: "#8a8f99"}
COL_INCLUDE, COL_IMAGE, COL_STATUS, COL_OCR, COL_BEFORE, COL_AFTER, COL_CHOICE, COL_FROM = \
    range(8)
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


class PackReviewDialog(QDialog):
    """mode: "import" (Before = your data) or "merge" (rows where packs disagree)."""

    def __init__(self, rows: list[ReviewRow], mode: str = "import", *, title: str = "",
                 skipped: int = 0, space: tuple[float, int] | None = None,
                 show_images: bool = True, learn_option: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.rows, self.mode = rows, mode
        self._space = space  # (MB used now, limit MB) for the footer
        self.setWindowTitle(title or ("Review import" if mode == "import" else "Review merge"))
        self.resize(1180, 720)

        intro = QLabel(
            "Check what will be added. Nothing changes until you press "
            + ("<b>Import</b>." if mode == "import" else "<b>Save merged pack</b>.")
            + " Untick anything you don't trust, or screenshots that show names or chat.")
        intro.setWordWrap(True)
        self.status_filter = QComboBox()
        self.status_filter.addItem("All", None)
        for status in (NEW, DIFFERS, SAME_SENTENCE, SAME):
            n = sum(r.status == status for r in rows)
            if n:
                self.status_filter.addItem(f"{STATUS_LABELS[status]} ({n})", status)
        self.game_filter = QComboBox()
        self.game_filter.addItem("All games", None)
        for g in sorted({r.game for r in rows if r.game}):
            self.game_filter.addItem(g, g)
        self.who_filter = QComboBox()
        self.who_filter.addItem("All contributors", None)
        for c in sorted({r.contributor for r in rows if r.contributor}):
            self.who_filter.addItem(c[:8], c)
        for box in (self.status_filter, self.game_filter, self.who_filter):
            box.currentIndexChanged.connect(self._filter)
        all_btn = QPushButton("Select all")
        none_btn = QPushButton("Select none")
        all_btn.clicked.connect(lambda: self._select(True))
        none_btn.clicked.connect(lambda: self._select(False))
        bar = QHBoxLayout()
        for w in (QLabel("Show"), self.status_filter, self.game_filter, self.who_filter):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(all_btn)
        bar.addWidget(none_btn)

        self.table = QTableWidget(len(rows), 8)
        self.table.setHorizontalHeaderLabels(
            ["Include", "Picture", "Status", "OCR read",
             "Before (yours)" if mode == "import" else "Before (first pack)",
             "After (theirs)" if mode == "import" else "After (other packs)",
             "Choice", "From"])
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
        self.table.setColumnHidden(COL_FROM, mode == "import" and len(
            {r.pack.name for r in rows}) <= 1)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        self._fill()
        self.table.itemChanged.connect(self._item_changed)

        self.learn = QCheckBox("Also learn OCR fixes from these (applied to your future captures; "
                               "see Settings → Learned corrections)")
        self.learn.setVisible(mode == "import" and learn_option)
        self.footer = QLabel()
        self.footer.setWordWrap(True)
        note = QLabel(f"{skipped} samples without an Edit fix were left out (only fixed "
                      "samples are shared)." if skipped else "")
        note.setStyleSheet("color: #8a8f99;")
        note.setVisible(bool(skipped))
        buttons = QDialogButtonBox()
        self.ok_btn = buttons.addButton("Import" if mode == "import" else "Save merged pack…",
                                        QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(bar)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.learn)
        layout.addWidget(note)
        layout.addWidget(self.footer)
        layout.addWidget(buttons)
        self._update_footer()
        self._thumbs_done = 0
        if show_images:
            QTimer.singleShot(0, self._load_thumbs)

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
            status.setData(_HTML, f"<b style='color:{STATUS_COLORS[row.status]}'>"
                                  f"{STATUS_LABELS[row.status]}</b>")
            status.setToolTip({
                NEW: "You don't have this picture (or have it without a right answer)",
                DIFFERS: "You have this picture with a different right answer",
                SAME_SENTENCE: "Another crop of a sentence you already have (skipped by "
                               "default to save space)",
                SAME: "Already identical in your data: nothing to import",
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
            source = QTableWidgetItem(f"{row.pack.name}\n{row.contributor[:8]}"
                                      + (f"\n{row.game}" if row.game else ""))
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
        box.currentIndexChanged.connect(lambda _=0, r=row, b=box: setattr(r, "choice",
                                                                         b.currentData()))
        return box

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
        status, game, who = (self.status_filter.currentData(), self.game_filter.currentData(),
                             self.who_filter.currentData())
        return ((status is None or row.status == status)
                and (game is None or row.game == game)
                and (who is None or row.contributor == who))

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
        new = [r for r in chosen if r.status in (NEW, SAME_SENTENCE)]
        differs = sum(r.status == DIFFERS for r in chosen)
        mb = sum(r.size for r in new) / 1024 / 1024
        text = (f"<b>{len(chosen)}</b> of {len(self.rows)} selected: {len(new)} new "
                f"({mb:.1f} MB), {differs} with a different answer.")
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
        self.ok_btn.setEnabled(bool(chosen))

    @property
    def learn_fixes(self) -> bool:
        return self.learn.isVisible() and self.learn.isChecked()
