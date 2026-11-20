"""Widget dùng chung: FlowLayout (tự xuống dòng khi hẹp), Switch (công tắc), ElidedButton (chữ dài tự cắt bằng …)."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QLayout, QPushButton, QSizePolicy, QWidgetItem


class FlowLayout(QLayout):
    """Xếp các widget từ trái sang phải, hết chỗ thì xuống dòng (cách chip/nút lọc thích ứng bề rộng)."""

    def __init__(self, parent=None, hspacing=6, vspacing=6):
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self._h, self._v = hspacing, vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, dry=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect: QRect, dry: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line_h > 0:
                x = area.x()
                y += line_h + self._v
                line_h = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._h
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class Switch(QCheckBox):
    """Công tắc bật/tắt có núm tròn; vẫn là QCheckBox (bàn phím, trạng thái, tín hiệu toggled như bình thường)."""

    W, H = 38, 20

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QCheckBox::indicator { width: 0px; height: 0px; }")
        self.accent = QColor("#2563eb")
        self.off = QColor("#9ca3af")
        self.knob = QColor("#ffffff")
        self.text_color = QColor("#111827")
        self.focus_color = QColor("#2563eb")

    def set_colors(self, accent: str, off: str, text: str):
        self.accent, self.off, self.text_color = QColor(accent), QColor(off), QColor(text)
        self.update()

    def sizeHint(self):
        base = super().sizeHint()
        return QSize(self.W + 10 + self.fontMetrics().horizontalAdvance(self.text()) + 4, max(self.H + 8, base.height()))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRect(0, (self.height() - self.H) // 2, self.W, self.H)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.accent if self.isChecked() else self.off)
        p.drawRoundedRect(track, self.H / 2, self.H / 2)
        d = self.H - 6
        x = track.right() - d - 2 if self.isChecked() else track.left() + 3
        p.setBrush(self.knob)
        p.drawEllipse(QRect(x, track.top() + 3, d, d))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(self.focus_color, 2))
            p.drawRoundedRect(track.adjusted(-2, -2, 2, 2), self.H / 2 + 2, self.H / 2 + 2)
        p.setPen(self.text_color)
        text_rect = QRect(self.W + 10, 0, self.width() - self.W - 10, self.height())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, self.text())
        p.end()

    def hitButton(self, pos):
        return self.rect().contains(pos)


class ElidedButton(QPushButton):
    """Nút chữ dài: cắt bằng … theo bề rộng hiện có (toàn văn nằm ở tooltip) nên không bao giờ làm cột bị rộng ra."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def setFullText(self, text: str):
        self._full = text
        self.setToolTip(text)
        self._elide()

    def fullText(self) -> str:
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def minimumSizeHint(self):
        return QSize(40, super().minimumSizeHint().height())

    def _elide(self):
        avail = max(20, self.width() - 24)
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, avail))
