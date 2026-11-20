"""Cửa sổ chính (Qt). Chỉ vẽ và chuyển thao tác của người dùng sang AppController; mọi quyết định nằm ở controller.

Bố cục: thanh điều khiển cố định ở trên (Bắt đầu/Dừng + các chip trạng thái), thân có hai kiểu tự đổi theo bề rộng:
rộng  = hai vùng làm việc cạnh nhau (Tướng | Sẵn sàng + Vùng Shop + Nâng cao),
hẹp   = một cột với thanh tab ở dưới (Tướng / Vùng Shop / Chạy), vùng chạm lớn.
Khung Nhật ký luôn hiện ở dưới cùng."""

from pathlib import Path

from PIL import Image
from shiboken6 import isValid
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
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
from core import diagnostics
from core.config import NUMERIC_LIMITS
from core.single_instance import APP_TITLE
from ui import overlay as overlay_mod
from ui import theme
from ui.champion_view import MODE_CARDS, MODE_TEXT, ChampionView
from ui.widgets import ElidedButton, FlowLayout, Switch

COMPACT_BELOW = 900  # px: hẹp hơn thì dùng bố cục một cột
HYSTERESIS = 40
PAGE_CHAMPIONS, PAGE_SHOP, PAGE_RUN = 0, 1, 2
STEP_TO_PAGE = {ctl.STEP_CHAMPIONS: PAGE_CHAMPIONS, ctl.STEP_REGION: PAGE_SHOP, ctl.STEP_CLICKS: PAGE_SHOP,
                ctl.STEP_SETTINGS: PAGE_RUN, ctl.STEP_OCR: PAGE_RUN}
MAX_LOG_LINES = 500


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


def make_card(title: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setProperty("card", True)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)
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


def filter_button(text: str, tip: str = "") -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setCheckable(True)
    b.setProperty("filter", True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
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
            lay.setContentsMargins(8, 8, 8, 8)
            lay.setSpacing(8)
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
        self.right_lay.setContentsMargins(8, 8, 8, 8)
        self.right_lay.setSpacing(8)
        self.right_scroll.setWidget(self.right_col)

        outer.addWidget(self._build_log())

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(8)
        row = QHBoxLayout()
        title = QLabel("TFT Auto Buy")
        title.setObjectName("title")
        row.addWidget(title)
        row.addStretch(1)
        self.hotkey_label = QLabel("")
        self.hotkey_label.setProperty("muted", True)
        row.addWidget(self.hotkey_label)
        self.start_btn = QPushButton("")
        self.start_btn.setProperty("primary", True)
        self.start_btn.setMinimumHeight(44)
        self.start_btn.setMinimumWidth(190)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setAccessibleName("Bắt đầu hoặc dừng quét")
        self.start_btn.clicked.connect(lambda: self.c.toggle())
        row.addWidget(self.start_btn)
        lay.addLayout(row)

        chips = FlowLayout(hspacing=6, vspacing=6)
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
        lay.addLayout(chips)
        return bar

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
        head = QHBoxLayout()
        heading = QLabel("Chọn tướng cần bắt")
        heading.setObjectName("heading")
        head.addWidget(heading)
        self.count_label = QLabel("")
        self.count_label.setProperty("muted", True)
        head.addWidget(self.count_label)
        head.addStretch(1)
        self.mode_btn = QPushButton("Dạng chữ")
        self.mode_btn.setMinimumWidth(96)
        self.mode_btn.setToolTip("Chuyển giữa thẻ có ảnh và danh sách chữ gọn")
        self.mode_btn.clicked.connect(self._toggle_view_mode)
        head.addWidget(self.mode_btn)
        lay.addLayout(head)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm tướng (Ctrl+F) — gõ tên tiếng Việt hoặc tiếng Anh")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Tìm tướng")
        self.search.textChanged.connect(lambda t: self.c.set_query(t))
        lay.addWidget(self.search)

        filt = FlowLayout(hspacing=6, vspacing=6)
        self.cost_buttons: dict[int, QToolButton] = {}
        for tier in range(1, 6):
            b = filter_button(f"{tier}g", f"Chỉ hiện tướng {tier} gold")
            b.toggled.connect(lambda on, t=tier: self.c.toggle_cost(t, on))
            self.cost_buttons[tier] = b
            filt.addWidget(b)
        self.only_sel_btn = filter_button("Đã chọn", "Chỉ hiện tướng đang tick (kể cả tướng mùa cũ đang ẩn không tính)")
        self.only_sel_btn.toggled.connect(lambda on: self.c.set_only_selected(on))
        self.old_btn = filter_button("Mùa cũ", "Hiện cả tướng các mùa trước")
        self.old_btn.toggled.connect(lambda on: self.c.set_show_old(on))
        filt.addWidget(self.only_sel_btn)
        filt.addWidget(self.old_btn)
        lay.addLayout(filt)

        self.view = ChampionView(self.c, self.palette_)
        self.view.setMinimumHeight(110)
        self.view.toggled.connect(lambda *_: None)
        lay.addWidget(self.view, 1)

        actions = FlowLayout(hspacing=6, vspacing=6)
        for text, fn in (("Chọn tất cả", lambda: self.c.select_all_visible()),
                         ("Bỏ chọn", lambda: self.c.deselect_all_visible()),
                         ("Upload ảnh", self._upload),
                         ("Tải lại", lambda: self.c.reload_champions())):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            actions.addWidget(b)
        lay.addLayout(actions)

        src = QFrame()
        src_lay = QVBoxLayout(src)
        src_lay.setContentsMargins(0, 4, 0, 0)
        src_lay.setSpacing(6)
        label = QLabel("Cách nhận diện tướng trong shop")
        label.setObjectName("heading")
        src_lay.addWidget(label)
        switches = FlowLayout(hspacing=18, vspacing=4)
        src_lay.addLayout(switches)
        self.sw_image = Switch("Bắt theo ảnh")
        self.sw_name = Switch("Bắt theo tên (OCR)")
        for sw in (self.sw_image, self.sw_name):
            switches.addWidget(sw)
        self.sw_image.toggled.connect(self._on_mode_changed)
        self.sw_name.toggled.connect(self._on_mode_changed)
        self.manual = QPlainTextEdit()
        self.manual.setPlaceholderText("Tên gõ tay cho OCR (phẩy hoặc xuống dòng), vd: Aatrox, Yasuo, Jinx")
        self.manual.setFixedHeight(48)
        self.manual.setAccessibleName("Tên tướng gõ tay")
        self.manual.textChanged.connect(self._on_manual_changed)
        src_lay.addWidget(self.manual)
        lay.addWidget(src)
        return card

    def _build_ready_card(self) -> QFrame:
        card, lay = make_card("Sẵn sàng chạy?")
        self.ready_lay = QVBoxLayout()
        self.ready_lay.setSpacing(2)
        lay.addLayout(self.ready_lay)
        self.ready_rows: dict[str, QPushButton] = {}
        return card

    def _build_shop_card(self) -> QFrame:
        card, lay = make_card("Vùng Shop và điểm click")
        hint = QLabel("Làm lần lượt 2 bước. Kéo khung CHỈ quanh hàng 5 thẻ tướng; điểm click đặt giữa ảnh tướng.")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        lay.addWidget(hint)
        self.region_btn = QPushButton("①  Chọn vùng Shop")
        self.region_btn.setProperty("step", True)
        self.region_btn.clicked.connect(lambda: self._calibrate_region())
        self.clicks_btn = QPushButton("②  Đặt 5 điểm click")
        self.clicks_btn.setProperty("step", True)
        self.clicks_btn.clicked.connect(lambda: self._calibrate_clicks())
        lay.addWidget(self.region_btn)
        lay.addWidget(self.clicks_btn)
        self.region_label = QLabel("")
        self.region_label.setProperty("muted", True)
        self.region_label.setWordWrap(True)
        lay.addWidget(self.region_label)
        self.preview = QLabel("Chưa có ảnh — chọn vùng Shop để xem trước")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(110)
        self.preview.setWordWrap(True)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.preview)
        self.preview_note = QLabel("")
        self.preview_note.setWordWrap(True)
        self.preview_note.setProperty("muted", True)
        lay.addWidget(self.preview_note)
        self.refresh_btn = QPushButton("Làm mới ảnh (chụp lại màn hình)")
        self.refresh_btn.clicked.connect(self._refresh_preview)
        lay.addWidget(self.refresh_btn)
        self._preview_pixmap: QPixmap | None = None
        return card

    def _build_advanced_card(self) -> QFrame:
        card, lay = make_card()
        self.adv_toggle = QToolButton()
        self.adv_toggle.setText("▸  Nâng cao")
        self.adv_toggle.setProperty("section", True)
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.adv_toggle.toggled.connect(self._toggle_advanced)
        lay.addWidget(self.adv_toggle)
        self.adv_body = QWidget()
        b = QVBoxLayout(self.adv_body)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(8)
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
        mrow = QHBoxLayout()  # nút Sao chép ở hàng tiêu đề để ô mã (40 ký tự) được trọn bề rộng, không bị cắt ở cửa sổ hẹp
        mrow.addWidget(QLabel("Mã máy (gửi cho người bán khi cần Key mới)"), 1)
        self.machine_copy = QToolButton()
        self.machine_copy.setText("Sao chép")
        self.machine_copy.setProperty("filter", True)
        self.machine_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.machine_edit.text()))
        mrow.addWidget(self.machine_copy)
        b.addLayout(mrow)
        self.machine_edit = QLineEdit()
        self.machine_edit.setReadOnly(True)
        self.machine_edit.setAccessibleName("Mã máy")
        b.addWidget(self.machine_edit)
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
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(8, 4, 8, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        label = QLabel("Nhật ký")
        label.setObjectName("heading")
        head.addWidget(label)
        head.addStretch(1)
        copy = QToolButton()
        copy.setText("Sao chép")
        copy.setProperty("filter", True)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.log_view.toPlainText()))
        head.addWidget(copy)
        self.diag_btn = QToolButton()
        self.diag_btn.setText("Xuất chẩn đoán")
        self.diag_btn.setProperty("filter", True)
        self.diag_btn.setToolTip("Gom phiên bản, kết quả tự kiểm tra, cấu hình (đã lược tọa độ) và log thành một file zip ở Desktop để gửi khi cần hỗ trợ")
        self.diag_btn.clicked.connect(self.c.export_diagnostics)
        head.addWidget(self.diag_btn)
        lay.addLayout(head)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(MAX_LOG_LINES)
        self.log_view.setAccessibleName("Nhật ký")
        self.log_view.setFixedHeight(88)
        lay.addWidget(self.log_view)
        self.log_wrap = wrap
        return wrap

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
        self.log_view.setFixedHeight(72 if self._compact else 88)

    def _detach(self, *widgets):
        for w in widgets:
            w.setParent(None)

    def _apply_layout(self, compact: bool):
        if compact == self._compact:
            return
        self._compact = compact
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
            self.splitter.setStretchFactor(0, 3)
            self.splitter.setStretchFactor(1, 2)
            self.splitter.setSizes([620, 440])
            self.body.setCurrentWidget(self.splitter)

    def go_to_step(self, step: str):
        """Dẫn người dùng tới nơi sửa điều kiện còn thiếu: đổi tab (hẹp) hoặc nháy khung tương ứng (rộng)."""
        if self._compact:
            self.tabbar.setCurrentIndex(STEP_TO_PAGE.get(step, PAGE_RUN))
        target = {ctl.STEP_CHAMPIONS: self.champ_panel, ctl.STEP_REGION: self.shop_card, ctl.STEP_CLICKS: self.shop_card,
                  ctl.STEP_SETTINGS: self.adv_card, ctl.STEP_OCR: self.ready_card}.get(step, self.ready_card)
        if step == ctl.STEP_SETTINGS and not self.adv_toggle.isChecked():
            self.adv_toggle.setChecked(True)
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
        for w, v in ((self.sw_image, c.detect_image), (self.sw_name, c.detect_name), (self.old_btn, c.show_old)):
            w.blockSignals(True)
            w.setChecked(v)
            w.blockSignals(False)
        self.manual.blockSignals(True)
        self.manual.setPlainText(c.manual_names)
        self.manual.blockSignals(False)
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
        total = len(self.c.visible())
        self.count_label.setText(f"{len(items)}/{total} tướng" if total else "chưa tải")
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
        done_region = bool(self.c.config.get("shop_region"))
        self.region_btn.setText(("✓  " if done_region else "①  ") + "Chọn vùng Shop" + (" (chọn lại)" if done_region else ""))
        clicks_ok = next((r.ok for r in reqs if r.key == "clicks"), False)
        self.clicks_btn.setText(("✓  " if clicks_ok else "②  ") + "Đặt 5 điểm click" + (" (đặt lại)" if clicks_ok else ""))
        self.region_label.setText(self.c.region_text())

    def _step_of(self, key: str) -> str:
        return getattr(self, "_step_of_map", {}).get(key, ctl.STEP_CHAMPIONS)

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

    def _ev_log(self, text):
        self.log_view.appendPlainText(text)

    def _ev_status(self, text):
        self.status_label.setText(text)

    def _ev_dialog(self, level, title, text):
        box = {"info": QMessageBox.information, "warning": QMessageBox.warning, "error": QMessageBox.critical}[level]
        box(self, title, text)

    def _ev_champions_changed(self):
        self._refresh_list()
        self._refresh_readiness()

    def _ev_filter_changed(self):
        self.old_btn.blockSignals(True)
        self.old_btn.setChecked(self.c.show_old)
        self.old_btn.blockSignals(False)
        self._refresh_list()

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

    def _ev_blocked(self, requirement):
        self.status_label.setText(f"Chưa chạy được: {requirement.text}")
        self._refresh_readiness()
        self.go_to_step(requirement.step)

    def _ev_ocr(self, text, tone):
        self.chip_ocr.setText(text)
        set_prop(self.chip_ocr, "tone", tone)

    def _ev_diagnostics_busy(self, busy):
        self.diag_btn.setEnabled(not busy)
        self.diag_btn.setText("Đang tạo..." if busy else "Xuất chẩn đoán")

    def _ev_diagnostics_saved(self, path):
        diagnostics.reveal_in_explorer(Path(path))

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
        self.machine_edit.setText(info["machine_code"])

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

    def closeEvent(self, event):
        self.c.close()
        super().closeEvent(event)
