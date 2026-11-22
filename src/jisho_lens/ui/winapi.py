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


_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongW.restype = ctypes.c_long

_HWND_TOPMOST = wintypes.HWND(-1)
_HWND_NOTOPMOST = wintypes.HWND(-2)
_GWL_EXSTYLE, _WS_EX_TOPMOST = -20, 0x00000008
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
_GWLP_HWNDPARENT, _GW_OWNER = -8, 4


def set_topmost(hwnd: int, topmost: bool = True) -> None:
    """Always on top and in front of the other always-on-top windows, or (False) a normal
    window again, behind every always-on-top window. No focus change."""
    _user32.SetWindowPos(hwnd, _HWND_TOPMOST if topmost else _HWND_NOTOPMOST, 0, 0, 0, 0,
                         _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE)


def place_below(hwnd: int, other: int) -> None:
    """Put `hwnd` right behind `other` (both normal windows). No focus change."""
    _user32.SetWindowPos(hwnd, other, 0, 0, 0, 0, _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE)


def foreground() -> int:
    """The window that has the focus (any app); 0 while Windows is switching."""
    return _user32.GetForegroundWindow() or 0


def is_topmost(hwnd: int) -> bool:
    return bool(_user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOPMOST)


def owner(hwnd: int) -> int:
    return _user32.GetWindow(hwnd, _GW_OWNER) or 0


def set_owner(hwnd: int, owner_hwnd: int) -> None:
    """Change the window that owns `hwnd` (0 = none). An owned window always stays in front
    of its owner."""
    _user32.SetWindowLongPtrW(hwnd, _GWLP_HWNDPARENT, owner_hwnd)


def exclude_from_capture(hwnd: int, exclude: bool = True) -> bool:
    """Hide a window from screenshots and screen capture (it stays visible to the user)."""
    affinity = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
    ok = bool(_user32.SetWindowDisplayAffinity(hwnd, affinity))
    if not ok:
        log.warning("SetWindowDisplayAffinity failed: %s", ctypes.get_last_error())
    return ok
