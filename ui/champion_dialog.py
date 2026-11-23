"""Hộp thoại chi tiết tướng: ảnh, cost, mùa, vai trò + hệ, chỉ số cơ bản và kỹ năng.

Dữ liệu do AppController lấy nền (core.champion_details); hộp thoại mở ngay rồi tự vẽ lại khi dữ liệu về (refresh). Chỗ nào nguồn
không có thì nói thẳng (không bịa): mô tả kỹ năng thiếu con số hiện `[?]`, tướng mùa cũ/sự kiện báo không có chi tiết."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from core.champion_details import MISSING, role_label, stat_rows
from core.champions import season_tooltip
from ui.theme import Palette
from ui.widgets import FlowLayout

PORTRAIT = 84


def _label(text: str, *, muted: bool = False, bold: bool = False, wrap: bool = False, size: str = "") -> QLabel:
    lb = QLabel(text)
    lb.setTextFormat(Qt.TextFormat.PlainText)  # tên/mô tả đến từ dữ liệu ngoài: không bao giờ hiểu là HTML
    lb.setWordWrap(wrap)
    if muted:
        lb.setProperty("muted", True)
    style = (f"font-size: {size};" if size else "") + ("font-weight: 700;" if bold else "")
    if style:
        lb.setStyleSheet(style)
    return lb


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item is not None and item.widget() is not None:
            item.widget().deleteLater()


class ChampionDialog(QDialog):
    """Không chặn cửa sổ chính (mở bằng show()). `controller` cần: portrait_path, details_state, detail_for, details_offline,
    request_details."""

    def __init__(self, controller, champ: dict, palette: Palette, parent=None):
        super().__init__(parent)
        self._c, self._champ, self._p = controller, champ, palette
        self.setObjectName("champion_dialog")
        self.setWindowTitle(champ["name"])
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumSize(500, 420)
        self.resize(540, 600)

        self.portrait = QLabel()
        self.portrait.setFixedSize(PORTRAIT, PORTRAIT)
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = _label(champ["name"], bold=True, size="16pt")
        self.title.setObjectName("champion_title")
        self.subtitle = _label(f"{champ['tier']} gold · {season_tooltip(champ)}", muted=True)
        self.chips_host = QWidget()
        self.chips = FlowLayout(self.chips_host, hspacing=6, vspacing=6)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        for w in (self.title, self.subtitle, self.chips_host):
            text_col.addWidget(w)
        text_col.addStretch(1)
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(self.portrait, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(text_col, 1)

        self.body_host = QWidget()
        self.body = QVBoxLayout(self.body_host)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(12)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.body_host)

        close_btn = QPushButton("Đóng")
        close_btn.clicked.connect(self.close)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.addLayout(head)
        root.addWidget(self.scroll, 1)
        root.addLayout(foot)
        self.refresh_portrait()
        self.refresh()

    @property
    def champion_name(self) -> str:
        return self._champ["name"]

    def set_palette(self, palette: Palette):
        self._p = palette
        self.refresh_portrait()

    # ------------------------------------------------------------------ ảnh
    def refresh_portrait(self):
        path = self._c.portrait_path(self._champ)
        pix = QPixmap(str(path)) if path else None
        if pix is not None and not pix.isNull():
            self.portrait.setStyleSheet("")
            self.portrait.setText("")
            self.portrait.setPixmap(pix.scaled(PORTRAIT, PORTRAIT, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                               Qt.TransformationMode.SmoothTransformation))
            return
        color = self._p.cost[max(0, min(4, self._champ["tier"] - 1))]
        self.portrait.setPixmap(QPixmap())
        self.portrait.setText(self._champ["name"][:1].upper())
        self.portrait.setStyleSheet(f"font-size: 30pt; font-weight: 700; color: {color}; background: {self._p.surface2}; "
                                    f"border: 2px solid {color}; border-radius: 10px;")

    # ------------------------------------------------------------------ nội dung
    def _note(self, text: str, *, retry: bool = False):
        self.body.addWidget(_label(text, muted=True, wrap=True))
        if retry:
            btn = QPushButton("Thử tải lại")
            btn.setObjectName("retry_details")
            btn.clicked.connect(lambda: self._c.request_details(force=True))
            self.body.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)

    def refresh(self):
        """Vẽ lại phần chi tiết theo trạng thái tải hiện tại (gọi lại khi controller báo details_changed)."""
        _clear(self.body)
        _clear(self.chips)
        state = self._c.details_state()
        detail = self._c.detail_for(self._champ)
        if detail is not None:
            self._show_detail(detail)
        elif state == "ready":
            self._note("Nguồn dữ liệu (CommunityDragon) không có chi tiết của tướng này — thường là tướng ở mùa cũ hoặc bản sự kiện.")
        elif state == "error":
            self._note(f"Không tải được dữ liệu chi tiết: {self._c.details_error}\nKiểm tra kết nối mạng rồi thử lại.", retry=True)
        else:
            self._note("Đang tải dữ liệu chi tiết…")
        self.body.addStretch(1)

    def _chip(self, text: str):
        chip = QLabel(text)
        chip.setTextFormat(Qt.TextFormat.PlainText)
        chip.setProperty("chip", True)
        self.chips.addWidget(chip)

    def _show_detail(self, d: dict):
        if d.get("role"):
            self._chip(role_label(d["role"]))
        for trait in d.get("traits", []):
            self._chip(trait)

        rows = stat_rows(d)
        if rows:
            self.body.addWidget(_label("Chỉ số cơ bản (tướng 1 sao)", bold=True))
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(6)
            for i, (label, value) in enumerate(rows):
                row, col = divmod(i, 2)
                grid.addWidget(_label(label, muted=True), row, col * 2)
                grid.addWidget(_label(value, bold=True), row, col * 2 + 1)
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(3, 1)
            self.body.addWidget(grid_host)

        ability = d.get("ability") or {}
        if ability.get("name") or ability.get("desc"):
            self.body.addWidget(_label(f"Kỹ năng: {ability.get('name') or '—'}", bold=True))
            desc = _label(ability.get("desc") or "Không có mô tả.", wrap=True)
            desc.setObjectName("ability_desc")
            desc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.body.addWidget(desc)
            if not ability.get("complete", True):
                self._note(f"Chỗ ghi {MISSING} là con số Riot không công bố trong dữ liệu (công thức tính nằm trong game), "
                           "thường gặp ở mùa mới nhất.")

        source = f"Dữ liệu mùa {d['set']} · nguồn CommunityDragon"
        if self._c.details_offline:
            source += " · đang dùng bản đã lưu (chưa cập nhật được)"
        self.body.addWidget(_label(source, muted=True, wrap=True, size="8.5pt"))
