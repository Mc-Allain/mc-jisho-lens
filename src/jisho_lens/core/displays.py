"""Detect monitors, resolutions and per-monitor scaling (Windows).

All rectangles are in physical pixels on the virtual desktop, which is what screenshots use.
Call enable_per_monitor_dpi_awareness() once at startup, before any window is created,
otherwise Windows reports scaled (virtualized) coordinates.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shcore = ctypes.WinDLL("shcore", use_last_error=True)

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
_PER_MONITOR_AWARE_V2 = wintypes.HANDLE(-4)
_MONITORINFOF_PRIMARY = 1
_MDT_EFFECTIVE_DPI = 0


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


_MonitorEnumProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)

_user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
_user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
_user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC,
    ctypes.c_void_p,
    _MonitorEnumProc,
    wintypes.LPARAM,
]
_user32.EnumDisplayMonitors.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFOEXW)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL
_shcore.GetDpiForMonitor.argtypes = [
    wintypes.HMONITOR,
    ctypes.c_int,
    ctypes.POINTER(wintypes.UINT),
    ctypes.POINTER(wintypes.UINT),
]
_shcore.GetDpiForMonitor.restype = ctypes.HRESULT


@dataclass(frozen=True)
class Display:
    device: str
    left: int
    top: int
    width: int
    height: int
    dpi: int
    primary: bool

    @property
    def scale_percent(self) -> int:
        return round(self.dpi * 100 / 96)

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


def enable_per_monitor_dpi_awareness() -> bool:
    """Make this process per-monitor DPI aware (v2). Returns False if it was already set."""
    return bool(_user32.SetProcessDpiAwarenessContext(_PER_MONITOR_AWARE_V2))


def get_displays() -> list[Display]:
    displays: list[Display] = []

    def _callback(hmon, _hdc, _rect, _data):
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if not _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return True
        dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
        hr = _shcore.GetDpiForMonitor(
            hmon, _MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
        )
        if hr != 0:
            dpi_x.value = 96
        r = info.rcMonitor
        displays.append(
            Display(
                device=info.szDevice,
                left=r.left,
                top=r.top,
                width=r.right - r.left,
                height=r.bottom - r.top,
                dpi=dpi_x.value,
                primary=bool(info.dwFlags & _MONITORINFOF_PRIMARY),
            )
        )
        return True

    _user32.EnumDisplayMonitors(None, None, _MonitorEnumProc(_callback), 0)
    displays.sort(key=lambda d: (not d.primary, d.left, d.top))
    return displays


def virtual_desktop_bounds(displays: list[Display]) -> tuple[int, int, int, int]:
    """(left, top, width, height) of the rectangle covering all displays."""
    left = min(d.left for d in displays)
    top = min(d.top for d in displays)
    right = max(d.right for d in displays)
    bottom = max(d.bottom for d in displays)
    return left, top, right - left, bottom - top


def describe_displays(displays: list[Display] | None = None) -> str:
    displays = displays if displays is not None else get_displays()
    lines = [f"{len(displays)} display(s):"]
    for d in displays:
        tag = " (primary)" if d.primary else ""
        lines.append(
            f"  {d.device}{tag}: {d.width}x{d.height} at ({d.left},{d.top}), "
            f"{d.scale_percent}% scaling ({d.dpi} DPI)"
        )
    return "\n".join(lines)
