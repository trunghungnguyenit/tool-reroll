import time

import numpy as np
import pytest

import core.scanner as sc
from tests.helpers import CENTERS, REGION, make_card, make_shop


def new_running(make_scanner, **kw):
    s = make_scanner(**kw)
    s._running = True  # _buy_batch chỉ click khi đang chạy; không cần dựng thread thật
    return s


def attempt(s, analyzed_shop, current_shop, slot=0, name="Vex", cooldown=None, method="tên"):
    """Mô phỏng: nhận diện trên analyzed_shop, tới lúc click thì màn hình đang là current_shop."""
    s._grab_shop = lambda: current_shop
    s._buy_batch([(slot, name, 1.0, method, s._slice_slots(analyzed_shop)[slot])], {} if cooldown is None else cooldown)


class TestGeometry:
    def test_slots_split_region_evenly(self, make_scanner):
        s = make_scanner()
        slots = s._slice_slots(np.zeros((REGION["height"], REGION["width"], 3), np.uint8))
        assert len(slots) == 5
        assert sum(x.shape[1] for x in slots) == REGION["width"]
        assert max(x.shape[1] for x in slots) - min(x.shape[1] for x in slots) <= 1

    def test_slots_ignore_click_points(self, make_scanner):
        """Điểm click lệch/ngoài vùng không được làm đổi cách cắt ô."""
        shop = np.zeros((REGION["height"], REGION["width"], 3), np.uint8)
        good = make_scanner()._slice_slots(shop)
        bad = make_scanner(slot_centers=[(0, 0)] * 5)._slice_slots(shop)
        assert [a.shape for a in good] == [b.shape for b in bad]

    def test_find_points_outside_region(self):
        pts = [(0, 0), (150, 100), (1099, 249), (1100, 100), (150, 250)]
        assert sc.find_points_outside_region(REGION, pts) == [1, 4, 5]
        assert sc.find_points_outside_region(REGION, CENTERS) == []


class TestStart:
    def test_refuses_points_outside_region(self, make_scanner):
        msgs = []
        s = make_scanner(slot_centers=[(0, 0)] * 5, on_status=msgs.append)
        s.start()
        assert not s.is_running and any("ngoài vùng" in m for m in msgs)

    def test_refuses_without_any_detection_mode(self, make_scanner):
        s = make_scanner(detect_by_name=False)
        s.start()
        assert not s.is_running


class TestStaleFrameProtection:
    def test_unchanged_shop_clicks_once(self, make_scanner, clicks):
        s = new_running(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        attempt(s, shop, shop)
        assert clicks == [CENTERS[0]]

    def test_slot_rerolled_during_ocr_does_not_click(self, make_scanner, clicks):
        s = new_running(make_scanner)
        attempt(s, make_shop(s, [1, 2, 3, 4, 5]), make_shop(s, [9, 2, 3, 4, 5]))
        assert clicks == []

    def test_slot_already_bought_does_not_click(self, make_scanner, clicks):
        s = new_running(make_scanner)
        attempt(s, make_shop(s, [1, 2, 3, 4, 5]), make_shop(s, [1, 2, 3, 4, 5], empty=(0,)))
        assert clicks == []

    def test_hover_glow_and_noise_still_count_as_same_card(self, make_scanner, clicks):
        s = new_running(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        noisy = np.clip(
            shop.astype(np.int16) + 18 + np.random.default_rng(0).normal(0, 5, shop.shape), 0, 255
        ).astype(np.uint8)
        attempt(s, shop, noisy)
        assert len(clicks) == 1

    def test_failed_grab_does_not_click(self, make_scanner, clicks):
        s = new_running(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: None
        s._buy_batch([(0, "Vex", 1.0, "tên", s._slice_slots(shop)[0])], {})
        assert clicks == []

    def test_stop_during_verification_does_not_click(self, make_scanner, clicks):
        """Bấm DỪNG đúng lúc đang chụp lại để kiểm tra → không được click nốt."""
        s = new_running(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])

        def grab_then_stop():
            s._running = False
            return shop

        s._grab_shop = grab_then_stop
        s._buy_batch([(0, "Vex", 1.0, "tên", s._slice_slots(shop)[0])], {})
        assert clicks == []

    def test_not_running_does_not_click(self, make_scanner, clicks):
        s = make_scanner()  # _running = False
        shop = make_shop(s, [1, 2, 3, 4, 5])
        attempt(s, shop, shop)
        assert clicks == []


class TestSlotLock:
    def test_image_then_ocr_on_same_slot_clicks_once(self, make_scanner, clicks):
        s = new_running(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        attempt(s, shop, shop, method="ảnh", cooldown={})
        attempt(s, shop, shop, method="tên", cooldown={})  # cooldown mới nên chỉ khóa ô mới chặn được
        assert len(clicks) == 1

    def test_lock_released_after_slot_changes_then_buys_again(self, make_scanner, clicks):
        s = new_running(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        attempt(s, shop, shop)
        s._release_changed_locks(s._slice_slots(make_shop(s, [1, 2, 3, 4, 5], empty=(0,))))  # ô trống sau khi mua
        assert s._locked == {}
        attempt(s, shop, shop)  # roll ra lại tướng đó ở ô đó
        assert len(clicks) == 2

    def test_lock_kept_while_card_unchanged(self, make_scanner, clicks):
        """Hết vàng/đầy ghế: thẻ vẫn ở đó nên không click lặp."""
        s = new_running(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        attempt(s, shop, shop)
        s._release_changed_locks(s._slice_slots(shop))
        attempt(s, shop, shop)
        assert len(clicks) == 1

    def test_other_slots_not_blocked_by_lock(self, make_scanner, clicks):
        s = new_running(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        attempt(s, shop, shop, slot=0)
        attempt(s, shop, shop, slot=3)
        assert clicks == [CENTERS[0], CENTERS[3]]


class _Blocks:
    """Chỉ đếm các dòng 'Không click...' trong danh sách Nhật ký (bỏ các dòng chẩn đoán đi kèm lần đầu bị chặn)."""

    def __init__(self, logs):
        self._logs = logs

    def __len__(self):
        return sum(1 for m in self._logs if m.startswith("Không click"))


class TestForegroundGate:
    def test_blocked_when_game_not_foreground_and_status_reported_once(self, make_scanner, clicks, foreground):
        msgs = []
        s = new_running(make_scanner, on_status=msgs.append)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        foreground["value"] = False
        attempt(s, shop, shop)
        attempt(s, shop, shop)
        assert clicks == [] and len(msgs) == 1 and "foreground" in msgs[0]

    def test_resumes_when_game_regains_focus(self, make_scanner, clicks, foreground):
        msgs = []
        s = new_running(make_scanner, on_status=msgs.append)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        foreground["value"] = False
        attempt(s, shop, shop)
        foreground["value"] = True
        attempt(s, shop, shop)
        assert len(clicks) == 1 and msgs[-1] == "Đang quét shop..."

    def test_waits_for_game_to_settle_after_regaining_focus(self, make_scanner, clicks, foreground, monkeypatch):
        """Log thật: click gửi NGAY lúc game vừa lên trước (Alt-Tab) thì thẻ vẫn còn. Phải chờ cửa sổ kích hoạt xong rồi mới click."""
        monkeypatch.setattr(sc, "FOREGROUND_SETTLE_S", 0.35)
        msgs, logs = [], []
        s = new_running(make_scanner, on_status=msgs.append, on_log=logs.append)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        foreground["value"] = False
        attempt(s, shop, shop)
        blocked_logs = len(logs)
        foreground["value"] = True
        attempt(s, shop, shop)  # game vừa lên trước
        assert clicks == [] and s._click_blocked
        assert len(logs) == blocked_logs and msgs == ["Game không ở foreground — tạm không click"]  # đang chờ ≠ "không ở foreground"
        s._front_since -= 1.0  # game đã ở trước đủ lâu
        attempt(s, shop, shop)
        assert len(clicks) == 1 and not s._click_blocked and msgs[-1] == "Đang quét shop..."

    def test_leaving_the_game_again_restarts_the_settle_wait(self, make_scanner, clicks, foreground, monkeypatch):
        monkeypatch.setattr(sc, "FOREGROUND_SETTLE_S", 0.35)
        s = new_running(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        foreground["value"] = False
        attempt(s, shop, shop)
        foreground["value"] = True
        attempt(s, shop, shop)
        s._front_since -= 1.0
        foreground["value"] = False  # ra khỏi game trước khi click được
        attempt(s, shop, shop)
        assert s._front_since is None
        foreground["value"] = True
        attempt(s, shop, shop)
        assert clicks == []  # phải đợi lại từ đầu

    def test_game_in_front_from_the_start_is_not_delayed(self, make_scanner, clicks, foreground, monkeypatch):
        monkeypatch.setattr(sc, "FOREGROUND_SETTLE_S", 0.35)
        s = new_running(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        attempt(s, shop, shop)
        assert len(clicks) == 1

    def test_unconfirmed_click_reports_how_long_after_game_came_to_front(self, make_scanner, clicks, foreground):
        logs = []
        s = new_running(make_scanner, on_log=logs.append)
        s._click_unconfirmed(1, "Akali", 0.9, 0.04)
        s._click_unconfirmed(4, "Akali", 0.9)
        assert "Click được gửi 0.04 giây sau khi game lên trước" in logs[0]
        assert "Click được gửi" not in logs[1]

    def test_block_logs_which_window_is_in_front(self, make_scanner, clicks, foreground):
        """Bị chặn vì foreground thì Nhật ký phải nói cửa sổ nào đang ở trước (để phân biệt 'đang ở app khác' với 'không nhận ra game')."""
        logs = []
        s = new_running(make_scanner, on_log=logs.append)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        foreground["value"] = False
        attempt(s, shop, shop)
        assert logs[0].startswith("Không click") and "notepad.exe" in logs[0] and "RiotWindowClass" in logs[0]
        assert logs[1:] == ["Chẩn đoán: giả lập."]  # lần đầu của đợt bị chặn: kèm chẩn đoán môi trường

    def test_block_log_is_throttled_then_repeats_and_resets(self, make_scanner, clicks, foreground):
        all_logs, clock = [], {"t": 100.0}
        s = new_running(make_scanner, on_log=all_logs.append)
        logs = _Blocks(all_logs)
        s._now = lambda: clock["t"]
        shop = make_shop(s, [1, 2, 3, 4, 5])
        foreground["value"] = False
        attempt(s, shop, shop)
        clock["t"] += sc.FOREGROUND_LOG_EVERY_S - 1
        attempt(s, shop, shop)
        assert len(logs) == 1  # chưa đủ lâu: không ghi lại
        clock["t"] += 2
        attempt(s, shop, shop)
        assert len(logs) == 2  # còn bị chặn sau FOREGROUND_LOG_EVERY_S: nhắc lại
        foreground["value"] = True
        attempt(s, shop, shop)  # game quay lại foreground → click, xóa dấu
        foreground["value"] = False
        s._locked.clear()
        attempt(s, shop, shop)
        assert len(logs) == 3  # lần chặn mới ghi ngay, không chờ hết chu kỳ cũ

    def test_blocked_state_clears_by_itself_when_game_returns(self, make_scanner, clicks, foreground):
        """Trước đây cờ 'bị chặn' chỉ được xóa khi có ứng viên mua: màn hình mãi báo 'không ở foreground' và vòng quét cứ phải OCR cả 5 ô."""
        msgs, logs = [], []
        s = new_running(make_scanner, on_status=msgs.append, on_log=logs.append)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s._click_blocked = True
        foreground["value"] = False
        s._scan_once({})
        assert s._click_blocked is True
        foreground["value"] = True
        s._scan_once({})
        assert s._click_blocked is False and msgs[-1] == "Đang quét shop..."
        assert any("foreground trở lại" in m for m in logs)

    def test_check_can_be_disabled(self, make_scanner, clicks, foreground):
        s = new_running(make_scanner, require_game_foreground=False)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        foreground["value"] = False
        attempt(s, shop, shop)
        assert len(clicks) == 1


def wait_until(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestLoopResilience:
    def test_transient_errors_are_skipped_and_scan_continues(self, make_scanner):
        events, calls = [], {"n": 0}
        s = make_scanner(on_error=lambda m, f: events.append((m, f)))

        def flaky(cooldown):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise ValueError("thoáng qua")
            return True

        s._scan_once = flaky
        s.start()
        try:
            assert wait_until(lambda: calls["n"] > 6)
            assert s.is_running
            assert len(events) == 1 and events[0][1] is False  # chỉ báo lần lỗi đầu của đợt, không fatal
        finally:
            s.stop()

    def test_persistent_errors_stop_scanner_and_report_fatal(self, make_scanner, monkeypatch):
        monkeypatch.setattr(sc, "MAX_CONSECUTIVE_ERRORS", 3)
        events = []
        s = make_scanner(on_error=lambda m, f: events.append((m, f)))

        def broken(cooldown):
            raise RuntimeError("hỏng hẳn")

        s._scan_once = broken
        s.start()
        assert wait_until(lambda: not s.is_running)
        assert wait_until(lambda: any(f for _, f in events))
        fatal = [m for m, f in events if f]
        assert len(fatal) == 1 and "RuntimeError" in fatal[0] and "hỏng hẳn" in fatal[0]

    def test_grab_failing_too_long_stops_scanner(self, make_scanner, monkeypatch):
        monkeypatch.setattr(sc, "GRAB_FAIL_LIMIT_S", 0.2)
        events = []
        s = make_scanner(on_error=lambda m, f: events.append((m, f)))
        s._grab_shop = lambda: None
        s._last_grab_error = "OSError: demo"
        s.start()
        assert wait_until(lambda: any(f for _, f in events))
        assert not s.is_running
        assert "OSError: demo" in [m for m, f in events if f][0]

    def test_error_during_shutdown_is_not_reported(self, make_scanner):
        events = []
        s = make_scanner(on_error=lambda m, f: events.append((m, f)))

        def die(cooldown):
            s._running = False
            raise RuntimeError("lỗi do dọn dẹp")

        s._scan_once = die
        s.start()
        assert wait_until(lambda: s._thread is not None and not s._thread.is_alive())
        assert events == []

    def test_loop_always_yields_cpu_even_with_zero_interval(self, make_scanner, monkeypatch):
        sleeps = []
        monkeypatch.setattr(sc.time, "sleep", lambda secs: sleeps.append(secs))
        s = make_scanner(scan_interval_ms=0)
        s._running = True
        runs = {"n": 0}

        def scan(cooldown):
            runs["n"] += 1
            if runs["n"] >= 5:
                s._running = False
            return True

        s._scan_once = scan
        s._run_loop()
        assert runs["n"] == 5 and sleeps and min(sleeps) >= sc.MIN_SLEEP_MS / 1000


class TestCleanup:
    def test_thread_closes_resources_on_exit(self, make_scanner):
        s = make_scanner()
        fake = s._sct
        s._scan_once = lambda cooldown: True
        s.start()
        assert wait_until(lambda: s.is_running)
        s.stop()
        assert wait_until(lambda: fake.closed)
        assert s._ocr_pool is None

    def test_stop_without_start_closes_immediately(self, make_scanner):
        s = make_scanner()
        fake = s._sct
        s.stop()
        assert fake.closed

    def test_close_is_idempotent(self, make_scanner):
        s = make_scanner()
        s.close()
        s.close()
        assert s._sct is None and s._ocr_pool is None

    def test_grab_after_close_returns_none_instead_of_raising(self, make_scanner):
        s = make_scanner()
        s.close()
        assert s._grab_shop() is None
        assert s._last_grab_error.startswith("AttributeError:") and "NoneType" in s._last_grab_error


class TestNameMatchingIntegration:
    NAMES = ["Graves", "Gragas", "Draven", "Vex", "T-Hex", "Vi", "Viktor"]

    def read(self, monkeypatch, text):
        monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: text)

    def test_scanner_compares_against_all_names(self, make_scanner, monkeypatch):
        s = make_scanner(target_names=["Graves"], all_names=self.NAMES, name_threshold=0.65)
        frame = np.zeros((10, 10, 3), np.uint8)
        self.read(monkeypatch, "Gragas")
        assert s._ocr_slot(frame)[0] is None  # Gragas giống Graves nhưng là tướng khác
        self.read(monkeypatch, "Graves 2")
        assert s._ocr_slot(frame)[0][0] == "Graves"

    def test_short_target_does_not_buy_longer_name(self, make_scanner, monkeypatch):
        s = make_scanner(target_names=["Vi"], all_names=self.NAMES)
        frame = np.zeros((10, 10, 3), np.uint8)
        self.read(monkeypatch, "Viktor")
        assert s._ocr_slot(frame)[0] is None
        self.read(monkeypatch, "Vi")
        assert s._ocr_slot(frame)[0][0] == "Vi"

    def test_without_all_names_falls_back_to_targets_only(self, make_scanner, monkeypatch):
        s = make_scanner(target_names=["Vex"])
        self.read(monkeypatch, "vex 3")
        assert s._ocr_slot(np.zeros((10, 10, 3), np.uint8))[0][0] == "Vex"

    def test_alias_in_other_language_is_matched(self, make_scanner, monkeypatch):
        s = make_scanner(
            target_names=["Ngộ Không"],
            all_names=[*self.NAMES, "Wukong", "Ngộ Không"],
            target_aliases={"Ngộ Không": ["Wukong"]},
        )
        self.read(monkeypatch, "Wukong 4")
        assert s._ocr_slot(np.zeros((10, 10, 3), np.uint8))[0][0] == "Ngộ Không"

    def test_default_threshold_is_safe(self, make_scanner):
        assert make_scanner().name_threshold >= 0.80


class TestOcrHealth:
    """Theo dõi lúc chạy: OCR đọc rỗng ở gần hết các ô trong 30 giây khi game ở foreground → cảnh báo 1 lần mỗi đợt."""

    @pytest.fixture
    def watch(self, make_scanner):
        events = {"errors": [], "logs": [], "health": []}
        s = make_scanner(
            on_error=lambda m, f: events["errors"].append((m, f)),
            on_log=events["logs"].append,
            on_ocr_health=events["health"].append,
        )
        clock = {"t": 1000.0}
        s._now = lambda: clock["t"]
        return s, events, clock

    def feed(self, s, clock, empties, seconds, step=1.0):
        end = clock["t"] + seconds
        while clock["t"] < end:
            s._track_ocr_health(empties)
            clock["t"] += step

    def test_thresholds_are_the_ones_the_user_chose(self):
        """Quyết định của người dùng: cảnh báo khi >= 4/5 ô đọc rỗng liên tục 30 giây. Đổi số này phải là chủ ý."""
        assert sc.OCR_EMPTY_SLOTS == 4 and sc.SLOT_COUNT == 5
        assert sc.OCR_EMPTY_WARN_S == 30.0

    def test_no_warning_before_the_deadline(self, watch):
        s, ev, clock = watch
        self.feed(s, clock, 5, sc.OCR_EMPTY_WARN_S - 2)
        assert ev["errors"] == [] and ev["health"] == []

    def test_warns_once_after_the_deadline_and_stays_quiet(self, watch):
        s, ev, clock = watch
        self.feed(s, clock, 5, sc.OCR_EMPTY_WARN_S + 20)
        assert len(ev["errors"]) == 1 and ev["errors"][0][1] is False  # không fatal
        assert ev["health"] == [False]
        assert "Làm mới ảnh" in ev["errors"][0][0] and "dải tên" in ev["errors"][0][0]

    def test_four_of_five_empty_counts_as_abnormal(self, watch):
        s, ev, clock = watch
        self.feed(s, clock, sc.OCR_EMPTY_SLOTS, sc.OCR_EMPTY_WARN_S + 2)
        assert len(ev["errors"]) == 1

    def test_three_empty_slots_is_normal(self, watch):
        """Vừa mua một tướng, vài ô trống là bình thường."""
        s, ev, clock = watch
        self.feed(s, clock, sc.OCR_EMPTY_SLOTS - 1, 120)
        assert ev["errors"] == [] and ev["health"] == []

    def test_recovery_is_reported_once(self, watch):
        s, ev, clock = watch
        self.feed(s, clock, 5, sc.OCR_EMPTY_WARN_S + 2)
        self.feed(s, clock, 1, 5)
        assert ev["health"] == [False, True]
        assert ev["logs"] == ["OCR đã đọc lại được chữ trong shop."]

    def test_a_new_streak_warns_again(self, watch):
        s, ev, clock = watch
        for _ in range(2):
            self.feed(s, clock, 5, sc.OCR_EMPTY_WARN_S + 2)
            self.feed(s, clock, 0, 3)
        assert len(ev["errors"]) == 2 and ev["health"] == [False, True, False, True]

    def test_short_gaps_reset_the_streak(self, watch):
        s, ev, clock = watch
        for _ in range(4):
            self.feed(s, clock, 5, sc.OCR_EMPTY_WARN_S - 10)
            self.feed(s, clock, 0, 1)  # một lần đọc được chữ → đếm lại từ đầu
        assert ev["errors"] == []

    def test_not_counted_while_game_is_in_background(self, watch, foreground):
        s, ev, clock = watch
        foreground["value"] = False
        self.feed(s, clock, 5, 300)
        assert ev["errors"] == [] and ev["health"] == []

    def test_switching_away_pauses_and_does_not_fake_a_recovery(self, watch, foreground):
        s, ev, clock = watch
        self.feed(s, clock, 5, sc.OCR_EMPTY_WARN_S + 2)  # đã cảnh báo
        foreground["value"] = False
        self.feed(s, clock, 5, 60)
        assert ev["health"] == [False] and ev["logs"] == []  # alt-tab không phải 'đã đọc lại được'

    def test_returning_to_game_restarts_the_count(self, watch, foreground):
        s, ev, clock = watch
        self.feed(s, clock, 5, sc.OCR_EMPTY_WARN_S - 5)
        foreground["value"] = False
        self.feed(s, clock, 5, 60)
        foreground["value"] = True
        self.feed(s, clock, 5, sc.OCR_EMPTY_WARN_S - 5)
        assert ev["errors"] == []  # thời gian ở cửa sổ khác không được cộng dồn

    def test_foreground_not_required_means_always_counted(self, make_scanner, foreground):
        s = make_scanner(require_game_foreground=False, on_error=lambda m, f: events.append(m))
        events = []
        clock = {"t": 0.0}
        s._now = lambda: clock["t"]
        foreground["value"] = False
        for _ in range(int(sc.OCR_EMPTY_WARN_S) + 2):
            s._track_ocr_health(5)
            clock["t"] += 1
        assert len(events) == 1


class TestOcrBatchAndErrors:
    def make(self, make_scanner, monkeypatch, texts):
        """Scanner có pool OCR; read_name_from_slot trả lần lượt texts[i] theo chỉ số cột (đọc từ giá trị pixel)."""
        s = make_scanner(target_names=["Vex"], all_names=["Vex", "Zed"])
        s._running = True  # đang quét: đợt OCR chỉ chờ kết quả khi scanner chưa bị dừng
        monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: texts[int(frame[0, 0, 0])])
        return s

    def slots(self, n=5):
        return [np.full((4, 4, 3), i, np.uint8) for i in range(n)]

    def test_counts_empty_slots_and_finds_target(self, make_scanner, monkeypatch):
        s = self.make(make_scanner, monkeypatch, ["", "Vex 2", "   ", "Zed", ""])
        results, empties = s._scan_names_parallel(self.slots())
        assert empties == 3  # '' và chuỗi toàn khoảng trắng đều là rỗng
        assert [r for r in results if r] == [(1, "Vex", results[1][2])]

    def test_without_pool_behaves_the_same(self, make_scanner, monkeypatch):
        s = self.make(make_scanner, monkeypatch, ["", "Vex 2", "", "", ""])
        s._ocr_pool = None
        results, empties = s._scan_names_parallel(self.slots())
        assert empties == 4 and results[1][1] == "Vex"

    def test_worker_failure_counts_as_empty_and_is_recorded(self, make_scanner, monkeypatch):
        from core import name_matcher as nm

        nm.drain_ocr_errors()
        s = self.make(make_scanner, monkeypatch, ["Vex", "Vex", "Vex", "Vex", "Vex"])

        def flaky(frame):
            if int(frame[0, 0, 0]) == 2:
                raise ValueError("ô 3 hỏng")
            return s._name_matcher.match("Vex"), False

        monkeypatch.setattr(s, "_ocr_slot", flaky)
        results, empties = s._scan_names_parallel(self.slots())
        assert empties == 1 and results[2] is None and results[0] is not None
        assert any("ValueError: ô 3 hỏng" in m for m in nm.drain_ocr_errors())

    def test_new_errors_reported_once_each(self, make_scanner):
        from core import name_matcher as nm

        nm.drain_ocr_errors()
        got = []
        s = make_scanner(on_error=lambda m, f: got.append((m, f)))
        for _ in range(3):
            nm.record_ocr_error("OCR en-US: lỗi A")
            nm.record_ocr_error("lỗi B")
        s._report_new_ocr_errors()
        s._report_new_ocr_errors()  # lần 2 không còn gì mới
        nm.record_ocr_error("lỗi B")
        s._report_new_ocr_errors()  # đã báo rồi → không báo lại
        assert sorted(m for m, _ in got) == ["Lỗi OCR: OCR en-US: lỗi A (x3)", "Lỗi OCR: lỗi B (x3)"]
        assert all(f is False for _, f in got)

    def test_start_discards_stale_errors(self, make_scanner):
        from core import name_matcher as nm

        nm.record_ocr_error("lỗi của lần chạy trước")
        s = make_scanner()
        s._scan_once = lambda cooldown: True
        s.start()
        try:
            assert nm.drain_ocr_errors() == {}
        finally:
            s.stop()

    def test_full_scan_loop_warns_after_30_seconds_of_empty_ocr(self, make_scanner, monkeypatch):
        """Từ đầu đến cuối qua _scan_once: shop có chữ nhưng OCR đọc rỗng suốt 30 s → đúng 1 cảnh báo, rồi hồi phục."""
        from tests.helpers import make_shop

        errors, health = [], []
        s = make_scanner(on_error=lambda m, f: errors.append(m), on_ocr_health=health.append)
        clock = {"t": 0.0}
        s._now = lambda: clock["t"]
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s._running = True
        text = {"v": ""}
        monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: text["v"])
        for _ in range(40):
            s._last_name_scan = -1e9  # luôn đến lượt quét tên
            assert s._scan_once({}) is True
            clock["t"] += 1.0
        assert len(errors) == 1 and "OCR không đọc được chữ" in errors[0] and health == [False]
        text["v"] = "Zed 3"
        s._last_name_scan = -1e9
        s._scan_once({})
        assert health == [False, True]


class TestBuildTemplates:
    def test_missing_custom_file_falls_back_to_ddragon_with_log(self, data_dir):
        import cv2

        data_dir.joinpath("templates").mkdir(parents=True)
        dd = data_dir / "templates" / "Aatrox.png"
        cv2.imwrite(str(dd), make_card(1))
        logs = []
        result = sc.build_templates(
            ["Aatrox"], {"Aatrox": r"C:\Users\Admin\x\custom_Aatrox.png"}, {"Aatrox": dd}, log=logs.append
        )
        assert list(result) == ["Aatrox"] and len(logs) == 1 and "Data Dragon" in logs[0]

    def test_custom_file_preferred_when_present(self, data_dir):
        import cv2

        tpl = data_dir / "templates"
        tpl.mkdir(parents=True)
        cv2.imwrite(str(tpl / "Aatrox.png"), make_card(1))
        cv2.imwrite(str(tpl / "custom_Aatrox.png"), make_card(2))
        logs = []
        result = sc.build_templates(
            ["Aatrox"], {"Aatrox": "templates/custom_Aatrox.png"}, {"Aatrox": tpl / "Aatrox.png"}, log=logs.append
        )
        assert list(result) == ["Aatrox"] and logs == []
        custom_only = sc.build_templates(["Aatrox"], {"Aatrox": "templates/custom_Aatrox.png"}, {})
        assert np.array_equal(result["Aatrox"], custom_only["Aatrox"])  # dùng ảnh upload, không phải Data Dragon

    def test_no_sources_gives_no_template(self, data_dir):
        assert sc.build_templates(["Vex"], {}, {}) == {}
