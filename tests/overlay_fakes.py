"""Màn hình giả cho test overlay: mô phỏng nhiều màn hình có độ phân giải, hệ số DPI và vị trí khác nhau (kể cả tọa độ âm)."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest

from ui.overlay import ScreenInfo


def screen(name="DISPLAY1", left=0, top=0, w=1200, h=600, ratio=1.5, color=Qt.GlobalColor.darkGray) -> ScreenInfo:
    """Màn hình giả: hình chữ nhật VẬT LÝ (left, top, w, h), hệ số DPI `ratio` (cửa sổ overlay rộng w/ratio điểm Qt)."""
    pix = QPixmap(w, h)
    pix.fill(color)
    return ScreenInfo(name, (left, top, w, h), ratio, pix)


def one_screen(w=800, h=400, ratio=1.0):
    return [screen(w=w, h=h, ratio=ratio)]


def two_screens():
    """Màn hình chính 1920x1080 scale 125% + màn hình phụ bên phải 2560x1440 scale 150% (khác DPI, như máy thật hay gặp)."""
    return [screen("DISPLAY1", 0, 0, 1920, 1080, 1.25), screen("DISPLAY2", 1920, 0, 2560, 1440, 1.5)]


class Cursor:
    """Con trỏ vật lý giả (thay GetCursorPos): test đặt vị trí rồi gửi sự kiện chuột Qt tương ứng."""

    def __init__(self):
        self.pos = (0, 0)

    def __call__(self):
        return self.pos

    def put(self, surface, local: QPoint):
        """Đặt con trỏ ở điểm `local` của cửa sổ `surface` (đổi sang pixel vật lý theo màn hình của cửa sổ đó)."""
        self.pos = surface.to_phys(local)
        return local


def drag(qtbot, overlay, cursor, surface, a: QPoint, b: QPoint):
    cursor.put(surface, a)
    qtbot.mousePress(surface, Qt.MouseButton.LeftButton, pos=a)
    mid = QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2)
    cursor.put(surface, mid)
    QTest.mouseMove(surface, mid)
    cursor.put(surface, b)
    qtbot.mouseRelease(surface, Qt.MouseButton.LeftButton, pos=b)
