"""Đợt OCR có MỘT hạn chung thay vì 5 lần chờ tuần tự 8 giây (tối đa 40 giây), bỏ qua OCR khi luồng còn kẹt,
tự hồi phục, và bấm DỪNG có hiệu lực ngay trong lúc chờ."""

import threading
import time

import numpy as np
import pytest

import core.scanner as sc
from core import name_matcher as nm


def slots(n=5):
    return [np.full((4, 4, 3), i, np.uint8) for i in range(n)]


class Harness:
    """Scanner với `_ocr_slot` giả: ô trong `stuck` chặn tới khi release.set(); các ô khác trả ngay kết quả."""

    def __init__(self, make_scanner, monkeypatch, stuck=(), timeout=0.3):
        monkeypatch.setattr(sc, "OCR_BATCH_TIMEOUT_S", timeout)
        self.events = {"errors": [], "logs": [], "health": []}
        self.s = make_scanner(
            target_names=["Vex"], all_names=["Vex", "Zed"],
            on_error=lambda m, f: self.events["errors"].append((m, f)),
            on_log=self.events["logs"].append, on_ocr_health=self.events["health"].append,
        )
        self.s._running = True
        self.stuck, self.release, self.calls = set(stuck), threading.Event(), []
        matcher = self.s._name_matcher

        def fake(frame):
            idx = int(frame[0, 0, 0])
            self.calls.append(idx)
            if idx in self.stuck:
                self.release.wait(15)
            return matcher.match("Vex 2" if idx == 1 else "Zed"), False

        self.s._ocr_slot = fake

    def run(self):
        t0 = time.perf_counter()
        out = self.s._scan_names_parallel(slots())
        return out, time.perf_counter() - t0

    def done(self):
        self.release.set()
        time.sleep(0.15)


@pytest.fixture
def harness(make_scanner, monkeypatch):
    made = []

    def factory(**kw):
        h = Harness(make_scanner, monkeypatch, **kw)
        made.append(h)
        return h

    yield factory
    for h in made:
        h.release.set()


class TestPinnedDecisions:
    def test_numbers_chosen_by_the_user(self):
        assert sc.OCR_BATCH_TIMEOUT_S == 2.0 and sc.OCR_WORKERS == 5

    def test_pool_has_one_worker_per_slot_and_none_without_name_mode(self, make_scanner):
        s = make_scanner()
        assert len(s._ocr_pool.threads) == sc.OCR_WORKERS == sc.SLOT_COUNT
        assert make_scanner(detect_by_name=False, detect_by_image=True, templates={"Vex": np.zeros((64, 64, 3), np.uint8)})._ocr_pool is None


class TestNormalBatch:
    def test_all_five_slots_run_in_parallel_within_one_batch(self, make_scanner, monkeypatch):
        """Rào chắn 5 bên: chỉ qua được nếu 5 ô OCR chạy đồng thời (trước đây 3 luồng sẽ kẹt)."""
        barrier = threading.Barrier(5, timeout=3)
        s = make_scanner(target_names=["Vex"], all_names=["Vex"])
        s._running = True
        s._ocr_slot = lambda frame: (barrier.wait(), (None, False))[1]
        results, empties = s._scan_names_parallel(slots())
        assert empties == 0 and s._ocr_stuck == []

    def test_fast_batch_reports_matches_and_is_not_slowed_by_the_deadline(self, harness):
        h = harness()
        (results, empties), dt = h.run()
        assert results[1] and results[1][1] == "Vex" and empties == 0 and dt < 0.25
        assert h.events["errors"] == [] and h.s._ocr_stuck == []


class TestDeadlineIsShared:
    def test_five_stuck_slots_cost_one_deadline_not_five(self, harness):
        h = harness(stuck={0, 1, 2, 3, 4}, timeout=0.3)
        (results, empties), dt = h.run()
        assert 0.25 <= dt < 0.9, f"phải ~1 hạn chung (0.3 s), không phải 5 hạn nối tiếp (1.5 s): {dt:.2f}s"
        assert empties == 5 and all(r is None for r in results) and len(h.s._ocr_stuck) == 5

    def test_slots_that_finished_keep_their_result_while_others_are_stuck(self, harness):
        h = harness(stuck={2, 3, 4}, timeout=0.3)
        (results, empties), dt = h.run()
        assert results[1] and results[1][1] == "Vex"  # ô 1 xong và vẫn được mua
        assert empties == 3 and len(h.s._ocr_stuck) == 3

    def test_stuck_is_reported_once_with_a_clear_message(self, harness):
        h = harness(stuck={0, 1, 2, 3, 4})
        h.run()
        assert len(h.events["errors"]) == 1 and h.events["errors"][0][1] is False
        msg = h.events["errors"][0][0]
        assert "OCR bị kẹt" in msg and "5/5" in msg and "bắt theo ảnh" in msg
        assert h.events["health"] == [False]


class TestSkipWhileStuck:
    def test_next_cycles_skip_ocr_instantly_without_piling_up_work(self, harness):
        h = harness(stuck={0, 1, 2, 3, 4})
        h.run()
        calls_before = len(h.calls)
        for _ in range(5):
            (results, empties), dt = h.run()
            assert empties is None and all(r is None for r in results) and dt < 0.05
        assert len(h.calls) == calls_before, "không được đẩy thêm việc vào pool đang kẹt"
        assert len(h.events["errors"]) == 1  # không báo lặp mỗi lượt

    def test_skipped_cycle_is_not_counted_as_empty_reading(self, harness, monkeypatch):
        """Bỏ qua OCR không được làm bộ theo dõi 'đọc rỗng 30 giây' tưởng là OCR đọc không ra chữ."""
        h = harness(stuck={0, 1, 2, 3, 4})
        h.run()
        tracked = []
        monkeypatch.setattr(h.s, "_track_ocr_health", tracked.append)
        from tests.helpers import make_shop

        h.s._grab_shop = lambda: make_shop(h.s, [1, 2, 3, 4, 5])
        h.s._last_name_scan = -1e9
        h.s._scan_once({})
        assert tracked == []

    def test_image_detection_keeps_running_while_ocr_is_stuck(self, harness, monkeypatch):
        h = harness(stuck={0, 1, 2, 3, 4})
        h.run()
        image_calls = []
        monkeypatch.setattr(h.s, "_match_image_fast", lambda frame: image_calls.append(1) and None)
        from tests.helpers import make_shop

        shops = iter([make_shop(h.s, [k, k + 1, k + 2, k + 3, k + 4]) for k in (1, 10, 20)])  # mỗi vòng shop khác (roll)
        h.s._grab_shop = lambda: next(shops)
        for _ in range(3):
            h.s._last_name_scan = -1e9
            assert h.s._scan_once({}) is True
        assert len(image_calls) == 15  # 5 ô x 3 vòng


class TestRecovery:
    def test_ocr_resumes_and_reports_once_when_the_stuck_workers_return(self, harness):
        h = harness(stuck={0, 1, 2, 3, 4})
        h.run()
        h.done()  # các luồng kẹt trả về
        h.stuck = set()
        (results, empties), _ = h.run()
        assert empties == 0 and results[1] and h.s._ocr_stuck == [] and not h.s._ocr_stuck_warned
        assert h.events["logs"] == ["OCR đã hồi phục sau khi bị kẹt."]
        assert h.events["health"] == [False, True]
        h.run()
        assert h.events["logs"].count("OCR đã hồi phục sau khi bị kẹt.") == 1

    def test_a_second_stuck_episode_warns_again(self, harness):
        h = harness(stuck={0, 1, 2, 3, 4})
        h.run()
        h.done()
        h.stuck = set()
        h.run()  # hồi phục
        h.release.clear()
        h.stuck = {0, 1, 2, 3, 4}
        h.run()  # kẹt lần 2
        assert len(h.events["errors"]) == 2 and h.events["health"] == [False, True, False]


class TestStopWhileWaiting:
    def test_stop_takes_effect_within_a_poll_interval_not_the_whole_deadline(self, harness, monkeypatch):
        h = harness(stuck={0, 1, 2, 3, 4}, timeout=10.0)  # hạn 10 s: nếu không kiểm tra DỪNG thì phải chờ cả 10 s
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("r", h.run()))
        t.start()
        time.sleep(0.2)
        h.s._running = False
        t.join(2)
        assert not t.is_alive(), "bấm DỪNG phải làm đợt OCR thoát ngay"
        assert out["r"][1] < 0.6

    def test_stopping_is_not_reported_as_stuck(self, harness):
        h = harness(stuck={0, 1, 2, 3, 4}, timeout=10.0)
        t = threading.Thread(target=h.run)
        t.start()
        time.sleep(0.2)
        h.s._running = False
        t.join(2)
        assert h.s._ocr_stuck == [] and h.events["errors"] == [] and h.events["health"] == []

    def test_scanner_thread_exits_quickly_even_though_ocr_is_hung(self, make_scanner, monkeypatch):
        """Từ đầu đến cuối với thread quét thật: OCR treo, bấm stop → thread thoát trong chớp mắt (trước: tới 40 s)."""
        from tests.helpers import make_shop

        s = make_scanner(target_names=["Vex"], all_names=["Vex"], scan_interval_ms=5, name_scan_interval_ms=0)
        release = threading.Event()
        started = threading.Event()

        def hung(frame):
            started.set()
            release.wait(30)
            return None, True

        s._ocr_slot = hung
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s.start()
        try:
            assert started.wait(3)
            time.sleep(0.1)
            t0 = time.perf_counter()
            s.stop()
            s._thread.join(3)
            assert not s._thread.is_alive() and time.perf_counter() - t0 < 1.0
        finally:
            release.set()


class TestErrorsAndCleanup:
    def test_worker_exception_is_recorded_and_slot_counts_as_empty(self, harness):
        nm.drain_ocr_errors()
        h = harness()

        def flaky(frame):
            if int(frame[0, 0, 0]) == 3:
                raise ValueError("ô 4 hỏng")
            return None, False

        h.s._ocr_slot = flaky
        (results, empties), _ = h.run()
        assert empties == 1 and any("ValueError: ô 4 hỏng" in m for m in nm.drain_ocr_errors())
        assert h.s._ocr_stuck == []  # lỗi ngoại lệ không phải kẹt

    def test_close_does_not_wait_for_a_stuck_worker(self, harness):
        h = harness(stuck={0, 1, 2, 3, 4})
        h.run()
        threads = list(h.s._ocr_pool.threads)
        t0 = time.perf_counter()
        h.s.close()
        assert time.perf_counter() - t0 < 0.3 and h.s._ocr_pool is None
        assert threads and all(t.daemon for t in threads)  # luồng kẹt là daemon nên không chặn thoát app

    def test_close_releases_the_worker_threads_so_start_stop_cycles_do_not_leak(self, make_scanner):
        """Mỗi lần bật/tắt tạo 1 scanner mới (5 luồng OCR). close() phải làm các luồng nhàn rỗi thoát."""
        s = make_scanner()
        threads = list(s._ocr_pool.threads)
        assert all(t.is_alive() for t in threads)
        s.close()
        for t in threads:
            t.join(2)
        assert not any(t.is_alive() for t in threads)

    def test_repeated_start_stop_cycles_leave_no_threads_behind(self, make_scanner):
        before = threading.active_count()
        for _ in range(5):
            s = make_scanner()
            s._scan_once = lambda cooldown: True
            s.start()
            time.sleep(0.05)
            s.stop()
            s._thread.join(2)
        time.sleep(0.2)
        assert threading.active_count() <= before + 1  # dung sai 1 cho luồng đang kết thúc

    def test_without_a_pool_ocr_runs_inline(self, harness):
        h = harness()
        h.s._ocr_pool = None
        (results, empties), _ = h.run()
        assert empties == 0 and results[1]
