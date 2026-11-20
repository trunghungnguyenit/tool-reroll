"""Overlay toàn màn hình để chọn vùng Shop và đặt 5 điểm click.

Cách làm: chụp sẵn ảnh màn hình (trước khi hiện overlay, cửa sổ chính đã ẩn) rồi vẽ ảnh đó làm nền (hơi tối). Nhờ vậy overlay có
kính lúp phóng to đúng điểm ảnh dưới con trỏ, hiện kích thước/tọa độ trực tiếp, và hoạt động trên nhiều màn hình. Tọa độ LƯU
là pixel vật lý lấy từ GetCursorPos (cùng hệ với mss và SetCursorPos), không phụ thuộc scale của Qt."""

import ctypes

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

MIN_REGION_W, MIN_REGION_H = 50, 30
MAG_SRC, MAG_ZOOM = 17, 8  # kính lúp: lấy 17x17 điểm ảnh vật lý, phóng 8 lần
GREEN, RED = QColor("#22c55e"), QColor("#ef4444")


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def physical_cursor() -> tuple[int, int] | None:
    """Vị trí con trỏ theo pixel vật lý (tiến trình DPI-aware). None nếu không đọc được."""
    pt = _POINT()
    try:
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
    except (AttributeError, OSError):
        pass
    return None


def grab_virtual_desktop() -> tuple[QPixmap, QRect]:
    """Ảnh toàn bộ màn hình ảo (logic) + hình chữ nhật của nó. Mỗi màn hình được chụp ở độ phân giải thật của nó."""
    virtual = QGuiApplication.primaryScreen().virtualGeometry()
    canvas = QPixmap(virtual.size())
    canvas.fill(Qt.GlobalColor.black)
    painter = QPainter(canvas)
    for screen in QGuiApplication.screens():
        shot = screen.grabWindow(0)
        g = screen.geometry()
        painter.drawPixmap(QRect(g.x() - virtual.x(), g.y() - virtual.y(), g.width(), g.height()), shot)
    painter.end()
    return canvas, virtual


class _BaseOverlay(QWidget):
    finished = Signal(object)
    cancelled = Signal()

    def __init__(self, background: QPixmap | None = None, virtual: QRect | None = None, phys=physical_cursor, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if background is None:
            background, virtual = grab_virtual_desktop()
        self._bg = background
        self._virtual = virtual
        self._phys = phys
        self._mouse = QPoint(0, 0)
        self.setGeometry(virtual)

    # --- tiện ích
    def _physical(self, event_pos: QPoint) -> tuple[int, int]:
        got = self._phys()
        if got is not None:
            return got
        screen = QGuiApplication.screenAt(self.mapToGlobal(event_pos)) or QGuiApplication.primaryScreen()
        g = self.mapToGlobal(event_pos)
        r = screen.devicePixelRatio()
        return int(g.x() * r), int(g.y() * r)

    def _paint_background(self, painter: QPainter):
        painter.drawPixmap(0, 0, self._bg)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))

    def _paint_hint(self, painter: QPainter, text: str):
        f = QFont(painter.font())
        f.setPointSize(13)
        f.setBold(True)
        painter.setFont(f)
        w = painter.fontMetrics().horizontalAdvance(text) + 36
        box = QRectF((self.width() - w) / 2, 18, w, 40)
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_magnifier(self, painter: QPainter, label: str):
        """Phóng to vùng quanh con trỏ (lấy từ ảnh chụp ở độ phân giải thật) và in tọa độ vật lý."""
        ratio = self._bg.devicePixelRatio() or 1.0
        screen = QGuiApplication.screenAt(self.mapToGlobal(self._mouse)) or QGuiApplication.primaryScreen()
        scale = screen.devicePixelRatio() / ratio if ratio else 1.0
        cx, cy = self._mouse.x() * scale, self._mouse.y() * scale
        half = MAG_SRC // 2
        src = QRect(int(cx) - half, int(cy) - half, MAG_SRC, MAG_SRC)
        size = MAG_SRC * MAG_ZOOM
        x = self._mouse.x() + 24
        y = self._mouse.y() + 24
        if x + size + 8 > self.width():
            x = self._mouse.x() - size - 24
        if y + size + 36 > self.height():
            y = self._mouse.y() - size - 60
        target = QRect(x, y, size, size)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setBrush(QColor(0, 0, 0))
        painter.drawRect(target.adjusted(-2, -2, 2, 2))
        painter.drawPixmap(target, self._bg.copy(src))
        c = target.center()
        painter.setPen(QPen(RED, 1))
        painter.drawLine(c.x() - MAG_ZOOM, c.y(), c.x() + MAG_ZOOM, c.y())
        painter.drawLine(c.x(), c.y() - MAG_ZOOM, c.x(), c.y() + MAG_ZOOM)
        painter.setPen(QColor("#ffffff"))
        painter.setBrush(QColor(0, 0, 0, 200))
        tag = QRect(target.left(), target.bottom() + 4, size, 24)
        painter.drawRect(tag)
        painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, label)

    def mouseMoveEvent(self, event):
        self._mouse = event.position().toPoint()
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.activateWindow()
        self.raise_()
        self.setFocus()


class RegionOverlay(_BaseOverlay):
    """Kéo khung quanh hàng 5 thẻ tướng. finished(region: dict[left, top, width, height]) theo pixel vật lý."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._start: QPoint | None = None
        self._start_phys: tuple[int, int] | None = None
        self._phys_now: tuple[int, int] | None = None
        self.last_rejected = False

    def _region_phys(self) -> dict | None:
        if self._start_phys is None or self._phys_now is None:
            return None
        (x1, y1), (x2, y2) = self._start_phys, self._phys_now
        return {"left": min(x1, x2), "top": min(y1, y2), "width": abs(x2 - x1), "height": abs(y2 - y1)}

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._start = event.position().toPoint()
        self._mouse = self._start
        self._start_phys = self._phys_now = self._physical(self._start)
        self.last_rejected = False
        self.update()

    def mouseMoveEvent(self, event):
        self._mouse = event.position().toPoint()
        if self._start is not None:
            self._phys_now = self._physical(self._mouse)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._phys_now = self._physical(event.position().toPoint())
        region = self._region_phys()
        self._start = None
        if region and region["width"] > MIN_REGION_W and region["height"] > MIN_REGION_H:
            self.finished.emit(region)
        else:  # kéo quá nhỏ: bỏ khung, cho kéo lại (không đóng overlay)
            self.last_rejected = True
            self._start_phys = self._phys_now = None
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        self._paint_background(painter)
        region = self._region_phys()
        label = f"{self._mouse.x()}, {self._mouse.y()}"
        if self._start is not None and region:
            rect = QRect(self._start, self._mouse).normalized()
            painter.drawPixmap(rect, self._bg, rect)  # phần được chọn sáng như ảnh gốc
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(GREEN, 2))
            painter.drawRect(rect)
            size_text = f"{region['width']} × {region['height']} px"
            painter.setPen(QColor("#ffffff"))
            painter.setBrush(QColor(0, 0, 0, 200))
            tag = QRect(rect.left(), max(0, rect.top() - 26), max(120, rect.width() // 2), 24)
            painter.drawRect(tag)
            painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, size_text)
            label = f"{region['left']}, {region['top']}"
        hint = ("Khung quá nhỏ — kéo lại cho phủ hàng 5 thẻ tướng (Esc để hủy)" if self.last_rejected
                else "Kéo khung quanh CHỈ hàng 5 thẻ tướng — không gồm vàng/nút (Esc để hủy)")
        self._paint_hint(painter, hint)
        self._paint_magnifier(painter, label)
        painter.end()


class ClickOverlay(_BaseOverlay):
    """Click lần lượt vào ảnh tướng của 5 ô. finished(points: list[(x, y)]) theo pixel vật lý."""

    def __init__(self, region: dict, inside, *a, **kw):
        super().__init__(*a, **kw)
        self._region = region
        self._inside = inside  # (x, y) vật lý -> có nằm trong vùng Shop không
        self.points: list[tuple[int, int]] = []
        self._logical: list[QPoint] = []
        self.warning = ""

    def _hint(self) -> str:
        n = len(self.points)
        base = f"Click vào ẢNH tướng ô {n + 1}/5 (Backspace: lùi 1 điểm, Esc: hủy)"
        return self.warning or base

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        x, y = self._physical(pos)
        if not self._inside(x, y):
            self.warning = f"Điểm nằm NGOÀI vùng Shop — click lại ô {len(self.points) + 1}/5"
            self.update()
            return
        self.warning = ""
        self.points.append((x, y))
        self._logical.append(pos)
        if len(self.points) >= 5:
            self.finished.emit(list(self.points))
            return
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Backspace and self.points:
            self.points.pop()
            self._logical.pop()
            self.warning = ""
            self.update()
            return
        super().keyPressEvent(event)

    def _region_rect_logical(self) -> QRect:
        """Vùng Shop (pixel vật lý) đổi sang tọa độ của overlay, dựa trên màn hình chứa góc trên-trái."""
        r = self._region
        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() or 1.0
        return QRect(int(r["left"] / ratio) - self._virtual.x(), int(r["top"] / ratio) - self._virtual.y(),
                     int(r["width"] / ratio), int(r["height"] / ratio))

    def paintEvent(self, event):
        painter = QPainter(self)
        self._paint_background(painter)
        rect = self._region_rect_logical()
        painter.drawPixmap(rect, self._bg, rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(GREEN, 2))
        painter.drawRect(rect)
        for i, pt in enumerate(self._logical, 1):
            painter.setBrush(RED)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawEllipse(QPointF(pt), 11, 11)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRectF(pt.x() - 11, pt.y() - 11, 22, 22), Qt.AlignmentFlag.AlignCenter, str(i))
        self._paint_hint(painter, self._hint())
        phys = self._phys()
        label = f"{phys[0]}, {phys[1]}" if phys else f"{self._mouse.x()}, {self._mouse.y()}"
        self._paint_magnifier(painter, label)
        painter.end()


def current_cursor_logical() -> QPoint:
    return QCursor.pos()
