"""Global hotkey via Win32 RegisterHotKey (works while a game has focus)."""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "meta": MOD_WIN,
}
_NAMED_KEYS = {
    **{f"f{i}": 0x6F + i for i in range(1, 25)},  # F1=0x70
    "space": 0x20,
    "tab": 0x09,
    "insert": 0x2D,
    "ins": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pgup": 0x21,
    "pageup": 0x21,
    "pgdown": 0x22,
    "pagedown": 0x22,
    "pause": 0x13,
    "print": 0x2C,
    "printscreen": 0x2C,
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    "\\": 0xDC,
}


@dataclass(frozen=True)
class Hotkey:
    modifiers: int
    vk: int
    text: str


def parse_hotkey(text: str) -> Hotkey:
    """'Ctrl+Alt+J' -> Hotkey. Raises ValueError for unknown parts or no modifier."""
    parts = [p.strip() for p in text.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    *mods, key = parts
    modifiers = 0
    for m in mods:
        if m.lower() not in _MODIFIERS:
            raise ValueError(f"unknown modifier {m!r}")
        modifiers |= _MODIFIERS[m.lower()]
    k = key.lower()
    if len(key) == 1 and key.isalnum() and key.isascii():
        vk = ord(key.upper())
    elif k in _NAMED_KEYS:
        vk = _NAMED_KEYS[k]
    else:
        raise ValueError(f"unknown key {key!r}")
    if modifiers == 0 and not (0x70 <= vk <= 0x87):
        raise ValueError("a hotkey needs Ctrl, Alt, Shift or Win unless it is F1-F24")
    shown_key = key.upper() if len(key) == 1 else key
    return Hotkey(modifiers=modifiers, vk=vk, text="+".join([*mods, shown_key]))


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt API)
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self._callback(int(msg.wParam))
                return True, 0
        return False, 0


ESC = Hotkey(modifiers=0, vk=0x1B, text="Esc")


class HotkeyManager(QObject):
    """Global hotkeys on the GUI thread, by name ("capture", "show", "cancel").

    `triggered(name)` is emitted for every hotkey; `pressed` for "capture" (kept for the
    original single-hotkey use).
    """

    triggered = Signal(str)
    pressed = Signal()
    _IDS = {"capture": 0xB00B, "show": 0xB00C, "cancel": 0xB00D}

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._filter = _Filter(self._on_hotkey)
        app.installNativeEventFilter(self._filter)
        self._registered: dict[str, Hotkey] = {}

    def register(self, text: str, name: str = "capture") -> tuple[bool, str]:
        """Returns (ok, message). On failure the previous hotkey of `name` stays registered.
        An empty text removes the hotkey (ok)."""
        if not text.strip():
            self.unregister(name)
            return True, ""
        try:
            hk = parse_hotkey(text)
        except ValueError as exc:
            return False, str(exc)
        return self.register_key(hk, name)

    def register_key(self, hk: Hotkey, name: str) -> tuple[bool, str]:
        previous = self._registered.get(name)
        self.unregister(name)
        hid = self._IDS[name]
        if _user32.RegisterHotKey(None, hid, hk.modifiers | MOD_NOREPEAT, hk.vk):
            self._registered[name] = hk
            log.info("hotkey %s registered: %s", name, hk.text)
            return True, hk.text
        err = ctypes.get_last_error()
        msg = f"{hk.text} is already used by another program" if err == 1409 else f"error {err}"
        log.warning("hotkey %s %s not registered: %s", name, hk.text, msg)
        if previous is not None:
            _user32.RegisterHotKey(None, hid, previous.modifiers | MOD_NOREPEAT, previous.vk)
            self._registered[name] = previous
        return False, msg

    def unregister(self, name: str | None = None) -> None:
        """Remove one hotkey, or all of them (name None)."""
        for n in [name] if name else list(self._registered):
            if self._registered.pop(n, None) is not None:
                _user32.UnregisterHotKey(None, self._IDS[n])

    def current_for(self, name: str) -> str | None:
        hk = self._registered.get(name)
        return hk.text if hk else None

    @property
    def current(self) -> str | None:
        return self.current_for("capture")

    def _on_hotkey(self, hotkey_id: int) -> None:
        for name, hid in self._IDS.items():
            if hid == hotkey_id:
                self.triggered.emit(name)
                if name == "capture":
                    self.pressed.emit()
