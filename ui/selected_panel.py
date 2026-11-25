"""Khung 'Tướng đã chọn': các tướng đang bắt (và tên gõ tay) dưới dạng chip có ảnh nhỏ, bấm × để bỏ chọn.

Vì sao có file này: danh sách tướng có hàng trăm thẻ và nhiều mùa, tick xong thì không còn nhìn được 'mình đang bắt những ai' nếu không
bật lọc 'Đã chọn'. Khung này luôn cho thấy đúng danh sách tool sẽ bắt, kể cả tên gõ tay cho OCR."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget

from ui.widgets import ElidedLabel, FlowLayout

MAX_CHIPS = 60  # chọn cả trăm tướng thì chỉ dựng chừng này chip (nhanh); phần còn lại ghi 'và N tướng nữa'
ICON = 22  # px, ảnh chân dung nhỏ trong chip
COMPACT_MAX_H = 84  # px: ở bố cục hẹp, khi mở ra khung chỉ cao chừng một hai hàng chip, còn lại cuộn


class SelectedPanel(QFrame):
    unselect = Signal(str)  # bấm × trên chip một tướng đã tick
    unselect_manual = Signal(str)  # bấm × trên chip một tên gõ tay
    clear_all = Signal()

    def __init__(self, portrait=None, parent=None):
        """portrait(name) -> QPixmap | None: ảnh chân dung của tướng (None thì chip không có ảnh)."""
        super().__init__(parent)
        self.setProperty("card", True)
        self.setObjectName("selected_card")
        self._portrait = portrait or (lambda name: None)
        self._key: tuple | None = None
        self._compact = False
        self._expanded = False  # chỉ dùng ở bố cục hẹp: mặc định thu lại thành một dòng để lưới tướng còn nhiều chỗ
        self._empty = True
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel("Tướng đã chọn")
        self.title.setObjectName("heading")
        self.toggle_btn = QPushButton("▸  Tướng đã chọn")  # chỉ hiện ở bố cục hẹp: bấm để mở/thu danh sách chip
        self.toggle_btn.setProperty("section", True)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setAccessibleName("Mở hoặc thu danh sách tướng đã chọn")
        self.toggle_btn.toggled.connect(self._on_toggled)
        self.toggle_btn.setVisible(False)
        self.count_label = QLabel("")
        self.count_label.setProperty("muted", True)
        self.summary = ElidedLabel()  # hẹp + đang thu: tên các tướng đã chọn trên một dòng
        self.summary.setProperty("muted", True)
        self.summary.setVisible(False)
        self.clear_btn = QPushButton("Bỏ chọn hết")
        self.clear_btn.setProperty("small", True)
        self.clear_btn.setToolTip("Bỏ chọn mọi tướng đã tick (tên gõ tay giữ nguyên)")
        self.clear_btn.setAccessibleName("Bỏ chọn hết các tướng")
        self.clear_btn.clicked.connect(lambda: self.clear_all.emit())
        head.addWidget(self.title)
        head.addWidget(self.toggle_btn)
        head.addWidget(self.count_label)
        head.addWidget(self.summary, 1)
        head.addStretch(1)
        head.addWidget(self.clear_btn)
        lay.addLayout(head)

        self.empty_label = QLabel("Chưa chọn tướng nào. Bấm vào thẻ tướng ở khung 'Chọn tướng cần bắt' để thêm.")
        self.empty_label.setProperty("muted", True)
        self.empty_label.setWordWrap(True)
        lay.addWidget(self.empty_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(30)
        self.body = QWidget()
        self.flow = FlowLayout(self.body, hspacing=5, vspacing=5)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll, 1)
        self.summary.setFullText("chưa chọn tướng nào")
        self._show_empty(True)

    # ------------------------------------------------------------------ hiển thị
    def set_compact(self, compact: bool):
        """Hẹp: mặc định thu thành MỘT dòng (số tướng + tên), bấm để mở ra 1–2 hàng chip (cuộn nếu nhiều). Rộng: luôn mở, cao theo thanh kéo."""
        self._compact = compact
        self.scroll.setMaximumHeight(COMPACT_MAX_H if compact else 16777215)
        self.layout().setContentsMargins(*((8, 3, 8, 3) if compact else (10, 8, 10, 8)))  # hẹp: dòng thu gọn mỏng, nhường chỗ cho lưới tướng
        self.layout().setSpacing(4 if compact else 6)
        self._apply_visibility()

    def _on_toggled(self, on: bool):
        self._expanded = on
        self.toggle_btn.setText(("▾  " if on else "▸  ") + "Tướng đã chọn")
        self._apply_visibility()

    def _show_empty(self, empty: bool):
        self._empty = empty
        self.clear_btn.setEnabled(not empty)
        self._apply_visibility()

    def _apply_visibility(self):
        """Rộng: tiêu đề + chip luôn hiện. Hẹp: nút mở/thu + một dòng tóm tắt; chip chỉ hiện khi mở."""
        compact, open_ = self._compact, (not self._compact) or self._expanded
        self.title.setVisible(not compact)
        self.toggle_btn.setVisible(compact)
        self.summary.setVisible(compact and not self._expanded)
        self.clear_btn.setVisible(open_)
        self.empty_label.setVisible(self._empty and open_)
        self.scroll.setVisible(not self._empty and open_)

    def _clear_chips(self):
        while self.flow.count():
            item = self.flow.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def set_data(self, chosen: list[tuple[str, int]], manual: list[str]):
        """chosen = [(tên, cost)] các tướng đã tick; manual = tên gõ tay (không trùng tướng đã tick). Không đổi thì không dựng lại."""
        key = (tuple(chosen), tuple(manual))
        if key == self._key:
            return
        self._key = key
        self._clear_chips()
        for name, tier in chosen[:MAX_CHIPS]:
            self.flow.addWidget(self._chip(name, tier, manual=False))
        room = max(0, MAX_CHIPS - len(chosen))
        for name in manual[:room] if room else manual[:3]:
            self.flow.addWidget(self._chip(name, 0, manual=True))
        hidden = max(0, len(chosen) - MAX_CHIPS)
        if hidden:
            more = QLabel(f"… và {hidden} tướng nữa (bật lọc 'Đã chọn' để xem hết)")
            more.setProperty("muted", True)
            self.flow.addWidget(more)
        parts = [f"{len(chosen)} tướng"] if chosen or not manual else []
        if manual:
            parts.append(f"{len(manual)} tên gõ tay")
        self.count_label.setText(" + ".join(parts) if parts else "")
        names = [n for n, _ in chosen] + manual
        self.summary.setFullText(", ".join(names) if names else "chưa chọn tướng nào")
        self._show_empty(not chosen and not manual)

    def _chip(self, name: str, tier: int, manual: bool) -> QFrame:
        chip = QFrame()
        chip.setProperty("chipsel", True)
        chip.setProperty("tier", str(tier) if tier else "0")
        chip.setProperty("manual", manual)
        row = QHBoxLayout(chip)
        row.setContentsMargins(5, 2, 2, 2)
        row.setSpacing(4)
        icon = QLabel()
        icon.setFixedSize(ICON, ICON)
        pix = None if manual else self._portrait(name)
        if pix is not None and not pix.isNull():
            icon.setPixmap(pix.scaled(ICON, ICON, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            icon.setScaledContents(False)
        else:
            icon.setVisible(False)
        row.addWidget(icon)
        label = QLabel(name + (" ✎" if manual else ""))
        row.addWidget(label)
        x = QToolButton()
        x.setProperty("chipx", True)
        x.setText("×")
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setToolTip(f"Xóa tên gõ tay '{name}'" if manual else f"Bỏ chọn {name}")
        x.setAccessibleName(f"Bỏ chọn {name}")
        x.clicked.connect(lambda _=False, n=name, m=manual: (self.unselect_manual if m else self.unselect).emit(n))
        row.addWidget(x)
        chip.setToolTip(f"{name} — tên gõ tay cho OCR" if manual else name)
        return chip

    # ------------------------------------------------------------------ cho test và truy vấn
    def chip_names(self) -> list[str]:
        out = []
        for i in range(self.flow.count()):
            w = self.flow.itemAt(i).widget()
            if w is not None and w.property("chipsel"):
                out.append(w.findChildren(QLabel)[-1].text().removesuffix(" ✎"))
        return out
