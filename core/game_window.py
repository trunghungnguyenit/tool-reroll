"""Kiểm tra cửa sổ đang ở foreground có phải game không (theo tên process) — tránh click nhầm app khác.
Cũng tìm cửa sổ game và đọc quyền Admin của tool/game để Nhật ký chỉ ra vì sao click không tới được game."""

import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION = 20  # TOKEN_INFORMATION_CLASS.TokenElevation
_ERROR_ACCESS_DENIED = 5
_MIN_GAME_WINDOW = 200  # cửa sổ nhỏ hơn mức này (px) không phải cửa sổ chơi game
GAME_WINDOW_CLASSES = frozenset({"riotwindowclass"})  # lớp cửa sổ chơi game của League of Legends / TFT (chữ thường)

# Kết quả của process_elevation()
ELEV_YES = "yes"  # chạy quyền Admin
ELEV_NO = "no"  # quyền thường
ELEV_DENIED = "denied"  # mở được process nhưng không đọc được token: thường vì process có quyền CAO HƠN tool
ELEV_UNKNOWN = "unknown"  # không mở được process (Vanguard chặn, process đã thoát...)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
_advapi32.OpenProcessToken.restype = wintypes.BOOL
_advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]
_advapi32.GetTokenInformation.restype = wintypes.BOOL

_user32.GetForegroundWindow.argtypes = []
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


def window_process_name(hwnd) -> str | None:
    """Tên file exe (chữ thường) của tiến trình sở hữu cửa sổ `hwnd`; None nếu không đọc được."""
    if not hwnd:
        return None

    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None

    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return os.path.basename(buf.value).lower()
    finally:
        _kernel32.CloseHandle(handle)


def window_class_name(hwnd) -> str | None:
    """Tên lớp cửa sổ (vd "RiotWindowClass"); None nếu không đọc được. Không cần mở process nên không bị chặn quyền."""
    if not hwnd:
        return None
    buf = ctypes.create_unicode_buffer(256)
    return buf.value if _user32.GetClassNameW(hwnd, buf, len(buf)) else None


def window_title(hwnd) -> str:
    """Tiêu đề cửa sổ ('' nếu không có hoặc không đọc được)."""
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    return buf.value if _user32.GetWindowTextW(hwnd, buf, len(buf)) else ""


def foreground_process_name() -> str | None:
    """Tên file exe (chữ thường) của cửa sổ foreground; None nếu không đọc được."""
    return window_process_name(_user32.GetForegroundWindow())


def foreground_class_name() -> str | None:
    """Tên lớp cửa sổ của cửa sổ foreground; None nếu không đọc được."""
    return window_class_name(_user32.GetForegroundWindow())


def is_game_foreground(process_names: frozenset[str]) -> bool:
    """True nếu cửa sổ foreground là game: process nằm trong `process_names` (đã viết thường), HOẶC lớp cửa sổ là lớp của
    cửa sổ chơi game Riot (`RiotWindowClass`). Lớp cửa sổ đọc được cả khi không mở được process của game (Vanguard, game chạy
    quyền cao hơn tool) hoặc khi file exe của game đổi tên. Không đọc được cả hai → False (không click)."""
    name = foreground_process_name()
    if name is not None and name in process_names:
        return True
    cls = foreground_class_name()
    return cls is not None and cls.lower() in GAME_WINDOW_CLASSES


def describe_foreground() -> str:
    """Mô tả cửa sổ đang ở trước, để ghi vào Nhật ký khi tool từ chối click ('process, lớp, tiêu đề')."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return "không có cửa sổ nào ở trước (hoặc màn hình đang khóa)"
    name = window_process_name(hwnd)
    return (
        f"{name or 'không đọc được tên process'} "
        f"(lớp '{window_class_name(hwnd) or '?'}', tiêu đề '{window_title(hwnd)[:40]}')"
    )


def process_elevation(pid: int) -> str:
    """Process `pid` chạy quyền Admin không: ELEV_YES / ELEV_NO / ELEV_DENIED / ELEV_UNKNOWN (xem hằng ở đầu file).
    Windows (UIPI) chặn chuột/phím giả lập từ app quyền thường tới cửa sổ của app quyền cao hơn — đây là lý do hay gặp nhất
    khiến tool 'click mà game không nhận'."""
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ELEV_UNKNOWN
    try:
        token = wintypes.HANDLE()
        if not _advapi32.OpenProcessToken(handle, _TOKEN_QUERY, ctypes.byref(token)):
            return ELEV_DENIED if ctypes.get_last_error() == _ERROR_ACCESS_DENIED else ELEV_UNKNOWN
        try:
            elevated = wintypes.DWORD(0)
            size = wintypes.DWORD(0)
            ok = _advapi32.GetTokenInformation(
                token, _TOKEN_ELEVATION, ctypes.byref(elevated), ctypes.sizeof(elevated), ctypes.byref(size)
            )
            if not ok:
                return ELEV_UNKNOWN
            return ELEV_YES if elevated.value else ELEV_NO
        finally:
            _kernel32.CloseHandle(token)
    finally:
        _kernel32.CloseHandle(handle)


def tool_elevation() -> str:
    """Chính tool này có đang chạy quyền Admin không."""
    return process_elevation(os.getpid())


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    pid: int
    process: str | None  # None = không đọc được tên process
    cls: str | None
    title: str
    rect: tuple[int, int, int, int]  # trái, trên, phải, dưới (pixel vật lý, tọa độ desktop ảo)
    elevation: str  # ELEV_*


def find_game_window(process_names: frozenset[str]) -> GameWindow | None:
    """Cửa sổ game lớn nhất đang hiện (process trong `process_names` hoặc lớp RiotWindowClass); None nếu chưa thấy."""
    best: tuple[int, int] | None = None  # (diện tích, hwnd)

    def callback(hwnd, _lparam):
        nonlocal best
        if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
            return True
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w < _MIN_GAME_WINDOW or h < _MIN_GAME_WINDOW or (best is not None and w * h <= best[0]):
            return True
        cls = window_class_name(hwnd)
        if (cls or "").lower() in GAME_WINDOW_CLASSES or window_process_name(hwnd) in process_names:
            best = (w * h, hwnd)
        return True

    _user32.EnumWindows(_WNDENUMPROC(callback), 0)
    if best is None:
        return None
    hwnd = best[1]
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return GameWindow(
        hwnd=int(hwnd), pid=int(pid.value), process=window_process_name(hwnd), cls=window_class_name(hwnd),
        title=window_title(hwnd), rect=(rect.left, rect.top, rect.right, rect.bottom),
        elevation=process_elevation(pid.value) if pid.value else ELEV_UNKNOWN,
    )


def suspect_game_process(process_names: frozenset[str]) -> str | None:
    """Cửa sổ foreground KHÔNG được nhận là game nhưng TÊN PROCESS có 'tft' hoặc 'league' (không tính chính tool này): nhiều khả
    năng là game với tên process mới (Riot đổi client). Trả tên process để gợi ý thêm vào cấu hình; không có thì None.
    Chỉ xét tên process, không xét tiêu đề: tab trình duyệt tên 'TFT builds' không được gợi ý nhầm."""
    hwnd = _user32.GetForegroundWindow()
    name = window_process_name(hwnd)
    if not name or name in process_names:
        return None
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    own_exe = os.path.basename(sys.executable).lower()
    if pid.value == os.getpid() or name == own_exe or name.startswith("tft_auto_buy"):
        return None
    return name if ("tft" in name or "league" in name) else None
