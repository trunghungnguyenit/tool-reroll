"""Ảnh thẻ tự học: nhận ra tướng đã chọn bằng chính ảnh thẻ trong game, không chờ OCR.

Vì sao có file này: ảnh mẫu Data Dragon không khớp ảnh trên thẻ shop của client TFT mới (điểm so khớp đúng tướng chỉ ~0), nên mọi
lần mua đều phải chờ OCR (hàng trăm ms khi game đang chạy) và khi roll nhanh thì thẻ đã đổi trước khi đọc xong. Thẻ của một tướng
luôn có cùng ảnh, nên lần đầu tool đọc tên bằng OCR thì ghi nhớ ảnh thẻ đó; những lần sau chỉ cần so ảnh (~0,1 ms mỗi tướng).

Đo trên ảnh shop thật: cùng một tướng ở ô khác (lệch ±6 px, tối đi) khớp 0,94–1,00; hai tướng khác nhau chỉ 0,34–0,44.

Ảnh thẻ được chuẩn hóa về một cỡ cố định, nên không phụ thuộc ô nào hay độ phân giải; mẫu là phần giữa của ảnh chuẩn và được trượt
trong ảnh của ô (±8 px) nên chịu được vài pixel lệch khi cắt thẻ. Mẫu lưu kèm kích thước ô lúc học; chỉ dùng khi ô hiện tại có kích
thước tương đương (đổi vùng Shop/độ phân giải thì mẫu cũ bị bỏ qua và tool học lại)."""

import json
import os
import queue
import threading
from pathlib import Path

import cv2
import numpy as np

CANON = (96, 54)  # (rộng, cao) ảnh chuẩn hóa của vùng ảnh thẻ
ZONE = (0.15, 0.78)  # dải chiều cao của ô chứa ảnh tướng và tộc/hệ (bỏ dải tên phía dưới)
PATCH = (slice(7, 47), slice(8, 88))  # mẫu = phần giữa ảnh chuẩn (40×80); cửa sổ tìm kiếm rộng hơn ±8/±7 px
MATCH_MIN = 0.88  # điểm tối thiểu để coi là cùng một thẻ (khác tướng đo được ≤ 0,45)
MARGIN = 0.05  # tướng thứ hai (khác tên) không được gần điểm của tướng thắng hơn mức này
SAME_ENOUGH = 0.96  # ảnh mới giống mẫu đã có ≥ mức này thì không cần thêm mẫu
MAX_SAMPLES = 3  # tối đa số mẫu mỗi tướng (ánh sáng/hiệu ứng khác nhau)
GEOMETRY_TOL = 0.05  # kích thước ô được lệch tối đa 5% so với lúc học
INDEX_NAME = "index.json"


def zone_geometry(slot: np.ndarray) -> tuple[int, int]:
    """(rộng ô, cao vùng ảnh) — để biết mẫu đã học có dùng được cho ô này không."""
    h, w = slot.shape[:2]
    return int(w), int(h * ZONE[1]) - int(h * ZONE[0])


def canon(slot: np.ndarray) -> np.ndarray:
    """Ảnh xám cỡ CANON của vùng ảnh thẻ trong ô."""
    h = slot.shape[0]
    zone = slot[int(h * ZONE[0]) : int(h * ZONE[1])]
    gray = cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY) if zone.ndim == 3 else zone
    return cv2.resize(gray, CANON, interpolation=cv2.INTER_AREA)


def _compatible(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return all(abs(x - y) <= GEOMETRY_TOL * max(x, y, 1) for x, y in zip(a, b))


class PortraitLibrary:
    """Mẫu ảnh thẻ theo tên tướng. An toàn gọi từ nhiều luồng (luồng quét và luồng OCR kiểm tra lại)."""

    def __init__(
        self, folder: Path | None = None, match_min: float = MATCH_MIN, max_samples: int = MAX_SAMPLES, background: bool = False
    ):
        # background=True: ghi/xóa file ở một luồng riêng (luồng quét không bao giờ chờ ổ đĩa/Windows Defender đang quét file mới)
        self._background = background
        self._io: queue.SimpleQueue = queue.SimpleQueue()
        self._io_thread: threading.Thread | None = None
        self._io_lock = threading.Lock()
        self.folder = Path(folder) if folder else None
        self.match_min = match_min
        self.max_samples = max_samples
        self._lock = threading.RLock()
        self._samples: dict[str, list[tuple[tuple[int, int], np.ndarray, str]]] = {}  # tên → [(kích thước ô, mẫu, tên file)]
        self._counter = 0
        if self.folder:
            self._load()

    def __bool__(self) -> bool:
        return bool(self._samples)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._samples)

    def count(self, name: str, geometry: tuple[int, int] | None = None) -> int:
        with self._lock:
            return sum(1 for g, _p, _f in self._samples.get(name, []) if geometry is None or _compatible(g, geometry))

    def match(
        self, window: np.ndarray, geometry: tuple[int, int], names: set[str] | frozenset[str] | None = None
    ) -> tuple[str, float] | None:
        """(tên, điểm) của tướng có mẫu giống `window` nhất, hoặc None nếu không đủ chắc (điểm < match_min, hoặc có một tướng khác
        cũng gần như khớp bằng nhau). `names`: chỉ xét các tên này (mục tiêu hiện tại)."""
        best_name, best, runner_up = None, 0.0, 0.0
        with self._lock:
            for name, samples in self._samples.items():
                if names is not None and name not in names:
                    continue
                score = 0.0
                for geom, patch, _f in samples:
                    if _compatible(geom, geometry):
                        score = max(score, float(cv2.matchTemplate(window, patch, cv2.TM_CCOEFF_NORMED).max()))
                if score > best:
                    best_name, best, runner_up = name, score, best
                elif score > runner_up:
                    runner_up = score
        if best_name is None or best < self.match_min or best - runner_up < MARGIN:
            return None
        return best_name, best

    def learn(self, name: str, window: np.ndarray, geometry: tuple[int, int]) -> bool:
        """Ghi nhớ ảnh thẻ của `name` nếu chưa có mẫu nào giống nó (và chưa đủ MAX_SAMPLES). True nếu vừa thêm mẫu."""
        patch = np.ascontiguousarray(window[PATCH])
        with self._lock:
            mine = [(g, p, f) for g, p, f in self._samples.get(name, []) if _compatible(g, geometry)]
            if len(mine) >= self.max_samples:
                return False
            if any(float(cv2.matchTemplate(window, p, cv2.TM_CCOEFF_NORMED).max()) >= SAME_ENOUGH for _g, p, _f in mine):
                return False
            self._counter += 1
            filename = f"p{self._counter:05d}.png"
            self._samples.setdefault(name, []).append((tuple(geometry), patch, filename))
            self._save(patch, filename)
            return True

    def forget(self, name: str) -> int:
        """Xóa mọi mẫu của `name` (mẫu bị nhầm). Trả số mẫu đã xóa."""
        with self._lock:
            removed = self._samples.pop(name, [])
            if removed:

                def job():
                    for _g, _p, filename in removed:
                        self._delete_file(filename)
                    self._write_index()

                self._submit(job)
            return len(removed)

    # ---- lưu / nạp (ảnh PNG xám nhỏ + index.json); lỗi đĩa không bao giờ làm hỏng việc quét ----
    def _submit(self, job) -> None:
        """Chạy việc đĩa: ngay tại chỗ, hoặc ở luồng ghi riêng khi background=True."""
        if not self._background:
            job()
            return
        with self._io_lock:
            if self._io_thread is None or not self._io_thread.is_alive():
                self._io_thread = threading.Thread(target=self._io_loop, daemon=True, name="PortraitWriter")
                self._io_thread.start()
        self._io.put(job)

    def _io_loop(self) -> None:
        while True:
            job = self._io.get()
            try:
                job()
            except Exception:
                pass

    def flush(self, timeout: float = 5.0) -> bool:
        """Chờ các việc ghi đã xếp hàng xong (test, và khi tắt tool). True nếu xong trong `timeout`."""
        if not self._background:
            return True
        done = threading.Event()
        self._submit(done.set)
        return done.wait(timeout)

    def _save(self, patch: np.ndarray, filename: str) -> None:
        if not self.folder:
            return

        def job():
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(self.folder / filename), patch)
                self._write_index()
            except Exception:
                pass

        self._submit(job)

    def _write_index(self) -> None:
        if not self.folder:
            return
        with self._lock:
            entries = [
                {"name": name, "geometry": list(geom), "file": filename}
                for name, samples in self._samples.items()
                for geom, _p, filename in samples
            ]
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.folder / (INDEX_NAME + ".tmp")
            tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.folder / INDEX_NAME)
        except Exception:
            pass

    def _delete_file(self, filename: str) -> None:
        if not self.folder:
            return
        try:
            (self.folder / filename).unlink(missing_ok=True)
        except Exception:
            pass

    def _load(self) -> None:
        try:
            entries = json.loads((self.folder / INDEX_NAME).read_text(encoding="utf-8"))
        except Exception:
            return
        for entry in entries if isinstance(entries, list) else []:
            try:
                name, geom, filename = str(entry["name"]), tuple(int(v) for v in entry["geometry"]), str(entry["file"])
                if len(geom) != 2 or Path(filename).name != filename:
                    continue
                patch = cv2.imread(str(self.folder / filename), cv2.IMREAD_GRAYSCALE)
                if patch is None or patch.shape != (PATCH[0].stop - PATCH[0].start, PATCH[1].stop - PATCH[1].start):
                    continue
                self._samples.setdefault(name, []).append((geom, patch, filename))
                digits = "".join(c for c in filename if c.isdigit())
                self._counter = max(self._counter, int(digits) if digits else 0)
            except Exception:
                continue
