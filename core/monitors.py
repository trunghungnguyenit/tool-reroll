"""Liệt kê màn hình theo pixel VẬT LÝ và tìm màn hình đang chứa cửa sổ game.

Vì sao có file này: vùng Shop và 5 điểm click được lưu bằng pixel vật lý trên desktop ảo (cùng hệ với mss và SetCursorPos). Khi
đổi màn hình chơi game, đổi độ phân giải/scale hoặc sắp xếp lại các màn hình, các tọa độ đó không còn đúng, nên app cần biết
"màn hình nào đang dùng" để dùng đúng bộ tọa độ đã lưu cho màn hình đó (xem core/profiles.py). Qt không cho tọa độ vật lý của
từng màn hình một cách đáng tin khi các màn hình khác scale, nên đọc thẳng từ Win32 (tiến trình đã DPI-aware, core/dpi.py)."""

import ctypes
import re
from ctypes import wintypes
from dataclasses import dataclass

from core import game_window

_MIN_GAME_WINDOW = 200  # cửa sổ nhỏ hơn mức này (px) không phải cửa sổ chơi game (vd cửa sổ ẩn, launcher thu nhỏ)


@dataclass(frozen=True)
class Monitor:
    device: str  # vd "\\.\DISPLAY2" (tên Windows đặt cho màn hình)
    left: int
    top: int
    width: int
    height: int
    scale: int = 100  # % scale của Windows (100/125/150...)
    primary: bool = False

    @property
    def key(self) -> str:
        """Khóa của bộ cấu hình: đổi độ phân giải của cùng một màn hình thì ra khóa khác (cần xác nhận lại)."""
        return f"{self.device}|{self.width}x{self.height}"

    @property
    def rect(self) -> dict:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}

    @property
    def number(self) -> int | None:
        found = re.search(r"(\d+)$", self.device)
        return int(found.group(1)) if found else None

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x < self.left + self.width and self.top <= y < self.top + self.height

    def label(self) -> str:
        n = self.number
        name = f"Màn hình {n}" if n else "Màn hình"
        return f"{name} · {self.width}×{self.height} · {self.scale}%" + (" · chính" if self.primary else "")


def monitor_for_point(monitors: list[Monitor], x: float, y: float) -> Monitor | None:
    return next((m for m in monitors if m.contains(x, y)), None)


def monitor_for_region(monitors: list[Monitor], region: dict) -> Monitor | None:
    """Màn hình chứa phần lớn vùng (diện tích giao nhau lớn nhất); vùng nằm ngoài mọi màn hình thì None."""
    best, best_area = None, 0
    for m in monitors:
        w = min(m.left + m.width, region["left"] + region["width"]) - max(m.left, region["left"])
        h = min(m.top + m.height, region["top"] + region["height"]) - max(m.top, region["top"])
        if w > 0 and h > 0 and w * h > best_area:
            best, best_area = m, w * h
    return best


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.RECT),
                                      wintypes.LPARAM)
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_MONITORINFOF_PRIMARY = 1
_MDT_EFFECTIVE_DPI = 0


def _user32():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p, _MONITORENUMPROC, wintypes.LPARAM]
    u.EnumDisplayMonitors.restype = wintypes.BOOL
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    u.GetMonitorInfoW.restype = wintypes.BOOL
    u.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    u.EnumWindows.restype = wintypes.BOOL
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsIconic.argtypes = [wintypes.HWND]
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.GetWindowRect.restype = wintypes.BOOL
    return u


def _scale_percent(hmon) -> int:
    """% scale của màn hình (96 DPI = 100%); không đọc được thì 100."""
    try:
        shcore = ctypes.WinDLL("shcore")
        dpi_x, dpi_y = wintypes.UINT(0), wintypes.UINT(0)
        shcore.GetDpiForMonitor.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(wintypes.UINT),
                                            ctypes.POINTER(wintypes.UINT)]
        shcore.GetDpiForMonitor.restype = ctypes.c_long
        if shcore.GetDpiForMonitor(hmon, _MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0 and dpi_x.value:
            return int(round(dpi_x.value * 100 / 96))
    except (AttributeError, OSError):
        pass
    return 100


def list_monitors() -> list[Monitor]:
    """Mọi màn hình đang bật, theo pixel vật lý, sắp từ trái sang phải. Lỗi hoặc không phải Windows thì danh sách rỗng."""
    found: list[Monitor] = []
    try:
        user32 = _user32()

        def callback(hmon, _hdc, _rect, _lparam):
            info = _MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                r = info.rcMonitor
                found.append(Monitor(info.szDevice, r.left, r.top, r.right - r.left, r.bottom - r.top, _scale_percent(hmon),
                                     bool(info.dwFlags & _MONITORINFOF_PRIMARY)))
            return True

        user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(callback), 0)
    except (AttributeError, OSError):
        return []
    return sorted(found, key=lambda m: (m.left, m.top))


def game_window_center(process_names: frozenset[str]) -> tuple[int, int] | None:
    """Tâm cửa sổ game (pixel vật lý) — cửa sổ lớn nhất đang hiện của các tiến trình trong `process_names`; None nếu không có."""
    best: tuple[int, tuple[int, int]] | None = None
    try:
        user32 = _user32()

        def callback(hwnd, _lparam):
            nonlocal best
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if w < _MIN_GAME_WINDOW or h < _MIN_GAME_WINDOW:
                return True
            if best is not None and w * h <= best[0]:
                return True
            if game_window.window_process_name(hwnd) in process_names:
                best = (w * h, ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2))
            return True

        user32.EnumWindows(_WNDENUMPROC(callback), 0)
    except (AttributeError, OSError):
        return None
    return best[1] if best else None


def game_monitor(process_names: frozenset[str], monitors: list[Monitor]) -> Monitor | None:
    """Màn hình đang chứa cửa sổ game; None nếu game chưa chạy hoặc không đọc được."""
    center = game_window_center(process_names)
    return monitor_for_point(monitors, *center) if center else None
