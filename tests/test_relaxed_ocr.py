"""OCR thưa khi mọi mục tiêu đã có ảnh thẻ, học ảnh ngay từ lần OCR đọc đúng (kể cả không kịp mua), và Nhật ký vòng quét chậm."""

import time

import pytest

import core.scanner as sc
from tests.helpers import CENTERS, make_shop

CARD_COLS = [(i * 200, (i + 1) * 200) for i in range(5)]


@pytest.fixture
def learner(make_scanner, tmp_path, monkeypatch):
    reads = []
    monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: reads.append(1) or "")
    logs = []

    def factory(**kw):
        kw.setdefault("learn_portraits", True)
        kw.setdefault("portraits_dir", tmp_path / "portraits")
        kw.setdefault("target_names", ["Vex", "Zed"])
        kw.setdefault("require_game_foreground", False)
        kw.setdefault("on_log", logs.append)
        s = make_scanner(**kw)
        s._running = True
        s._card_cols = list(CARD_COLS)
        return s

    factory.logs = logs
    factory.reads = reads
    return factory


def teach(s, seeds_by_name):
    """Học ảnh thẻ cho từng tướng như khi OCR vừa đọc đúng rồi mua: seeds_by_name = {tên: hạt giống thẻ}."""
    for name, seed in seeds_by_name.items():
        shop = make_shop(s, [seed, 2, 3, 4, 5])
        s._grab_shop = lambda shop=shop: shop
        slot = s._slice_slots(shop)[0]
        s._maybe_learn(name, 1.0, 1.0, slot)
    s._locked.clear()


def prime_geometry(s):
    shop = make_shop(s, [1, 2, 3, 4, 5])
    s._geometry = sc.zone_geometry(s._slice_slots(shop)[0])


class TestRelaxedMode:
    def test_not_relaxed_without_samples_or_with_one_target_missing(self, learner):
        s = learner()
        prime_geometry(s)
        assert s._ocr_relaxed() is False
        teach(s, {"Vex": 11})
        assert s._ocr_relaxed() is False  # còn Zed chưa có ảnh: vẫn OCR để học
        teach(s, {"Zed": 12})
        assert s._ocr_relaxed() is True

    def test_never_relaxed_when_learning_is_off_or_cards_unknown(self, learner, make_scanner):
        assert make_scanner()._ocr_relaxed() is False
        s = learner()
        teach(s, {"Vex": 11, "Zed": 12})
        prime_geometry(s)
        s._card_cols = None
        assert s._ocr_relaxed() is False

    def test_samples_for_another_slot_size_do_not_count(self, learner):
        s = learner()
        teach(s, {"Vex": 11, "Zed": 12})
        s._geometry = (s._geometry[0] * 2, s._geometry[1] * 2) if s._geometry else (999, 999)
        assert s._ocr_relaxed() is False

    def test_due_slots_are_only_a_slow_sweep_ignoring_changes(self, learner):
        s = learner()
        teach(s, {"Vex": 11, "Zed": 12})
        prime_geometry(s)
        s._last_idle_ocr = 100.0
        assert s._ocr_due_slots(100.5, {0, 1, 2}) == []  # đổi thẻ không còn kích hoạt OCR
        s._settle_until = [200.0] * 5
        assert s._ocr_due_slots(101.0, {3}) == []
        assert s._ocr_due_slots(100.0 + sc.RELAXED_OCR_S + 0.01, set()) == [0, 1, 2, 3, 4]
        assert s._ocr_due_slots(100.0 + sc.RELAXED_OCR_S + 0.02, set()) == []  # vừa quét xong

    def test_normal_scheduling_when_not_relaxed(self, learner):
        s = learner()
        prime_geometry(s)
        s._last_idle_ocr = time.perf_counter()
        assert s._ocr_due_slots(time.perf_counter(), {1}) == [1]

    def test_no_ocr_runs_between_sweeps_but_the_image_path_still_buys(self, learner, clicks):
        s = learner()
        teach(s, {"Vex": 11, "Zed": 12})
        s.async_ocr = False
        s._ocr_pool = None
        s._last_idle_ocr = time.perf_counter()  # vừa quét lưới an toàn
        learner.reads.clear()
        for seeds in ([1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [1, 2, 3, 11, 5]):  # roll liên tục, Vex hiện ở ô 4
            shop = make_shop(s, seeds)
            s._grab_shop = lambda shop=shop: shop
            s._scan_once({})
        assert learner.reads == []  # OCR không chạy lần nào
        assert clicks == [CENTERS[3]]


class TestLearnFromOcr:
    def test_ocr_match_teaches_the_card_even_without_a_buy(self, learner, clicks):
        s = learner()
        shop = make_shop(s, [11, 2, 3, 4, 5])
        s._slot_sigs = [sc._slot_signature(f) for f in s._slice_slots(shop)]
        s._learn_from_ocr([(0, "Vex", 1.0), None, None, None, None], s._slice_slots(shop))
        assert s._portraits.count("Vex") == 1 and clicks == []
        assert any("Đã học ảnh thẻ Vex" in m for m in learner.logs)

    def test_a_card_that_changed_since_the_read_is_not_learned(self, learner):
        s = learner()
        read = make_shop(s, [11, 2, 3, 4, 5])
        now = make_shop(s, [99, 2, 3, 4, 5])
        s._slot_sigs = [sc._slot_signature(f) for f in s._slice_slots(now)]
        s._learn_from_ocr([(0, "Vex", 1.0), None, None, None, None], s._slice_slots(read))
        assert s._portraits.count("Vex") == 0

    def test_fuzzy_ocr_matches_are_not_learned(self, learner):
        s = learner()
        shop = make_shop(s, [11, 2, 3, 4, 5])
        s._slot_sigs = [sc._slot_signature(f) for f in s._slice_slots(shop)]
        s._learn_from_ocr([(0, "Vex", 0.85), None, None, None, None], s._slice_slots(shop))
        assert s._portraits.count("Vex") == 0

    def test_a_second_look_of_a_known_champion_is_added_as_another_sample(self, learner):
        """Dáng khác của cùng một tướng (skin/hiệu ứng) mà ảnh đã học không khớp: sweep OCR đọc ra → học thêm mẫu."""
        s = learner()
        teach(s, {"Vex": 11})
        shop = make_shop(s, [21, 2, 3, 4, 5])
        s._slot_sigs = [sc._slot_signature(f) for f in s._slice_slots(shop)]
        s._learn_from_ocr([(0, "Vex", 1.0), None, None, None, None], s._slice_slots(shop))
        assert s._portraits.count("Vex") == 2

    def test_off_when_learning_is_disabled(self, make_scanner):
        s = make_scanner()
        s._learn_from_ocr([(0, "Vex", 1.0), None, None, None, None], [None] * 5)  # không lỗi, không làm gì


class TestStallDiagnostics:
    def test_slow_loop_is_logged_with_a_breakdown(self, learner):
        s = learner()
        s._grab_ms, s._buy_ms = 300.0, 50.0
        s._log_if_stalled(900.0)
        assert len(learner.logs) == 1
        line = learner.logs[0]
        assert "Vòng quét chậm 900 ms" in line and "chụp màn hình 300 ms" in line and "mua 50 ms" in line and "còn lại 550 ms" in line

    def test_fast_loops_are_not_logged(self, learner):
        s = learner()
        s._log_if_stalled(sc.STALL_LOG_MS - 1)
        assert learner.logs == []

    def test_log_is_capped(self, learner):
        s = learner()
        for _ in range(sc.STALL_LOG_MAX + 15):
            s._log_if_stalled(1000.0)
        assert len(learner.logs) == sc.STALL_LOG_MAX

    def test_scan_once_records_capture_and_buy_time(self, learner, clicks):
        s = learner()
        shop = make_shop(s, [1, 2, 3, 4, 5])

        def slow_grab():
            time.sleep(0.03)
            return shop

        s._grab_shop = slow_grab
        s._ocr_pool = None
        s.detect_by_name = False
        s._scan_once({})
        assert s._grab_ms >= 25 and len(s._capture_ms) == 1

    def test_buy_batch_time_is_accumulated(self, learner, clicks):
        s = learner()
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: (time.sleep(0.02), shop)[1]
        s._buy_batch([(0, "Vex", 1.0, "tên", s._slice_slots(shop)[0])], {})
        assert s._buy_ms >= 15 and clicks

    def test_summary_reports_capture_speed(self, learner):
        s = learner()
        s._capture_ms.extend([2.0, 4.0, 40.0])
        s._log_loop_summary()
        line = next(m for m in learner.logs if m.startswith("Chụp màn hình"))
        assert "3 lần" in line and "mss" in line and "chậm nhất 40 ms" in line
