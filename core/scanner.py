"""
Quét shop TFT liên tục: nhận diện tướng (ảnh/OCR) và tự click mua.
Tối ưu: chụp 1 lần cả shop, template xử lý sẵn, OCR song song 5 ô.
"""

import ctypes
import threading
import time
import traceback
from collections import Counter, deque
from concurrent.futures import wait
from pathlib import Path

import cv2
import mss
import numpy as np

from core import license as license_check
from core.buyer import buy_slot_async, premove_async
from core.cards import find_card_columns
from core.portraits import PortraitLibrary, zone_geometry
from core.portraits import canon as portrait_canon
from core.capture import open_dxgi
from core.champions import load_template_image, prepare_shop_template
from core.config import game_process_set, resolve_template_path
from core.diagnostics import collect_environment
from core.game_window import describe_foreground, is_game_foreground, suspect_game_process
from core.ocr_pool import OcrPool
from core.name_matcher import (
    DEFAULT_NAME_THRESHOLD,
    NameMatcher,
    drain_ocr_errors,
    read_name_from_slot,
    record_ocr_error,
)

try:
    _kernel32 = ctypes.windll.kernel32
    # ABOVE_NORMAL đủ để phản hồi nhanh mà không tranh CPU với thread game (HIGHEST làm giảm FPS).
    THREAD_PRIORITY_ABOVE_NORMAL = 1
except Exception:
    _kernel32 = None

MIN_SLEEP_MS = 1.0  # mỗi vòng luôn nhường CPU tối thiểu từng này, kể cả khi đặt tốc độ quét 0 ms


def _boost_thread_priority():
    """Nâng nhẹ ưu tiên thread quét shop để phản hồi nhanh hơn trên Windows."""
    if _kernel32 is None:
        return
    try:
        handle = _kernel32.GetCurrentThread()
        _kernel32.SetThreadPriority(handle, THREAD_PRIORITY_ABOVE_NORMAL)
    except Exception:
        pass


def _extract_portrait(frame: np.ndarray) -> np.ndarray:
    """Cắt vùng mặt tướng (phần trên ô shop) để so khớp ảnh."""
    h, w = frame.shape[:2]
    ph = max(24, int(h * 0.52))
    pw = max(24, int(w * 0.58))
    x0 = (w - pw) // 2
    y0 = max(0, int(h * 0.04))
    return frame[y0 : y0 + ph, x0 : x0 + pw]


SLOT_COUNT = 5
MAX_CONSECUTIVE_ERRORS = 20  # quá số vòng lỗi liên tiếp này thì dừng hẳn và báo UI
OCR_EMPTY_SLOTS = 4  # từng này ô trở lên đọc ra rỗng liên tục là bất thường (shop luôn có chữ ở mọi ô còn thẻ)
OCR_EMPTY_WARN_S = 30.0  # ...kéo dài từng này giây khi game ở foreground thì cảnh báo 1 lần mỗi đợt
MAX_REPORTED_OCR_ERRORS = 20
OCR_WORKERS = 5  # = số ô shop: cả 5 ô OCR song song trong 1 đợt (3 luồng phải chạy 2 đợt: 16,8 ms so với 10,5 ms)
OCR_BATCH_TIMEOUT_S = 2.0  # hạn chờ cho CẢ đợt OCR (bình thường ~10-20 ms). Trước đây: 5 lần chờ tuần tự 8 giây = 40 giây
OCR_POLL_S = 0.05  # trong lúc chờ OCR cứ mỗi chừng này lại kiểm tra bấm DỪNG
SETTLE_S = 0.6  # ô vừa đổi thẻ: OCR lại ô đó trong khoảng này (chữ tên có thể hiện dần khi thẻ còn đang chạy hiệu ứng)
CHAIN_GAP_S = 0.08  # ô đổi liên tục cách nhau dưới mức này là CÙNG một lần thẻ hiện (hiệu ứng), không phải roll mới
IDLE_OCR_S = 0.5  # shop đứng yên: vẫn OCR cả 5 ô mỗi chừng này như lưới an toàn (không bao giờ bỏ sót vĩnh viễn)
BLOCKED_OCR_S = 0.25  # đang bị chặn click vì game không ở foreground: OCR cả 5 ô mỗi chừng này (không phải mỗi 50 ms: dồn OCR làm bị kẹt)
BURST_S = 0.5  # sau khi người dùng bấm phím roll: quét dày trong khoảng này
SKIP_LOG_EVERY_S = 1.0  # cùng một lý do bỏ click chỉ ghi Nhật ký tối đa mỗi chừng này (kèm số lần bị nén)
FOREGROUND_LOG_EVERY_S = 10.0  # đang bị chặn vì game không ở foreground: nhắc lại cửa sổ đang ở trước mỗi chừng này
LEARN_MIN_CORR = 0.97  # chỉ học ảnh thẻ khi khung lúc đọc tên và khung lúc click gần như y hệt (thẻ không còn chạy hiệu ứng)
SHADOW_MIN_SCORE = 0.90  # OCR kiểm tra lại sau khi mua bằng ảnh: đọc ra một tên KHÁC với độ giống từ mức này mới coi là ảnh tự học bị nhầm
RELAXED_OCR_S = 2.0  # mọi mục tiêu đã có ảnh thẻ học được: OCR chỉ còn là lưới an toàn, cả 5 ô mỗi chừng này...
RELAXED_SETTLED_S = 0.4  # ...và CHỈ khi shop đã đứng yên chừng này (đang roll liên tục thì kết quả OCR luôn cũ, chỉ tốn CPU của game)
SHADOW_TRUST = 3  # mẫu ảnh của một tướng đã được OCR xác nhận đúng chừng này lần sau khi mua thì thôi đọc lại (đỡ tốn OCR mỗi lần mua)
STALL_LOG_MS = 400  # một vòng quét lâu hơn mức này thì ghi Nhật ký vòng đó mất thời gian ở đâu (chụp / mua / còn lại)
STALL_LOG_MAX = 20
CARD_DETECT_EVERY_S = 0.5  # chưa tìm được vị trí 5 thẻ trong khung: thử lại mỗi chừng này (shop đang trống/hiệu ứng thì chưa đủ 5 thẻ)
FOREGROUND_SETTLE_S = 0.35  # game vừa lên trước (Alt-Tab, hiệu ứng toàn màn hình): chờ chừng này rồi mới click. Click ngay lúc cửa
# sổ còn đang kích hoạt thường bị game bỏ qua (Nhật ký: "đã click" mà thẻ vẫn còn)
MAX_LATENCY_SAMPLES = 2000
GRAB_FAIL_LIMIT_S = 5.0  # chụp màn hình lỗi liên tục quá lâu (vd: UAC/khóa máy kéo dài) thì dừng hẳn

# --- Chống mua nhầm + chẩn đoán ---
RECHECK_BELOW_SCORE = 0.98  # khớp TÊN dưới mức này (khớp mờ / mảnh chữ) phải được OCR lại trên khung xác nhận mới click
RECHECK_TIMEOUT_S = 0.6  # đọc lại quá hạn → không xác minh được → không click
CLICK_VERIFY_S = 0.6  # sau khi click: chờ tối đa từng này để thấy thẻ biến mất (đã mua)
CLICK_FAIL_WARN = 3  # từng này lần click liên tiếp không thấy thẻ biến mất → báo lỗi (không dừng quét)
SHOP_LOG_STABLE_S = 0.30  # chữ 5 ô shop đứng yên chừng này mới ghi 1 dòng "Shop: ..." (bỏ qua lúc thẻ còn chạy hiệu ứng)
SHOP_LOG_MAX = 400  # tối đa số dòng "Shop: ..." mỗi lần chạy (tránh tràn Nhật ký khi roll cả buổi)
NEAR_MISS_MIN = 0.55  # chữ OCR giống một mục tiêu từ mức này nhưng không mua → ghi "gần khớp" để chỉnh ngưỡng
NEAR_MISS_MAX_LINES = 100
BLACK_FRAME_WARN_S = 5.0  # khung vùng Shop đen liên tục chừng này khi game ở foreground → cảnh báo
BLACK_FRAME_LOG_EVERY_S = 60.0

_SIGNATURE_SIZE = (40, 20)


class _OcrResult(tuple):
    """Kết quả OCR 1 ô: hai phần tử (mục tiêu khớp hoặc None, True nếu không đọc ra chữ) như tuple cũ, kèm `.text` là chữ đã đọc
    để ghi Nhật ký. Là tuple nên code/test cũ vẫn giải nén và so sánh như trước."""

    text: str

    def __new__(cls, match, empty, text: str):
        obj = super().__new__(cls, (match, empty))
        obj.text = text
        return obj


class LoopStats:
    """
    Đo chu kỳ THỰC của vòng quét: khoảng cách giữa hai lần bắt đầu liên tiếp (gồm cả phần nghỉ, thời gian chụp
    màn hình và các đợt OCR chậm). Chu kỳ thực luôn >= thời gian chụp màn hình (~7 ms trên máy thử), nên đặt
    'chu kỳ tối thiểu' nhỏ hơn mức đó không làm quét nhanh hơn.
    """

    def __init__(self, window_s: float = 1.0, max_samples: int = 5000):
        self.window_s = window_s
        self._all = deque(maxlen=max_samples)  # chu kỳ (ms) của các vòng gần nhất, để tính p95
        self.count = 0
        self.total_ms = 0.0
        self.max_ms = 0.0
        self._win: list[float] = []
        self._win_start: float | None = None

    def add(self, period_ms: float, now: float) -> None:
        self.count += 1
        self.total_ms += period_ms
        self.max_ms = max(self.max_ms, period_ms)
        self._all.append(period_ms)
        if self._win_start is None:
            self._win_start = now
        self._win.append(period_ms)

    def take_window(self, now: float) -> dict | None:
        """Mỗi window_s giây trả {avg_ms, max_ms, count} của cửa sổ vừa qua rồi bắt đầu cửa sổ mới; chưa đến hạn → None."""
        if self._win_start is None or now - self._win_start < self.window_s or not self._win:
            return None
        snap = {"avg_ms": sum(self._win) / len(self._win), "max_ms": max(self._win), "count": len(self._win)}
        self._win, self._win_start = [], now
        return snap

    def summary(self) -> dict | None:
        """Tổng kết từ lúc bắt đầu: {count, avg_ms, p95_ms, max_ms}; None nếu chưa có vòng nào."""
        if not self.count:
            return None
        ordered = sorted(self._all)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        return {"count": self.count, "avg_ms": self.total_ms / self.count, "p95_ms": p95, "max_ms": self.max_ms}


def format_loop_speed(avg_ms: float, max_ms: float | None = None) -> str:
    """Chữ hiển thị dưới ô 'Chu kỳ quét tối thiểu', vd '9.0 ms/vòng (≈ 111 vòng/giây), chậm nhất 25 ms'."""
    text = f"{avg_ms:.1f} ms/vòng (≈ {1000 / max(avg_ms, 0.001):.0f} vòng/giây)"
    return text + (f", chậm nhất {max_ms:.0f} ms" if max_ms is not None else "")


MIN_LOOPS_FOR_SUMMARY = 20  # ít vòng hơn mức này thì tổng kết không có ý nghĩa


def find_points_outside_region(region: dict, centers: list) -> list[int]:
    """Số thứ tự (1-based) các điểm click nằm ngoài vùng shop."""
    left, top = region["left"], region["top"]
    right, bottom = left + region["width"], top + region["height"]
    return [
        i + 1
        for i, (x, y) in enumerate(centers)
        if not (left <= x < right and top <= y < bottom)
    ]


def _describe_error(exc: BaseException) -> str:
    """'TênLỗi: nội dung (file:dòng)' — đủ để biết lỗi ở đâu mà không cần mở traceback."""
    frames = traceback.extract_tb(exc.__traceback__)
    where = f" ({Path(frames[-1].filename).name}:{frames[-1].lineno})" if frames else ""
    return f"{type(exc).__name__}: {exc}{where}"


def _slot_signature(slot_frame: np.ndarray) -> np.ndarray:
    """Chữ ký nhỏ (xám, đã trừ trung bình) của 1 ô shop — dùng để biết ô có còn là thẻ cũ không."""
    gray = cv2.cvtColor(slot_frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, _SIGNATURE_SIZE, interpolation=cv2.INTER_AREA).astype(np.float32)
    return small - small.mean()


def _card_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Tương quan Pearson của hai chữ ký (1.0 = giống hệt). Hai ô phẳng (trống) giống nhau → 1.0; một phẳng một không → 0.0."""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-3 or nb < 1e-3:
        return 1.0 if (na < 1e-3 and nb < 1e-3) else 0.0
    return float(np.sum(a * b) / (na * nb))


def _same_card(a: np.ndarray, b: np.ndarray, min_corr: float) -> bool:
    """Hai chữ ký là cùng 1 thẻ nếu tương quan Pearson >= min_corr (không bị lệch khi thẻ sáng lên lúc hover)."""
    return _card_correlation(a, b) >= min_corr


class ShopScanner:
    """Engine quét shop: chụp màn hình → nhận diện → click mua tướng."""

    def __init__(
        self,
        shop_region: dict,
        slot_centers: list[tuple[int, int]],
        templates: dict[str, np.ndarray],
        target_names: list[str] | None = None,
        threshold: float = 0.72,
        name_threshold: float = DEFAULT_NAME_THRESHOLD,
        detect_by_image: bool = True,
        detect_by_name: bool = True,
        scan_interval_ms: int = 3,
        name_scan_interval_ms: int = 50,
        buy_cooldown_ms: int = 90,
        buy_delay_ms: int = 0,
        card_same_corr: float = 0.80,
        require_game_foreground: bool = True,
        game_process_names: list[str] | None = None,
        all_names: list[str] | None = None,
        target_aliases: dict[str, list[str]] | None = None,
        on_match=None,
        on_status=None,
        on_error=None,
        on_log=None,
        on_ocr_health=None,
        on_stats=None,
        capture_backend: str = "mss",
        verbose_log: bool = True,
        learn_portraits: bool = False,
        portraits_dir=None,
        async_ocr: bool = False,
    ):
        self.shop_region = shop_region
        self.capture_backend = capture_backend  # "mss" (mặc định, luôn dùng được) hoặc "auto" (thử DXGI trước, tự quay về mss)
        self.slot_centers = slot_centers
        self.templates = templates
        self.target_names = target_names or list(templates.keys())
        self.threshold = threshold
        self.name_threshold = name_threshold
        # Toàn bộ tên tướng trong game: để OCR đọc "Gragas" không bị nhận nhầm thành mục tiêu "Graves".
        self._name_matcher = NameMatcher(self.target_names, all_names, name_threshold, target_aliases)
        self.detect_by_image = detect_by_image and bool(templates)
        self.detect_by_name = detect_by_name
        # Ảnh thẻ tự học (core/portraits.py): lần đầu đọc tên bằng OCR thì nhớ ảnh thẻ, các lần sau nhận ra bằng ảnh trong vài ms.
        # Cần OCR để học nên chỉ bật khi bắt theo tên.
        self._portraits: PortraitLibrary | None = PortraitLibrary(portraits_dir, background=True) if learn_portraits and detect_by_name else None
        self._target_set = frozenset(self.target_names)
        self.async_ocr = async_ocr and detect_by_name  # OCR chạy ở luồng riêng: vòng quét không phải chờ OCR xong
        self.scan_interval_ms = max(0, scan_interval_ms)
        self.name_scan_interval_ms = name_scan_interval_ms
        self.buy_cooldown_ms = buy_cooldown_ms
        self.buy_delay_ms = buy_delay_ms
        self.card_same_corr = card_same_corr
        self.require_game_foreground = require_game_foreground
        self.game_process_names = game_process_set(game_process_names)  # tên đã biết + tên trong config
        self._click_blocked = False  # đang bị chặn click vì game không ở foreground (để báo status 1 lần)
        self._foreground_logged_at: float | None = None  # lần cuối ghi vào Nhật ký "cửa sổ nào đang ở trước" khi bị chặn
        self._front_since: float | None = None  # lúc game lên trước sau lần bị chặn gần nhất (None = đang không ở trước / chưa từng bị chặn)
        self._last_blocked_ocr = 0.0
        self._dxgi_gap_logged = False  # đã ghi Nhật ký "DXGI tạm mất khung" trong lần chạy này
        self.verbose_log = verbose_log  # ghi thêm dòng "Shop: ..." mỗi lần roll và "gần khớp" (tắt: chỉ còn lỗi, mua, tổng kết)
        self.stats: Counter = Counter()  # đếm sự kiện của lần chạy này, ghi 1 dòng tổng kết khi dừng
        self._ocr_ms_total = 0.0
        self._slot_text = [""] * SLOT_COUNT  # chữ OCR đọc được gần nhất của từng ô
        self._slot_hit: list[tuple[str, float] | None] = [None] * SLOT_COUNT  # mục tiêu khớp của chữ đó
        self._shop_logged: tuple | None = None  # nội dung dòng "Shop: ..." đã ghi gần nhất (không ghi lặp)
        self._shop_dirty_at: float | None = None  # lúc chữ 5 ô đổi gần nhất mà chưa được ghi
        self._shop_lines = 0
        self._near_seen: dict[int, str] = {}  # ô → chữ "gần khớp" đã ghi (không ghi lặp)
        self._pending_verify: list[dict] = []  # lần click đang chờ thấy thẻ biến mất
        self._click_fail_streak = 0
        self._last_health_check = 0.0
        self._black_since: float | None = None
        self._black_logged_at: float | None = None
        self.on_match = on_match
        self.on_status = on_status
        self.on_error = on_error  # on_error(msg: str, fatal: bool) — fatal=True: scanner đã tự dừng
        self.on_log = on_log  # on_log(msg: str): thông tin thường (không phải lỗi), vd OCR đọc lại được
        self.on_ocr_health = on_ocr_health  # on_ocr_health(ok: bool): OCR đang đọc được chữ hay không
        self.on_stats = on_stats  # on_stats({avg_ms, max_ms, count}): chu kỳ thực của vòng quét, mỗi giây 1 lần

        self._running = False
        self._thread: threading.Thread | None = None
        self._sct = mss.MSS()  # mss.mss() đã deprecated từ mss 10.2.0
        self._last_grab_error = ""
        self._dxgi = None  # nguồn chụp DXGI (mở và dùng trong luồng quét)
        self._dxgi_thread: int | None = None
        self._shop_monitor = self._build_shop_monitor()
        self._slot_w = 0
        self._card_top_ratio = 0.18
        self._card_cols: list[tuple[int, int]] | None = None  # cột [x0, x1) của 5 thẻ tìm được trong khung (None = chia đều vùng)
        self._card_detect_at = 0.0
        self._geometry: tuple[int, int] | None = None  # kích thước ô lúc so ảnh đã học gần nhất (để biết mục tiêu nào đã có mẫu)
        self._grab_ms = 0.0  # vòng quét hiện tại: thời gian chụp màn hình / thời gian trong _buy_batch (chẩn đoán vòng chậm)
        self._buy_ms = 0.0
        self._capture_ms: deque = deque(maxlen=5000)
        self._stall_logs = 0
        self._shadow_ok: Counter = Counter()  # tên → số lần OCR xác nhận đúng sau khi mua bằng ảnh (từ SHADOW_TRUST thì tin ảnh)
        self._gray_templates: list[tuple[str, np.ndarray]] = []
        self._portrait_size: tuple[int, int] = (48, 48)
        self._last_name_scan = 0.0
        self._locked: dict[int, np.ndarray] = {}  # ô đã click mua → chữ ký thẻ lúc click
        self._now = time.monotonic  # tách ra để test điều khiển được thời gian
        self._perf = time.perf_counter  # đồng hồ độ phân giải cao cho nhịp vòng quét
        self.loop_stats = LoopStats()
        self._ocr_empty_since: float | None = None
        self._ocr_warned = False
        self._reported_ocr_errors: set[str] = set()
        self._ocr_pool = OcrPool(OCR_WORKERS) if detect_by_name else None  # luồng daemon: OCR treo không chặn thoát app
        # OCR ở luồng riêng (async_ocr): vòng quét đẩy yêu cầu rồi quay lại quét tiếp, kết quả được nhận ở các vòng sau
        self._ocr_thread: threading.Thread | None = None
        self._ocr_wake = threading.Event()
        self._ocr_lock = threading.Lock()
        self._ocr_request: tuple | None = None  # (các ô cần đọc, 5 ô của khung lúc yêu cầu)
        self._ocr_busy = False  # đã đẩy yêu cầu và chưa có kết quả
        self._ocr_wanted: set[int] = set()  # ô cần OCR mà luồng OCR đang bận: gộp lại, đọc ở khung MỚI NHẤT khi rảnh
        self._ocr_done: deque = deque()  # kết quả đã xong chờ vòng quét nhận: (kết quả, số ô rỗng, 5 ô đã đọc)
        self._ocr_stuck: list = []  # các lần OCR của đợt quá hạn mà luồng vẫn chưa trả về
        self._ocr_stuck_warned = False
        # Theo dõi thay đổi từng ô (quét theo thay đổi, đo độ trễ "thẻ hiện → click")
        self._slot_sigs: list[np.ndarray | None] = [None] * SLOT_COUNT
        self._first_seen = [0.0] * SLOT_COUNT  # lúc thẻ hiện hiện tại được thấy lần đầu (đầu chuỗi đổi liên tục)
        self._last_change = [0.0] * SLOT_COUNT
        self._settle_until = [0.0] * SLOT_COUNT
        self._burst_until = 0.0
        self._prev_frame: np.ndarray | None = None
        self._last_had_cands = False  # lượt trước có ô trúng ảnh (kể cả đã mua) → lượt này phải xử lý lại, không coi là đứng yên
        self._last_idle_ocr = 0.0
        self._skip_state: dict[str, list] = {}  # lý do bỏ click → [lần ghi cuối, số lần bị nén]
        self.latencies_ms: deque = deque(maxlen=MAX_LATENCY_SAMPLES)  # "thẻ hiện → click" của các lần mua thành công
        self._init_fast_templates()

    def _build_shop_monitor(self) -> dict | None:
        """Chuyển shop_region thành dict cho thư viện chụp màn hình mss."""
        if not self.shop_region:
            return None
        r = self.shop_region
        return {"left": r["left"], "top": r["top"], "width": r["width"], "height": r["height"]}

    def _init_slot_geometry(self):
        """Mỗi ô rộng 1/5 vùng shop (thẻ TFT cách đều). Điểm click chỉ dùng để click, không dùng để cắt ô."""
        if self.shop_region:
            self._slot_w = max(24, self.shop_region["width"] // SLOT_COUNT)

    def _slice_slots(self, shop: np.ndarray) -> list[np.ndarray]:
        """Cắt 5 ô theo vị trí thẻ tìm được trong khung (xem _detect_cards); chưa tìm được thì chia đều vùng shop thành 5 cột.
        Bỏ thanh cấp/vàng phía trên, giữ đủ tên tướng ở dưới."""
        h, w = shop.shape[:2]
        y0 = min(int(h * self._card_top_ratio), h - 24)
        cards = shop[y0:, :]
        cols = self._card_cols
        if cols is not None and cols[-1][1] <= w:
            return [cards[:, a:b] for a, b in cols]
        return [cards[:, i * w // SLOT_COUNT : (i + 1) * w // SLOT_COUNT] for i in range(SLOT_COUNT)]

    def _detect_cards(self, shop: np.ndarray):
        """Tìm vị trí thật của 5 thẻ trong khung (core/cards.py) để vùng Shop kéo thừa/lệch không làm đọc cụt tên. Thử lại mỗi
        CARD_DETECT_EVERY_S tới khi thành công, rồi giữ nguyên (thẻ không đổi chỗ trong ván). Điểm click chỉ dùng để chọn đúng 5 thẻ."""
        now = self._now()
        if now - self._card_detect_at < CARD_DETECT_EVERY_S:
            return
        self._card_detect_at = now
        left = self.shop_region["left"] if self.shop_region else 0
        try:
            cols = find_card_columns(shop, [x - left for x, _y in self.slot_centers])
        except Exception:
            return  # không tìm được thì cứ chia đều như trước, không làm hỏng vòng quét
        if cols is None:
            return
        self._card_cols = cols
        # Cách cắt ô vừa đổi: chữ ký/khóa/khung cũ thuộc cách cắt cũ nên bỏ đi (không so sánh lẫn hai cách cắt).
        self._slot_sigs = [None] * SLOT_COUNT
        self._locked.clear()
        self._pending_verify.clear()
        self._prev_frame = None
        if self.on_log:
            width = shop.shape[1]
            span = cols[-1][1] - cols[0][0]
            extra = (
                f" Vùng Shop bạn chọn rộng {width} px nhưng 5 thẻ chỉ chiếm {span} px: tool đã tự cắt theo từng thẻ thật nên "
                "không bị cụt tên (cảnh báo 'vùng Shop KHÔNG khớp' nếu có ở trên không còn áp dụng)."
                if width - span > 0.1 * width else ""
            )
            self._safe_callback(
                self.on_log,
                "Đã nhận ra vị trí 5 thẻ trong vùng Shop (cột x: " + ", ".join(f"{a}–{b}" for a, b in cols) + ")." + extra,
            )

    def _init_fast_templates(self):
        """Pre-process ảnh mẫu tướng sang grayscale cùng kích thước — so khớp nhanh hơn."""
        self._init_slot_geometry()
        if not self.shop_region or not self.templates:
            return

        sh = int(self.shop_region["height"] * (1 - self._card_top_ratio))
        sw = self._slot_w
        portrait = _extract_portrait(np.zeros((max(sh, 24), max(sw, 24), 3), dtype=np.uint8))
        self._portrait_size = (portrait.shape[1], portrait.shape[0])

        self._gray_templates = []
        for name, template in self.templates.items():
            if name not in self.target_names:
                continue
            roi = _extract_portrait(template)
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, self._portrait_size, interpolation=cv2.INTER_AREA)
            self._gray_templates.append((name, gray))

    def start(self):
        """Bắt đầu quét shop trong thread nền."""
        if self._running:
            return
        try:
            license_check.require_active()
        except license_check.LicenseError as e:
            if self.on_status:
                self.on_status(f"Cần Key xác thực: {e}")
            return
        if not self._shop_monitor or not self.target_names or len(self.slot_centers) != SLOT_COUNT:
            if self.on_status:
                self.on_status("Chưa cấu hình shop hoặc chưa chọn tướng")
            return
        if find_points_outside_region(self.shop_region, self.slot_centers):
            if self.on_status:
                self.on_status("Có điểm click nằm ngoài vùng Shop")
            return
        if not self.detect_by_image and not self.detect_by_name:
            if self.on_status:
                self.on_status("Bật 'Bắt theo ảnh' hoặc 'Bắt theo tên'")
            return

        drain_ocr_errors()  # lỗi OCR của lần chạy/kiểm tra trước không còn liên quan
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ShopScanner")
        self._thread.start()

        if self.on_status:
            modes = []
            if self.detect_by_image:
                modes.append("ảnh")
            if self.detect_by_name:
                modes.append("tên")
            self.on_status(f"Đang quét shop ({'+'.join(modes)})...")

    def stop(self):
        """Dừng vòng quét shop (không chờ thread; thread tự thoát và dọn tài nguyên ở vòng gần nhất)."""
        self._running = False
        self._ocr_wake.set()  # luồng OCR riêng thoát ngay thay vì chờ hết lượt chờ
        if self._thread is None:  # chưa từng chạy → không có thread nào sẽ dọn hộ
            self.close()
        if self.on_status:
            self.on_status("Đã dừng")

    def close(self):
        """Giải phóng pool OCR và handle chụp màn hình (mss). Gọi nhiều lần cũng an toàn."""
        if self._portraits is not None:
            self._portraits.flush(1.0)  # ảnh thẻ học được ghi ở luồng nền: chờ ghi nốt trước khi thoát
        pool, self._ocr_pool = self._ocr_pool, None
        if pool:
            pool.shutdown()  # không chờ: luồng OCR đang kẹt (nếu có) là daemon nên không chặn thoát
        dxgi = self._dxgi
        if dxgi is not None and threading.get_ident() == self._dxgi_thread:  # COM/DXGI chỉ giải phóng ở luồng đã tạo
            self._dxgi = None
            dxgi.close()
        sct, self._sct = self._sct, None
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass

    def notify_roll(self):
        """Người dùng vừa bấm phím roll: trong BURST_S giây OCR lại ô đang ổn định mà không chờ chu kỳ, và vòng quét không nghỉ
        thêm. An toàn gọi từ luồng bất kỳ."""
        self._burst_until = time.perf_counter() + BURST_S
        self.stats["roll_key"] += 1
        if self.stats["roll_key"] == 1 and self.on_log:
            self._safe_callback(self.on_log, "Nhận phím roll lần đầu: tool thấy được phím bấm trong game.")

    @property
    def is_running(self) -> bool:
        """Tool có đang quét shop không."""
        return self._running

    def _grab_shop(self) -> np.ndarray | None:
        """Chụp toàn bộ vùng shop 1 lần (5 ô trong 1 ảnh)."""
        try:
            dxgi = self._dxgi
            if dxgi is not None:
                try:
                    frame = dxgi.grab()
                    if getattr(dxgi, "none_frames", 0) and not self._dxgi_gap_logged and self.on_log:
                        self._dxgi_gap_logged = True
                        self._safe_callback(
                            self.on_log,
                            "DXGI tạm mất khung (thường do game đổi chế độ hiển thị) — dùng mss trong lúc chờ DXGI phục hồi.",
                        )
                    return frame
                except Exception as e:  # khung DXGI không đáng tin / driver lỗi → về mss, không dừng quét
                    self._drop_dxgi(e)
            shot = self._sct.grab(self._shop_monitor)  # _sct = None sau close() → AttributeError → trả None
            return np.asarray(shot, dtype=np.uint8)[:, :, :3]
        except Exception as e:
            self._last_grab_error = _describe_error(e)
            return None

    def _mss_frame(self) -> np.ndarray:
        """Khung của vùng shop bằng mss (dùng để đối chiếu với DXGI)."""
        return np.asarray(self._sct.grab(self._shop_monitor), dtype=np.uint8)[:, :, :3]

    def _open_capture(self):
        """Đầu luồng quét: thử DXGI nếu được bật; ghi vào Nhật ký đang dùng cách chụp nào (và vì sao không dùng DXGI)."""
        if self.capture_backend != "auto" or not self.shop_region:
            return
        try:
            source, why = open_dxgi(self.shop_region, self._mss_frame)
        except Exception as e:
            source, why = None, f"{type(e).__name__}: {str(e)[:60]}"
        if source is not None:
            self._dxgi = source
            self._dxgi_thread = threading.get_ident()
        if self.on_log:
            self._safe_callback(
                self.on_log,
                "Chụp màn hình: DXGI (~1 ms mỗi khung, nhanh hơn mss ~10 ms)." if source is not None
                else f"Chụp màn hình: mss — không dùng được DXGI: {why}.",
            )

    def _drop_dxgi(self, exc: BaseException):
        dxgi, self._dxgi = self._dxgi, None
        if dxgi is not None:
            dxgi.close()
        if self.on_log:
            self._safe_callback(self.on_log, f"Chụp DXGI gặp vấn đề ({exc}) — chuyển sang mss.")

    def _release_changed_locks(self, slots: list[np.ndarray], sigs: list[np.ndarray] | None = None):
        """Mở khóa ô đã mua khi nội dung ô đổi (ô trống sau khi mua, hoặc shop vừa roll)."""
        for idx, locked_sig in list(self._locked.items()):
            sig = sigs[idx] if sigs is not None else _slot_signature(slots[idx])
            if not _same_card(locked_sig, sig, self.card_same_corr):
                del self._locked[idx]

    def _track_changes(self, sigs: list[np.ndarray], t_frame: float) -> set[int]:
        """Ô nào vừa đổi thẻ so với khung trước? Cập nhật lúc thẻ hiện (đo độ trễ) và cửa sổ 'đang ổn định' (để OCR lại)."""
        changed = set()
        for i, sig in enumerate(sigs):
            prev = self._slot_sigs[i]
            if prev is not None and _same_card(prev, sig, self.card_same_corr):
                continue
            if prev is None or t_frame - self._last_change[i] > CHAIN_GAP_S:
                self._first_seen[i] = t_frame  # lần thẻ hiện mới (không phải khung kế tiếp của cùng hiệu ứng)
            self._slot_sigs[i] = sig
            self._last_change[i] = t_frame
            self._settle_until[i] = t_frame + SETTLE_S
            changed.add(i)
        return changed

    def _skip(self, key: str, msg: str):
        """Ghi 1 dòng 'vì sao bỏ click' vào Nhật ký; cùng lý do thì nén lại (tối đa 1 dòng mỗi SKIP_LOG_EVERY_S)."""
        if not self.on_log:
            return
        now = time.monotonic()
        last, suppressed = self._skip_state.get(key, (0.0, 0))
        if last and now - last < SKIP_LOG_EVERY_S:
            self._skip_state[key] = [last, suppressed + 1]
            return
        self._skip_state[key] = [now, 0]
        extra = f" (+{suppressed} lần nữa trong giây trước)" if suppressed else ""
        self._safe_callback(self.on_log, msg + extra)

    def _log_foreground_block(self):
        """Ghi Nhật ký vì sao không click: cửa sổ nào đang ở trước và tool cần process nào. Lần đầu bị chặn ghi ngay, sau đó chỉ
        nhắc lại mỗi FOREGROUND_LOG_EVERY_S. Nhờ dòng này mới phân biệt được 'đang ở app khác' với 'tool không nhận ra game'."""
        if not self.on_log:
            return
        now = self._now()
        if self._foreground_logged_at is not None and now - self._foreground_logged_at < FOREGROUND_LOG_EVERY_S:
            return
        first_of_episode = self._foreground_logged_at is None
        self._foreground_logged_at = now
        try:
            front = describe_foreground()
        except Exception as e:
            front = f"không đọc được ({type(e).__name__})"
        self._safe_callback(
            self.on_log,
            f"Không click: game không ở foreground. Cửa sổ đang ở trước: {front}. "
            f"Tool nhận game là: {', '.join(sorted(self.game_process_names))} hoặc lớp cửa sổ RiotWindowClass.",
        )
        try:
            suspect = suspect_game_process(self.game_process_names)
        except Exception:
            suspect = None
        if suspect:
            self._safe_callback(
                self.on_log,
                f"Gợi ý: '{suspect}' có vẻ là game nhưng chưa nằm trong danh sách tool nhận. Nếu đây là cửa sổ chơi game, hãy thêm "
                f'"{suspect}" vào mục "game_process_names" trong data/config.json (rồi mở lại tool).',
            )
        if first_of_episode:
            self._log_environment()

    def _log_environment(self):
        """Ghi Nhật ký quyền Admin của tool/game, cửa sổ game, vùng Shop có nằm trong cửa sổ game không (core/diagnostics.py)."""
        if not self.on_log:
            return
        try:
            lines = collect_environment(
                self.game_process_names, self.shop_region, None if self._card_cols else self.slot_centers
            )
        except Exception as e:
            lines = [f"Chẩn đoán môi trường không đọc được: {type(e).__name__}: {str(e)[:80]}"]
        for line in lines:
            self._safe_callback(self.on_log, line)

    def _buy_batch(self, cands: list[tuple], cooldown: dict):
        t_buy = time.perf_counter()
        try:
            self._buy_batch_inner(cands, cooldown)
        finally:
            self._buy_ms += (time.perf_counter() - t_buy) * 1000

    def _buy_batch_inner(self, cands: list[tuple], cooldown: dict):
        """
        Mua một LOẠT ô đã nhận diện trong cùng một lượt: cands = [(ô, tên, điểm, cách, khung ô đã phân tích)].
        Chỉ click ô VẪN là thẻ đã nhận diện: kết quả nhận diện (nhất là OCR) tính trên khung cũ, nên chụp lại MỘT lần cho cả
        loạt rồi so từng ô trước khi click. Ô đã click mua bị khóa đến khi nội dung ô đổi (tránh click lặp: ảnh + OCR cùng
        ô, hết vàng/đầy ghế). Các điểm click được gửi liên tiếp cho luồng click (không chờ nhau). Mỗi lần bỏ click vì lý
        do bất thường đều được ghi 1 dòng vào Nhật ký.
        """
        if not self._running or not cands:
            return
        now = time.perf_counter()
        live = [c for c in cands if now - cooldown.get((c[0], c[1]), 0) >= self.buy_cooldown_ms / 1000]
        if not live:  # vừa click ô này rồi (ảnh và OCR cùng thấy một thẻ): bình thường, không phải bỏ sót
            return

        if self.buy_delay_ms > 0:
            time.sleep(self.buy_delay_ms / 1000)

        if self.require_game_foreground:
            if not self._foreground_settled():
                in_front = self._front_since is not None  # game đã lên trước nhưng chưa đủ FOREGROUND_SETTLE_S: chờ, không báo lỗi
                if not self._click_blocked:
                    self._click_blocked = True
                    if self.on_status and not in_front:
                        self.on_status("Game không ở foreground — tạm không click")
                self.stats["blocked"] += 1
                if not in_front:
                    self._log_foreground_block()
                return
            if self._click_blocked:
                self._click_blocked = False
                self._foreground_logged_at = None
                if self.on_status:
                    self.on_status("Đang quét shop...")

        t_dec = time.perf_counter()
        premove_async(self.slot_centers[live[0][0]])  # con trỏ bay tới ô trong lúc chụp xác nhận; click sau đó không chờ di chuột nữa
        try:
            fresh = self._grab_shop()
            if fresh is None:
                self._skip("grab", "Bỏ click: không chụp lại được shop để xác nhận.")
                return
            fresh_slots = self._slice_slots(fresh)
        except Exception:
            return  # không xác minh được thì không click
        t_ver = time.perf_counter()

        to_click = []
        corrs: dict[int, float] = {}
        for slot, name, score, method, analyzed in live:
            try:
                fresh_sig = _slot_signature(fresh_slots[slot])
                corr = _card_correlation(_slot_signature(analyzed), fresh_sig)
            except Exception:
                continue
            if corr < self.card_same_corr:
                # Thẻ nhận bằng ẢNH chỉ cần còn là ĐÚNG tướng đó (so ảnh thẻ trên khung mới): thẻ còn đang chạy hiệu ứng (phóng/mờ dần)
                # làm hai khung cách nhau ~30 ms khác nhau dù vẫn là cùng một thẻ (Nhật ký thật: 'độ giống 0.66/0.71/0.76 < 0.80' bỏ oan).
                # Shop đã roll sang tướng khác thì ảnh không còn khớp và vẫn bị bỏ như cũ.
                if method == "ảnh" and self._still_that_champion(name, fresh_slots[slot]):
                    self.stats["identity_verified"] += 1
                else:
                    # shop đã đổi từ lúc nhận diện → bỏ, vòng sau quét lại
                    self._skip(
                        f"changed:{slot}",
                        f"Bỏ click {name} ô {slot + 1}: thẻ đã đổi giữa lúc nhận diện và xác nhận "
                        f"(độ giống {corr:.2f} < {self.card_same_corr:.2f}).",
                    )
                    continue
            locked_sig = self._locked.get(slot)
            if locked_sig is not None:
                if _same_card(locked_sig, fresh_sig, self.card_same_corr):
                    continue  # ô này đã click mua rồi, thẻ chưa đổi
                del self._locked[slot]
            if method == "tên" and score < RECHECK_BELOW_SCORE and not self._recheck_name(slot, name, fresh_slots[slot]):
                continue
            corrs[slot] = corr
            to_click.append((slot, name, score, method, fresh_sig))

        if not self._running or not to_click:  # bị dừng trong lúc kiểm tra → không click
            return
        t_click = time.perf_counter()
        for slot, name, _score, _method, fresh_sig in to_click:
            cooldown[(slot, name)] = t_click
            buy_slot_async(self.slot_centers[slot])
            self._locked[slot] = fresh_sig
            self.stats["clicks"] += 1
            front_s = (t_click - self._front_since) if self._front_since is not None else None
            self._pending_verify.append({"slot": slot, "name": name, "sig": fresh_sig, "t": t_click, "front_s": front_s})

        for slot, name, score, method, _sig in to_click:
            if self.on_match:
                self.on_match(name, slot + 1, score, method)
            self._log_evidence(slot, name, score, method, corrs.get(slot))
            self._record_latency(name, slot, t_dec, t_ver, t_click)
            if self._portraits is not None:  # sau khi đã click: học/kiểm tra ảnh không làm chậm lần mua này
                if method == "tên":
                    self._maybe_learn(name, score, corrs.get(slot), fresh_slots[slot])
                else:
                    self._shadow_check(slot, name, fresh_slots[slot])

    def _recheck_name(self, slot: int, name: str, fresh_slot: np.ndarray) -> bool:
        """Chống mua nhầm: khớp tên KHÔNG chính xác (khớp mờ / mảnh chữ) phải được OCR lại trên khung chụp xác nhận và ra
        đúng mục tiêu đó mới click. Đọc lại ra tên khác, ra rỗng hay quá hạn đều không click (vòng sau quét lại)."""
        pool = self._ocr_pool
        if pool is None:
            return True
        try:
            outcome = pool.submit(self._ocr_slot, fresh_slot).result(timeout=RECHECK_TIMEOUT_S)
        except Exception as e:  # kể cả quá hạn: không xác minh được thì không click
            self.stats["recheck_fail"] += 1
            self._skip(
                f"recheck:{slot}",
                f"Bỏ click {name} ô {slot + 1}: không đọc lại được tên để xác nhận ({type(e).__name__}).",
            )
            return False
        match = outcome[0]
        if match and match[0] == name:
            return True
        self.stats["recheck_reject"] += 1
        self._skip(
            f"recheck:{slot}",
            f"Bỏ click {name} ô {slot + 1}: đọc lại lần 2 ra {getattr(outcome, 'text', '?')!r}, không còn khớp {name} "
            "(khớp mờ nên phải đọc đúng 2 lần mới mua — tránh mua nhầm).",
        )
        return False

    def _log_evidence(self, slot: int, name: str, score: float, method: str, corr: float | None):
        """Bằng chứng của MỖI lần mua: OCR đọc ra chữ gì, khớp mức nào, có tên nào khác gần giống không. Mua nhầm tướng thì đọc
        dòng này là biết do OCR đọc sai chữ, ngưỡng khớp quá thấp, hay thẻ đổi sau khi nhận diện."""
        if not self.on_log:
            return
        if method == "tên":
            text = self._slot_text[slot]
            detail = f"OCR đọc {text!r} → {name} (tên {score:.0%})"
            if score < RECHECK_BELOW_SCORE and text:
                near = ", ".join(f"{n} {s:.0%}" for s, n, _t in self._name_matcher.explain(text) if n != name)
                detail += f", đã đọc lại lần 2 vẫn khớp; tên khác gần giống: {near or 'không có'}"
        else:
            detail = f"so ảnh mẫu → {name} (ảnh {score:.0%})"
        corr_text = f"; độ giống thẻ lúc xác nhận {corr:.2f}" if corr is not None else ""
        self._safe_callback(self.on_log, f"   ↳ bằng chứng ô {slot + 1}: {detail}{corr_text}.")

    def _check_click_results(self, slots: list[np.ndarray], now: float):
        """Mỗi lần click phải thấy thẻ ở ô đó biến mất/đổi trong CLICK_VERIFY_S. Không thấy = click có thể không tới game."""
        if not self._pending_verify:
            return
        waiting = []
        for p in self._pending_verify:
            slot, name = p["slot"], p["name"]
            waited = now - p["t"]
            try:
                same = _same_card(p["sig"], _slot_signature(slots[slot]), self.card_same_corr)
            except Exception:
                continue
            if not same:
                self.stats["confirmed"] += 1
                self._click_fail_streak = 0
                if self.on_log:
                    self._safe_callback(
                        self.on_log, f"   ✓ Xác nhận ô {slot + 1}: thẻ {name} đã biến mất/đổi sau {waited * 1000:.0f} ms (đã mua)."
                    )
            elif waited >= CLICK_VERIFY_S:
                self._click_unconfirmed(slot, name, waited, p.get("front_s"))
            else:
                waiting.append(p)
        self._pending_verify = waiting

    def _click_unconfirmed(self, slot: int, name: str, waited: float, front_s: float | None = None):
        self.stats["unconfirmed"] += 1
        self._click_fail_streak += 1
        if self.on_log:
            after = f" Click được gửi {front_s:.2f} giây sau khi game lên trước." if front_s is not None else ""
            self._safe_callback(
                self.on_log,
                f"Cảnh báo: đã click ô {slot + 1} ({name}) nhưng thẻ vẫn còn sau {waited:.1f} giây.{after} Có thể: hết vàng / đầy ghế; "
                "game chạy quyền Admin còn tool thì không (Windows chặn click) → chạy tool bằng Administrator; hoặc điểm click lệch.",
            )
        if self._click_fail_streak == CLICK_FAIL_WARN:
            self._report_error(
                f"{CLICK_FAIL_WARN} lần click liên tiếp không có tác dụng (thẻ vẫn còn). Xem các dòng 'Chẩn đoán' bên dưới; "
                "nếu đủ vàng và còn ghế thì gần như chắc chắn là lệch quyền Admin hoặc lệch điểm click.",
                fatal=False,
            )
            self._log_environment()

    def _record_latency(self, name: str, slot: int, t_dec: float, t_ver: float, t_click: float):
        """Độ trễ từ lúc thẻ hiện (thấy lần đầu) tới lúc gửi lệnh click, ghi vào Nhật ký để chỉnh theo số thật."""
        seen = self._first_seen[slot]
        if seen <= 0:
            return  # chưa theo dõi được lúc thẻ hiện (gọi lẻ ngoài vòng quét)
        total = (t_click - seen) * 1000
        self.latencies_ms.append(total)
        if self.on_log:
            self._safe_callback(
                self.on_log,
                f"   ↳ {name} ô {slot + 1}: {total:.0f} ms từ lúc thẻ hiện (nhận diện {(t_dec - seen) * 1000:.0f} + "
                f"xác nhận {(t_ver - t_dec) * 1000:.0f} + xử lý {(t_click - t_ver) * 1000:.0f}).",
            )

    def _match_image_fast(self, slot_frame: np.ndarray) -> tuple[str, float] | None:
        """So khớp portrait trong ô shop với ảnh mẫu tướng đã chọn."""
        if not self.detect_by_image or not self._gray_templates:
            return None

        roi = _extract_portrait(slot_frame)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        if gray.shape[::-1] != self._portrait_size:
            gray = cv2.resize(gray, self._portrait_size, interpolation=cv2.INTER_AREA)

        best_name = None
        best_score = 0.0
        for name, tpl in self._gray_templates:
            score = float(cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)[0, 0])
            if score > best_score:
                best_score = score
                best_name = name

        if best_name and best_score >= self.threshold:
            return best_name, best_score
        return None

    def _match_learned(self, slot: int, slot_frame: np.ndarray) -> tuple[str, float] | None:
        """Nhận ra tướng đã chọn bằng ảnh thẻ đã học (vài trăm micro giây, không chờ OCR). Chỉ dùng khi đã tìm được vị trí thật của
        5 thẻ (ảnh chuẩn hóa mới đồng đều giữa các ô). Ô đã click mua (thẻ chưa đổi) thì bỏ qua."""
        lib = self._portraits
        if not lib or self._card_cols is None or slot in self._locked:
            return None
        try:
            self._geometry = geometry = zone_geometry(slot_frame)
            hit = lib.match(portrait_canon(slot_frame), geometry, self._target_set)
        except Exception:
            return None
        if hit:
            self.stats["learned_hits"] += 1
        return hit

    def _still_that_champion(self, name: str, slot_frame: np.ndarray) -> bool:
        """Thẻ ở ô này (khung mới) vẫn khớp ảnh đã học của `name`?"""
        lib = self._portraits
        if not lib or self._card_cols is None:
            return False
        try:
            return lib.match(portrait_canon(slot_frame), zone_geometry(slot_frame), frozenset({name})) is not None
        except Exception:
            return False

    def _maybe_learn(self, name: str, score: float, corr: float | None, slot_frame: np.ndarray):
        """Vừa mua `name` nhờ OCR đọc đúng tên: ghi nhớ ảnh thẻ để lần sau nhận ra bằng ảnh. Chỉ học khi đọc tên chắc chắn (khớp
        đúng/trọn tên) và thẻ đứng yên giữa lúc đọc và lúc click. Nếu ảnh này đang khớp mẫu của một tướng KHÁC thì mẫu đó sai: xóa."""
        lib = self._portraits
        if lib is None or self._card_cols is None or score < RECHECK_BELOW_SCORE or corr is None or corr < LEARN_MIN_CORR:
            return
        try:
            geometry, window = zone_geometry(slot_frame), portrait_canon(slot_frame)
            other = lib.match(window, geometry)
            if other and other[0] != name:
                dropped = lib.forget(other[0])
                self.stats["learned_conflicts"] += 1
                self._safe_callback(
                    self.on_log,
                    f"Cảnh báo: thẻ OCR đọc là {name} lại giống ảnh đã học của {other[0]} ({other[1]:.0%}). Đã xóa {dropped} ảnh tự học "
                    f"của {other[0]} để không mua nhầm.",
                )
                return
            if lib.learn(name, window, geometry):
                self.stats["learned"] += 1
                if self.on_log:
                    self._safe_callback(
                        self.on_log,
                        f"Đã học ảnh thẻ {name} (mẫu {lib.count(name, geometry)}): lần sau tool nhận ra {name} bằng ảnh trong vài ms, "
                        "không chờ OCR.",
                    )
        except Exception:
            pass  # học ảnh chỉ là tăng tốc: lỗi gì cũng không được làm hỏng việc mua

    def _shadow_check(self, slot: int, name: str, slot_frame: np.ndarray):
        """Vừa mua `name` bằng ảnh (không có OCR xác nhận): đọc tên thẻ đó bằng OCR ở luồng nền (không làm chậm click). Nếu OCR đọc
        ra một tên KHÁC chắc chắn thì ảnh tự học của `name` bị nhầm: xóa để không nhầm lần nữa. Đọc rỗng/méo thì bỏ qua."""
        pool = self._ocr_pool
        if pool is None or self._portraits is None or self._shadow_ok[name] >= SHADOW_TRUST:
            return  # mẫu ảnh này đã được OCR xác nhận đủ lần: tin ảnh, đừng tốn OCR mỗi lần mua
        try:
            pool.submit(self._ocr_slot, slot_frame.copy()).add_done_callback(lambda fut: self._shadow_result(slot, name, fut))
        except Exception:
            pass

    def _shadow_result(self, slot: int, name: str, fut):
        try:
            outcome = fut.result()
            text = getattr(outcome, "text", "").strip()
            if not text:
                return
            match = outcome[0]
            if match and match[0] == name:
                self.stats["learned_verified"] += 1
                self._shadow_ok[name] += 1
                return
            top = self._name_matcher.explain(text, 1)
            other = match[0] if match else (top[0][1] if top and top[0][0] >= SHADOW_MIN_SCORE and top[0][1] != name else None)
            if other is None or other == name:
                return
            dropped = self._portraits.forget(name) if self._portraits else 0
            self._shadow_ok[name] = 0
            self.stats["learned_conflicts"] += 1
            self._safe_callback(
                self.on_log,
                f"Cảnh báo: vừa mua {name} ô {slot + 1} bằng ảnh nhưng OCR đọc thẻ đó là {other}. Đã xóa {dropped} ảnh tự học của {name} "
                "để không mua nhầm nữa.",
            )
        except Exception:
            pass

    def _ocr_slot(self, slot_frame: np.ndarray) -> tuple[tuple[str, float] | None, bool]:
        """OCR 1 ô: (mục tiêu khớp hoặc None, True nếu OCR không đọc ra chữ nào)."""
        text = read_name_from_slot(slot_frame)
        return _OcrResult(self._name_matcher.match(text), not text.strip(), text)

    def _scan_names_parallel(
        self, slots: list[np.ndarray], only: list[int] | None = None
    ) -> tuple[list[tuple[int, str, float] | None], int | None]:
        """
        OCR các ô `only` (mặc định cả 5) song song. Trả (kết quả theo chỉ số ô, số ô OCR không đọc ra chữ nào).
        Số ô rỗng là None khi lượt này BỎ QUA OCR vì luồng OCR của đợt trước còn kẹt, hoặc chỉ OCR một phần số ô
        (không tính là 'đọc rỗng': việc theo dõi sức khỏe OCR chỉ có nghĩa khi OCR đủ 5 ô).
        """
        indices = list(range(len(slots))) if only is None else list(only)
        frames = [slots[i] for i in indices]
        results: list[tuple[int, str, float] | None] = [None] * len(slots)

        pool = self._ocr_pool  # stop()/close() có thể đặt về None từ thread khác → đọc 1 lần
        if pool:
            if not self._ocr_workers_free():
                return results, None
            t_ocr = self._perf()
            outcomes = self._ocr_batch(pool, frames)
            self._ocr_ms_total += (self._perf() - t_ocr) * 1000
            self.stats["ocr_batches"] += 1
        else:
            outcomes = [self._ocr_slot(frame) for frame in frames]

        empties = 0
        for i, outcome in zip(indices, outcomes):
            match, empty = outcome
            empties += empty
            text = getattr(outcome, "text", None)
            if text is not None:
                self._note_ocr_text(i, text, match)
            if match:
                results[i] = (i, match[0], match[1])
        return results, (empties if len(indices) == len(slots) else None)

    def _ocr_relaxed(self) -> bool:
        """Mọi mục tiêu đã có ảnh thẻ học được cho kích thước ô hiện tại: nhánh ảnh lo việc nhận ra, OCR không cần chạy liên tục (đang
        làm game và chính tool chậm đi: Nhật ký thật ghi OCR ~300 ms mỗi đợt và hay bị kẹt). Thiếu mẫu của bất kỳ mục tiêu nào thì
        vẫn OCR như thường để học nó."""
        lib, geometry = self._portraits, self._geometry
        if lib is None or geometry is None or self._card_cols is None or not self._target_set:
            return False
        return all(lib.count(name, geometry) > 0 for name in self._target_set)

    def _corr_to_current(self, slot: int, frame: np.ndarray) -> float:
        """Độ giống giữa ảnh đã đưa cho OCR và thẻ hiện ở ô đó (khung quét mới nhất); 1.0 nếu chưa có gì để so."""
        current = self._slot_sigs[slot]
        if current is None:
            return 1.0
        try:
            return _card_correlation(_slot_signature(frame), current)
        except Exception:
            return 0.0

    def _learn_from_ocr(self, results: list, read_slots: list[np.ndarray]):
        """OCR vừa đọc đúng tên một mục tiêu (kể cả khi không kịp mua): nếu thẻ vẫn đứng yên thì học ảnh thẻ đó. Nhờ vậy mục tiêu
        mới (hoặc một dáng khác của thẻ) có ảnh ngay lần thấy đầu tiên, không phải đợi một lần mua thành công."""
        if self._portraits is None:
            return
        for r in results:
            if r:
                self._maybe_learn(r[1], r[2], self._corr_to_current(r[0], read_slots[r[0]]), read_slots[r[0]])

    def _ocr_due_slots(self, now: float, changed: set[int]) -> list[int]:
        """
        Ô nào cần OCR lượt này. Ô VỪA ĐỔI thẻ được OCR ngay (không chờ chu kỳ); ô còn đang 'ổn định' (SETTLE_S sau khi đổi,
        chữ tên có thể hiện dần) được OCR lại theo chu kỳ (không chờ chu kỳ khi vừa bấm roll); cả 5 ô được OCR khi đang bị
        chặn click vì game không ở foreground (để mua ngay khi quay lại) và mỗi IDLE_OCR_S như lưới an toàn khi shop đứng yên.
        """
        if self._ocr_relaxed():
            if now - self._last_idle_ocr < RELAXED_OCR_S or now - max(self._last_change) < RELAXED_SETTLED_S:
                return []  # đang roll (thẻ vừa đổi) thì không OCR: nhánh ảnh lo, và kết quả OCR sẽ cũ trước khi có
            self._last_idle_ocr = now
            return list(range(SLOT_COUNT))
        due = set(changed)
        burst = now < self._burst_until  # vừa bấm roll: không chờ chu kỳ OCR (nhưng KHÔNG ép OCR cả 5 ô: OCR ~13 ms chặn nhánh ảnh)
        interval_ok = burst or self.name_scan_interval_ms <= 0 or now - self._last_name_scan >= self.name_scan_interval_ms / 1000
        if interval_ok:
            due.update(i for i in range(SLOT_COUNT) if now < self._settle_until[i])
            if self._click_blocked and now - self._last_blocked_ocr >= BLOCKED_OCR_S:
                self._last_blocked_ocr = now
                due.update(range(SLOT_COUNT))
            if now - self._last_idle_ocr >= IDLE_OCR_S:
                self._last_idle_ocr = now
                due.update(range(SLOT_COUNT))
        return sorted(due)

    def _scan_names_async(self, slots: list[np.ndarray], changed: set[int], cooldown: dict):
        """Nhánh tên khi OCR chạy ở luồng riêng: nhận kết quả đã xong, rồi nếu luồng OCR đang rảnh thì đẩy các ô cần đọc (ở khung
        MỚI NHẤT) và quay lại quét ngay. Vòng quét vì thế không bao giờ chờ OCR: nhánh ảnh được kiểm tra mỗi vài ms thay vì mỗi
        lần OCR xong (~100 ms khi game đang chạy)."""
        self._collect_ocr_results(cooldown)
        now = time.perf_counter()
        due = self._ocr_due_slots(now, changed)
        if due:
            self._last_name_scan = now
            self._ocr_wanted.update(due)
        if self._ocr_wanted and not self._ocr_busy:
            wanted = sorted(self._ocr_wanted)
            self._ocr_wanted.clear()
            self._ocr_busy = True
            with self._ocr_lock:
                self._ocr_request = (wanted, slots)
            self._ocr_wake.set()

    def _collect_ocr_results(self, cooldown: dict):
        """Xử lý mọi kết quả OCR đã xong (theo thứ tự): theo dõi sức khỏe OCR, bỏ kết quả của thẻ đã đổi, mua các ô khớp."""
        while self._ocr_done:
            results, empty_slots, read_slots = self._ocr_done.popleft()
            if empty_slots is not None:
                self._track_ocr_health(empty_slots)
            self._report_new_ocr_errors()
            self._learn_from_ocr(results, read_slots)
            cands = []
            for r in results:
                if not r:
                    continue
                if self._card_changed_since(r[0], read_slots[r[0]]):
                    self.stats["stale_ocr"] += 1  # roll nhanh: thẻ đã đổi từ lúc đọc, click sẽ vô ích (không ghi Nhật ký)
                    continue
                cands.append((r[0], r[1], r[2], "tên", read_slots[r[0]]))
            if cands:
                self._buy_batch(cands, cooldown)

    def _card_changed_since(self, slot: int, read_frame: np.ndarray) -> bool:
        """Thẻ hiện ở ô `slot` (khung quét mới nhất) có khác ảnh đã đưa cho OCR không."""
        current = self._slot_sigs[slot]
        if current is None:
            return False
        try:
            return not _same_card(_slot_signature(read_frame), current, self.card_same_corr)
        except Exception:
            return False

    def _ocr_dispatch_loop(self):
        """Luồng OCR riêng: nhận yêu cầu mới nhất, đọc (song song 5 ô như bản đồng bộ), để kết quả cho vòng quét."""
        while self._running:
            self._ocr_wake.wait(0.25)
            self._ocr_wake.clear()
            with self._ocr_lock:
                request, self._ocr_request = self._ocr_request, None
            if request is None:
                continue
            indices, read_slots = request
            try:
                results, empty_slots = self._scan_names_parallel(read_slots, indices)
                self._ocr_done.append((results, empty_slots, read_slots))
            except Exception as e:  # lỗi lạ: bỏ đợt này, vòng quét tự yêu cầu lại
                record_ocr_error(f"Luồng OCR: {type(e).__name__}: {str(e)[:100]}")
            finally:
                self._ocr_busy = False

    def _ocr_workers_free(self) -> bool:
        """
        False nếu đợt OCR trước còn luồng kẹt: không đẩy thêm việc vào pool đang kẹt (sẽ xếp hàng chồng chất).
        Khi các luồng kẹt trả về thì tự dùng lại OCR và báo 1 lần.
        """
        if not self._ocr_stuck:
            return True
        if any(not f.done() for f in self._ocr_stuck):
            return False
        self._ocr_stuck = []
        if self._ocr_stuck_warned:
            self._ocr_stuck_warned = False
            if self.on_log:
                self._safe_callback(self.on_log, "OCR đã hồi phục sau khi bị kẹt.")
            if self.on_ocr_health:
                self._safe_callback(self.on_ocr_health, True)
        return True

    def _ocr_batch(self, pool, slots: list[np.ndarray]) -> list[tuple[tuple[str, float] | None, bool]]:
        """
        Chạy OCR cho cả đợt với MỘT hạn chung (OCR_BATCH_TIMEOUT_S) thay vì chờ từng ô tuần tự, và kiểm tra bấm DỪNG
        mỗi OCR_POLL_S nên dừng có hiệu lực ngay. Ô nào chưa xong khi hết hạn thì coi là 'rỗng' và đánh dấu kẹt.
        """
        futures = [pool.submit(self._ocr_slot, frame) for frame in slots]
        deadline = self._perf() + OCR_BATCH_TIMEOUT_S
        pending = set(futures)
        while pending and self._running:
            remaining = deadline - self._perf()
            if remaining <= 0:
                break
            _, pending = wait(pending, timeout=min(OCR_POLL_S, remaining))

        outcomes = []
        for fut in futures:
            if fut.done():
                try:
                    outcomes.append(fut.result())
                except Exception as e:
                    record_ocr_error(f"OCR ô shop thất bại: {type(e).__name__}: {str(e)[:80]}")
                    outcomes.append((None, True))
            else:
                outcomes.append((None, True))

        stuck = [f for f in futures if not f.done()]
        if stuck and self._running:  # đang dừng thì không phải 'kẹt': luồng chỉ đang bị bỏ lại
            self._ocr_stuck = stuck
            self._ocr_stuck_warned = True
            self._report_error(
                f"OCR bị kẹt: {len(stuck)}/{len(slots)} ô chưa xong sau {OCR_BATCH_TIMEOUT_S:.0f} giây. Tạm bỏ qua OCR "
                "cho tới khi hết kẹt (bắt theo ảnh, nếu đang bật, vẫn chạy).",
                fatal=False,
            )
            if self.on_ocr_health:
                self._safe_callback(self.on_ocr_health, False)
        return outcomes

    def _game_in_front(self) -> bool:
        """Game đang ở foreground? (Không bắt buộc foreground thì coi như luôn đúng.)"""
        return (not self.require_game_foreground) or is_game_foreground(self.game_process_names)

    def _foreground_settled(self) -> bool:
        """Được phép click chưa: game ở trước, và nếu vừa bị chặn thì đã ở trước đủ FOREGROUND_SETTLE_S (cửa sổ kích hoạt xong).
        Game ở trước liên tục từ đầu thì không phải chờ gì."""
        if not self._game_in_front():
            self._front_since = None
            return False
        if not self._click_blocked:
            return True
        now = time.perf_counter()
        if self._front_since is None:
            self._front_since = now
        return now - self._front_since >= FOREGROUND_SETTLE_S

    def _track_ocr_health(self, empty_slots: int):
        """
        Theo dõi OCR lúc chạy: từ OCR_EMPTY_SLOTS ô trở lên đọc rỗng liên tục OCR_EMPTY_WARN_S giây khi game ở
        foreground → cảnh báo 1 lần mỗi đợt (vùng Shop lệch hoặc OCR hỏng giữa chừng); đọc lại được thì báo 1 lần.
        Game không ở foreground thì tạm ngừng đếm (người dùng đang ở cửa sổ khác).
        """
        if not self._game_in_front():
            self._ocr_empty_since = None
            return
        if empty_slots < OCR_EMPTY_SLOTS:
            self._ocr_empty_since = None
            if self._ocr_warned:
                self._ocr_warned = False
                if self.on_log:
                    self.on_log("OCR đã đọc lại được chữ trong shop.")
                if self.on_ocr_health:
                    self.on_ocr_health(True)
            return

        now = self._now()
        if self._ocr_empty_since is None:
            self._ocr_empty_since = now
        elif not self._ocr_warned and now - self._ocr_empty_since >= OCR_EMPTY_WARN_S:
            self._ocr_warned = True
            self._report_error(
                f"OCR không đọc được chữ ở {empty_slots}/{SLOT_COUNT} ô shop suốt {OCR_EMPTY_WARN_S:.0f} giây khi game đang "
                "ở foreground. Kiểm tra vùng Shop (bấm 'Làm mới ảnh': dải tên ở đáy thẻ phải nằm trong ảnh và không bị "
                "lệch) và dòng 'OCR:' ghi lúc bắt đầu. Nếu shop đang bị che (carousel, chọn lõi) thì bỏ qua cảnh báo này.",
                fatal=False,
            )
            if self.on_ocr_health:
                self.on_ocr_health(False)

    def _report_new_ocr_errors(self):
        """Báo lỗi OCR (ngoại lệ, quá hạn...) — mỗi nội dung khác nhau chỉ báo 1 lần, kèm số lần gặp."""
        for msg, count in drain_ocr_errors().items():
            if msg in self._reported_ocr_errors or len(self._reported_ocr_errors) >= MAX_REPORTED_OCR_ERRORS:
                continue
            self._reported_ocr_errors.add(msg)
            self._report_error(f"Lỗi OCR: {msg}" + (f" (x{count})" if count > 1 else ""), fatal=False)

    def _report_error(self, msg: str, fatal: bool):
        """Báo lỗi cho UI; fatal=True thì dừng scanner trước (UI sẽ đưa nút về 'BẮT ĐẦU')."""
        if fatal:
            self.stop()
        if self.on_error:
            self.on_error(msg, fatal)

    @staticmethod
    def _safe_callback(fn, *args):
        """Gọi callback của giao diện từ thread quét; giao diện đã đóng (root.after lỗi) không được làm hỏng vòng quét."""
        try:
            fn(*args)
        except Exception:
            pass

    def _log_loop_summary(self):
        """Khi dừng: ghi 1 dòng tổng kết chu kỳ thực (dùng để debug 'quét có đủ nhanh không')."""
        s = self.loop_stats.summary()
        if s and s["count"] >= MIN_LOOPS_FOR_SUMMARY and self.on_log:
            self._safe_callback(
                self.on_log,
                f"Quét: {s['count']} vòng, trung bình {s['avg_ms']:.1f} ms/vòng, p95 {s['p95_ms']:.1f} ms, "
                f"chậm nhất {s['max_ms']:.0f} ms.",
            )
        if self._capture_ms and self.on_log:
            cm = sorted(self._capture_ms)
            self._safe_callback(
                self.on_log,
                f"Chụp màn hình ({'DXGI' if self._dxgi is not None else 'mss'}): {len(cm)} lần, trung bình {sum(cm) / len(cm):.1f} ms, "
                f"p95 {cm[min(len(cm) - 1, int(len(cm) * 0.95))]:.1f} ms, chậm nhất {cm[-1]:.0f} ms.",
            )
        gaps = getattr(self._dxgi, "none_frames", 0)
        if gaps and self.on_log:
            self._safe_callback(self.on_log, f"DXGI tạm mất khung {gaps} lần trong lúc chạy (đã dùng mss thay, không bỏ lỡ khung nào).")
        if self.on_log and any(self.stats.values()):
            st = self.stats
            ocr = f", OCR {st['ocr_batches']} đợt (TB {self._ocr_ms_total / st['ocr_batches']:.0f} ms)" if st["ocr_batches"] else ""
            self._safe_callback(
                self.on_log,
                f"Thống kê: click {st['clicks']} (thấy thẻ biến mất {st['confirmed']}, không thấy {st['unconfirmed']}); bỏ vì đọc lại "
                f"lần 2 không khớp {st['recheck_reject']}, không đọc lại được {st['recheck_fail']}; lượt bị chặn vì game không "
                f"ở foreground {st['blocked']}; phím roll nhận {st['roll_key']} lần{ocr}.",
            )
        if self.on_log and self._portraits is not None and any(
            self.stats[k] for k in ("learned", "learned_hits", "learned_verified", "learned_conflicts")
        ):
            st = self.stats
            self._safe_callback(
                self.on_log,
                f"Ảnh thẻ tự học: {st['learned']} mẫu mới, {st['learned_hits']} lượt nhận ra bằng ảnh, OCR xác nhận đúng "
                f"{st['learned_verified']} lần, phát hiện nhầm {st['learned_conflicts']} lần.",
            )
        if self.latencies_ms and self.on_log:
            lat = sorted(self.latencies_ms)
            self._safe_callback(
                self.on_log,
                f"Độ trễ mua (thẻ hiện → click): {len(lat)} lần, trung bình {sum(lat) / len(lat):.0f} ms, "
                f"p95 {lat[min(len(lat) - 1, int(len(lat) * 0.95))]:.0f} ms, chậm nhất {lat[-1]:.0f} ms.",
            )

    def _log_if_stalled(self, loop_ms: float):
        """Vòng quét lâu bất thường: ghi nó mất thời gian ở đâu để lần sau biết điểm nghẽn thật (chụp màn hình, mua, hay chờ CPU)."""
        if loop_ms < STALL_LOG_MS or self._stall_logs >= STALL_LOG_MAX or not self.on_log:
            return
        self._stall_logs += 1
        rest = max(0.0, loop_ms - self._grab_ms - self._buy_ms)
        self._safe_callback(
            self.on_log,
            f"Vòng quét chậm {loop_ms:.0f} ms: chụp màn hình {self._grab_ms:.0f} ms, mua {self._buy_ms:.0f} ms, còn lại {rest:.0f} ms "
            f"(cách chụp: {'DXGI' if self._dxgi is not None else 'mss'}).",
        )

    def _scan_once(self, cooldown: dict) -> bool:
        """
        1 vòng: chụp shop → nhận diện → click mua khi khớp. False nếu không chụp được màn hình.
        Nhánh ảnh được mua NGAY (không chờ OCR); nhánh tên chỉ OCR các ô cần OCR (xem _ocr_due_slots).
        """
        if self._click_blocked:
            self._refresh_block_state()
        self._buy_ms = 0.0
        t_grab = time.perf_counter()
        shop = self._grab_shop()
        t_frame = time.perf_counter()
        self._grab_ms = (t_frame - t_grab) * 1000
        if shop is None:
            return False
        self._capture_ms.append(self._grab_ms)

        if self._card_cols is None:
            self._detect_cards(shop)
        slots = self._slice_slots(shop)
        self._check_frame_health(shop)
        self._check_click_results(slots, t_frame)
        prev = self._prev_frame
        # Khung GIỐNG HỆT khung trước (shop đứng yên; DXGI trả lại khung cũ khi màn hình không đổi) thì chữ ký và so khớp ảnh
        # sẽ ra đúng kết quả cũ: bỏ qua để không đốt CPU của game. Vẫn xử lý lại nếu lượt trước có ứng viên mua chưa xong.
        static = (
            prev is not None and not self._last_had_cands and not self._click_blocked
            and prev.shape == shop.shape and np.array_equal(prev, shop)
        )
        self._prev_frame = shop
        changed: set[int] = set()
        img_cands = []
        if not static:
            sigs = [_slot_signature(f) for f in slots]
            changed = self._track_changes(sigs, t_frame)
            if self._locked:
                self._release_changed_locks(slots, sigs)

            for i, slot_frame in enumerate(slots):
                if not self._running:
                    break
                img_match = self._match_image_fast(slot_frame) or self._match_learned(i, slot_frame)
                if img_match:
                    img_cands.append((i, img_match[0], img_match[1], "ảnh", slot_frame))
        self._last_had_cands = bool(img_cands)
        if img_cands:
            self._buy_batch(img_cands, cooldown)

        if self.detect_by_name and self._running and self.async_ocr:
            self._scan_names_async(slots, changed, cooldown)
        elif self.detect_by_name and self._running:
            now = time.perf_counter()
            due = self._ocr_due_slots(now, changed)
            if due:
                self._last_name_scan = now
                name_results, empty_slots = self._scan_names_parallel(slots, due)
                if empty_slots is not None:  # None = lượt này bỏ qua OCR (còn kẹt) hoặc chỉ OCR một phần
                    self._track_ocr_health(empty_slots)
                self._report_new_ocr_errors()
                self._learn_from_ocr(name_results, slots)
                name_cands = [(r[0], r[1], r[2], "tên", slots[r[0]]) for r in name_results if r]
                if name_cands:
                    self._buy_batch(name_cands, cooldown)
        self._flush_shop_log()
        return True

    def _refresh_block_state(self):
        """Đang bị chặn click vì game không ở foreground: mở chặn ngay khi game quay lại (không đợi tới khi có ứng viên mua), để
        trạng thái trên màn hình đúng và vòng quét hết phải OCR cả 5 ô mỗi lượt."""
        if not self._foreground_settled():
            return
        self._click_blocked = False
        self._foreground_logged_at = None
        if self.on_status:
            self.on_status("Đang quét shop...")
        if self.on_log:
            self._safe_callback(self.on_log, "Game đã ở foreground trở lại — tiếp tục click.")

    def _check_frame_health(self, shop: np.ndarray):
        """Khung vùng Shop ĐEN liên tục khi game ở foreground = tool không nhìn thấy game (fullscreen độc quyền hoặc vùng Shop
        sai màn hình) → OCR rỗng và không bao giờ mua. Kiểm tra mỗi giây, cảnh báo tối đa mỗi BLACK_FRAME_LOG_EVERY_S."""
        now = self._now()
        if now - self._last_health_check < 1.0:
            return
        self._last_health_check = now
        if float(shop[::8, ::8].mean()) >= 1.0 or not self._game_in_front():
            self._black_since = None
            return
        if self._black_since is None:
            self._black_since = now
            return
        if now - self._black_since < BLACK_FRAME_WARN_S:
            return
        if self._black_logged_at is not None and now - self._black_logged_at < BLACK_FRAME_LOG_EVERY_S:
            return
        self._black_logged_at = now
        if self.on_log:
            self._safe_callback(
                self.on_log,
                f"Cảnh báo: khung chụp vùng Shop ĐEN suốt {now - self._black_since:.0f} giây dù game ở foreground. Game đang ở chế độ "
                "fullscreen độc quyền (đổi sang Borderless/Windowed trong cài đặt video của game) hoặc vùng Shop nằm sai màn hình.",
            )

    def _note_ocr_text(self, slot: int, text: str, match: tuple[str, float] | None):
        """Nhớ chữ OCR gần nhất của ô; chữ đổi thì đánh dấu để ghi dòng 'Shop: ...', và ghi 'gần khớp' nếu chữ suýt là mục tiêu."""
        text = text.strip()
        if text == self._slot_text[slot] and match == self._slot_hit[slot]:
            return
        self._slot_text[slot] = text
        self._slot_hit[slot] = match
        self._shop_dirty_at = self._now()
        if not self.verbose_log or match or not text or self._near_seen.get(slot) == text:
            return
        self._near_seen[slot] = text
        if self.stats["near_miss"] >= NEAR_MISS_MAX_LINES or not self.on_log:
            return
        nearest = self._name_matcher.nearest_target(text)
        if nearest is None or nearest[1] < NEAR_MISS_MIN:
            return
        self.stats["near_miss"] += 1
        top = ", ".join(f"{n} {sc:.0%}" for sc, n, _t in self._name_matcher.explain(text))
        self._safe_callback(
            self.on_log,
            f"Gần khớp ô {slot + 1}: OCR đọc {text!r} giống mục tiêu {nearest[0]} {nearest[1]:.0%} nhưng KHÔNG mua "
            f"(ngưỡng tên {self.name_threshold:.0%}). Tên giống nhất trong cả danh sách: {top}.",
        )

    def _flush_shop_log(self):
        """Ghi 1 dòng 'Shop: tên1 | tên2 | ...' (★ = mục tiêu) khi chữ 5 ô đã đứng yên SHOP_LOG_STABLE_S. Nhìn dòng này là biết tool
        đang đọc ra gì mỗi lần roll — đọc sai/rỗng/là rác của cửa sổ khác thì lộ ngay."""
        if not self.verbose_log or self._shop_dirty_at is None or not self.on_log:
            return
        if self._now() - self._shop_dirty_at < SHOP_LOG_STABLE_S:
            return
        self._shop_dirty_at = None
        snapshot = tuple((self._slot_text[i], self._slot_hit[i] is not None) for i in range(SLOT_COUNT))
        if snapshot == self._shop_logged:
            return
        self._shop_logged = snapshot
        if self._shop_lines >= SHOP_LOG_MAX:
            if self._shop_lines == SHOP_LOG_MAX:
                self._shop_lines += 1
                self._safe_callback(self.on_log, f"(Đã ghi {SHOP_LOG_MAX} dòng 'Shop:' — ngừng ghi thêm để Nhật ký không tràn.)")
            return
        self._shop_lines += 1
        parts = [f"{(text.replace(chr(10), ' ')[:18] or '–')}{'★' if hit else ''}" for text, hit in snapshot]
        suffix = "  (game không ở trước: có thể đây là chữ của cửa sổ khác)" if self._click_blocked else ""
        self._safe_callback(self.on_log, "Shop: " + " | ".join(parts) + suffix)

    def _loop(self):
        """
        Vòng lặp chính. Lỗi thoáng qua thì bỏ qua vòng đó và quét tiếp; lỗi liên tục
        (MAX_CONSECUTIVE_ERRORS vòng, hoặc không chụp được màn hình quá GRAB_FAIL_LIMIT_S) thì dừng và báo UI.
        """
        _boost_thread_priority()
        try:
            self._run_loop()
        finally:
            self._log_loop_summary()
            self.close()  # thread tự dọn tài nguyên mình dùng (mss được dùng ở thread này)

    def _run_loop(self):
        if self.async_ocr:
            self._ocr_thread = threading.Thread(target=self._ocr_dispatch_loop, daemon=True, name="OCR-dispatch")
            self._ocr_thread.start()
        self._open_capture()
        self._log_environment()
        cooldown: dict = {}
        errors = 0
        grab_fail_since: float | None = None
        prev_start: float | None = None

        while self._running:
            t0 = self._perf()

            try:
                grabbed = self._scan_once(cooldown)
            except Exception as e:
                if not self._running:
                    return  # đang dừng — lỗi do dọn dẹp, không báo
                errors += 1
                detail = _describe_error(e)
                if errors == 1:
                    self._report_error(f"Lỗi vòng quét (quét tiếp): {detail}", fatal=False)
                if errors >= MAX_CONSECUTIVE_ERRORS:
                    self._report_error(f"Đã dừng: {errors} vòng lỗi liên tiếp. Lỗi cuối: {detail}", fatal=True)
                    return
                time.sleep(0.05)
                continue
            errors = 0
            self._log_if_stalled((self._perf() - t0) * 1000)

            if not grabbed:
                if grab_fail_since is None:
                    grab_fail_since = t0
                elif t0 - grab_fail_since >= GRAB_FAIL_LIMIT_S:
                    self._report_error(
                        f"Đã dừng: không chụp được màn hình trong {GRAB_FAIL_LIMIT_S:.0f}s. {self._last_grab_error}",
                        fatal=True,
                    )
                    return
                time.sleep(0.002)
                continue
            grab_fail_since = None

            if prev_start is not None:  # chu kỳ = từ lúc bắt đầu vòng trước tới lúc bắt đầu vòng này
                self.loop_stats.add((t0 - prev_start) * 1000, t0)
                snap = self.loop_stats.take_window(t0)
                if snap and self.on_stats:
                    self._safe_callback(self.on_stats, snap)
            prev_start = t0

            elapsed_ms = (self._perf() - t0) * 1000
            dense = time.perf_counter() < self._burst_until  # vừa bấm roll: không nghỉ thêm ngoài mức tối thiểu
            time.sleep((MIN_SLEEP_MS if dense else max(self.scan_interval_ms - elapsed_ms, MIN_SLEEP_MS)) / 1000)


def build_templates(
    champion_names: list[str],
    custom_paths: dict[str, str],
    ddragon_paths: dict[str, Path],
    log=None,
) -> dict[str, np.ndarray]:
    """
    Tạo dict ảnh mẫu cho từng tướng.
    Ưu tiên ảnh custom (upload); thiếu hoặc không đọc được thì dùng ảnh Data Dragon (và báo qua log).
    """
    templates = {}
    for name in champion_names:
        img = None
        custom = custom_paths.get(name)
        if custom:
            path = resolve_template_path(custom)
            img = load_template_image(path) if path else None
            if img is None and log:
                log(f"Ảnh upload của {name} không đọc được ({custom}) — dùng ảnh Data Dragon")
        if img is None and name in ddragon_paths:
            img = load_template_image(ddragon_paths[name])
        if img is not None:
            templates[name] = prepare_shop_template(img)
    return templates
