"""Cửa sổ chính (Qt). Chỉ vẽ và chuyển thao tác của người dùng sang AppController; mọi quyết định nằm ở controller.

Bố cục: thanh điều khiển cố định ở trên (Bắt đầu/Dừng + các chip trạng thái), thân có hai kiểu tự đổi theo bề rộng:
rộng  = hai vùng làm việc cạnh nhau (Tướng | Sẵn sàng + Vùng Shop + Nâng cao),
hẹp   = một cột với thanh tab ở dưới (Tướng / Vùng Shop / Chạy), vùng chạm lớn.
Thanh Nhật ký ở dưới cùng, mặc định ĐÓNG (một dòng: tiêu đề + số dòng mới + dòng mới nhất), bấm để mở."""


from PIL import Image
from shiboken6 import isValid
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core import controller as ctl
from core.config import NUMERIC_LIMITS
from core.single_instance import APP_TITLE
from ui import overlay as overlay_mod
from ui import theme
from ui.champion_dialog import ChampionDialog
from ui.champion_view import MODE_CARDS, MODE_TEXT, ChampionView
from ui.widgets import ElidedButton, ElidedLabel, FlowLayout, HintTextEdit, Switch

COMPACT_BELOW = 900  # px: hẹp hơn thì dùng bố cục một cột
HYSTERESIS = 40
PAGE_CHAMPIONS, PAGE_SHOP, PAGE_RUN = 0, 1, 2
STEP_TO_PAGE = {ctl.STEP_CHAMPIONS: PAGE_CHAMPIONS, ctl.STEP_REGION: PAGE_SHOP, ctl.STEP_CLICKS: PAGE_SHOP,
                ctl.STEP_SETTINGS: PAGE_RUN, ctl.STEP_OCR: PAGE_RUN}
MAX_LOG_LINES = 500
RIGHT_W = 320  # cột phải (bố cục rộng): hẹp cố định để khung chọn tướng chiếm phần còn lại
MANUAL_BOX_HEIGHT = 100  # px: ô tên gõ tay cao cỡ 4 dòng (trước đây 44 px chỉ vừa một dòng nên chữ gõ dài bị khuất)
LOG_OPEN_H, LOG_OPEN_H_COMPACT = 120, 96


class UiPoster(QObject):
    """Đưa một hàm từ thread bất kỳ về luồng giao diện (signal queued)."""

    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._run)

    def post(self, fn):
        self.call.emit(fn)

    @staticmethod
    def _run(fn):
        fn()


def make_card(title: str | None = None, margins=(10, 8, 10, 8), spacing=6) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setProperty("card", True)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    if title:
        head = QLabel(title)
        head.setObjectName("heading")
        lay.addWidget(head)
    return card, lay


def repolish(widget: QWidget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_prop(widget: QWidget, name: str, value):
    if widget.property(name) != value:
        widget.setProperty(name, value)
        repolish(widget)


def filter_button(text: str, tip: str = "", pill: bool = False) -> QToolButton:
    """Nút lọc dạng viên thuốc; pill=True là cỡ nhỏ (cao ~22px) cho hàng lọc cost/mùa."""
    b = QToolButton()
    b.setText(text)
    b.setCheckable(True)
    b.setProperty("filter", True)
    if pill:
        b.setProperty("pill", True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def small_button(text: str, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setProperty("small", True)
    if tip:
        b.setToolTip(tip)
    return b


def section_button(text: str, checked: bool) -> QPushButton:
    """Tiêu đề bấm để thu/mở một khối (▾ mở, ▸ thu), chữ căn trái, cả hàng là vùng bấm; văn bản do bên gọi đặt lại khi trạng thái đổi."""
    b = QPushButton(text)
    b.setProperty("section", True)
    b.setCheckable(True)
    b.setChecked(checked)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class MainWindow(QMainWindow):
    def __init__(self, make_controller, overlay_factory=None):
        """make_controller(notify, post) -> AppController. overlay_factory cho phép test thay overlay thật."""
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 840)
        self.setMinimumSize(420, 560)
        self._poster = UiPoster()
        self._overlay_factory = overlay_factory
        self._overlay = None
        self._compact: bool | None = None
        self._mode_pref = "auto"
        self.palette_ = theme.LIGHT
        self._detail_dialog: ChampionDialog | None = None  # hộp thoại chi tiết tướng đang mở (tối đa một)
        self.c = make_controller(self.on_event, self._poster.post)
        self._mode_pref = self.c.config.get("theme", "auto") if self.c.config.get("theme") in ("auto", "light", "dark") else "auto"

        self._build()
        self._apply_theme()
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self._apply_theme())
        self._wire_settings_from_controller()
        self._apply_layout(self.width() < COMPACT_BELOW)
        self._refresh_all()
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QTimer.singleShot(0, self.c.start_up)

    # ------------------------------------------------------------------ dựng giao diện
    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_topbar())

        self.body = QStackedWidget()
        outer.addWidget(self.body, 1)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.body.addWidget(self.splitter)  # trang 0: bố cục rộng
        self.compact_page = QWidget()  # trang 1: bố cục hẹp
        cl = QVBoxLayout(self.compact_page)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack, 1)
        self.tabbar = QTabBar()
        self.tabbar.setShape(QTabBar.Shape.RoundedSouth)
        self.tabbar.setExpanding(True)
        self.tabbar.setDrawBase(False)
        for name in ("1 · Tướng", "2 · Vùng Shop", "3 · Chạy"):
            self.tabbar.addTab(name)
        self.tabbar.currentChanged.connect(self.stack.setCurrentIndex)
        cl.addWidget(self.tabbar)
        self.body.addWidget(self.compact_page)

        self.champ_panel = self._build_champion_panel()
        self.ready_card = self._build_ready_card()
        self.shop_card = self._build_shop_card()
        self.adv_card = self._build_advanced_card()
        self.compact_pages = [QWidget(), QWidget(), QWidget()]
        for page in self.compact_pages:
            lay = QVBoxLayout(page)
            lay.setContentsMargins(6, 6, 6, 6)
            lay.setSpacing(6)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)

        self.right_scroll = QScrollArea()
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.right_col = QWidget()
        self.right_lay = QVBoxLayout(self.right_col)
        self.right_lay.setContentsMargins(6, 6, 6, 6)
        self.right_lay.setSpacing(6)
        self.right_scroll.setWidget(self.right_col)

        outer.addWidget(self._build_log())

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        self.top_grid = QGridLayout(bar)
        self.top_grid.setContentsMargins(12, 6, 12, 6)
        self.top_grid.setHorizontalSpacing(10)
        self.top_grid.setVerticalSpacing(4)
        self.title_label = QLabel("TFT Auto Buy")
        self.title_label.setObjectName("title")

        self.top_right = QWidget()
        right = QHBoxLayout(self.top_right)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        self.hotkey_label = QLabel("")
        self.hotkey_label.setProperty("muted", True)
        right.addWidget(self.hotkey_label)
        self.start_btn = QPushButton("")
        self.start_btn.setProperty("primary", True)
        self.start_btn.setMinimumHeight(36)
        self.start_btn.setMinimumWidth(170)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setAccessibleName("Bắt đầu hoặc dừng quét")
        self.start_btn.clicked.connect(lambda: self.c.toggle())
        right.addWidget(self.start_btn)

        self.chips_box = QWidget()
        chips = FlowLayout(self.chips_box, hspacing=6, vspacing=4)
        self.chip_ready = self._chip("")
        self.chip_selected = self._chip("")
        self.chip_ocr = self._chip("OCR: chưa kiểm tra")
        self.chip_speed = self._chip("Tốc độ: chưa chạy")
        self.chip_speed.setToolTip(ctl.SPEED_IDLE_TEXT)
        for chip in (self.chip_ready, self.chip_selected, self.chip_ocr, self.chip_speed):
            chips.addWidget(chip)
        self.status_label = QLabel("Sẵn sàng")
        self.status_label.setProperty("muted", True)
        chips.addWidget(self.status_label)
        self._top_compact: bool | None = None
        self._place_topbar(False)
        return bar

    def _place_topbar(self, compact: bool):
        """Rộng: MỘT hàng (tên | chip | phím + nút Bắt đầu). Hẹp: tên + nút ở hàng trên, chip xuống hàng dưới."""
        if compact == self._top_compact:
            return
        self._top_compact = compact
        g = self.top_grid
        for w in (self.title_label, self.top_right, self.chips_box):
            g.removeWidget(w)
        for col in range(3):
            g.setColumnStretch(col, 0)
        if compact:
            g.addWidget(self.title_label, 0, 0)
            g.addWidget(self.top_right, 0, 1, Qt.AlignmentFlag.AlignRight)
            g.addWidget(self.chips_box, 1, 0, 1, 2)
            g.setColumnStretch(0, 1)
        else:
            g.addWidget(self.title_label, 0, 0)
            g.addWidget(self.chips_box, 0, 1)
            g.addWidget(self.top_right, 0, 2, Qt.AlignmentFlag.AlignRight)
            g.setColumnStretch(1, 1)

    @staticmethod
    def _chip(text: str) -> QLabel:
        chip = QLabel(text)
        chip.setProperty("chip", True)
        chip.setProperty("tone", "muted")
        chip.setWordWrap(False)
        return chip

    def _build_champion_panel(self) -> QWidget:
        card, lay = make_card()
        card.setObjectName("champ_card")
        # Hàng đầu: tiêu đề + đếm | ô tìm kiếm | Dạng chữ (rộng: một hàng; hẹp: ô tìm xuống hàng dưới)
        self.champ_title = QWidget()
        title_lay = QHBoxLayout(self.champ_title)
        title_lay.setContentsMargins(0, 0, 0, 0)
        title_lay.setSpacing(8)
        heading = QLabel("Chọn tướng cần bắt")
        heading.setObjectName("heading")
        title_lay.addWidget(heading)
        self.count_label = QLabel("")
        self.count_label.setProperty("muted", True)
        title_lay.addWidget(self.count_label)
        self.mode_btn = small_button("Dạng chữ", "Chuyển giữa thẻ có ảnh và danh sách chữ gọn")
        self.mode_btn.setMinimumWidth(84)
        self.mode_btn.clicked.connect(self._toggle_view_mode)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm tướng (Ctrl+F) — tên tiếng Việt/Anh, mọi mùa")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(120)
        self.search.setAccessibleName("Tìm tướng")
        self.search.textChanged.connect(lambda t: self.c.set_query(t))
        self.head_grid = QGridLayout()
        self.head_grid.setContentsMargins(0, 0, 0, 0)
        self.head_grid.setHorizontalSpacing(8)
        self.head_grid.setVerticalSpacing(4)
        lay.addLayout(self.head_grid)
        self._head_compact: bool | None = None
        self._place_champ_head(False)

        # MỘT hàng lọc gồm cost, Đã chọn và các chip mùa (cùng cỡ nhỏ) để tiết kiệm chiều cao
        filt = FlowLayout(hspacing=4, vspacing=4)
        self.filter_row = filt
        self.cost_buttons: dict[int, QToolButton] = {}
        for tier in range(1, 6):
            b = filter_button(f"{tier}g", f"Chỉ hiện tướng {tier} gold", pill=True)
            b.toggled.connect(lambda on, t=tier: self.c.toggle_cost(t, on))
            self.cost_buttons[tier] = b
            filt.addWidget(b)
        self.only_sel_btn = filter_button("Đã chọn", "Chỉ hiện tướng đang tick", pill=True)
        self.only_sel_btn.toggled.connect(lambda on: self.c.set_only_selected(on))
        filt.addWidget(self.only_sel_btn)
        lay.addLayout(filt)
        # Chip mùa: Tất cả + một chip cho mỗi mùa có trong Data Dragon (dựng lại khi danh sách mùa đổi). Chọn nhiều mùa được.
        self.season_all: QToolButton | None = None
        self.season_buttons: dict[int, QToolButton] = {}
        self._season_widgets: list[QWidget] = []
        self._rebuild_season_chips()

        self.view = ChampionView(self.c, self.palette_)
        self.view.setMinimumHeight(110)
        self.view.toggled.connect(lambda *_: None)
        self.view.detail_requested.connect(self._open_detail)
        lay.addWidget(self.view, 1)

        # Một hàng dưới khung: thao tác chọn + cách nhận diện (2 công tắc) + ô tên gõ tay ẩn sau nút
        actions = FlowLayout(hspacing=6, vspacing=4)
        for text, fn in (("Chọn tất cả", lambda: self.c.select_all_visible()),
                         ("Bỏ chọn", lambda: self.c.deselect_all_visible()),
                         ("Upload ảnh", self._upload),
                         ("Tải lại", lambda: self.c.reload_champions())):
            b = small_button(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            actions.addWidget(b)
        how = QLabel("Nhận diện:")
        how.setProperty("muted", True)
        actions.addWidget(how)
        self.sw_image = Switch("Ảnh")
        self.sw_name = Switch("Tên (OCR)")
        self.sw_image.setToolTip("Bắt theo ảnh chân dung tướng")
        self.sw_name.setToolTip("Bắt theo tên đọc bằng OCR")
        for sw in (self.sw_image, self.sw_name):
            actions.addWidget(sw)
        self.sw_image.toggled.connect(self._on_mode_changed)
        self.sw_name.toggled.connect(self._on_mode_changed)
        self.manual_btn = filter_button("Tên gõ tay ▸", "Gõ thêm tên tướng cho OCR (phẩy hoặc xuống dòng)", pill=True)
        self.manual_btn.toggled.connect(self._toggle_manual)
        actions.addWidget(self.manual_btn)
        lay.addLayout(actions)
        self.manual = HintTextEdit()  # không dùng QPlainTextEdit thường: chữ đang gõ bằng Telex/IME bị đè lên placeholder
        self.manual.setPlaceholderText("Tên gõ tay cho OCR (phẩy hoặc xuống dòng), vd: Aatrox, Yasuo, Jinx")
        self.manual.setFixedHeight(MANUAL_BOX_HEIGHT)
        self.manual.setAccessibleName("Tên tướng gõ tay")
        self.manual.textChanged.connect(self._on_manual_changed)
        self.manual.setVisible(False)
        lay.addWidget(self.manual)
        return card

    def _place_champ_head(self, compact: bool):
        if compact == self._head_compact:
            return
        self._head_compact = compact
        g = self.head_grid
        for w in (self.champ_title, self.search, self.mode_btn):
            g.removeWidget(w)
        for col in range(3):
            g.setColumnStretch(col, 0)
        if compact:
            g.addWidget(self.champ_title, 0, 0)
            g.addWidget(self.mode_btn, 0, 2)
            g.addWidget(self.search, 1, 0, 1, 3)
            g.setColumnStretch(1, 1)
        else:
            g.addWidget(self.champ_title, 0, 0)
            g.addWidget(self.search, 0, 1)
            g.addWidget(self.mode_btn, 0, 2)
            g.setColumnStretch(1, 1)

    def _toggle_manual(self, on: bool):
        self.manual.setVisible(on)
        self.manual_btn.setText("Tên gõ tay ▾" if on else "Tên gõ tay ▸")

    def _sync_manual_visibility(self):
        """Đã có tên gõ tay thì hiện ô nhập ngay (tránh ẩn mất tên đang dùng); chưa có thì ẩn sau nút."""
        if self.c.manual_names.strip() and not self.manual_btn.isChecked():
            self.manual_btn.setChecked(True)

    def _build_ready_card(self) -> QFrame:
        card, lay = make_card()
        self.ready_toggle = section_button("▾  Sẵn sàng chạy?", True)
        self.ready_toggle.toggled.connect(self._on_ready_toggled)
        lay.addWidget(self.ready_toggle)
        self.ready_body = QWidget()
        self.ready_lay = QVBoxLayout(self.ready_body)
        self.ready_lay.setContentsMargins(0, 0, 0, 0)
        self.ready_lay.setSpacing(0)
        lay.addWidget(self.ready_body)
        self.ready_rows: dict[str, QPushButton] = {}
        self._ready_state: bool | None = None  # đã đủ điều kiện chưa ở lần cập nhật trước (để tự thu/mở khi đổi trạng thái)
        return card

    def _on_ready_toggled(self, on: bool):
        self.ready_body.setVisible(on)
        self._refresh_ready_header()

    def _refresh_ready_header(self):
        ready = self.c.first_missing() is None
        open_ = self.ready_toggle.isChecked()
        todo = sum(1 for r in self.c.requirements() if not r.ok and r.blocking)
        text = "✓ Sẵn sàng chạy" if ready else f"✗ Chưa sẵn sàng · còn {todo} việc"
        self.ready_toggle.setText(("▾  " if open_ else "▸  ") + text)
        set_prop(self.ready_toggle, "tone", "ok" if ready else "fail")

    def _build_shop_card(self) -> QFrame:
        card, lay = make_card()
        self.shop_toggle = section_button("▾  Vùng Shop và điểm click", True)
        self.shop_toggle.toggled.connect(self._on_shop_toggled)
        lay.addWidget(self.shop_toggle)
        self.shop_body = QWidget()
        body = QVBoxLayout(self.shop_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        lay.addWidget(self.shop_body)

        steps = FlowLayout(hspacing=6, vspacing=4)
        self.region_btn = small_button("①  Vùng Shop", "Bước 1: kéo khung CHỈ quanh hàng 5 thẻ tướng")
        self.region_btn.setProperty("step", True)
        self.region_btn.clicked.connect(lambda: self._calibrate_region())
        self.clicks_btn = small_button("②  5 điểm click", "Bước 2: click lần lượt vào giữa ảnh tướng của 5 ô")
        self.clicks_btn.setProperty("step", True)
        self.clicks_btn.clicked.connect(lambda: self._calibrate_clicks())
        self.view_btn = small_button("👁  Xem", "Hiện khung vùng Shop và 5 chấm đỏ đánh số ngay trên màn hình thật để đối chiếu với game")
        self.view_btn.clicked.connect(lambda: self._view_on_screen())
        for b in (self.region_btn, self.clicks_btn, self.view_btn):
            steps.addWidget(b)
        body.addLayout(steps)
        self.monitor_label = QLabel("")
        self.monitor_label.setWordWrap(True)
        self.monitor_label.setProperty("muted", True)
        body.addWidget(self.monitor_label)
        self.region_label = QLabel("")
        self.region_label.setProperty("muted", True)
        self.region_label.setWordWrap(True)
        body.addWidget(self.region_label)
        self.preview = QLabel("Chưa có ảnh — chọn vùng Shop để xem trước")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(56)
        self.preview.setWordWrap(True)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        body.addWidget(self.preview)
        foot = QHBoxLayout()
        foot.setSpacing(6)
        self.preview_note = QLabel("")
        self.preview_note.setWordWrap(True)
        self.preview_note.setProperty("muted", True)
        foot.addWidget(self.preview_note, 1)
        self.refresh_btn = small_button("↻ Làm mới", "Chụp lại màn hình để cập nhật ảnh xem trước")
        self.refresh_btn.clicked.connect(self._refresh_preview)
        foot.addWidget(self.refresh_btn)
        body.addLayout(foot)
        self._preview_pixmap: QPixmap | None = None
        self._shop_ok: bool | None = None
        return card

    def _on_shop_toggled(self, on: bool):
        self.shop_body.setVisible(on)
        self.shop_toggle.setText(("▾  " if on else "▸  ") + "Vùng Shop và điểm click" + self._shop_status_tail())

    def _shop_status_tail(self) -> str:
        if not hasattr(self, "c"):
            return ""
        done = bool(self.c.config.get("shop_region")) and not self.c.monitor_pending
        clicks = len(self.c.config.get("slot_centers") or []) == 5
        return "  ·  ✓" if done and clicks else "  ·  ✗"

    def _build_advanced_card(self) -> QFrame:
        card, lay = make_card()
        lay.setSpacing(4)
        self.adv_toggle = section_button("▸  Nâng cao", False)
        self.adv_toggle.toggled.connect(self._toggle_advanced)
        lay.addWidget(self.adv_toggle)
        self.adv_body = QWidget()
        b = QVBoxLayout(self.adv_body)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(4)
        self.sl_image, self.lb_image = self._slider_row(b, "Độ khớp ảnh", lambda v: self._set_threshold("image", v))
        self.sl_name, self.lb_name = self._slider_row(b, "Độ khớp tên OCR", lambda v: self._set_threshold("name", v))
        lo, hi = (int(x) for x in NUMERIC_LIMITS["scan_interval_ms"])
        row = QHBoxLayout()
        row.addWidget(QLabel("Chu kỳ quét tối thiểu (ms, 0 = nhanh nhất)"))
        row.addStretch(1)
        self.interval = QSpinBox()
        self.interval.setRange(lo, hi)
        self.interval.setAccessibleName("Chu kỳ quét tối thiểu")
        self.interval.valueChanged.connect(self._on_interval_changed)
        row.addWidget(self.interval)
        b.addLayout(row)
        rrow = QHBoxLayout()
        rlabel = QLabel("Phím roll trong game (quét dày khi bấm; để trống = tắt)")
        rlabel.setWordWrap(True)
        rrow.addWidget(rlabel, 1)
        self.roll_edit = QLineEdit(self.c.roll_key)
        self.roll_edit.setMaxLength(12)
        self.roll_edit.setFixedWidth(70)
        self.roll_edit.setAccessibleName("Phím roll")
        self.roll_edit.editingFinished.connect(lambda: self.c.set_roll_key(self.roll_edit.text()))
        rrow.addWidget(self.roll_edit)
        b.addLayout(rrow)
        crow = QHBoxLayout()
        clabel = QLabel("Cách chụp màn hình (áp dụng lần quét sau)")
        clabel.setWordWrap(True)
        crow.addWidget(clabel, 1)
        self.capture_box = QComboBox()
        self.capture_box.setAccessibleName("Cách chụp màn hình")
        for key, text in (("auto", "Tự động (DXGI nếu được)"), ("mss", "Chỉ mss")):
            self.capture_box.addItem(text, key)
        self.capture_box.setCurrentIndex(max(0, self.capture_box.findData(self.c.config.get("capture_backend", "auto"))))
        self.capture_box.currentIndexChanged.connect(self._on_capture_changed)
        crow.addWidget(self.capture_box)
        b.addLayout(crow)
        self.speed_label = QLabel(ctl.SPEED_IDLE_TEXT)
        self.speed_label.setProperty("muted", True)
        self.speed_label.setWordWrap(True)
        b.addWidget(self.speed_label)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Giao diện"))
        trow.addStretch(1)
        self.theme_box = QComboBox()
        for key, text in (("auto", "Theo Windows"), ("light", "Sáng"), ("dark", "Tối")):
            self.theme_box.addItem(text, key)
        self.theme_box.currentIndexChanged.connect(self._on_theme_changed)
        trow.addWidget(self.theme_box)
        b.addLayout(trow)
        license_title = QLabel("Giấy phép")
        license_title.setObjectName("heading")
        b.addWidget(license_title)
        self.license_state = QLabel("")
        self.license_state.setWordWrap(True)
        self.license_state.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        b.addWidget(self.license_state)
        self._refresh_license()
        self.adv_body.setVisible(False)
        lay.addWidget(self.adv_body)
        return card

    def _slider_row(self, parent_lay: QVBoxLayout, text: str, on_change):
        row = QHBoxLayout()
        row.addWidget(QLabel(text))
        row.addStretch(1)
        value = QLabel("")
        value.setObjectName("heading")
        row.addWidget(value)
        parent_lay.addLayout(row)
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(50, 95)
        sl.setAccessibleName(text)
        sl.valueChanged.connect(on_change)
        parent_lay.addWidget(sl)
        return sl, value

    def _build_log(self) -> QWidget:
        """Thanh Nhật ký, mặc định ĐÓNG: tiêu đề + badge số dòng mới (cam/đỏ khi có cảnh báo/lỗi) + dòng mới nhất. Mở ra thì có
        Sao chép / Xóa / Cuộn cuối."""
        wrap = QFrame()
        wrap.setObjectName("logbar")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(8, 3, 8, 4)
        lay.setSpacing(3)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.log_toggle = QToolButton()
        self.log_toggle.setProperty("logtoggle", True)
        self.log_toggle.setCheckable(True)
        self.log_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.log_toggle.setText("▸  Nhật ký")
        self.log_toggle.setAccessibleName("Mở hoặc đóng Nhật ký")
        self.log_toggle.toggled.connect(self._toggle_log)
        head.addWidget(self.log_toggle)
        self.log_badge = QLabel("")
        self.log_badge.setProperty("badge", True)
        self.log_badge.setProperty("tone", "muted")
        self.log_badge.setVisible(False)
        head.addWidget(self.log_badge)
        self.log_preview = ElidedLabel()
        self.log_preview.setProperty("logpreview", True)
        head.addWidget(self.log_preview, 100)
        head.addStretch(1)  # khi dòng xem trước ẩn (đang mở), nút công cụ vẫn dồn sang phải thay vì giãn ra
        self.log_tools = QWidget()
        tools = QHBoxLayout(self.log_tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(4)
        self.log_bottom_btn = small_button("⤓ Cuối", "Cuộn xuống dòng mới nhất")
        self.log_bottom_btn.clicked.connect(self._log_to_bottom)
        self.log_clear_btn = small_button("Xóa", "Xóa Nhật ký")
        self.log_clear_btn.clicked.connect(self._clear_log)
        tools.addWidget(self.log_bottom_btn)
        tools.addWidget(self.log_clear_btn)
        self.log_tools.setVisible(False)
        head.addWidget(self.log_tools)
        self.log_copy_btn = small_button("Sao chép", "Sao chép toàn bộ Nhật ký")
        self.log_copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.log_view.toPlainText()))
        head.addWidget(self.log_copy_btn)
        lay.addLayout(head)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(MAX_LOG_LINES)
        self.log_view.setAccessibleName("Nhật ký")
        self.log_view.setFixedHeight(LOG_OPEN_H)
        self.log_view.setVisible(False)
        lay.addWidget(self.log_view)
        self._log_new = 0
        self._log_level = "info"
        self.log_wrap = wrap
        return wrap

    def _toggle_log(self, on: bool):
        self.log_view.setVisible(on)
        self.log_tools.setVisible(on)
        self.log_preview.setVisible(not on)
        self.log_toggle.setText(("▾" if on else "▸") + "  Nhật ký")
        if on:
            self._log_new, self._log_level = 0, "info"  # đã xem: xóa badge
            self._log_to_bottom()
        self._refresh_log_badge()
        self._apply_log_height()

    def _apply_log_height(self):
        self.log_view.setFixedHeight(LOG_OPEN_H_COMPACT if self._compact else LOG_OPEN_H)

    def _log_to_bottom(self):
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _clear_log(self):
        self.log_view.clear()
        self._log_new, self._log_level = 0, "info"
        self.log_preview.setFullText("")
        self._refresh_log_badge()

    def _refresh_log_badge(self):
        """Badge chỉ hiện khi Nhật ký đang đóng và có dòng mới; màu theo mức nặng nhất trong các dòng mới."""
        show = (not self.log_toggle.isChecked()) and self._log_new > 0
        self.log_badge.setVisible(show)
        self.log_badge.setText("99+" if self._log_new > 99 else str(self._log_new))
        tone = {"error": "fail", "warn": "warn"}.get(self._log_level, "muted")
        set_prop(self.log_badge, "tone", tone)
        set_prop(self.log_preview, "tone", tone if self._log_new else "muted")

    # ------------------------------------------------------------------ bố cục thích ứng
    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = event.size().width()
        if self._compact is None:
            want_compact = w < COMPACT_BELOW
        elif self._compact:  # đang hẹp: chỉ sang rộng khi vượt hẳn ngưỡng (tránh nhấp nháy khi kéo cửa sổ)
            want_compact = w < COMPACT_BELOW + HYSTERESIS
        else:
            want_compact = w < COMPACT_BELOW - HYSTERESIS
        if self._compact is None or want_compact != self._compact:
            self._apply_layout(want_compact)
        self._apply_log_height()

    def _detach(self, *widgets):
        for w in widgets:
            w.setParent(None)

    def _apply_layout(self, compact: bool):
        if compact == self._compact:
            return
        self._compact = compact
        self._place_topbar(compact)
        self._place_champ_head(compact)
        panels = (self.champ_panel, self.ready_card, self.shop_card, self.adv_card)
        self._detach(*panels)
        if compact:
            for page in self.compact_pages:
                lay = page.layout()
                while lay.count():
                    lay.takeAt(0)
            self.compact_pages[PAGE_CHAMPIONS].layout().addWidget(self.champ_panel)
            self.compact_pages[PAGE_SHOP].layout().addWidget(self.shop_card)
            self.compact_pages[PAGE_SHOP].layout().addStretch(1)
            run = self.compact_pages[PAGE_RUN].layout()
            run.addWidget(self.ready_card)
            run.addWidget(self.adv_card)
            run.addStretch(1)
            self.stack.setCurrentIndex(self.tabbar.currentIndex())
            self.body.setCurrentWidget(self.compact_page)
        else:
            while self.right_lay.count():
                self.right_lay.takeAt(0)
            self.right_lay.addWidget(self.ready_card)
            self.right_lay.addWidget(self.shop_card)
            self.right_lay.addWidget(self.adv_card)
            self.right_lay.addStretch(1)
            self.splitter.addWidget(self.champ_panel)
            self.splitter.addWidget(self.right_scroll)
            self.right_scroll.setMinimumWidth(RIGHT_W - 40)
            self.right_scroll.setMaximumWidth(RIGHT_W + 80)
            self.splitter.setStretchFactor(0, 1)  # khung tướng chiếm mọi phần rộng thêm
            self.splitter.setStretchFactor(1, 0)
            self.splitter.setSizes([max(300, self.width() - RIGHT_W), RIGHT_W])
            self.body.setCurrentWidget(self.splitter)

    def go_to_step(self, step: str):
        """Dẫn người dùng tới nơi sửa điều kiện còn thiếu: đổi tab (hẹp) hoặc nháy khung tương ứng (rộng)."""
        if self._compact:
            self.tabbar.setCurrentIndex(STEP_TO_PAGE.get(step, PAGE_RUN))
        target = {ctl.STEP_CHAMPIONS: self.champ_panel, ctl.STEP_REGION: self.shop_card, ctl.STEP_CLICKS: self.shop_card,
                  ctl.STEP_SETTINGS: self.adv_card, ctl.STEP_OCR: self.ready_card}.get(step, self.ready_card)
        if step == ctl.STEP_SETTINGS and not self.adv_toggle.isChecked():
            self.adv_toggle.setChecked(True)
        if step in (ctl.STEP_REGION, ctl.STEP_CLICKS) and not self.shop_toggle.isChecked():
            self.shop_toggle.setChecked(True)
        if step == ctl.STEP_OCR and not self.ready_toggle.isChecked():
            self.ready_toggle.setChecked(True)
        set_prop(target, "attention", True)
        QTimer.singleShot(1600, lambda t=target: set_prop(t, "attention", False) if isValid(t) else None)
        if step == ctl.STEP_CHAMPIONS:
            self.search.setFocus()
        elif step == ctl.STEP_SETTINGS:
            self.interval.setFocus()

    # ------------------------------------------------------------------ theme
    def _apply_theme(self):
        self.palette_ = theme.pick(self._mode_pref)
        QApplication.instance().setStyleSheet(theme.stylesheet(self.palette_))
        self.view.set_palette(self.palette_)
        if self._detail_dialog is not None:
            self._detail_dialog.set_palette(self.palette_)
        if hasattr(self, "license_state"):  # lần gọi đầu (trong __init__) thì mục Nâng cao chưa dựng
            self._refresh_license()
        for sw in (self.sw_image, self.sw_name):
            sw.set_colors(self.palette_.accent, self.palette_.border, self.palette_.text)
        self._refresh_all()

    def _on_capture_changed(self):
        from core.config import save_config

        self.c.config["capture_backend"] = self.capture_box.currentData()
        save_config(self.c.config)

    def _on_theme_changed(self):
        self._mode_pref = self.theme_box.currentData()
        self.c.config["theme"] = self._mode_pref
        from core.config import save_config

        save_config(self.c.config)
        self._apply_theme()

    # ------------------------------------------------------------------ đồng bộ controller -> widget
    def _wire_settings_from_controller(self):
        c = self.c
        for w, v in ((self.sw_image, c.detect_image), (self.sw_name, c.detect_name)):
            w.blockSignals(True)
            w.setChecked(v)
            w.blockSignals(False)
        self.manual.blockSignals(True)
        self.manual.setPlainText(c.manual_names)
        self.manual.blockSignals(False)
        self._sync_manual_visibility()
        for sl, lb, v in ((self.sl_image, self.lb_image, c.threshold), (self.sl_name, self.lb_name, c.name_threshold)):
            sl.blockSignals(True)
            sl.setValue(round(v * 100))
            sl.blockSignals(False)
            lb.setText(f"{v:.0%}")
        self.interval.blockSignals(True)
        try:
            self.interval.setValue(int(c.interval_text))
        except ValueError:
            self.interval.setValue(self.interval.minimum())
        self.interval.blockSignals(False)
        self.theme_box.blockSignals(True)
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(self._mode_pref)))
        self.theme_box.blockSignals(False)

    def _refresh_all(self):
        self._refresh_list()
        self._refresh_readiness()
        self.hotkey_label.setText(self.c.hotkey_text())
        self._refresh_start_button()
        self.region_label.setText(self.c.region_text())

    def _refresh_list(self):
        items = self.c.filtered()
        self.view.champion_model.set_items(items)
        available = set(self.c.costs_available())
        for tier, b in self.cost_buttons.items():
            b.setEnabled(tier in available or b.isChecked())
        total = len(self.c.champions)
        if not total:
            self.count_label.setText("chưa tải")
        elif self.c.is_searching():
            self.count_label.setText(f"{len(items)} kết quả (tìm trong mọi mùa)")
        else:
            self.count_label.setText(f"{len(items)}/{total} tướng")
        self._sync_season_chips()
        self._refresh_selected_chip()

    def _refresh_selected_chip(self):
        n = len(self.c.target_names())
        self.chip_selected.setText(f"{n} tướng đang chọn")
        set_prop(self.chip_selected, "tone", "ok" if n else "warn")

    def _refresh_readiness(self):
        reqs = self.c.requirements()
        for r in reqs:
            row = self.ready_rows.get(r.key)
            if row is None:
                row = ElidedButton()
                row.setProperty("row", True)
                row.setCursor(Qt.CursorShape.PointingHandCursor)
                row.clicked.connect(lambda _=False, k=r.key: self.go_to_step(self._step_of(k)))
                self.ready_rows[r.key] = row
                self.ready_lay.addWidget(row)
            mark = "✓" if r.ok else ("✗" if r.blocking else "!")
            row.setFullText(f"{mark}  {r.text}")
            row.setAccessibleName(f"{'Đạt' if r.ok else 'Thiếu'}: {r.text}")
            set_prop(row, "state", "ok" if r.ok else ("fail" if r.blocking else "warn"))
        for key in [k for k in self.ready_rows if k not in {r.key for r in reqs}]:
            self.ready_rows.pop(key).deleteLater()
        missing = self.c.first_missing()
        if missing is None:
            self.chip_ready.setText("✓ Sẵn sàng")
            set_prop(self.chip_ready, "tone", "ok")
        else:
            self.chip_ready.setText(f"✗ {missing.text}")
            set_prop(self.chip_ready, "tone", "fail")
        self._step_of_map = {r.key: r.step for r in reqs}
        self._refresh_selected_chip()
        self._refresh_start_button()
        done_region = bool(self.c.config.get("shop_region")) and not self.c.monitor_pending
        self.view_btn.setText("👁  Xác nhận" if self.c.monitor_pending else "👁  Xem")
        self.view_btn.setToolTip("Xem gợi ý quy đổi trên màn hình, bấm Enter để dùng" if self.c.monitor_pending else
                                 "Hiện khung vùng Shop và 5 chấm đỏ đánh số ngay trên màn hình thật để đối chiếu với game")
        self.region_btn.setText(("✓  " if done_region else "①  ") + "Vùng Shop")
        self.region_btn.setToolTip("Chọn lại vùng Shop (kéo khung CHỈ quanh hàng 5 thẻ tướng)" if done_region else
                                   "Bước 1: kéo khung CHỈ quanh hàng 5 thẻ tướng")
        clicks_ok = next((r.ok for r in reqs if r.key == "clicks"), False)
        self.clicks_btn.setText(("✓  " if clicks_ok else "②  ") + "5 điểm click")
        self.clicks_btn.setToolTip("Đặt lại 5 điểm click" if clicks_ok else "Bước 2: click lần lượt vào giữa ảnh tướng của 5 ô")
        self.region_label.setText(self.c.region_text())
        self._auto_fold_blocks(missing is None)

    def _step_of(self, key: str) -> str:
        return getattr(self, "_step_of_map", {}).get(key, ctl.STEP_CHAMPIONS)

    def _auto_fold_blocks(self, ready: bool):
        """Thu/mở tự động khi trạng thái ĐỔI: 'Sẵn sàng' co thành 1 dòng khi đủ điều kiện và tự mở liệt kê khi thiếu; 'Vùng Shop' thu lại
        lúc mở app nếu đã cấu hình xong và tự mở khi cấu hình hỏng/chưa xác nhận. Người dùng tự thu/mở thì giữ nguyên tới lần đổi sau."""
        if ready != self._ready_state:
            self._ready_state = ready
            self.ready_toggle.setChecked(not ready)
        self._refresh_ready_header()
        shop_ok = (bool(self.c.config.get("shop_region")) and not self.c.monitor_pending
                   and len(self.c.config.get("slot_centers") or []) == 5)
        if self._shop_ok is None:
            self.shop_toggle.setChecked(not shop_ok)
        elif self._shop_ok and not shop_ok:
            self.shop_toggle.setChecked(True)
        self._shop_ok = shop_ok
        self.shop_toggle.setText(("▾  " if self.shop_toggle.isChecked() else "▸  ") + "Vùng Shop và điểm click"
                                 + self._shop_status_tail())

    def _refresh_start_button(self):
        running = self.c.running
        preparing = self.c.preparing
        if preparing:
            text = "Đang chuẩn bị…"
        else:
            text = self.c.toggle_text(running)
        self.start_btn.setText(text)
        self.start_btn.setEnabled(not preparing)
        set_prop(self.start_btn, "running", running)
        set_prop(self.start_btn, "blocked", (not running) and (not self.c.ready()))
        tip = "Chạy/dừng quét. " + ("" if self.c.ready() or running else "Chưa đủ điều kiện: bấm để được dẫn tới bước còn thiếu.")
        self.start_btn.setToolTip(tip)

    # ------------------------------------------------------------------ sự kiện từ controller
    def on_event(self, event: str, **d):
        handler = getattr(self, f"_ev_{event}", None)
        if handler:
            handler(**d)

    def _ev_log(self, text, level="info"):
        self.log_view.appendPlainText(text)
        if self.log_toggle.isChecked():
            return
        self._log_new += 1
        rank = {"info": 0, "warn": 1, "error": 2}
        if rank.get(level, 0) > rank[self._log_level]:
            self._log_level = level
        self.log_preview.setFullText(text.split("] ", 1)[1] if text.startswith("[") and "] " in text else text)
        self._refresh_log_badge()

    def _ev_status(self, text):
        self.status_label.setText(text)

    def _ev_dialog(self, level, title, text):
        box = {"info": QMessageBox.information, "warning": QMessageBox.warning, "error": QMessageBox.critical}[level]
        box(self, title, text)

    def _ev_champions_changed(self):
        self._rebuild_season_chips()
        self._refresh_list()
        self._refresh_readiness()

    def _ev_filter_changed(self):
        self._refresh_list()

    # ------------------------------------------------------------------ chip chọn mùa
    def _clear_season_chips(self):
        row = self.filter_row
        for w in self._season_widgets:
            for i in range(row.count()):
                if row.itemAt(i).widget() is w:
                    row.takeAt(i)
                    break
            w.deleteLater()
        self._season_widgets = []

    def _rebuild_season_chips(self):
        """Dựng lại chip mùa theo các mùa hiện có (mùa mới ra tự có chip). Chỉ dựng lại khi danh sách mùa thật sự đổi. Các chip nằm
        cùng hàng với chip cost và tự xuống dòng khi hẹp."""
        seasons = self.c.seasons_available() if hasattr(self, "c") else []
        if self.season_all is not None and list(self.season_buttons) == seasons:
            self._sync_season_chips()
            return
        self._clear_season_chips()
        row = self.filter_row
        label = QLabel("Mùa:")
        label.setProperty("muted", True)
        self._season_widgets.append(label)
        row.addWidget(label)
        self.season_buttons = {}
        self.season_all = filter_button("Tất cả", "Hiện tướng của mọi mùa", pill=True)
        self.season_all.clicked.connect(lambda _=False: self._on_season_all())
        self._season_widgets.append(self.season_all)
        row.addWidget(self.season_all)
        for season in seasons:
            b = filter_button(f"M{season}", f"Chỉ hiện tướng có ở mùa {season} (chọn nhiều mùa được)", pill=True)
            b.clicked.connect(lambda checked=False, s=season: self._on_season_clicked(s, checked))
            self.season_buttons[season] = b
            self._season_widgets.append(b)
            row.addWidget(b)
        row.invalidate()
        self._sync_season_chips()

    def _sync_season_chips(self):
        if self.season_all is None:
            return
        chosen = self.c.seasons
        searching = self.c.is_searching()
        for season, b in self.season_buttons.items():
            b.setChecked(season in chosen)
            b.setToolTip("Đang tìm kiếm nên hiện mọi mùa — bộ lọc mùa sẽ áp dụng lại khi xóa ô tìm" if searching
                         else f"Chỉ hiện tướng có ở mùa {season} (chọn nhiều mùa được)")
        self.season_all.setChecked(not chosen)

    def _on_season_all(self):
        self.c.clear_seasons()

    def _on_season_clicked(self, season: int, checked: bool):
        self.c.toggle_season(season, checked)

    def _ev_selection_changed(self):
        if self.c.only_selected:
            self._refresh_list()
        else:
            self.view.champion_model.refresh_all()
        self._refresh_readiness()

    def _ev_readiness_changed(self):
        self._refresh_readiness()

    def _ev_config_changed(self):
        self._refresh_readiness()

    def _ev_monitor_changed(self):
        st = self.c.monitor_status
        self.monitor_label.setText(st.text if st else "")
        pending = self.c.monitor_pending
        self.monitor_label.setStyleSheet(f"color: {theme.tone_color(self.palette_, 'warn')};" if pending else "")
        self._refresh_readiness()

    def _ev_blocked(self, requirement):
        self.status_label.setText(f"Chưa chạy được: {requirement.text}")
        self._refresh_readiness()
        self.go_to_step(requirement.step)

    def _ev_ocr(self, text, tone):
        self.chip_ocr.setText(text)
        set_prop(self.chip_ocr, "tone", tone)

    def _ev_speed(self, text):
        self.chip_speed.setText("Tốc độ: chưa chạy" if text == ctl.SPEED_IDLE_TEXT else text)
        self.chip_speed.setToolTip(text)
        self.speed_label.setText(text)

    def _ev_running_changed(self, running):
        self._refresh_start_button()

    def _ev_preparing(self, on):
        self._refresh_start_button()

    def _ev_hotkey_changed(self):
        self.hotkey_label.setText(self.c.hotkey_text())
        self._refresh_start_button()

    def _ev_portrait_ready(self, name):
        self.view.champion_model.refresh_name(name)
        if self._detail_dialog is not None and self._detail_dialog.champion_name == name:
            self._detail_dialog.refresh_portrait()

    # ------------------------------------------------------------------ chi tiết tướng
    def _open_detail(self, name: str):
        """Mở hộp thoại chi tiết của tướng (thay hộp đang mở nếu có) và bắt đầu tải dữ liệu chi tiết nếu chưa có."""
        champ = next((c for c in self.c.champions if c["name"] == name), None)
        if champ is None:
            return
        if self._detail_dialog is not None:
            self._detail_dialog.close()
        self.c.request_details()
        dialog = ChampionDialog(self.c, champ, self.palette_, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(lambda _=None, d=dialog: self._detail_closed(d))
        self._detail_dialog = dialog
        dialog.show()

    def _detail_closed(self, dialog):
        if self._detail_dialog is dialog:
            self._detail_dialog = None

    def _ev_details_changed(self):
        if self._detail_dialog is not None:
            self._detail_dialog.refresh()

    def _ev_preview_busy(self, busy):
        self.refresh_btn.setEnabled(not busy)

    def _ev_preview(self, image, note, tone):
        if image is not None:
            self._set_preview_image(image)
        self.preview_note.setText(note)
        color = theme.tone_color(self.palette_, tone)
        self.preview_note.setStyleSheet(f"color: {color};")

    def _set_preview_image(self, pil: Image.Image):
        rgba = pil.convert("RGBA")
        qimg = QImage(rgba.tobytes(), rgba.width, rgba.height, QImage.Format.Format_RGBA8888).copy()
        self._preview_pixmap = QPixmap.fromImage(qimg)
        self._fit_preview()

    def _fit_preview(self):
        if self._preview_pixmap is None:
            return
        w = max(120, self.preview.width() - 6)
        self.preview.setPixmap(self._preview_pixmap.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation))
        self.preview.setMinimumHeight(0)

    # ------------------------------------------------------------------ thao tác người dùng
    def _toggle_view_mode(self):
        cards = self.view.mode == MODE_CARDS
        self.view.set_mode(MODE_TEXT if cards else MODE_CARDS)
        self.mode_btn.setText("Dạng thẻ ảnh" if cards else "Dạng chữ")

    def _on_mode_changed(self):
        self.c.detect_image = self.sw_image.isChecked()
        self.c.detect_name = self.sw_name.isChecked()
        self.c.changed()

    def _on_manual_changed(self):
        self.c.manual_names = self.manual.toPlainText()
        self.c.changed()

    def _set_threshold(self, which: str, slider_value: int):
        v = slider_value / 100
        if which == "image":
            self.c.threshold = v
            self.lb_image.setText(f"{v:.0%}")
        else:
            self.c.name_threshold = v
            self.lb_name.setText(f"{v:.0%}")

    def _on_interval_changed(self, value: int):
        self.c.interval_text = str(value)
        self.c.changed()

    def _refresh_license(self):
        info = self.c.license_summary()
        if info["ok"]:
            text = f"✓ Đã kích hoạt cho máy này · Key ID {info['key_id']}" + (f" · kích hoạt {info['activated']}" if info["activated"] else "")
            tone = "ok"
        else:
            text, tone = f"✗ Giấy phép không hợp lệ: {info['reason']}", "fail"
        self.license_state.setText(text)
        self.license_state.setStyleSheet(f"color: {theme.tone_color(self.palette_, tone)};")

    def _toggle_advanced(self, on: bool):
        if on:
            self._refresh_license()  # giấy phép có thể đổi từ lần mở trước
        self.adv_body.setVisible(on)
        self.adv_toggle.setText(("▾" if on else "▸") + "  Nâng cao")

    def _focus_search(self):
        if self._compact:
            self.tabbar.setCurrentIndex(PAGE_CHAMPIONS)
        self.search.setFocus()
        self.search.selectAll()

    def _refresh_preview(self):
        if not self.c.refresh_preview():
            QMessageBox.information(self, "Xem trước", "Chọn vùng Shop trước.")
            self.go_to_step(ctl.STEP_REGION)

    def _upload(self):
        names = [n for n in self.c.selected_names()]
        if len(names) != 1:
            QMessageBox.information(self, "Upload ảnh",
                                    "Chọn đúng 1 tướng (tick) rồi upload ảnh chân dung của tướng đó.")
            return
        path, _ = QFileDialog.getOpenFileName(self, f"Chọn ảnh tướng {names[0]}", "",
                                              "Ảnh (*.png *.jpg *.jpeg *.webp);;Tất cả (*.*)")
        if not path:
            return
        try:
            self.c.upload_template(names[0], path)
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, "Upload ảnh", f"Không dùng được file này: {e}")
            return
        QMessageBox.information(self, "OK", f"Đã lưu ảnh tướng {names[0]}")

    # ------------------------------------------------------------------ overlay chọn vùng / điểm click
    def _open_overlay(self, build):
        """Thu nhỏ cửa sổ, chờ Windows vẽ xong, chụp màn hình rồi mới hiện overlay (nền overlay là ảnh chụp đó)."""
        self.showMinimized()

        def go():
            self._overlay = build()
            self._overlay.cancelled.connect(self._close_overlay)
            self._overlay.showFullScreen()

        QTimer.singleShot(220, go)

    def _close_overlay(self):
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _calibrate_region(self):
        self.c.log("Kéo khung chọn vùng 5 ô shop (Esc để hủy)...")

        def build():
            ov = (self._overlay_factory or overlay_mod.RegionOverlay)() if self._overlay_factory is None \
                else self._overlay_factory("region")
            ov.finished.connect(self._region_done)
            return ov

        self._open_overlay(build)

    def _region_done(self, region):
        self._close_overlay()
        self.c.set_region(region)

    def _calibrate_clicks(self):
        region = self.c.config.get("shop_region")
        if not region:
            QMessageBox.warning(self, "Cảnh báo", "Hãy chọn vùng Shop trước.")
            self.go_to_step(ctl.STEP_REGION)
            return
        self.c.log("Click lần lượt giữa 5 ô shop...")

        def build():
            ov = overlay_mod.ClickOverlay(region, self.c.point_inside_region) if self._overlay_factory is None \
                else self._overlay_factory("clicks")
            ov.finished.connect(self._clicks_done)
            return ov

        self._open_overlay(build)

    def _clicks_done(self, points):
        self._close_overlay()
        self.c.set_click_points(points)

    def _view_on_screen(self):
        """Hiện vùng Shop + 5 điểm click trên màn hình thật. Màn hình chưa có bộ đã xác nhận thì hiện GỢI Ý quy đổi, Enter để dùng."""
        plan = self.c.view_plan()
        if plan is None:
            QMessageBox.information(self, "Xem trên màn hình", "Chưa có vùng Shop để xem — hãy chọn vùng Shop trước.")
            self.go_to_step(ctl.STEP_REGION)
            return
        mon = plan["monitor"]
        title = mon.label() if mon else ""

        def build():
            if self._overlay_factory is None:
                ov = overlay_mod.ViewOverlay(plan["region"], plan["centers"], title, plan["confirm"])
            else:
                ov = self._overlay_factory("view", plan)
            ov.cancelled.connect(self._close_overlay)
            ov.finished.connect(self._view_confirmed)
            return ov

        self._open_overlay(build)

    def _view_confirmed(self, _accepted=True):
        self._close_overlay()
        self.c.accept_suggestion()

    def closeEvent(self, event):
        self.c.close()
        super().closeEvent(event)
