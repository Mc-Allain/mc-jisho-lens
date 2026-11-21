"""Settings > Components: install or remove UniDic-lite, full UniDic, JMdict, KANJIDIC2 and
Wiktionary. Nothing is installed by default; the dictionaries need a UniDic, and removing
the last UniDic removes them too. Work runs in the background with progress messages."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jisho_lens import components


class _Task(QObject):
    progress = Signal(str)
    done = Signal(list, str)  # changed component ids, error message ("" on success)

    def __init__(self, action: str, component_id: str) -> None:
        super().__init__()
        self.action, self.component_id = action, component_id

    @Slot()
    def run(self) -> None:
        try:
            fn = components.install if self.action == "install" else components.uninstall
            changed = fn(self.component_id, progress=self.progress.emit)
            self.done.emit(changed, "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit([], str(exc) or exc.__class__.__name__)


class ComponentsPanel(QGroupBox):
    changed = Signal(list)  # component ids installed or removed

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Components (optional — nothing is installed by default)", parent)
        self._rows: dict[str, tuple[QLabel, QPushButton]] = {}
        self._thread: QThread | None = None
        grid = QGridLayout()
        for row, c in enumerate(components.COMPONENTS.values()):
            name = QLabel(f"<b>{c.name}</b> <span style='color:#8a8f99'>({c.size})</span>"
                          f"<br><span style='color:#8a8f99'>{c.purpose}</span>")
            name.setWordWrap(True)
            status = QLabel()
            button = QPushButton()
            button.clicked.connect(lambda _=False, cid=c.id: self._clicked(cid))
            grid.addWidget(name, row, 0)
            grid.addWidget(status, row, 1)
            grid.addWidget(button, row, 2)
            self._rows[c.id] = (status, button)
        grid.setColumnStretch(0, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #8a8f99;")
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(self.message)
        self.refresh()

    def refresh(self, busy: bool = False) -> None:
        has_unidic = bool(components.installed_unidics())
        for cid, (status, button) in self._rows.items():
            installed = components.is_installed(cid)
            status.setText("Installed" if installed else "Not installed")
            status.setStyleSheet("color: #7fd18b;" if installed else "color: #8a8f99;")
            button.setText("Remove" if installed else "Install")
            needs_unidic = (components.COMPONENTS[cid].kind == "dictionary"
                            and not installed and not has_unidic)
            button.setEnabled(not busy and not needs_unidic)
            button.setToolTip("Needs word splitting: install UniDic-lite or full UniDic first."
                              if needs_unidic else "")

    def _clicked(self, component_id: str) -> None:
        installed = components.is_installed(component_id)
        name = components.COMPONENTS[component_id].name
        if installed:
            extra = components.removal_effects(component_id)
            text = f"Remove {name}?"
            if extra:
                names = ", ".join(components.COMPONENTS[e].name for e in extra)
                text += (f"\n\nThis is the last word splitter, so these dictionaries will be "
                         f"removed too: {names}.")
            if QMessageBox.question(self, "Remove component", text) != \
                    QMessageBox.StandardButton.Yes:
                return
        self._start("uninstall" if installed else "install", component_id)

    def _start(self, action: str, component_id: str) -> None:
        self.refresh(busy=True)
        verb = "Installing" if action == "install" else "Removing"
        self.message.setText(f"{verb} {components.COMPONENTS[component_id].name}…")
        self._thread = QThread(self)
        self._task = _Task(action, component_id)
        self._task.moveToThread(self._thread)
        self._thread.started.connect(self._task.run)
        self._task.progress.connect(self.message.setText)
        self._task.done.connect(self._finished)
        self._thread.start()

    def _finished(self, changed: list, error: str) -> None:
        self._thread.quit()
        self._thread.wait()
        self._thread = None
        self.message.setText(f"Failed: {error}" if error else self.message.text())
        self.refresh()
        if changed:
            self.changed.emit(changed)

    @property
    def busy(self) -> bool:
        return self._thread is not None
