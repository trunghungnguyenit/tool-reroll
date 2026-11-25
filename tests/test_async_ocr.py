"""OCR chạy ở luồng riêng (async_ocr): vòng quét không chờ OCR, kết quả cũ của thẻ đã đổi bị bỏ, nhánh ảnh không bị OCR chặn."""

import threading
import time

import pytest

import core.scanner as sc
from tests.helpers import CENTERS, make_shop

SLOW_S = 0.3


def wait_until(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class FakeOcr:
    """read_name_from_slot giả: đọc "Vex" ở ô mà khung có hạt giống 1, mất `delay` giây, ghi lại các lần gọi."""

    def __init__(self, delay=0.0):
        self.delay = delay
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self, frame):
        with self.lock:
            self.calls += 1
        time.sleep(self.delay)
        return "Vex"


@pytest.fixture
def ocr(monkeypatch):
    fake = FakeOcr()
    monkeypatch.setattr(sc, "read_name_from_slot", fake)
    return fake


@pytest.fixture
def async_scanner(make_scanner, ocr):
    started = []

    def factory(**kw):
        kw.setdefault("async_ocr", True)
        kw.setdefault("require_game_foreground", False)
        s = make_scanner(**kw)
        s._running = True
        t = threading.Thread(target=s._ocr_dispatch_loop, daemon=True)
        t.start()
        started.append((s, t))
        return s

    yield factory
    for s, t in started:
        s._running = False
        s._ocr_wake.set()
        t.join(2)


def scan(s, shop, cooldown=None):
    s._grab_shop = lambda: shop
    return s._scan_once({} if cooldown is None else cooldown)


class TestNonBlocking:
    def test_scan_once_returns_while_ocr_is_still_running(self, async_scanner, ocr, clicks):
        ocr.delay = SLOW_S
        s = async_scanner()
        shop = make_shop(s, [1, 2, 3, 4, 5])
        t0 = time.perf_counter()
        scan(s, shop)
        assert time.perf_counter() - t0 < SLOW_S / 2  # bản đồng bộ phải chờ cả đợt OCR ở đây
        assert s._ocr_busy and clicks == []

    def test_result_is_bought_on_a_later_scan(self, async_scanner, ocr, clicks):
        s = async_scanner()
        shop = make_shop(s, [1, 2, 3, 4, 5])
        scan(s, shop)
        assert wait_until(lambda: len(s._ocr_done) > 0 or not s._ocr_busy)
        scan(s, shop)
        assert clicks and all(c in CENTERS for c in clicks)  # "Vex" khớp ở các ô đọc được
        assert not s._ocr_done

    def test_sync_mode_is_unchanged_by_default(self, make_scanner, ocr, clicks):
        s = make_scanner(require_game_foreground=False)
        s._running = True
        assert s.async_ocr is False
        scan(s, make_shop(s, [1, 2, 3, 4, 5]))
        assert clicks  # kết quả có ngay trong cùng một vòng

    def test_needs_name_detection(self, make_scanner):
        assert make_scanner(async_ocr=True, detect_by_name=False, detect_by_image=True, templates={"x": __import__("numpy").zeros((64, 64, 3), "uint8")}).async_ocr is False


class TestScheduling:
    def test_only_one_job_in_flight_and_wanted_slots_are_merged(self, async_scanner, ocr, clicks):
        ocr.delay = SLOW_S
        s = async_scanner()
        shop = make_shop(s, [1, 2, 3, 4, 5])
        scan(s, shop)
        first_calls = None
        shop2 = make_shop(s, [1, 2, 77, 4, 5])  # ô 3 đổi trong lúc OCR đang chạy
        scan(s, shop2)
        assert s._ocr_busy and 2 in s._ocr_wanted  # không đẩy thêm yêu cầu, chỉ ghi nhớ ô cần đọc
        assert wait_until(lambda: not s._ocr_busy, 5)
        first_calls = ocr.calls
        scan(s, shop2)  # rảnh → đẩy yêu cầu mới ở khung mới nhất
        assert wait_until(lambda: ocr.calls > first_calls, 3)

    def test_next_job_reads_the_newest_frame(self, async_scanner, ocr, clicks, monkeypatch):
        seen = []
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: seen.append(int(f[40, 40, 0])) or "")
        s = async_scanner()
        a = make_shop(s, [1, 2, 3, 4, 5])
        b = make_shop(s, [6, 7, 8, 9, 10])
        scan(s, a)
        assert wait_until(lambda: not s._ocr_busy)
        n = len(seen)
        scan(s, b)
        assert wait_until(lambda: len(seen) > n)
        assert set(seen[n:]) != set(seen[:n])  # đọc ảnh của khung b, không phải khung a cũ

    def test_stale_results_are_dropped_silently(self, async_scanner, ocr, clicks):
        logs = []
        s = async_scanner(on_log=logs.append)
        old = make_shop(s, [1, 2, 3, 4, 5])
        scan(s, old)
        assert wait_until(lambda: len(s._ocr_done) > 0)
        new = make_shop(s, [21, 22, 23, 24, 25])  # roll nhanh: thẻ đã đổi hết trước khi kết quả được nhận
        scan(s, new)
        assert clicks == [] and s.stats["stale_ocr"] > 0
        assert not any("Bỏ click" in m for m in logs)  # không làm đầy Nhật ký bằng 'thẻ đã đổi'

    def test_fresh_results_are_not_dropped(self, async_scanner, ocr, clicks):
        s = async_scanner()
        shop = make_shop(s, [1, 2, 3, 4, 5])
        scan(s, shop)
        assert wait_until(lambda: len(s._ocr_done) > 0)
        scan(s, shop)
        assert clicks and s.stats["stale_ocr"] == 0

    def test_results_are_handled_in_order(self, async_scanner, ocr, clicks):
        s = async_scanner()
        order = []
        s._buy_batch = lambda cands, cooldown: order.append([c[0] for c in cands])
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._slot_sigs = [sc._slot_signature(f) for f in s._slice_slots(shop)]
        s._ocr_done.append(([(0, "Vex", 1.0), None, None, None, None], 0, s._slice_slots(shop)))
        s._ocr_done.append(([None, (1, "Vex", 1.0), None, None, None], 0, s._slice_slots(shop)))
        s._collect_ocr_results({})
        assert order == [[0], [1]]


class TestRobustness:
    def test_dispatcher_survives_an_ocr_crash_and_frees_the_slot(self, async_scanner, ocr, clicks, monkeypatch):
        s = async_scanner()
        shop = make_shop(s, [1, 2, 3, 4, 5])
        boom = {"on": True}
        real = s._scan_names_parallel

        def flaky(slots, only=None):
            if boom["on"]:
                raise RuntimeError("OCR hỏng")
            return real(slots, only)

        s._scan_names_parallel = flaky
        scan(s, shop)
        assert wait_until(lambda: not s._ocr_busy)
        boom["on"] = False
        s._ocr_wanted.update(range(5))
        scan(s, shop)
        assert wait_until(lambda: len(s._ocr_done) > 0 or clicks)

    def test_stop_wakes_the_dispatcher_promptly(self, make_scanner, ocr):
        s = make_scanner(async_ocr=True)
        s._running = True
        t = threading.Thread(target=s._ocr_dispatch_loop, daemon=True)
        t.start()
        t0 = time.perf_counter()
        s.stop()
        t.join(2)
        assert not t.is_alive() and time.perf_counter() - t0 < 0.2

    def test_run_loop_starts_the_dispatcher_only_when_async(self, make_scanner, ocr, monkeypatch):
        for flag in (True, False):
            s = make_scanner(async_ocr=flag)
            s._running = True
            monkeypatch.setattr(s, "_open_capture", lambda: None)
            monkeypatch.setattr(s, "_log_environment", lambda: None)
            monkeypatch.setattr(s, "_scan_once", lambda cooldown, s=s: setattr(s, "_running", False) or True)
            s._run_loop()
            assert (s._ocr_thread is not None) is flag
            s._ocr_wake.set()


class TestImagePathIsNotBlockedByOcr:
    """Lý do làm OCR nền: nhánh ảnh được kiểm tra mỗi vòng quét. OCR đồng bộ chặn vòng quét ~100+ ms mỗi lần."""

    @staticmethod
    def learned_scanner(factory, tmp_path, async_ocr):
        s = factory(
            async_ocr=async_ocr, learn_portraits=True, portraits_dir=tmp_path / f"p{async_ocr}", target_names=["Vex", "Zed"],
        )
        s._card_cols = [(i * 200, (i + 1) * 200) for i in range(5)]
        shop = make_shop(s, [11, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s._buy_batch([(0, "Vex", 1.0, "tên", s._slice_slots(shop)[0])], {})
        s._locked.clear()
        s._pending_verify.clear()
        return s

    def measure(self, s, ocr):
        """Thời gian từ lúc Vex hiện (ô 4, thẻ mới) tới lúc click, khi OCR mất SLOW_S cho mỗi đợt."""
        ocr.delay = SLOW_S
        s._clicks = []
        shop_other = make_shop(s, [1, 2, 3, 4, 5])
        scan(s, shop_other)  # một đợt OCR chậm đang chạy (hoặc đang chặn ở bản đồng bộ)
        shop = make_shop(s, [1, 2, 3, 11, 5])  # Vex hiện ở ô 4
        t0 = time.perf_counter()
        end = t0 + 3
        while time.perf_counter() < end:
            scan(s, shop)
            if s.stats["learned_hits"]:
                break
            time.sleep(0.002)
        return time.perf_counter() - t0

    def test_async_bought_by_image_far_faster_than_sync_ocr_cycle(self, make_scanner, ocr, clicks, tmp_path):
        started = []

        def factory(**kw):
            kw["require_game_foreground"] = False
            s = make_scanner(**kw)
            s._running = True
            if kw.get("async_ocr"):
                t = threading.Thread(target=s._ocr_dispatch_loop, daemon=True)
                t.start()
                started.append((s, t))
            return s

        try:
            fast = self.learned_scanner(factory, tmp_path, True)
            slow = self.learned_scanner(factory, tmp_path, False)
            t_async = self.measure(fast, ocr)
            clicks.clear()
            t_sync = self.measure(slow, ocr)
        finally:
            for s, t in started:
                s._running = False
                s._ocr_wake.set()
                t.join(2)
        print(f"LATENCY image path while OCR takes {SLOW_S * 1000:.0f} ms: async {t_async * 1000:.1f} ms, sync {t_sync * 1000:.1f} ms")
        assert t_async < SLOW_S / 3, t_async  # nhận ra bằng ảnh trong vài vòng quét, không đợi OCR
        assert t_sync >= SLOW_S * 0.9, t_sync  # bản đồng bộ: vòng quét kẹt trong đợt OCR
