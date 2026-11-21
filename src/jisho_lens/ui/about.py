"""About window: version and the attributions required by the data licences."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from jisho_lens import __version__


def _dictionary_line() -> str:
    try:
        from jisho_lens.dictionary import optional_dictionary

        d = optional_dictionary()
        if d is None:
            return "Dictionary database not installed."
        meta = d.meta()
        line = (f"JMdict version {meta.get('jmdict_date', '?')}, "
                f"KANJIDIC2 version {meta.get('kanjidic2_date', '?')}")
        if meta.get("wiktionary_date"):
            line += f", Wiktionary data {meta['wiktionary_date']}"
        return line + "."
    except Exception:  # noqa: BLE001
        return "Dictionary information unavailable."


ABOUT_HTML = """
<h3>Jisho Lens {version}</h3>
<p>Read Japanese text in games: capture, OCR, readings, meanings.</p>
<p><b>Dictionary data.</b> This application uses the
<a href="https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project">JMdict</a> and
<a href="https://www.edrdg.org/wiki/index.php/KANJIDIC_Project">KANJIDIC2</a> dictionary files.
These files are the property of the
<a href="https://www.edrdg.org/">Electronic Dictionary Research and Development Group</a>,
and are used in conformance with the Group's
<a href="https://www.edrdg.org/edrdg/licence.html">licence</a> (CC BY-SA 4.0).<br>
{dictionary}</p>
<p><b>Extra words.</b> Words missing from JMdict (dialect, slang, newer words, e.g. じっちゃ)
come from <a href="https://en.wiktionary.org/">Wiktionary</a>, available under
<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>, extracted by
<a href="https://github.com/tatuylonen/wiktextract">Wiktextract</a> /
<a href="https://kaikki.org/">kaikki.org</a> (Ylonen, 2022).</p>
<p><b>Word splitting and readings:</b> MeCab via fugashi, with
<a href="https://clrd.ninjal.ac.jp/unidic/">UniDic</a> (NINJAL, BSD licence);
romaji by cutlet.</p>
<p><b>OCR:</b> RapidOCR with PaddleOCR models (Apache 2.0), ONNX Runtime (MIT),
Windows.Media.Ocr. <b>UI:</b> Qt for Python / PySide6 (LGPL v3).</p>
"""


class AboutWindow(QDialog):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("About Jisho Lens")
        self.setMinimumWidth(460)
        label = QLabel(ABOUT_HTML.format(version=__version__, dictionary=_dictionary_line()))
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(buttons)
