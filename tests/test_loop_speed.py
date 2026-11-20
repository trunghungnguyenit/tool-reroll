"""Chu kỳ quét tối thiểu: nhãn từng ghi '0 = nhanh nhất ≈ 1 ms/vòng' trong khi một lần chụp màn hình đã mất ~7 ms.
Giờ chu kỳ THỰC được đo và hiển thị, thay vì hứa một con số cố định."""

import time
from pathlib import Path

import pytest

import core.controller as ctl
import core.scanner as sc

ROOT = Path(__file__).resolve().parent.parent


class TestLoopStats:
    def feed(self, stats, periods, start=0.0, step=0.125):  # 0.125 = nhị phân chính xác, không sai số cộng dồn
        now = start
        for p in periods:
            now += step
            stats.add(p, now)
        return now

    def test_summary_of_nothing_is_none(self):
        assert sc.LoopStats().summary() is None

    def test_summary_values(self):
        s = sc.LoopStats()
        self.feed(s, [10.0, 20.0, 30.0, 40.0])
        r = s.summary()
        assert r["count"] == 4 and r["avg_ms"] == 25.0 and r["max_ms"] == 40.0

    def test_p95_catches_rare_slow_loops_that_the_average_hides(self):
        s = sc.LoopStats()
        self.feed(s, [9.0] * 95 + [120.0] * 5)  # 5% vòng bị OCR làm chậm
        r = s.summary()
        assert r["avg_ms"] == pytest.approx(14.55) and r["p95_ms"] == 120.0 and r["max_ms"] == 120.0

    def test_p95_of_uniform_samples_is_that_value(self):
        s = sc.LoopStats()
        self.feed(s, [9.0] * 50)
        assert s.summary()["p95_ms"] == 9.0

    def test_single_sample(self):
        s = sc.LoopStats()
        s.add(8.0, 0.0)
        assert s.summary() == {"count": 1, "avg_ms": 8.0, "p95_ms": 8.0, "max_ms": 8.0}

    def test_sample_memory_is_bounded_but_counters_are_exact(self):
        s = sc.LoopStats(max_samples=100)
        self.feed(s, [5.0] * 1000)
        assert s.count == 1000 and len(s._all) == 100 and s.summary()["avg_ms"] == 5.0

    def test_window_emits_once_per_second_with_that_windows_numbers(self):
        s = sc.LoopStats(window_s=1.0)
        now = self.feed(s, [10.0] * 4)  # 0.5 s
        assert s.take_window(now) is None
        now = self.feed(s, [30.0] * 5, start=now)  # tới 1.125 s, cửa sổ bắt đầu từ 0.125 → đủ 1 s
        snap = s.take_window(now)
        assert snap["count"] == 9 and snap["avg_ms"] == pytest.approx((40 + 150) / 9) and snap["max_ms"] == 30.0
        assert s.take_window(now) is None  # vừa phát xong

    def test_each_window_is_independent(self):
        s = sc.LoopStats(window_s=1.0)
        now = self.feed(s, [10.0] * 9)
        assert s.take_window(now)["avg_ms"] == 10.0
        now = self.feed(s, [50.0] * 9, start=now)
        assert s.take_window(now)["avg_ms"] == 50.0

    def test_no_window_before_any_sample(self):
        assert sc.LoopStats().take_window(100.0) is None


class TestFormat:
    def test_text_has_period_rate_and_worst_case(self):
        assert sc.format_loop_speed(9.0, 25.4) == "9.0 ms/vòng (≈ 111 vòng/giây), chậm nhất 25 ms"

    def test_worst_case_is_optional(self):
        assert sc.format_loop_speed(30.0) == "30.0 ms/vòng (≈ 33 vòng/giây)"

    def test_zero_does_not_divide_by_zero(self):
        assert "vòng/giây" in sc.format_loop_speed(0.0)


def wait_until(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class TestScannerReportsRealPeriod:
    @pytest.fixture
    def run(self, make_scanner):
        def runner(interval_ms, seconds, **kw):
            snaps, logs = [], []
            s = make_scanner(scan_interval_ms=interval_ms, on_stats=snaps.append, on_log=logs.append, **kw)
            s.loop_stats = sc.LoopStats(window_s=0.2)  # cửa sổ ngắn để test nhanh; logic y hệt cửa sổ 1 giây
            s._scan_once = lambda cooldown: True  # bỏ phần chụp/OCR để chỉ đo nhịp nghỉ
            s.start()
            time.sleep(seconds)
            s.stop()
            s._thread.join(3)
            return s, snaps, logs

        return runner

    def test_period_is_never_shorter_than_the_configured_minimum(self, run):
        """Bất biến cốt lõi của 'chu kỳ tối thiểu': mọi chu kỳ đo được >= giá trị đặt."""
        s, snaps, logs = run(20, 0.9)
        assert snaps, "phải có ít nhất 1 lần báo mỗi cửa sổ"
        assert all(x["avg_ms"] >= 19.0 for x in snaps)
        assert s.loop_stats.summary()["max_ms"] >= 20.0

    def test_zero_setting_is_floored_by_the_cpu_yield(self, run):
        """Đặt 0 ms vẫn nghỉ >= MIN_SLEEP_MS mỗi vòng, nên chu kỳ thực không bao giờ là 0."""
        s, snaps, logs = run(0, 0.7)
        assert snaps and all(x["avg_ms"] >= sc.MIN_SLEEP_MS for x in snaps)

    def test_snapshots_arrive_once_per_window(self, run):
        s, snaps, logs = run(10, 1.1)  # cửa sổ 0.2 s → khoảng 5 lần
        assert 3 <= len(snaps) <= 6
        assert all(set(x) == {"avg_ms", "max_ms", "count"} for x in snaps)

    def test_summary_is_logged_once_when_it_stops(self, run):
        s, snaps, logs = run(10, 0.6)
        summaries = [line for line in logs if line.startswith("Quét:")]
        assert len(summaries) == 1
        assert "vòng" in summaries[0] and "p95" in summaries[0] and "chậm nhất" in summaries[0]

    def test_no_summary_for_a_run_that_was_too_short_to_mean_anything(self, make_scanner):
        logs = []
        s = make_scanner(scan_interval_ms=100, on_log=logs.append)
        s._scan_once = lambda cooldown: True
        s.start()
        time.sleep(0.25)  # ~3 vòng < MIN_LOOPS_FOR_SUMMARY
        s.stop()
        s._thread.join(3)
        assert not [line for line in logs if line.startswith("Quét:")]

    def test_a_crashing_ui_callback_does_not_stop_the_scan(self, make_scanner):
        """Giao diện đã đóng thì root.after ném lỗi; thread quét không được chết vì thế."""
        calls = {"n": 0}

        def broken(snap):
            calls["n"] += 1
            raise RuntimeError("main thread is not in main loop")

        s = make_scanner(scan_interval_ms=10, on_stats=broken, on_log=broken)
        s.loop_stats = sc.LoopStats(window_s=0.1)
        s._scan_once = lambda cooldown: True
        s.start()
        try:
            assert wait_until(lambda: calls["n"] >= 2, 5)
            assert s.is_running
        finally:
            s.stop()
            s._thread.join(3)

    def test_failed_grabs_do_not_count_as_loops(self, make_scanner):
        s = make_scanner(scan_interval_ms=5)
        s._scan_once = lambda cooldown: False  # chụp lỗi → vòng không hoàn tất
        s._running = True
        runs = {"n": 0}

        def scan(cd):
            runs["n"] += 1
            if runs["n"] >= 30:
                s._running = False
            return False

        s._scan_once = scan
        s._run_loop()
        assert s.loop_stats.count == 0

    def test_without_callbacks_nothing_breaks(self, make_scanner):
        s = make_scanner(scan_interval_ms=5)
        s._scan_once = lambda cooldown: True
        s.start()
        time.sleep(0.3)
        s.stop()
        s._thread.join(3)
        assert s.loop_stats.count > 0


class TestLabelWording:
    """Chốt chặn cho đúng lời hứa sai trước đây."""

    ROOT = Path(__file__).resolve().parent.parent
    SOURCE = "\n".join((ROOT / f).read_text(encoding="utf-8") for f in ("ui/main_window.py", "core/controller.py"))

    def test_label_is_a_minimum_period_not_a_speed(self):
        assert "Chu kỳ quét tối thiểu" in self.SOURCE and "Tốc độ quét" not in self.SOURCE

    def test_no_fixed_one_millisecond_promise(self):
        assert "≈ 1 ms" not in self.SOURCE and "1 ms/vòng" not in self.SOURCE

    def test_idle_hint_explains_the_real_limit(self):
        assert "thời gian chụp màn hình" in ctl.SPEED_IDLE_TEXT
