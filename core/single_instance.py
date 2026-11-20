"""Chỉ cho chạy MỘT bản app mỗi phiên đăng nhập Windows. Hai bản cùng lúc sẽ cùng bắt phím F8 toàn cục, cùng click lên
một màn hình, và ghi chồng lên config/log. Bản thứ hai đưa cửa sổ của bản đang chạy lên trước rồi thoát."""

import ctypes
import time
from ctypes import wintypes

APP_TITLE = "TFT Auto Buy - Bắt tướng tự động"  # tiêu đề cửa sổ chính; bản thứ hai dùng nó để tìm cửa sổ cũ

# "Local\" = theo phiên đăng nhập: phím F8 và click đều thuộc một desktop, mỗi tài khoản Windows chạy được một bản.
# Tên cố định (không theo thư mục cài) nên hai bản exe ở hai thư mục khác nhau cũng chặn nhau.
MUTEX_NAME = "Local\\TFTAutoBuy.SingleInstance"

_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)

_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowW.restype = wintypes.HWND
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL


class InstanceLock:
    """Giữ mutex cho tới khi release() hoặc tiến trình thoát (Windows tự nhả, nên không bao giờ bị kẹt khóa cũ)."""

    def __init__(self, handle):
        self._handle = handle

    def release(self):
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None


_held: list[InstanceLock] = []  # giữ tham chiếu để mutex sống suốt đời tiến trình


def acquire_instance_lock(name: str = MUTEX_NAME) -> InstanceLock | None:
    """Trả InstanceLock nếu đây là bản đầu tiên; None nếu đã có bản khác đang giữ khóa (hoặc không tạo được mutex)."""
    ctypes.set_last_error(0)
    handle = _kernel32.CreateMutexW(None, False, name)
    already = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
    if not handle:
        return None  # không tạo được mutex (hiếm: bị chặn quyền) — coi như đã có bản khác, thà không chạy còn hơn chạy đôi
    if already:
        _kernel32.CloseHandle(handle)  # chỉ là tay cầm thứ hai tới mutex của bản kia
        return None
    lock = InstanceLock(handle)
    _held.append(lock)
    return lock


def activate_existing_window(title: str = APP_TITLE, wait_s: float = 3.0) -> bool:
    """
    Đưa cửa sổ của bản đang chạy lên trước (khôi phục nếu đang thu nhỏ). Bản kia có thể vừa giữ khóa mà chưa dựng xong
    cửa sổ (exe khởi động chậm) nên thử lại tới wait_s giây. True nếu tìm thấy cửa sổ.
    """
    deadline = time.monotonic() + wait_s
    while True:
        hwnd = _user32.FindWindowW(None, title)
        if hwnd:
            if _user32.IsIconic(hwnd):
                _user32.ShowWindow(hwnd, _SW_RESTORE)
            _user32.SetForegroundWindow(hwnd)  # có thể bị Windows chặn; khi đó nút trên thanh tác vụ sẽ nhấp nháy
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
