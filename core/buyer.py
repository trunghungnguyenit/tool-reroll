"""Tự động click chuột để mua tướng trong shop TFT.

`buy_slot_async` KHÔNG click ngay trong luồng gọi: nó đưa điểm vào hàng đợi cho một luồng click riêng. Luồng quét nhờ vậy không
bao giờ phải chờ (trước đây mỗi lần click chặn luồng quét 30 ms để chờ trả chuột). Nhiều điểm đến gần nhau được click liên tiếp
không nghỉ, và con trỏ chỉ được trả về MỘT lần, sau khi điểm cuối đã được click đủ lâu."""

import ctypes
import queue
import threading
import time

from core.logging_setup import logger

user32 = ctypes.windll.user32

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
_MOVE_FLAGS = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK

_SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN, _SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN = 76, 77, 78, 79

# Chờ hệ thống xử lý xong sự kiện click rồi mới trả chuột về — trả quá sớm thì click có thể rơi vào chỗ cũ.
_RESTORE_DELAY_S = 0.03
# Game (nhất là client TFT Unreal mới) đọc chuột theo từng khung hình: di chuột + nhấn + nhả trong cùng một micro giây thì game
# vẫn thấy chuột ở chỗ cũ hoặc bỏ lỡ cú nhấn → Nhật ký ghi "đã click" mà thẻ vẫn còn. Cho game ≥ 1 khung hình để thấy chuột đã tới
# nơi, rồi giữ nút xuống ≥ 1 khung hình (60 fps = 16,7 ms).
_MOVE_SETTLE_S = 0.02
_HOLD_S = 0.03
# Di chuột TRƯỚC (premove): ngay khi nhận diện được ô cần mua, con trỏ đã bay tới ô đó trong lúc tool còn chụp lại shop để xác nhận (~30 ms),
# nên khi xác nhận xong cú nhấn đi ngay, không còn chờ _MOVE_SETTLE_S sau xác nhận (nhanh hơn ~20 ms và cú nhấn sát lúc xác nhận hơn).
_PREMOVE_WAIT_S = 0.25  # đã di chuột trước mà không có lệnh click (xác nhận bị loại / chụp chậm): chờ từng này rồi trả chuột về
_PREMOVE_VALID_S = 0.5  # con trỏ đã bay tới điểm đó chưa quá từng này giây thì coi như vẫn đang ở đó


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _move_event(x: int, y: int):
    """Gửi sự kiện di chuyển chuột THẬT (WM_MOUSEMOVE) tới (x, y). SetCursorPos chỉ đặt con trỏ, không báo cho game biết chuột
    vừa di chuyển; game cập nhật thẻ đang trỏ vào dựa trên sự kiện này. Tọa độ chuẩn hóa 0..65535 trên toàn desktop ảo."""
    left, top = user32.GetSystemMetrics(_SM_XVIRTUALSCREEN), user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
    width, height = user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN), user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
    if width <= 1 or height <= 1:
        return
    nx = min(65535, max(0, round((x - left) * 65535 / (width - 1))))
    ny = min(65535, max(0, round((y - top) * 65535 / (height - 1))))
    user32.mouse_event(_MOVE_FLAGS, nx, ny, 0, 0)


def _move_to(x: int, y: int):
    user32.SetCursorPos(x, y)  # đặt chính xác tới từng pixel (sự kiện chuẩn hóa bên dưới có thể lệch 1 px)
    try:
        _move_event(x, y)
    except Exception:  # không gửi được sự kiện di chuyển thì vẫn click như trước, không bỏ lượt mua
        logger.exception("Không gửi được sự kiện di chuyển chuột")


def _press(x: int, y: int, there_since: float | None = None):
    """Nhấn-nhả tại (x, y). `there_since` (giờ perf_counter): con trỏ đã được di chuột trước tới đúng điểm này từ lúc đó, nên chỉ chờ
    phần còn lại của _MOVE_SETTLE_S (thường là 0) thay vì di chuột lại và chờ đủ."""
    if there_since is None:
        _move_to(x, y)
        time.sleep(_MOVE_SETTLE_S)
    else:
        remaining = _MOVE_SETTLE_S - (time.perf_counter() - there_since)
        if remaining > 0:
            time.sleep(remaining)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    try:
        time.sleep(_HOLD_S)
    finally:  # nút đã nhấn thì luôn phải nhả, kể cả khi bị ngắt giữa chừng
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def _read_cursor() -> _POINT | None:
    prev = _POINT()
    return prev if user32.GetCursorPos(ctypes.byref(prev)) else None


def click(x: int, y: int, restore_cursor: bool = True):
    """Di chuyển chuột tới (x, y), click trái 1 lần rồi trả con trỏ về vị trí cũ (đồng bộ: có chờ trước khi trả chuột)."""
    prev = _read_cursor() if restore_cursor else None
    _press(x, y)
    if prev is not None:
        time.sleep(_RESTORE_DELAY_S)
        user32.SetCursorPos(prev.x, prev.y)


class ClickWorker:
    """Luồng nền thực hiện click. Một 'loạt' = các điểm đến liên tiếp, mỗi điểm cách điểm trước chưa tới _RESTORE_DELAY_S."""

    def __init__(self, restore_cursor: bool = True):
        self.restore_cursor = restore_cursor
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pending = 0
        self._idle = threading.Condition()
        self.clicks_done = 0
        self._at: tuple[tuple[int, int], float] | None = None  # (điểm, lúc) con trỏ vừa được di chuột trước tới

    def submit(self, point: tuple[int, int]):
        self._put(point, True)

    def premove(self, point: tuple[int, int]):
        """Di chuột tới `point` ngay (chưa nhấn): dùng khi sắp có lệnh click cho điểm đó (xem _PREMOVE_WAIT_S)."""
        self._put(point, False)

    def _put(self, point: tuple[int, int], press: bool):
        self._ensure_thread()
        with self._idle:
            self._pending += 1
        self._q.put((point, press))

    def wait_idle(self, timeout: float = 2.0) -> bool:
        """Chờ tới khi mọi điểm đã được click và con trỏ đã được trả về (dùng cho test và khi tắt app)."""
        with self._idle:
            return self._idle.wait_for(lambda: self._pending == 0, timeout)

    def _ensure_thread(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True, name="ClickWorker")
                self._thread.start()

    def _done(self, n: int):
        with self._idle:
            self._pending -= n
            self._idle.notify_all()

    def _run(self):
        while True:
            point, press = self._q.get()
            handled = 0
            prev = None
            try:
                prev = _read_cursor() if self.restore_cursor else None
                while True:
                    if press:
                        at = self._at
                        there = at[1] if at is not None and at[0] == point and time.perf_counter() - at[1] <= _PREMOVE_VALID_S else None
                        _press(*point, there_since=there)
                        self._at = None
                        self.clicks_done += 1
                    else:
                        _move_to(*point)
                        self._at = (point, time.perf_counter())
                    handled += 1
                    # điểm kế tiếp đến kịp trong thời gian chờ → xử lý ngay, chưa trả chuột (sau di chuột trước thì chờ lệnh click lâu hơn)
                    try:
                        point, press = self._q.get(timeout=_RESTORE_DELAY_S if press else _PREMOVE_WAIT_S)
                    except queue.Empty:
                        break
                self._at = None
                if prev is not None:
                    user32.SetCursorPos(prev.x, prev.y)
            except Exception:
                logger.exception("Lỗi khi click")
            finally:
                self._done(handled or 1)


_worker = ClickWorker()


def buy_slot_async(slot_center: tuple[int, int]):
    """Click mua ngay (không chặn luồng gọi): điểm được luồng click riêng xử lý trong vài trăm micro giây."""
    _worker.submit((slot_center[0], slot_center[1]))


def premove_async(slot_center: tuple[int, int]):
    """Đưa con trỏ tới ô trước khi chắc chắn sẽ click (không chặn luồng gọi). Click ngay sau đó không phải chờ di chuột nữa."""
    _worker.premove((slot_center[0], slot_center[1]))

