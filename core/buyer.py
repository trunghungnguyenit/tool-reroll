"""Tự động click chuột để mua tướng trong shop TFT."""

import ctypes
import time

user32 = ctypes.windll.user32

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def click(x: int, y: int):
    """Di chuyển chuột tới (x, y) và click trái 1 lần."""
    user32.SetCursorPos(x, y)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def buy_slot(slot_center: tuple[int, int], delay_ms: int = 0):
    """Click mua tướng tại tọa độ giữa ô shop, có thể chờ delay_ms trước khi click."""
    if delay_ms > 0:
        time.sleep(delay_ms / 1000)
    click(slot_center[0], slot_center[1])


def buy_slot_async(slot_center: tuple[int, int]):
    """Click mua ngay lập tức — dùng trong vòng quét nhanh, không chờ thêm."""
    click(slot_center[0], slot_center[1])
