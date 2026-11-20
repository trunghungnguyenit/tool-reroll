"""Pool luồng DAEMON cho OCR.

Vì sao không dùng ThreadPoolExecutor: luồng của nó không phải daemon và Python chờ chúng khi thoát. Một lần gọi OCR
treo vĩnh viễn (engine Windows kẹt) sẽ làm tiến trình KHÔNG thoát được, kể cả sau shutdown(wait=False) — cửa sổ đóng
rồi mà tiến trình vẫn sống, giữ mutex một-bản-chạy và chặn luôn việc mở lại app. Luồng daemon thì bị bỏ lại khi thoát."""

import queue
import threading
from concurrent.futures import Future


class OcrPool:
    """submit(fn, *args) -> Future, như ThreadPoolExecutor nhưng luồng là daemon và shutdown không chờ."""

    def __init__(self, workers: int, name: str = "OCR"):
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._closed = False
        self._lock = threading.Lock()
        self.threads = [
            threading.Thread(target=self._work, daemon=True, name=f"{name}-{i}") for i in range(workers)
        ]
        for t in self.threads:
            t.start()

    def submit(self, fn, *args) -> Future:
        with self._lock:
            if self._closed:
                raise RuntimeError("OcrPool đã đóng")
            future: Future = Future()
            self._queue.put((future, fn, args))
            return future

    def _work(self):
        while True:
            item = self._queue.get()
            if item is None:  # tín hiệu dừng
                return
            future, fn, args = item
            if not future.set_running_or_notify_cancel():  # đã bị hủy khi còn xếp hàng
                continue
            try:
                future.set_result(fn(*args))
            except BaseException as e:  # kể cả lỗi lạ: Future phải luôn có kết quả để bên chờ không treo
                future.set_exception(e)

    def shutdown(self) -> None:
        """Đóng pool: hủy việc đang xếp hàng, báo các luồng nghỉ. Không chờ luồng đang chạy (có thể đang kẹt)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            while True:  # hủy việc chưa bắt đầu
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is not None:
                    item[0].cancel()
            for _ in self.threads:
                self._queue.put(None)
