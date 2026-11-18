"""
Quét shop TFT liên tục: nhận diện tướng (ảnh/OCR) và tự click mua.
Tối ưu: chụp 1 lần cả shop, template xử lý sẵn, OCR song song 5 ô.
"""

import ctypes
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import mss
import numpy as np

from core.buyer import buy_slot_async
from core.champions import load_template_image, prepare_shop_template
from core.name_matcher import match_name_in_text, read_name_from_slot

try:
    _kernel32 = ctypes.windll.kernel32
    THREAD_PRIORITY_HIGHEST = 2
except Exception:
    _kernel32 = None


def _boost_thread_priority():
    """Tăng ưu tiên thread quét shop để phản hồi nhanh hơn trên Windows."""
    if _kernel32 is None:
        return
    try:
        handle = _kernel32.GetCurrentThread()
        _kernel32.SetThreadPriority(handle, THREAD_PRIORITY_HIGHEST)
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


class ShopScanner:
    """Engine quét shop: chụp màn hình → nhận diện → click mua tướng."""

    def __init__(
        self,
        shop_region: dict,
        slot_centers: list[tuple[int, int]],
        templates: dict[str, np.ndarray],
        target_names: list[str] | None = None,
        threshold: float = 0.72,
        name_threshold: float = 0.65,
        detect_by_image: bool = True,
        detect_by_name: bool = True,
        scan_interval_ms: int = 3,
        name_scan_interval_ms: int = 50,
        buy_cooldown_ms: int = 90,
        buy_delay_ms: int = 0,
        on_match=None,
        on_status=None,
    ):
        self.shop_region = shop_region
        self.slot_centers = slot_centers
        self.templates = templates
        self.target_names = target_names or list(templates.keys())
        self.threshold = threshold
        self.name_threshold = name_threshold
        self.detect_by_image = detect_by_image and bool(templates)
        self.detect_by_name = detect_by_name
        self.scan_interval_ms = max(0, scan_interval_ms)
        self.name_scan_interval_ms = name_scan_interval_ms
        self.buy_cooldown_ms = buy_cooldown_ms
        self.buy_delay_ms = buy_delay_ms
        self.on_match = on_match
        self.on_status = on_status

        self._running = False
        self._thread: threading.Thread | None = None
        self._sct = mss.mss()
        self._shop_monitor = self._build_shop_monitor()
        self._slot_half_w = 0
        self._card_top_ratio = 0.18
        self._gray_templates: list[tuple[str, np.ndarray]] = []
        self._portrait_size: tuple[int, int] = (48, 48)
        self._last_name_scan = 0.0
        self._ocr_pool = ThreadPoolExecutor(max_workers=3) if detect_by_name else None
        self._init_fast_templates()

    def _build_shop_monitor(self) -> dict | None:
        """Chuyển shop_region thành dict cho thư viện chụp màn hình mss."""
        if not self.shop_region:
            return None
        r = self.shop_region
        return {"left": r["left"], "top": r["top"], "width": r["width"], "height": r["height"]}

    def _init_slot_geometry(self):
        """Tính độ rộng mỗi ô shop theo khoảng cách giữa các điểm click (chính xác hơn chia đều)."""
        if len(self.slot_centers) >= 2:
            xs = [c[0] for c in self.slot_centers]
            spacings = [abs(xs[i + 1] - xs[i]) for i in range(len(xs) - 1)]
            self._slot_half_w = max(40, int(sum(spacings) / len(spacings) * 0.46))
        elif self.shop_region:
            self._slot_half_w = max(40, self.shop_region["width"] // 10)

    def _slice_slots(self, shop: np.ndarray) -> list[np.ndarray]:
        """Cắt 5 ô shop theo tọa độ click; bỏ thanh cấp/vàng phía trên, giữ đủ tên tướng ở dưới."""
        h, w = shop.shape[:2]
        y0 = min(int(h * self._card_top_ratio), h - 24)
        cards = shop[y0:, :]
        card_w = cards.shape[1]
        left = self.shop_region["left"]

        slots = []
        for cx, _ in self.slot_centers:
            rel_x = cx - left
            x0 = max(0, rel_x - self._slot_half_w)
            x1 = min(card_w, rel_x + self._slot_half_w)
            slots.append(cards[:, x0:x1])
        return slots

    def _init_fast_templates(self):
        """Pre-process ảnh mẫu tướng sang grayscale cùng kích thước — so khớp nhanh hơn."""
        self._init_slot_geometry()
        if not self.shop_region or not self.templates:
            return

        sh = int(self.shop_region["height"] * (1 - self._card_top_ratio))
        sw = self._slot_half_w * 2
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
        if not self._shop_monitor or not self.target_names or len(self.slot_centers) != 5:
            if self.on_status:
                self.on_status("Chưa cấu hình shop hoặc chưa chọn tướng")
            return
        if not self.detect_by_image and not self.detect_by_name:
            if self.on_status:
                self.on_status("Bật 'Bắt theo ảnh' hoặc 'Bắt theo tên'")
            return

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
        """Dừng vòng quét shop."""
        self._running = False
        if self._ocr_pool:
            self._ocr_pool.shutdown(wait=False, cancel_futures=True)
            self._ocr_pool = None
        if self.on_status:
            self.on_status("Đã dừng")

    @property
    def is_running(self) -> bool:
        """Tool có đang quét shop không."""
        return self._running

    def _grab_shop(self) -> np.ndarray | None:
        """Chụp toàn bộ vùng shop 1 lần (5 ô trong 1 ảnh)."""
        try:
            shot = self._sct.grab(self._shop_monitor)
            return np.asarray(shot, dtype=np.uint8)[:, :, :3]
        except Exception:
            return None

    def _try_buy(self, slot_idx: int, name: str, score: float, method: str, cooldown: dict):
        """Click mua tướng nếu chưa mua ô đó gần đây (tránh click trùng)."""
        key = (slot_idx, name)
        now = time.perf_counter()
        if now - cooldown.get(key, 0) < self.buy_cooldown_ms / 1000:
            return
        cooldown[key] = now

        center = self.slot_centers[slot_idx]
        if self.buy_delay_ms > 0:
            time.sleep(self.buy_delay_ms / 1000)
        buy_slot_async(center)

        if self.on_match:
            self.on_match(name, slot_idx + 1, score, method)

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

    def _match_name_fast(self, slot_frame: np.ndarray) -> tuple[str, float] | None:
        """OCR đọc tên tướng trong ô shop và so với danh sách cần bắt."""
        if not self.detect_by_name:
            return None
        ocr_text = read_name_from_slot(slot_frame)
        return match_name_in_text(ocr_text, self.target_names, self.name_threshold)

    def _scan_names_parallel(self, slots: list[np.ndarray]) -> list[tuple[int, str, float] | None]:
        """OCR 5 ô shop song song để tăng tốc bắt theo tên."""
        results: list[tuple[int, str, float] | None] = [None] * len(slots)

        if self._ocr_pool:
            futures = [self._ocr_pool.submit(self._match_name_fast, frame) for frame in slots]
            for i, fut in enumerate(futures):
                try:
                    match = fut.result(timeout=8.0)
                    if match:
                        results[i] = (i, match[0], match[1])
                except Exception:
                    pass
        else:
            for i, frame in enumerate(slots):
                match = self._match_name_fast(frame)
                if match:
                    results[i] = (i, match[0], match[1])
        return results

    def _loop(self):
        """Vòng lặp chính: chụp shop → nhận diện từng ô → click mua ngay khi khớp."""
        _boost_thread_priority()
        cooldown: dict = {}

        while self._running:
            t0 = time.perf_counter()

            shop = self._grab_shop()
            if shop is None:
                time.sleep(0.002)
                continue

            slots = self._slice_slots(shop)

            for i, slot_frame in enumerate(slots):
                if not self._running:
                    break
                img_match = self._match_image_fast(slot_frame)
                if img_match:
                    self._try_buy(i, img_match[0], img_match[1], "ảnh", cooldown)

            if self.detect_by_name:
                now = time.perf_counter()
                if (
                    self.name_scan_interval_ms <= 0
                    or now - self._last_name_scan >= self.name_scan_interval_ms / 1000
                ):
                    self._last_name_scan = now
                    name_results = self._scan_names_parallel(slots)
                    for item in name_results:
                        if item is None:
                            continue
                        idx, name, score = item
                        self._try_buy(idx, name, score, "tên", cooldown)

            elapsed_ms = (time.perf_counter() - t0) * 1000
            if self.scan_interval_ms > 0:
                sleep_ms = self.scan_interval_ms - elapsed_ms
                if sleep_ms > 0:
                    time.sleep(sleep_ms / 1000)


def build_templates(
    champion_names: list[str],
    custom_paths: dict[str, str],
    ddragon_paths: dict[str, Path],
) -> dict[str, np.ndarray]:
    """
    Tạo dict ảnh mẫu cho từng tướng.
    Ưu tiên ảnh custom (upload) trước, không có thì dùng ảnh Data Dragon.
    """
    templates = {}
    for name in champion_names:
        img = None
        if name in custom_paths:
            img = load_template_image(Path(custom_paths[name]))
        elif name in ddragon_paths:
            img = load_template_image(ddragon_paths[name])
        if img is not None:
            templates[name] = prepare_shop_template(img)
    return templates
