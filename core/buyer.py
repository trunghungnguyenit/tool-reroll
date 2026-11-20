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

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# Chờ hệ thống xử lý xong sự kiện click rồi mới trả chuột về — trả quá sớm thì click có thể rơi vào chỗ cũ.
_RESTORE_DELAY_S = 0.03


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _press(x: int, y: int):
    user32.SetCursorPos(x, y)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
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

    def submit(self, point: tuple[int, int]):
        self._ensure_thread()
        with self._idle:
            self._pending += 1
        self._q.put(point)

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
            point = self._q.get()
            handled = 0
            prev = None
            try:
                prev = _read_cursor() if self.restore_cursor else None
                while True:
                    _press(*point)
                    handled += 1
                    self.clicks_done += 1
                    try:  # điểm kế tiếp đến kịp trong thời gian chờ → click ngay, chưa trả chuột
                        point = self._q.get(timeout=_RESTORE_DELAY_S)
                    except queue.Empty:
                        break
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


def wait_clicks_done(timeout: float = 2.0) -> bool:
    return _worker.wait_idle(timeout)
