"""Danh sách tướng: model + delegate tự vẽ. Chỉ giữ dữ liệu của các mục đang lọc; bật/tắt chọn chỉ báo `dataChanged` cho
đúng mục đó, đổi bộ lọc thì reset model (vài chục mục, rất nhẹ) nên gõ tìm kiếm không dựng/hủy widget nào."""

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from core.champions import season_label, season_tooltip
from ui.theme import Palette, qcolor

CARD_W, CARD_H = 104, 140
ROW_H = 34
INFO_SIZE = 18  # nút ⓘ (xem chi tiết) ở góc trái trên của thẻ
MODE_CARDS, MODE_TEXT = "cards", "text"

ChampionRole = Qt.ItemDataRole.UserRole + 1


def info_rect(card: QRectF) -> QRectF:
    """Ô nút ⓘ trong thẻ; `card` là khung thẻ đã thu vào 4 px (đúng khung delegate dùng để vẽ)."""
    return QRectF(card.left() + 4, card.top() + 4, INFO_SIZE, INFO_SIZE)


def inner_card_rect(visual: QRect) -> QRectF:
    return QRectF(visual).adjusted(4, 4, -4, -4)


class ChampionModel(QAbstractListModel):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._items: list[dict] = []
        self._pix: dict[str, QPixmap | None] = {}

    def set_items(self, items: list[dict]):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def items(self) -> list[dict]:
        return self._items

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        champ = self._items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return champ["name"]
        if role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if self._c.is_selected(champ["name"]) else Qt.CheckState.Unchecked
        if role == ChampionRole:
            return champ
        if role == Qt.ItemDataRole.ToolTipRole:
            alt = champ.get("alt_name")
            extra = f" ({alt})" if alt and alt != champ["name"] else ""
            return f"{champ['name']}{extra} — {champ['tier']} gold, {season_tooltip(champ)}\nChuột phải hoặc bấm ⓘ: xem chỉ số, kỹ năng, hệ"
        if role == Qt.ItemDataRole.AccessibleTextRole:
            state = "đã chọn" if self._c.is_selected(champ["name"]) else "chưa chọn"
            return f"{champ['name']}, {champ['tier']} gold, {season_tooltip(champ)}, {state}"
        return None

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.CheckStateRole and index.isValid():
            self._c.set_selected(self._items[index.row()]["name"], Qt.CheckState(value) == Qt.CheckState.Checked)
            return True
        return False

    def refresh_all(self):
        if self._items:
            self.dataChanged.emit(self.index(0), self.index(len(self._items) - 1))

    def refresh_name(self, name: str):
        for row, c in enumerate(self._items):
            if c["name"] == name:
                self._pix.pop(name, None)
                self.dataChanged.emit(self.index(row), self.index(row))
                return

    def portrait(self, champ: dict) -> QPixmap | None:
        name = champ["name"]
        if name not in self._pix or self._pix[name] is None:
            path = self._c.portrait_path(champ)
            pix = QPixmap(str(path)) if path else None
            self._pix[name] = pix if pix is not None and not pix.isNull() else None
        return self._pix[name]


class ChampionDelegate(QStyledItemDelegate):
    def __init__(self, view, palette: Palette):
        super().__init__(view)
        self._view = view
        self.palette_ = palette

    def sizeHint(self, option, index):
        if self._view.mode == MODE_CARDS:
            return QSize(CARD_W, CARD_H)
        return QSize(max(150, self._view.viewport().width() - 2), ROW_H)  # theo viewport (đã trừ thanh cuộn dọc): không sinh thanh cuộn ngang

    def paint(self, painter: QPainter, option, index):
        p = self.palette_
        champ = index.data(ChampionRole)
        if champ is None:
            return
        selected = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focus = bool(option.state & QStyle.StateFlag.State_HasFocus)
        cost_color = QColor(p.cost[max(0, min(4, champ["tier"] - 1))])
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = inner_card_rect(option.rect)
        bg = qcolor(p.accent_soft) if selected else qcolor(p.surface)
        border = QColor(p.accent_line) if selected else QColor(p.accent_line if hover else p.border)
        painter.setBrush(bg)
        painter.setPen(QPen(border, 2 if (selected or focus) else 1))
        painter.drawRoundedRect(rect, 9, 9)

        if self._view.mode == MODE_CARDS:
            self._paint_card(painter, rect, champ, selected, cost_color, index)
        else:
            self._paint_row(painter, rect, champ, selected, cost_color)
        painter.restore()

    def _paint_card(self, painter, rect, champ, selected, cost_color, index):
        p = self.palette_
        side = 64
        art = QRectF(rect.center().x() - side / 2, rect.top() + 10, side, side)
        pix = index.model().portrait(champ)
        if pix is not None:
            painter.save()
            from PySide6.QtGui import QPainterPath

            path = QPainterPath()
            path.addRoundedRect(art, 8, 8)
            painter.setClipPath(path)
            painter.drawPixmap(art.toRect(), pix.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                        Qt.TransformationMode.SmoothTransformation))
            painter.restore()
        else:  # chưa tải ảnh: chữ cái đầu trên nền màu cost
            painter.setBrush(qcolor(cost_color.name(), 60))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(art, 8, 8)
            painter.setPen(cost_color)
            f = QFont(painter.font())
            f.setPointSize(20)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(art, Qt.AlignmentFlag.AlignCenter, champ["name"][:1].upper())
        painter.setPen(QPen(cost_color, 3))
        painter.drawLine(int(art.left()), int(art.bottom() + 3), int(art.right()), int(art.bottom() + 3))

        painter.setPen(QColor(p.muted))
        f = QFont(painter.font())
        f.setPointSize(8)
        painter.setFont(f)
        painter.drawText(QRectF(rect.left() + 2, art.bottom() + 6, rect.width() - 4, 16),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, season_label(champ))

        painter.setPen(QColor(p.text))
        f = QFont(painter.font())
        f.setPointSize(9)
        f.setBold(selected)
        painter.setFont(f)
        text = QRectF(rect.left() + 4, art.bottom() + 24, rect.width() - 8, 34)
        painter.drawText(text, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                         champ["name"])
        if selected:
            self._badge(painter, QRectF(rect.right() - 22, rect.top() + 4, 18, 18))
        self._info_badge(painter, info_rect(rect))

    def _info_badge(self, painter, r: QRectF):
        """Nút ⓘ: vòng tròn nền thẻ + chữ i, vẽ đè lên góc ảnh nên luôn nhìn rõ."""
        p = self.palette_
        painter.setBrush(qcolor(p.surface))
        painter.setPen(QPen(QColor(p.muted), 1))
        painter.drawEllipse(r)
        f = QFont(painter.font())
        f.setPointSize(8)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor(p.muted))
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "i")

    def _row_text_rect(self, rect):
        return QRectF(rect.left() + 34, rect.top(), max(60, rect.width() - 190), rect.height())

    def _paint_row(self, painter, rect, champ, selected, cost_color):
        p = self.palette_
        box = QRectF(rect.left() + 8, rect.center().y() - 8, 16, 16)
        painter.setPen(QPen(QColor(p.accent_line if selected else p.border), 2))
        painter.setBrush(QColor(p.accent) if selected else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 4, 4)
        if selected:
            painter.setPen(QPen(QColor(p.accent_text), 2))
            painter.drawLine(int(box.left() + 3), int(box.center().y()), int(box.center().x() - 1), int(box.bottom() - 4))
            painter.drawLine(int(box.center().x() - 1), int(box.bottom() - 4), int(box.right() - 3), int(box.top() + 4))
        painter.setPen(QColor(p.text))
        f = QFont(painter.font())
        f.setBold(selected)
        painter.setFont(f)
        painter.drawText(self._row_text_rect(rect), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         champ["name"])
        painter.setPen(QColor(p.muted))
        f = QFont(painter.font())
        f.setBold(False)
        f.setPointSize(8)
        painter.setFont(f)
        painter.drawText(QRectF(rect.right() - 160, rect.top(), 112, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, season_label(champ))
        painter.setPen(cost_color)
        painter.drawText(QRectF(rect.right() - 44, rect.top(), 38, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{champ['tier']}g")

    def _badge(self, painter, r: QRectF):
        p = self.palette_
        painter.setBrush(QColor(p.accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(r)
        painter.setPen(QPen(QColor(p.accent_text), 2))
        painter.drawLine(int(r.left() + 4), int(r.center().y()), int(r.center().x() - 1), int(r.bottom() - 5))
        painter.drawLine(int(r.center().x() - 1), int(r.bottom() - 5), int(r.right() - 4), int(r.top() + 5))


class ChampionView(QListView):
    """Một lần bấm/Space/Enter đổi trạng thái chọn của mục; hỗ trợ bàn phím (mũi tên, Space)."""

    toggled = Signal(str, bool)
    detail_requested = Signal(str)  # tên tướng: người dùng muốn xem chi tiết (nút ⓘ, chuột phải hoặc phím I)

    def __init__(self, controller, palette: Palette, parent=None):
        super().__init__(parent)
        self._c = controller
        self.mode = MODE_CARDS
        self._model = ChampionModel(controller, self)
        self.setModel(self._model)
        self._delegate = ChampionDelegate(self, palette)
        self.setItemDelegate(self._delegate)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Thanh cuộn dọc luôn hiện: bề rộng viewport không đổi khi số tướng đổi, nên lưới không phải chia lại cột mỗi lần lọc/tìm.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setAccessibleName("Danh sách tướng")
        self.set_mode(MODE_CARDS)

    @property
    def champion_model(self) -> ChampionModel:
        return self._model

    def set_palette(self, palette: Palette):
        self._delegate.palette_ = palette
        self.viewport().update()

    def set_mode(self, mode: str):
        self.mode = mode
        if mode == MODE_CARDS:
            self.setViewMode(QListView.ViewMode.IconMode)
            self.setFlow(QListView.Flow.LeftToRight)
            self.setWrapping(True)
            self.setMovement(QListView.Movement.Static)
            self.setSpacing(0)
            self.setGridSize(self.cell_size())
        else:
            self.setViewMode(QListView.ViewMode.ListMode)
            self.setFlow(QListView.Flow.TopToBottom)
            self.setWrapping(False)
            self.setSpacing(0)
            self.setGridSize(QSize())
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def columns(self) -> int:
        """Số cột thẻ vừa với bề rộng hiện có (ít nhất 1)."""
        return max(1, self.viewport().width() // CARD_W)

    def cell_size(self) -> QSize:
        """Ô lưới: chiều cao cố định, chiều rộng chia ĐỀU phần bề rộng còn lại cho các cột để thẻ lấp kín hàng (không thừa khoảng trống
        lệch bên phải)."""
        width = self.viewport().width()
        return QSize(max(CARD_W, width // self.columns()) if width > 0 else CARD_W, CARD_H)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.mode == MODE_CARDS and self.gridSize() != self.cell_size():
            self.setGridSize(self.cell_size())  # chỉ đổi khi cột/độ rộng ô thật sự đổi: kéo cửa sổ không dựng lại gì nặng

    def _toggle_index(self, index):
        if not index.isValid():
            return
        champ = index.data(ChampionRole)
        on = not self._c.is_selected(champ["name"])
        self._c.set_selected(champ["name"], on)
        self.toggled.emit(champ["name"], on)

    def _request_detail(self, index):
        if index.isValid():
            self.detail_requested.emit(index.data(ChampionRole)["name"])

    def _on_info_badge(self, index, pos) -> bool:
        """Điểm bấm có nằm trên nút ⓘ của thẻ không (chỉ dạng thẻ ảnh mới có nút này)."""
        return (self.mode == MODE_CARDS and index.isValid()
                and info_rect(inner_card_rect(self.visualRect(index))).contains(QPointF(pos)))

    def mouseReleaseEvent(self, event):
        pos = event.position().toPoint()
        index = self.indexAt(pos)
        if event.button() == Qt.MouseButton.LeftButton:
            if self._on_info_badge(index, pos):
                self._request_detail(index)  # bấm ⓘ chỉ mở chi tiết, không đổi trạng thái chọn
            else:
                self._toggle_index(index)
        elif event.button() == Qt.MouseButton.RightButton:
            self._request_detail(index)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._toggle_index(self.currentIndex())
            return
        if event.key() == Qt.Key.Key_I:
            self._request_detail(self.currentIndex())
            return
        super().keyPressEvent(event)

    def sizeHintForRow(self, row):
        return ROW_H if self.mode == MODE_TEXT else super().sizeHintForRow(row)

