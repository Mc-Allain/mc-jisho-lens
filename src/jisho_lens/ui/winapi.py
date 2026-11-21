"""Small Win32 helpers for windows."""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.SetWindowDisplayAffinity.restype = wintypes.BOOL

WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004+


def exclude_from_capture(hwnd: int, exclude: bool = True) -> bool:
    """Hide a window from screenshots and screen capture (it stays visible to the user)."""
    affinity = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
    ok = bool(_user32.SetWindowDisplayAffinity(hwnd, affinity))
    if not ok:
        log.warning("SetWindowDisplayAffinity failed: %s", ctypes.get_last_error())
    return ok
