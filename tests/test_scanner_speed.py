"""Tối ưu tốc độ bắt tướng khi roll liên tục: mua cả loạt với MỘT lần chụp xác nhận, quét OCR theo thay đổi, quét dày khi bấm
roll, đo độ trễ 'thẻ hiện → click' và ghi lý do bỏ click vào Nhật ký."""

import numpy as np
import pytest

import core.scanner as sc
from tests.helpers import make_shop


def running(make_scanner, **kw):
    s = make_scanner(**kw)
    s._running = True
    return s


class Log:
    def __init__(self):
        self.lines = []

    def __call__(self, msg):
        self.lines.append(msg)

    def text(self):
        return "\n".join(self.lines)


def cands(s, shop, slots, names=("Vex", "Zed", "Jinx", "Ahri", "Lux"), method="ảnh"):
    parts = s._slice_slots(shop)
    return [(i, names[i], 0.9, method, parts[i]) for i in slots]


class TestBuyBatch:
    def test_one_confirmation_capture_for_the_whole_batch(self, make_scanner, clicks):
        s = running(make_scanner, require_game_foreground=False)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        grabs = []
        s._grab_shop = lambda: grabs.append(1) or shop
        s._buy_batch(cands(s, shop, [0, 2, 4]), {})
        assert len(grabs) == 1  # trước đây: mỗi ô một lần chụp lại (~12 ms mỗi lần)
        assert clicks == [s.slot_centers[0], s.slot_centers[2], s.slot_centers[4]]

    def test_all_matches_notify_and_lock(self, make_scanner, clicks):
        got = []
        s = running(make_scanner, require_game_foreground=False, on_match=lambda *a: got.append(a))
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s._buy_batch(cands(s, shop, [1, 3]), {})
        assert [(g[0], g[1]) for g in got] == [("Zed", 2), ("Ahri", 4)] and set(s._locked) == {1, 3}

    def test_only_the_changed_slot_is_dropped(self, make_scanner, clicks):
        s = running(make_scanner, require_game_foreground=False)
        analyzed = make_shop(s, [1, 2, 3, 4, 5])
        current = make_shop(s, [1, 2, 99, 4, 5])  # ô 3 vừa roll sang thẻ khác
        s._grab_shop = lambda: current
        s._buy_batch(cands(s, analyzed, [0, 2, 4]), {})
        assert clicks == [s.slot_centers[0], s.slot_centers[4]]

    def test_changed_card_is_reported_with_correlation(self, make_scanner, clicks):
        log = Log()
        s = running(make_scanner, require_game_foreground=False, on_log=log)
        analyzed = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: make_shop(s, [99, 2, 3, 4, 5])
        s._buy_batch(cands(s, analyzed, [0]), {})
        assert clicks == []
        assert "Bỏ click Vex ô 1: thẻ đã đổi giữa lúc nhận diện và xác nhận" in log.text() and "< 0.80" in log.text()

    def test_repeated_skip_reason_is_throttled_and_counted(self, make_scanner, clicks, monkeypatch):
        log = Log()
        clock = {"t": 100.0}
        s = running(make_scanner, require_game_foreground=False, on_log=log)
        monkeypatch.setattr(sc.time, "monotonic", lambda: clock["t"])
        analyzed = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: make_shop(s, [99, 2, 3, 4, 5])
        for _ in range(4):
            s._buy_batch(cands(s, analyzed, [0]), {})
        assert len(log.lines) == 1  # 3 lần sau bị nén trong cùng giây
        clock["t"] += sc.SKIP_LOG_EVERY_S + 0.1
        s._buy_batch(cands(s, analyzed, [0]), {})
        assert len(log.lines) == 2 and "(+3 lần nữa trong giây trước)" in log.lines[1]

    def test_different_slots_are_logged_separately(self, make_scanner, clicks):
        log = Log()
        s = running(make_scanner, require_game_foreground=False, on_log=log)
        analyzed = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: make_shop(s, [99, 98, 3, 4, 5])
        s._buy_batch(cands(s, analyzed, [0, 1]), {})
        assert len(log.lines) == 2

    def test_cooldown_duplicates_are_silent_and_cost_no_capture(self, make_scanner, clicks):
        log = Log()
        s = running(make_scanner, require_game_foreground=False, on_log=log)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        grabs = []
        s._grab_shop = lambda: grabs.append(1) or shop
        cd = {(0, "Vex"): sc.time.perf_counter()}
        s._buy_batch(cands(s, shop, [0]), cd)
        assert grabs == [] and clicks == [] and log.lines == []

    def test_foreground_blocked_means_no_capture_and_no_click(self, make_scanner, clicks, foreground):
        foreground["value"] = False
        statuses = []
        s = running(make_scanner, on_status=statuses.append)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        grabs = []
        s._grab_shop = lambda: grabs.append(1) or shop
        s._buy_batch(cands(s, shop, [0]), {})
        assert grabs == [] and clicks == [] and s._click_blocked and statuses == ["Game không ở foreground — tạm không click"]

    def test_capture_failure_is_reported(self, make_scanner, clicks):
        log = Log()
        s = running(make_scanner, require_game_foreground=False, on_log=log)
        s._grab_shop = lambda: None
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._buy_batch(cands(s, shop, [0]), {})
        assert clicks == [] and "không chụp lại được shop" in log.text()

    def test_stop_during_verification_prevents_click(self, make_scanner, clicks):
        s = running(make_scanner, require_game_foreground=False)
        shop = make_shop(s, [1, 2, 3, 4, 5])

        def grab():
            s._running = False
            return shop

        s._grab_shop = grab
        s._buy_batch(cands(s, shop, [0]), {})
        assert clicks == []

    def test_locked_slot_is_not_clicked_twice_in_a_batch(self, make_scanner, clicks):
        s = running(make_scanner, require_game_foreground=False)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s._buy_batch(cands(s, shop, [0]), {})
        s._buy_batch(cands(s, shop, [0]), {})
        assert len(clicks) == 1


class TestLatencyReporting:
    def test_latency_line_with_breakdown_and_samples(self, make_scanner, clicks):
        log = Log()
        s = running(make_scanner, require_game_foreground=False, on_log=log)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s._first_seen[2] = sc.time.perf_counter() - 0.030  # thẻ hiện cách đây 30 ms
        s._buy_batch(cands(s, shop, [2]), {})
        assert len(s.latencies_ms) == 1 and 29 < s.latencies_ms[0] < 200
        assert "Jinx ô 3:" in log.text() and "ms từ lúc thẻ hiện (nhận diện" in log.text() and "xác nhận" in log.text()

    def test_no_latency_when_appearance_unknown(self, make_scanner, clicks):
        s = running(make_scanner, require_game_foreground=False)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s._buy_batch(cands(s, shop, [0]), {})
        assert len(s.latencies_ms) == 0

    def test_summary_on_stop_includes_latency_percentiles(self, make_scanner):
        log = Log()
        s = make_scanner(on_log=log)
        s.latencies_ms.extend([20.0, 30.0, 40.0, 100.0])
        s._log_loop_summary()
        assert "Độ trễ mua (thẻ hiện → click): 4 lần, trung bình 48 ms" in log.text() and "chậm nhất 100 ms" in log.text()

    def test_samples_are_bounded(self, make_scanner):
        s = make_scanner()
        s.latencies_ms.extend(range(sc.MAX_LATENCY_SAMPLES + 500))
        assert len(s.latencies_ms) == sc.MAX_LATENCY_SAMPLES

    def test_end_to_end_through_scan_once_measures_from_first_sight(self, make_scanner, clicks, monkeypatch):
        log = Log()
        s = running(make_scanner, require_game_foreground=False, detect_by_name=True, on_log=log)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: "Vex" if int(frame[0, 0, 0]) >= 0 else "")
        s._ocr_pool = None
        s._scan_once({})
        assert clicks and any("ms từ lúc thẻ hiện" in ln for ln in log.lines)


class TestChangeTracking:
    def sigs(self, s, shop):
        return [sc._slot_signature(f) for f in s._slice_slots(shop)]

    def test_first_frame_marks_every_slot_changed(self, make_scanner):
        s = make_scanner()
        shop = make_shop(s, [1, 2, 3, 4, 5])
        assert s._track_changes(self.sigs(s, shop), 10.0) == {0, 1, 2, 3, 4}
        assert s._first_seen == [10.0] * 5 and all(abs(u - 10.6) < 1e-9 for u in s._settle_until)

    def test_same_frame_changes_nothing(self, make_scanner):
        s = make_scanner()
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._track_changes(self.sigs(s, shop), 10.0)
        assert s._track_changes(self.sigs(s, shop), 10.02) == set()

    def test_only_the_rerolled_slot_changes(self, make_scanner):
        s = make_scanner()
        s._track_changes(self.sigs(s, make_shop(s, [1, 2, 3, 4, 5])), 10.0)
        assert s._track_changes(self.sigs(s, make_shop(s, [1, 2, 77, 4, 5])), 10.5) == {2}
        assert s._first_seen[2] == 10.5 and s._first_seen[0] == 10.0

    def test_animation_frames_keep_the_first_sighting(self, make_scanner):
        """Thẻ đổi liên tục (hiệu ứng) trong chuỗi ngắn: lúc thẻ hiện là khung ĐẦU TIÊN, không bị đẩy về khung cuối."""
        s = make_scanner()
        s._track_changes(self.sigs(s, make_shop(s, [1, 2, 3, 4, 5])), 10.0)
        s._track_changes(self.sigs(s, make_shop(s, [1, 2, 70, 4, 5])), 11.000)
        s._track_changes(self.sigs(s, make_shop(s, [1, 2, 71, 4, 5])), 11.016)
        s._track_changes(self.sigs(s, make_shop(s, [1, 2, 72, 4, 5])), 11.032)
        assert s._first_seen[2] == 11.000 and s._last_change[2] == 11.032

    def test_next_roll_after_a_gap_is_a_new_sighting(self, make_scanner):
        s = make_scanner()
        s._track_changes(self.sigs(s, make_shop(s, [1, 2, 3, 4, 5])), 10.0)
        s._track_changes(self.sigs(s, make_shop(s, [1, 2, 70, 4, 5])), 11.0)
        s._track_changes(self.sigs(s, make_shop(s, [1, 2, 71, 4, 5])), 11.0 + sc.CHAIN_GAP_S + 0.05)
        assert s._first_seen[2] == pytest.approx(11.0 + sc.CHAIN_GAP_S + 0.05)


class TestOcrScheduling:
    def test_new_slots_are_ocr_immediately_even_inside_the_interval(self, make_scanner):
        s = make_scanner(name_scan_interval_ms=50)
        s._last_name_scan = 100.0
        assert s._ocr_due_slots(100.01, {2}) == [2]

    def test_static_shop_is_not_ocr_every_interval(self, make_scanner):
        s = make_scanner(name_scan_interval_ms=50)
        s._settle_until = [0.0] * 5
        s._last_idle_ocr = 100.0
        s._last_name_scan = 0.0
        assert s._ocr_due_slots(100.2, set()) == []

    def test_settling_slots_are_retried_each_interval_but_not_before(self, make_scanner):
        s = make_scanner(name_scan_interval_ms=50)
        s._settle_until = [0.0, 0.0, 101.0, 0.0, 0.0]
        s._last_idle_ocr = 100.0
        s._last_name_scan = 100.0
        assert s._ocr_due_slots(100.02, set()) == []  # chưa tới chu kỳ
        assert s._ocr_due_slots(100.06, set()) == [2]

    def test_idle_sweep_is_a_safety_net_for_a_static_shop(self, make_scanner):
        s = make_scanner(name_scan_interval_ms=50)
        s._last_idle_ocr = 100.0
        assert s._ocr_due_slots(100.2, set()) == []
        assert s._ocr_due_slots(100.0 + sc.IDLE_OCR_S + 0.01, set()) == [0, 1, 2, 3, 4]
        assert s._last_idle_ocr == pytest.approx(100.0 + sc.IDLE_OCR_S + 0.01)

    def test_roll_burst_skips_the_interval_wait_but_does_not_force_ocr_of_every_slot(self, make_scanner):
        s = make_scanner(name_scan_interval_ms=50)
        s._settle_until = [0.0, 0.0, 10**9, 0.0, 0.0]
        s._last_idle_ocr = sc.time.perf_counter()
        s._last_name_scan = sc.time.perf_counter()  # vừa OCR xong: bình thường phải chờ 50 ms
        assert s._ocr_due_slots(sc.time.perf_counter(), set()) == []
        s.notify_roll()
        assert s._ocr_due_slots(sc.time.perf_counter(), set()) == [2]  # chỉ ô đang ổn định, không phải cả 5

    def test_burst_without_any_settling_slot_does_no_ocr(self, make_scanner):
        s = make_scanner(name_scan_interval_ms=50)
        s._last_idle_ocr = sc.time.perf_counter()
        s.notify_roll()
        assert s._ocr_due_slots(sc.time.perf_counter(), set()) == []

    def test_burst_expires(self, make_scanner):
        s = make_scanner(name_scan_interval_ms=50)
        s._last_idle_ocr = 200.0
        s._burst_until = 100.0
        assert s._ocr_due_slots(100.2, set()) == []

    def test_blocked_click_keeps_scanning_all_slots_to_buy_when_game_returns(self, make_scanner):
        s = make_scanner(name_scan_interval_ms=50)
        s._click_blocked = True
        s._last_idle_ocr = 100.0
        s._last_blocked_ocr = 99.0
        assert s._ocr_due_slots(100.2, set()) == [0, 1, 2, 3, 4]

    def test_blocked_scan_of_all_slots_is_throttled_so_ocr_does_not_pile_up(self, make_scanner):
        """Bị chặn mà vẫn OCR cả 5 ô mỗi 50 ms thì OCR (cùng CPU với game) bị kẹt: chỉ làm mỗi BLOCKED_OCR_S."""
        s = make_scanner(name_scan_interval_ms=50)
        s._click_blocked = True
        s._last_idle_ocr = 100.0
        s._last_blocked_ocr = 100.0
        assert s._ocr_due_slots(100.1, set()) == []
        assert s._ocr_due_slots(100.0 + sc.BLOCKED_OCR_S + 0.01, set()) == [0, 1, 2, 3, 4]

    def test_zero_interval_ocr_every_loop_for_settling_slots(self, make_scanner):
        s = make_scanner(name_scan_interval_ms=0)
        s._settle_until = [0.0, 105.0, 0.0, 0.0, 0.0]
        s._last_idle_ocr = 100.0
        s._last_name_scan = 100.0
        assert s._ocr_due_slots(100.001, set()) == [1]

    def test_notify_roll_sets_deadline_in_the_future(self, make_scanner):
        s = make_scanner()
        before = sc.time.perf_counter()
        s.notify_roll()
        assert before + sc.BURST_S - 0.01 <= s._burst_until <= sc.time.perf_counter() + sc.BURST_S


class TestPartialOcr:
    def ocr_frames(self, make_scanner, monkeypatch):
        seen = []
        s = make_scanner()
        s._ocr_pool = None
        monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: seen.append(int(frame[0, 0, 0])) or "Vex")
        return s, seen

    def shop_with_markers(self, s):
        shop = np.zeros((s.shop_region["height"], s.shop_region["width"], 3), np.uint8)
        y0 = int(shop.shape[0] * s._card_top_ratio)
        w = shop.shape[1]
        for i in range(5):
            shop[y0:, i * w // 5:(i + 1) * w // 5] = (i + 1) * 10
        return shop

    def test_only_requested_slots_are_read_and_indices_are_preserved(self, make_scanner, monkeypatch):
        s, seen = self.ocr_frames(make_scanner, monkeypatch)
        slots = s._slice_slots(self.shop_with_markers(s))
        results, empties = s._scan_names_parallel(slots, [1, 3])
        assert sorted(seen) == [20, 40]
        assert [r[0] if r else None for r in results] == [None, 1, None, 3, None]
        assert empties is None  # OCR một phần: không dùng để đánh giá sức khỏe OCR

    def test_full_sweep_reports_empty_count(self, make_scanner, monkeypatch):
        s = make_scanner()
        s._ocr_pool = None
        texts = {10: "Vex", 20: "", 30: "", 40: "", 50: ""}
        monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: texts[int(frame[0, 0, 0])])
        slots = s._slice_slots(self.shop_with_markers(s))
        results, empties = s._scan_names_parallel(slots)
        assert empties == 4 and results[0] is not None

    def test_partial_ocr_never_triggers_ocr_health_tracking(self, make_scanner, monkeypatch):
        s, _ = self.ocr_frames(make_scanner, monkeypatch)
        health = []
        s._track_ocr_health = lambda e: health.append(e)
        s._running = True
        cur = {"shop": make_shop(s, [1, 2, 3, 4, 5])}
        s._grab_shop = lambda: cur["shop"]
        s._scan_once({})  # khung đầu: cả 5 ô vừa đổi → OCR đủ 5 ô → có đánh giá sức khỏe
        assert health == [0]
        s._settle_until = [0.0] * 5
        s._last_idle_ocr = sc.time.perf_counter()
        cur["shop"] = make_shop(s, [1, 2, 77, 4, 5])
        s._scan_once({})  # chỉ ô 3 đổi → OCR một phần → KHÔNG đánh giá
        assert health == [0]


class TestScanOrdering:
    def test_image_buy_happens_before_ocr_runs(self, make_scanner, clicks, monkeypatch):
        """Nhánh ảnh mua NGAY, không phải chờ OCR ~13 ms của cùng vòng."""
        order = []
        monkeypatch.setattr(sc, "buy_slot_async", lambda c: order.append("click"))
        s = running(make_scanner, require_game_foreground=False, detect_by_image=True, detect_by_name=True)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s.detect_by_image = True
        s._match_image_fast = lambda frame: ("Vex", 0.95) if not order else None  # chỉ ô đầu trúng
        s._ocr_pool = None
        monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: order.append("ocr") or "")
        s._scan_once({})
        assert order and order[0] == "click" and "ocr" in order

    def test_static_shop_skips_ocr_after_settling(self, make_scanner, monkeypatch):
        calls = []
        s = running(make_scanner, require_game_foreground=False, name_scan_interval_ms=0)
        s._ocr_pool = None
        monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: calls.append(1) or "")
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s._scan_once({})
        assert len(calls) == 5  # khung đầu: 5 ô
        calls.clear()
        s._settle_until = [0.0] * 5
        s._last_idle_ocr = sc.time.perf_counter()
        s._scan_once({})
        assert calls == []  # shop đứng yên và đã ổn định: không OCR thừa

    def test_reroll_of_one_slot_ocrs_only_that_slot(self, make_scanner, monkeypatch):
        calls = []
        s = running(make_scanner, require_game_foreground=False, name_scan_interval_ms=50)
        s._ocr_pool = None
        monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: calls.append(1) or "")
        shops = [make_shop(s, [1, 2, 3, 4, 5]), make_shop(s, [1, 2, 77, 4, 5])]
        cur = {"shop": shops[0]}
        s._grab_shop = lambda: cur["shop"]
        s._scan_once({})
        calls.clear()
        s._settle_until = [0.0] * 5
        s._last_idle_ocr = sc.time.perf_counter()
        cur["shop"] = shops[1]
        s._scan_once({})
        assert len(calls) == 1

    def test_dense_loop_does_not_sleep_beyond_the_minimum_after_a_roll(self, make_scanner, monkeypatch):
        sleeps = []
        monkeypatch.setattr(sc.time, "sleep", lambda secs: sleeps.append(secs))
        s = make_scanner(scan_interval_ms=50)
        s._running = True
        shop = make_shop(s, [1, 2, 3, 4, 5])
        n = {"i": 0}

        def grab():
            n["i"] += 1
            if n["i"] >= 3:
                s._running = False
            return shop

        s._grab_shop = grab
        s.notify_roll()
        s._ocr_pool = None
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "")
        s._run_loop()
        assert sleeps and max(sleeps) <= sc.MIN_SLEEP_MS / 1000 + 1e-9


class TestStaticFrameSkip:
    def scanner(self, make_scanner, **kw):
        kw.setdefault("require_game_foreground", False)
        s = running(make_scanner, **kw)
        s._ocr_pool = None
        self.matches = []
        self.ocr = []
        s._match_image_fast = lambda f: self.matches.append(1) or None
        return s

    def test_identical_frame_skips_signatures_and_image_matching(self, make_scanner, monkeypatch):
        s = self.scanner(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop.copy()
        s._scan_once({})
        assert len(self.matches) == 5
        s._scan_once({})
        assert len(self.matches) == 5  # khung y hệt: không so khớp lại

    def test_changed_frame_is_processed_again(self, make_scanner):
        s = self.scanner(make_scanner)
        cur = {"shop": make_shop(s, [1, 2, 3, 4, 5])}
        s._grab_shop = lambda: cur["shop"]
        s._scan_once({})
        cur["shop"] = make_shop(s, [1, 2, 77, 4, 5])
        s._scan_once({})
        assert len(self.matches) == 10

    def test_a_single_changed_pixel_counts_as_change(self, make_scanner):
        s = self.scanner(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        frames = [shop.copy(), shop.copy()]
        frames[1][100, 100, 0] ^= 1
        it = iter(frames)
        s._grab_shop = lambda: next(it)
        s._scan_once({})
        s._scan_once({})
        assert len(self.matches) == 10

    def test_frame_after_a_match_is_always_reprocessed(self, make_scanner, clicks):
        """Lượt trước có ứng viên (mua rồi hoặc chưa xong) thì không coi khung đứng yên là 'không có gì mới'."""
        s = running(make_scanner, require_game_foreground=False, detect_by_name=False)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop.copy()
        calls = []
        s._match_image_fast = lambda f: calls.append(1) or (("Vex", 0.9) if len(calls) == 1 else None)
        s._scan_once({})
        n = len(calls)
        s._scan_once({})
        assert len(calls) == n + 5

    def test_blocked_click_keeps_reprocessing_static_frames(self, make_scanner, foreground):
        s = self.scanner(make_scanner, require_game_foreground=True)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop.copy()
        s._scan_once({})
        s._click_blocked = True
        foreground["value"] = False  # game vẫn không ở trước (nếu game quay lại thì cờ tự xóa, xem test_scanner)
        s._scan_once({})
        assert len(self.matches) == 10

    def test_ocr_schedule_still_runs_on_static_frames(self, make_scanner, monkeypatch):
        calls = []
        s = self.scanner(make_scanner, name_scan_interval_ms=0)
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: calls.append(1) or "")
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop.copy()
        s._scan_once({})
        calls.clear()
        s._scan_once({})  # khung y hệt nhưng các ô còn đang 'ổn định' (SETTLE_S): OCR vẫn phải chạy lại
        assert len(calls) == 5

    def test_idle_sweep_works_on_a_static_shop(self, make_scanner, monkeypatch):
        calls = []
        s = self.scanner(make_scanner, name_scan_interval_ms=0)
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: calls.append(1) or "")
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop.copy()
        s._scan_once({})
        s._settle_until = [0.0] * 5
        s._last_idle_ocr = 0.0
        calls.clear()
        s._scan_once({})
        assert len(calls) == 5  # lưới an toàn: shop đứng yên vẫn được OCR lại mỗi IDLE_OCR_S
