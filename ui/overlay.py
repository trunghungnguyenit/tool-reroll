"""Overlay chọn vùng Shop, đặt 5 điểm click và XEM lại chúng trên màn hình thật — chạy được trên nhiều màn hình.

Mỗi màn hình có MỘT cửa sổ overlay riêng (`_Surface`), vẽ ảnh chụp của chính màn hình đó ở độ phân giải thật và dùng hệ số DPI
của chính nó. Trước đây dùng một cửa sổ trải qua mọi màn hình rồi `showFullScreen()`: Qt chỉ phủ được một màn hình, và khi các
màn hình khác scale thì khung/kính lúp lệch. Các cửa sổ dùng chung một "bộ điều phối" (`_Overlay`) giữ trạng thái (khung đang
kéo, các điểm đã click), nên kéo/click ở màn hình nào cũng được.

Tọa độ LƯU là pixel vật lý trên desktop ảo lấy từ GetCursorPos (cùng hệ với mss và SetCursorPos), không phụ thuộc scale của Qt.
Cửa sổ nào cũng đổi qua lại giữa pixel vật lý và pixel Qt bằng tỉ lệ của riêng màn hình đó (`_Surface.to_local/to_phys`).
Vùng Shop bị giữ trong MỘT màn hình (màn hình nơi bắt đầu kéo): chụp DXGI và bộ cấu hình theo màn hình đều cần như vậy."""

import ctypes
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QPixmap, QScreen
from PySide6.QtWidgets import QWidget

from core import monitors as monitors_mod

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


@dataclass
class ScreenInfo:
    """Một màn hình: hình chữ nhật VẬT LÝ trên desktop ảo (left, top, width, height), hệ số DPI, ảnh chụp ở độ phân giải thật."""

    name: str
    phys: tuple[int, int, int, int]
    ratio: float
    pixmap: QPixmap
    qscreen: QScreen | None = None

    @property
    def logical_size(self) -> tuple[int, int]:
        return max(1, round(self.phys[2] / self.ratio)), max(1, round(self.phys[3] / self.ratio))

    def contains(self, x: float, y: float) -> bool:
        left, top, w, h = self.phys
        return left <= x < left + w and top <= y < top + h


def collect_screens(monitors: list | None = None) -> list[ScreenInfo]:
    """Chụp mọi màn hình (một lần) và ghép với hình chữ nhật vật lý của từng màn hình (đọc từ Win32 theo tên thiết bị;
    không khớp thì suy ra từ Qt)."""
    mons = monitors if monitors is not None else monitors_mod.list_monitors()
    by_device = {m.device: m for m in mons}
    out = []
    for screen in QGuiApplication.screens():
        g = screen.geometry()
        ratio = screen.devicePixelRatio() or 1.0
        m = by_device.get(screen.name())
        phys = (m.left, m.top, m.width, m.height) if m else (g.x(), g.y(), round(g.width() * ratio), round(g.height() * ratio))
        out.append(ScreenInfo(screen.name(), phys, ratio, screen.grabWindow(0), screen))
    return out


class _Surface(QWidget):
    """Cửa sổ overlay của MỘT màn hình. Chỉ vẽ và chuyển sự kiện cho bộ điều phối."""

    def __init__(self, group: "_Overlay", info: ScreenInfo):
        super().__init__()
        self.group = group
        self.info = info
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if info.qscreen is not None:
            self.setScreen(info.qscreen)
            self.setGeometry(info.qscreen.geometry())
        else:
            self.setGeometry(QRect(0, 0, *info.logical_size))

    def to_local(self, x: float, y: float) -> QPointF:
        """Pixel vật lý trên desktop ảo → tọa độ trong cửa sổ này."""
        left, top, w, h = self.info.phys
        return QPointF((x - left) * self.width() / w, (y - top) * self.height() / h)

    def to_phys(self, pos: QPoint) -> tuple[int, int]:
        """Tọa độ trong cửa sổ này → pixel vật lý (dự phòng khi không đọc được con trỏ vật lý)."""
        left, top, w, h = self.info.phys
        return round(left + pos.x() * w / max(1, self.width())), round(top + pos.y() * h / max(1, self.height()))

    def paintEvent(self, event):
        painter = QPainter(self)
        self.group.paint(self, painter)
        painter.end()

    def mousePressEvent(self, event):
        self.group.on_press(self, event)

    def mouseMoveEvent(self, event):
        self.group.on_move(self, event)

    def mouseReleaseEvent(self, event):
        self.group.on_release(self, event)

    def keyPressEvent(self, event):
        if not self.group.on_key(event):
            super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.activateWindow()
        self.raise_()
        self.setFocus()


class _Overlay(QObject):
    """Bộ điều phối: một _Surface cho mỗi màn hình + trạng thái dùng chung. Lớp con cài on_press/paint... theo từng việc."""

    finished = Signal(object)
    cancelled = Signal()

    def __init__(self, screens: list[ScreenInfo] | None = None, phys=physical_cursor, parent=None):
        super().__init__(parent)
        self.screens = screens if screens is not None else collect_screens()
        self._phys = phys
        self.surfaces = [_Surface(self, s) for s in self.screens]
        self._mouse_surface: _Surface | None = None
        self._mouse_phys: tuple[int, int] | None = None

    # --- hiện/ẩn
    def show(self):
        for s in self.surfaces:
            s.show()

    def showFullScreen(self):
        """Mỗi cửa sổ phủ kín màn hình của nó. Cửa sổ ở màn hình đang có con trỏ hiện SAU CÙNG để nhận phím (Esc)."""
        cursor = self._phys()
        order = sorted(self.surfaces, key=lambda s: bool(cursor) and s.info.contains(*cursor))
        for s in order:
            if s.info.qscreen is not None:
                s.showFullScreen()
            else:  # màn hình mô tả bằng số liệu (không có QScreen thật, vd test): giữ đúng kích thước đã mô tả
                s.show()

    def hide(self):
        for s in self.surfaces:
            s.hide()

    def deleteLater(self):
        for s in self.surfaces:
            s.deleteLater()
        super().deleteLater()

    def update(self):
        for s in self.surfaces:
            s.update()

    # --- tiện ích
    def physical(self, surface: _Surface, pos: QPoint) -> tuple[int, int]:
        got = self._phys()
        return got if got is not None else surface.to_phys(pos)

    def on_move(self, surface: _Surface, event):
        self._mouse_surface = surface
        self._mouse_phys = self.physical(surface, event.position().toPoint())
        self.update()

    def on_press(self, surface: _Surface, event):
        pass

    def on_release(self, surface: _Surface, event):
        pass

    def on_key(self, event) -> bool:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return True
        return False

    def paint(self, surface: _Surface, painter: QPainter):
        raise NotImplementedError

    # --- vẽ chung
    @staticmethod
    def paint_background(surface: _Surface, painter: QPainter):
        painter.drawPixmap(surface.rect(), surface.info.pixmap)
        painter.fillRect(surface.rect(), QColor(0, 0, 0, 90))

    @staticmethod
    def paint_hint(surface: _Surface, painter: QPainter, text: str):
        f = QFont(painter.font())
        f.setPointSize(13)
        f.setBold(True)
        painter.setFont(f)
        w = min(surface.width() - 16, painter.fontMetrics().horizontalAdvance(text) + 36)
        box = QRectF((surface.width() - w) / 2, 18, w, 40)
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def paint_tag(painter: QPainter, rect: QRect, text: str):
        painter.setPen(QColor("#ffffff"))
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.drawRect(rect)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def paint_magnifier(self, surface: _Surface, painter: QPainter, label: str):
        """Phóng to vùng quanh con trỏ (lấy từ ảnh chụp ở độ phân giải thật) và in tọa độ vật lý. Chỉ vẽ ở màn hình có con trỏ."""
        if self._mouse_surface is not surface or self._mouse_phys is None:
            return
        left, top, pw, ph = surface.info.phys
        mx, my = self._mouse_phys
        bg = surface.info.pixmap
        cx, cy = (mx - left) * bg.width() / pw, (my - top) * bg.height() / ph  # điểm ảnh trong ảnh chụp
        half = MAG_SRC // 2
        src = QRect(int(cx) - half, int(cy) - half, MAG_SRC, MAG_SRC)
        size = MAG_SRC * MAG_ZOOM
        pos = surface.to_local(mx, my).toPoint()
        x, y = pos.x() + 24, pos.y() + 24
        if x + size + 8 > surface.width():
            x = pos.x() - size - 24
        if y + size + 36 > surface.height():
            y = pos.y() - size - 60
        target = QRect(x, y, size, size)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setBrush(QColor(0, 0, 0))
        painter.drawRect(target.adjusted(-2, -2, 2, 2))
        painter.drawPixmap(target, bg.copy(src))
        c = target.center()
        painter.setPen(QPen(RED, 1))
        painter.drawLine(c.x() - MAG_ZOOM, c.y(), c.x() + MAG_ZOOM, c.y())
        painter.drawLine(c.x(), c.y() - MAG_ZOOM, c.x(), c.y() + MAG_ZOOM)
        self.paint_tag(painter, QRect(target.left(), target.bottom() + 4, size, 24), label)

    @staticmethod
    def region_rect_local(surface: _Surface, region: dict) -> QRect:
        a = surface.to_local(region["left"], region["top"])
        b = surface.to_local(region["left"] + region["width"], region["top"] + region["height"])
        return QRectF(a, b).toRect()

    def paint_dots(self, surface: _Surface, painter: QPainter, points: list):
        for i, (x, y) in enumerate(points, 1):
            pt = surface.to_local(x, y)
            if not surface.rect().contains(pt.toPoint()):
                continue  # điểm của màn hình khác
            painter.setBrush(RED)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawEllipse(pt, 11, 11)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRectF(pt.x() - 11, pt.y() - 11, 22, 22), Qt.AlignmentFlag.AlignCenter, str(i))

    def paint_region_frame(self, surface: _Surface, painter: QPainter, region: dict):
        """Vẽ viền xanh quanh vùng Shop và làm sáng phần bên trong như ảnh gốc."""
        rect = self.region_rect_local(surface, region)
        painter.save()
        painter.setClipRect(rect)
        painter.drawPixmap(surface.rect(), surface.info.pixmap)
        painter.restore()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(GREEN, 2))
        painter.drawRect(rect)
        return rect


class RegionOverlay(_Overlay):
    """Kéo khung quanh hàng 5 thẻ tướng. finished(region: dict[left, top, width, height]) theo pixel vật lý."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._start_surface: _Surface | None = None
        self._start_phys: tuple[int, int] | None = None
        self._phys_now: tuple[int, int] | None = None
        self.last_rejected = False

    def _clamp(self, point: tuple[int, int]) -> tuple[int, int]:
        """Giữ điểm trong màn hình nơi bắt đầu kéo: vùng Shop không được trải qua hai màn hình."""
        left, top, w, h = self._start_surface.info.phys
        return min(max(point[0], left), left + w - 1), min(max(point[1], top), top + h - 1)

    def _region_phys(self) -> dict | None:
        if self._start_phys is None or self._phys_now is None:
            return None
        (x1, y1), (x2, y2) = self._start_phys, self._phys_now
        return {"left": min(x1, x2), "top": min(y1, y2), "width": abs(x2 - x1), "height": abs(y2 - y1)}

    def on_press(self, surface, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._start_surface = surface
        self._mouse_surface = surface
        self._start_phys = self._phys_now = self._clamp(self.physical(surface, event.position().toPoint()))
        self._mouse_phys = self._start_phys
        self.last_rejected = False
        self.update()

    def on_move(self, surface, event):
        if self._start_surface is not None:
            self._mouse_surface = self._start_surface  # chuột đang được cửa sổ nơi bắt đầu kéo giữ, kể cả khi đã ra ngoài nó
            self._phys_now = self._clamp(self.physical(surface, event.position().toPoint()))
            self._mouse_phys = self._phys_now
            self.update()
            return
        super().on_move(surface, event)

    def on_release(self, surface, event):
        if event.button() != Qt.MouseButton.LeftButton or self._start_surface is None:
            return
        self._phys_now = self._clamp(self.physical(surface, event.position().toPoint()))
        region = self._region_phys()
        self._start_surface = None
        if region and region["width"] > MIN_REGION_W and region["height"] > MIN_REGION_H:
            self.finished.emit(region)
        else:  # kéo quá nhỏ: bỏ khung, cho kéo lại (không đóng overlay)
            self.last_rejected = True
            self._start_phys = self._phys_now = None
            self.update()

    def paint(self, surface, painter):
        self.paint_background(surface, painter)
        region = self._region_phys()
        label = f"{self._mouse_phys[0]}, {self._mouse_phys[1]}" if self._mouse_phys else ""
        if self._start_surface is surface and region:
            rect = self.paint_region_frame(surface, painter, region)
            tag = QRect(rect.left(), max(0, rect.top() - 26), max(120, rect.width() // 2), 24)
            self.paint_tag(painter, tag, f"{region['width']} × {region['height']} px")
            label = f"{region['left']}, {region['top']}"
        hint = ("Khung quá nhỏ — kéo lại cho phủ hàng 5 thẻ tướng (Esc để hủy)" if self.last_rejected
                else "Kéo khung quanh CHỈ hàng 5 thẻ tướng — không gồm vàng/nút (Esc để hủy)")
        self.paint_hint(surface, painter, hint)
        self.paint_magnifier(surface, painter, label)


class ClickOverlay(_Overlay):
    """Click lần lượt vào ảnh tướng của 5 ô. finished(points: list[(x, y)]) theo pixel vật lý."""

    def __init__(self, region: dict, inside, *a, **kw):
        super().__init__(*a, **kw)
        self._region = region
        self._inside = inside  # (x, y) vật lý -> có nằm trong vùng Shop không
        self.points: list[tuple[int, int]] = []
        self.warning = ""

    def _hint(self) -> str:
        n = len(self.points)
        base = f"Click vào ẢNH tướng ô {n + 1}/5 (Backspace: lùi 1 điểm, Esc: hủy)"
        return self.warning or base

    def on_press(self, surface, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = self.physical(surface, event.position().toPoint())
        if not self._inside(x, y):
            self.warning = f"Điểm nằm NGOÀI vùng Shop — click lại ô {len(self.points) + 1}/5"
            self.update()
            return
        self.warning = ""
        self.points.append((x, y))
        if len(self.points) >= 5:
            self.finished.emit(list(self.points))
            return
        self.update()

    def on_key(self, event) -> bool:
        if event.key() == Qt.Key.Key_Backspace:
            if self.points:
                self.points.pop()
                self.warning = ""
                self.update()
            return True
        return super().on_key(event)

    def paint(self, surface, painter):
        self.paint_background(surface, painter)
        self.paint_region_frame(surface, painter, self._region)
        self.paint_dots(surface, painter, self.points)
        self.paint_hint(surface, painter, self._hint())
        self.paint_magnifier(surface, painter, f"{self._mouse_phys[0]}, {self._mouse_phys[1]}" if self._mouse_phys else "")


class ViewOverlay(_Overlay):
    """Chỉ XEM: hiện khung vùng Shop và 5 chấm đỏ đánh số trên màn hình thật (đúng nơi tool sẽ chụp/click), để đối chiếu với game.
    Chặn click; click bất kỳ hoặc Esc thì phát `cancelled` (đóng). `confirm=True` (gợi ý quy đổi chờ xác nhận): Enter hoặc Space
    phát `finished(True)` (dùng gợi ý), còn click/Esc là bỏ qua."""

    def __init__(self, region: dict, centers: list, title: str = "", confirm: bool = False, *a, **kw):
        super().__init__(*a, **kw)
        self._region = region
        self._centers = [tuple(c) for c in centers]
        self.title = title
        self.confirm = confirm

    def _hint(self) -> str:
        if self.confirm:
            return "Gợi ý quy đổi — Enter: DÙNG · Esc hoặc click: bỏ qua"
        return "Vùng Shop (khung xanh) và 5 điểm click (chấm đỏ) — click hoặc Esc để đóng"

    def on_press(self, surface, event):
        self.cancelled.emit()

    def on_key(self, event) -> bool:
        if self.confirm and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.finished.emit(True)
            return True
        return super().on_key(event)

    def paint(self, surface, painter):
        self.paint_background(surface, painter)
        rect = self.paint_region_frame(surface, painter, self._region)
        on_this_screen = surface.rect().intersects(rect)
        if on_this_screen:
            label = f"Vùng Shop {self._region['width']} × {self._region['height']} px" + (f" · {self.title}" if self.title else "")
            self.paint_tag(painter, QRect(rect.left(), max(0, rect.top() - 26), max(260, rect.width() // 2), 24), label)
            if not self._centers:
                self.paint_tag(painter, QRect(rect.left(), rect.bottom() + 6, 300, 24), "Chưa đặt 5 điểm click (bước ②)")
        self.paint_dots(surface, painter, self._centers)
        self.paint_hint(surface, painter, self._hint())
