"""Nhật ký chẩn đoán và chống mua nhầm của scanner: đọc lại lần 2 cho khớp mờ, bằng chứng mỗi lần mua, xác nhận click có tác
dụng, dòng 'Shop: ...', 'gần khớp', khung đen, phím roll, tổng kết."""

import time

import numpy as np
import pytest

import core.scanner as sc
from tests.helpers import CENTERS, make_shop


def running(make_scanner, **kw):
    s = make_scanner(**kw)
    s._running = True
    return s


def buy(s, shop, score, method="tên", slot=0, name="Vex"):
    """Nhận diện trên `shop` với điểm `score`, rồi click khi màn hình vẫn là `shop`."""
    s._grab_shop = lambda: shop
    s._buy_batch([(slot, name, score, method, s._slice_slots(shop)[slot])], {})


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


# --------------------------------------------------------------------------- đọc lại lần 2 (chống mua nhầm)
class TestSecondReadForFuzzyMatches:
    def test_exact_match_clicks_without_a_second_read(self, make_scanner, clicks, monkeypatch):
        reads = []
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: reads.append(1) or "Vex")
        s = running(make_scanner)
        buy(s, make_shop(s, [1, 2, 3, 4, 5]), score=1.0)
        assert clicks == [CENTERS[0]] and reads == []

    def test_fuzzy_match_clicks_when_second_read_confirms(self, make_scanner, clicks, monkeypatch):
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "Vex")
        s = running(make_scanner)
        buy(s, make_shop(s, [1, 2, 3, 4, 5]), score=0.85)
        assert clicks == [CENTERS[0]]

    def test_fuzzy_match_is_not_clicked_when_second_read_is_another_champion(self, make_scanner, clicks, monkeypatch):
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "Veigar")
        logs = []
        s = running(make_scanner, on_log=logs.append)
        buy(s, make_shop(s, [1, 2, 3, 4, 5]), score=0.85)
        assert clicks == [] and s.stats["recheck_reject"] == 1
        assert any("Bỏ click Vex ô 1" in m and "'Veigar'" in m and "lần 2" in m for m in logs)

    def test_fuzzy_match_is_not_clicked_when_second_read_is_empty(self, make_scanner, clicks, monkeypatch):
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "")
        s = running(make_scanner)
        buy(s, make_shop(s, [1, 2, 3, 4, 5]), score=0.85)
        assert clicks == [] and s.stats["recheck_reject"] == 1

    def test_fuzzy_match_is_not_clicked_when_second_read_times_out(self, make_scanner, clicks, monkeypatch):
        monkeypatch.setattr(sc, "RECHECK_TIMEOUT_S", 0.05)
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: time.sleep(0.4) or "Vex")
        logs = []
        s = running(make_scanner, on_log=logs.append)
        buy(s, make_shop(s, [1, 2, 3, 4, 5]), score=0.85)
        assert clicks == [] and s.stats["recheck_fail"] == 1
        assert any("không đọc lại được tên" in m for m in logs)

    def test_image_matches_are_not_second_read(self, make_scanner, clicks, monkeypatch):
        reads = []
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: reads.append(1) or "")
        s = running(make_scanner)
        buy(s, make_shop(s, [1, 2, 3, 4, 5]), score=0.7, method="ảnh")
        assert clicks == [CENTERS[0]] and reads == []

    def test_only_the_mismatching_slot_is_dropped_from_a_batch(self, make_scanner, clicks, monkeypatch):
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "Vex")
        s = running(make_scanner)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        slots = s._slice_slots(shop)
        # ô 1 khớp chính xác (không đọc lại); ô 3 khớp mờ và đọc lại ra "Vex" → cả hai click
        s._buy_batch([(0, "Vex", 1.0, "tên", slots[0]), (2, "Vex", 0.85, "tên", slots[2])], {})
        assert clicks == [CENTERS[0], CENTERS[2]]


# --------------------------------------------------------------------------- bằng chứng mỗi lần mua
class TestBuyEvidence:
    def test_every_buy_logs_what_ocr_read_and_how_similar_the_card_was(self, make_scanner, clicks):
        logs = []
        s = running(make_scanner, on_log=logs.append)
        s._slot_text[0] = "Vex"
        buy(s, make_shop(s, [1, 2, 3, 4, 5]), score=1.0)
        line = next(m for m in logs if "bằng chứng ô 1" in m)
        assert "OCR đọc 'Vex'" in line and "tên 100%" in line and "độ giống thẻ lúc xác nhận 1.00" in line

    def test_fuzzy_buy_lists_other_names_that_looked_similar(self, make_scanner, clicks, monkeypatch):
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "Vex")
        logs = []
        s = running(make_scanner, on_log=logs.append, all_names=["Vex", "Vix", "Vox"])
        s._slot_text[0] = "Vax"
        buy(s, make_shop(s, [1, 2, 3, 4, 5]), score=0.85)
        line = next(m for m in logs if "bằng chứng ô 1" in m)
        assert "'Vax'" in line and "đã đọc lại lần 2 vẫn khớp" in line and "vix" in line.lower()

    def test_image_buy_evidence_says_image(self, make_scanner, clicks):
        logs = []
        s = running(make_scanner, on_log=logs.append)
        buy(s, make_shop(s, [1, 2, 3, 4, 5]), score=0.9, method="ảnh")
        assert any("so ảnh mẫu" in m and "ảnh 90%" in m for m in logs)


# --------------------------------------------------------------------------- xác nhận click có tác dụng
class TestClickVerification:
    def click_once(self, make_scanner, **kw):
        s = running(make_scanner, **kw)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        buy(s, shop, score=1.0)
        return s, shop

    def test_card_disappearing_confirms_the_buy(self, make_scanner, clicks):
        logs = []
        s, _ = self.click_once(make_scanner, on_log=logs.append)
        assert len(s._pending_verify) == 1
        gone = make_shop(s, [1, 2, 3, 4, 5], empty={0})
        s._check_click_results(s._slice_slots(gone), time.perf_counter())
        assert s.stats["confirmed"] == 1 and s._pending_verify == []
        assert any("Xác nhận ô 1" in m and "đã mua" in m for m in logs)

    def test_card_still_there_inside_the_window_keeps_waiting_silently(self, make_scanner, clicks):
        logs = []
        s, shop = self.click_once(make_scanner, on_log=logs.append)
        s._check_click_results(s._slice_slots(shop), time.perf_counter())
        assert len(s._pending_verify) == 1 and s.stats["unconfirmed"] == 0
        assert not any(m.startswith("Cảnh báo") for m in logs)

    def test_card_still_there_after_the_window_warns_with_causes(self, make_scanner, clicks):
        logs = []
        s, shop = self.click_once(make_scanner, on_log=logs.append)
        s._check_click_results(s._slice_slots(shop), time.perf_counter() + sc.CLICK_VERIFY_S + 0.1)
        assert s.stats["unconfirmed"] == 1 and s._pending_verify == []
        warn = next(m for m in logs if m.startswith("Cảnh báo: đã click ô 1"))
        assert "Administrator" in warn and "hết vàng" in warn

    def test_three_failed_clicks_in_a_row_report_an_error_and_the_environment(self, make_scanner):
        errors, logs = [], []
        s = running(make_scanner, on_error=lambda m, f: errors.append((m, f)), on_log=logs.append)
        for _ in range(sc.CLICK_FAIL_WARN):
            s._click_unconfirmed(0, "Vex", 0.7)
        assert len(errors) == 1 and errors[0][1] is False  # báo lỗi nhưng KHÔNG dừng quét
        assert "Chẩn đoán: giả lập." in logs

    def test_a_confirmed_buy_resets_the_failure_streak(self, make_scanner, clicks):
        s, _ = self.click_once(make_scanner)
        s._click_unconfirmed(0, "Vex", 0.7)
        s._click_unconfirmed(0, "Vex", 0.7)
        s._check_click_results(s._slice_slots(make_shop(s, [1, 2, 3, 4, 5], empty={0})), time.perf_counter())
        assert s._click_fail_streak == 0

    def test_scan_loop_runs_the_check_on_every_frame(self, make_scanner, clicks):
        s, shop = self.click_once(make_scanner, detect_by_name=False, detect_by_image=False)
        s._grab_shop = lambda: make_shop(s, [1, 2, 3, 4, 5], empty={0})
        s._scan_once({})
        assert s.stats["confirmed"] == 1


# --------------------------------------------------------------------------- dòng "Shop: ..." và "gần khớp"
class TestShopLog:
    def make(self, make_scanner, **kw):
        logs, clock = [], Clock()
        s = running(make_scanner, on_log=logs.append, **kw)
        s._now = clock
        return s, logs, clock

    def test_logs_five_names_with_a_star_on_targets_once_they_are_stable(self, make_scanner):
        s, logs, clock = self.make(make_scanner)
        s._note_ocr_text(0, "Rakan", None)
        s._note_ocr_text(4, "Vex 2", ("Vex", 0.98))
        s._flush_shop_log()
        assert logs == []  # chữ vừa đổi: chờ đứng yên (thẻ còn chạy hiệu ứng)
        clock.t += sc.SHOP_LOG_STABLE_S + 0.01
        s._flush_shop_log()
        assert logs == ["Shop: Rakan | – | – | – | Vex 2★"]

    def test_same_shop_is_not_logged_twice(self, make_scanner):
        s, logs, clock = self.make(make_scanner)
        s._note_ocr_text(0, "Rakan", None)
        clock.t += 1
        s._flush_shop_log()
        s._note_ocr_text(0, "Rakan", None)  # đọc lại ra y hệt
        clock.t += 1
        s._flush_shop_log()
        assert len(logs) == 1

    def test_flickering_text_inside_the_stable_window_is_logged_only_in_its_final_form(self, make_scanner):
        s, logs, clock = self.make(make_scanner)
        s._note_ocr_text(0, "Ral«", None)
        clock.t += 0.1
        s._note_ocr_text(0, "Rakan", None)
        clock.t += 0.1
        s._flush_shop_log()
        clock.t += sc.SHOP_LOG_STABLE_S
        s._flush_shop_log()
        assert logs == ["Shop: Rakan | – | – | – | –"]

    def test_marks_when_the_game_is_not_in_front(self, make_scanner):
        s, logs, clock = self.make(make_scanner)
        s._click_blocked = True
        s._note_ocr_text(0, "Nhật ký", None)
        clock.t += 1
        s._flush_shop_log()
        assert "game không ở trước" in logs[0]

    def test_is_capped_per_run(self, make_scanner):
        s, logs, clock = self.make(make_scanner)
        s._shop_lines = sc.SHOP_LOG_MAX
        for i in range(3):
            s._note_ocr_text(0, f"Tên{i}", None)
            clock.t += 1
            s._flush_shop_log()
        assert len(logs) == 1 and "ngừng ghi thêm" in logs[0]

    def test_verbose_off_logs_nothing(self, make_scanner):
        s, logs, clock = self.make(make_scanner, verbose_log=False)
        s._note_ocr_text(0, "Rakan", None)
        clock.t += 1
        s._flush_shop_log()
        assert logs == []

    def test_scan_loop_feeds_the_shop_log(self, make_scanner, monkeypatch):
        s, logs, clock = self.make(make_scanner, require_game_foreground=False, name_scan_interval_ms=0)
        s._ocr_pool = None
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "Rakan")
        s._scan_once({})
        clock.t += 1
        s._scan_once({})
        assert any(m.startswith("Shop: Rakan | Rakan") for m in logs)


class TestNearMiss:
    def make(self, make_scanner, **kw):
        logs = []
        s = running(make_scanner, on_log=logs.append, target_names=["Yunara"], name_threshold=0.9, **kw)
        return s, logs

    def test_text_close_to_a_target_but_below_threshold_is_logged(self, make_scanner):
        s, logs = self.make(make_scanner)
        text = "Yunarr"
        assert s._name_matcher.match(text) is None
        s._note_ocr_text(0, text, None)
        line = next(m for m in logs if m.startswith("Gần khớp ô 1"))
        assert "'Yunarr'" in line and "Yunara" in line and "KHÔNG mua" in line and "90%" in line

    def test_same_text_is_logged_once(self, make_scanner):
        s, logs = self.make(make_scanner)
        s._note_ocr_text(0, "Yunarr", None)
        s._note_ocr_text(0, "Yunarr", None)
        s._slot_text[0] = ""  # đổi rồi đọc lại đúng chữ cũ ở lần OCR kế tiếp
        s._note_ocr_text(0, "Yunarr", None)
        assert sum(m.startswith("Gần khớp") for m in logs) == 1

    def test_unrelated_text_is_not_logged(self, make_scanner):
        s, logs = self.make(make_scanner)
        s._note_ocr_text(0, "Rakan", None)
        s._note_ocr_text(1, "Ral«", None)
        assert not any(m.startswith("Gần khớp") for m in logs)

    def test_matched_text_is_not_a_near_miss(self, make_scanner):
        s, logs = self.make(make_scanner)
        s._note_ocr_text(0, "Yunara", ("Yunara", 1.0))
        assert not any(m.startswith("Gần khớp") for m in logs)

    def test_verbose_off_and_cap(self, make_scanner):
        s, logs = self.make(make_scanner, verbose_log=False)
        s._note_ocr_text(0, "Yunarr", None)
        assert logs == []
        s2, logs2 = self.make(make_scanner)
        s2.stats["near_miss"] = sc.NEAR_MISS_MAX_LINES
        s2._note_ocr_text(0, "Yunarr", None)
        assert logs2 == []


# --------------------------------------------------------------------------- khung đen, phím roll, tổng kết
class TestFrameHealth:
    def test_black_frame_in_game_warns_after_a_few_seconds_then_only_every_minute(self, make_scanner, foreground):
        logs, clock = [], Clock()
        s = running(make_scanner, on_log=logs.append)
        s._now = clock
        black = np.zeros((40, 40, 3), np.uint8)
        s._check_frame_health(black)  # bắt đầu đếm
        clock.t += sc.BLACK_FRAME_WARN_S + 1
        s._check_frame_health(black)
        warn = [m for m in logs if "ĐEN" in m]
        assert len(warn) == 1 and "Borderless" in warn[0]
        clock.t += 10
        s._check_frame_health(black)
        assert len([m for m in logs if "ĐEN" in m]) == 1  # chưa đủ BLACK_FRAME_LOG_EVERY_S
        clock.t += sc.BLACK_FRAME_LOG_EVERY_S
        s._check_frame_health(black)
        assert len([m for m in logs if "ĐEN" in m]) == 2

    def test_black_frame_is_ignored_when_the_game_is_not_in_front(self, make_scanner, foreground):
        logs, clock = [], Clock()
        s = running(make_scanner, on_log=logs.append)
        s._now = clock
        foreground["value"] = False
        black = np.zeros((40, 40, 3), np.uint8)
        s._check_frame_health(black)
        clock.t += 30
        s._check_frame_health(black)
        assert logs == []

    def test_a_normal_frame_resets_the_black_timer(self, make_scanner, foreground):
        logs, clock = [], Clock()
        s = running(make_scanner, on_log=logs.append)
        s._now = clock
        black, lit = np.zeros((40, 40, 3), np.uint8), np.full((40, 40, 3), 90, np.uint8)
        s._check_frame_health(black)
        clock.t += 3
        s._check_frame_health(lit)
        clock.t += 3
        s._check_frame_health(black)
        clock.t += 3
        s._check_frame_health(black)
        assert logs == []  # mỗi đợt đen chưa tới BLACK_FRAME_WARN_S


class TestRollKeyAndSummary:
    def test_first_roll_key_is_announced_and_all_are_counted(self, make_scanner):
        logs = []
        s = make_scanner(on_log=logs.append)
        s.notify_roll()
        s.notify_roll()
        assert s.stats["roll_key"] == 2
        assert sum("Nhận phím roll lần đầu" in m for m in logs) == 1

    def test_roll_key_without_log_callback_is_safe(self, make_scanner):
        s = make_scanner()
        s.notify_roll()
        assert s.stats["roll_key"] == 1

    def test_summary_line_reports_the_counters(self, make_scanner):
        logs = []
        s = make_scanner(on_log=logs.append)
        s.stats.update(clicks=4, confirmed=3, unconfirmed=1, recheck_reject=2, blocked=7, roll_key=5, ocr_batches=10)
        s._ocr_ms_total = 150.0
        s._log_loop_summary()
        line = next(m for m in logs if m.startswith("Thống kê:"))
        assert "click 4" in line and "thấy thẻ biến mất 3" in line and "không thấy 1" in line
        assert "không khớp 2" in line and "foreground 7" in line and "phím roll nhận 5 lần" in line
        assert "OCR 10 đợt (TB 15 ms)" in line

    def test_summary_is_silent_when_nothing_happened(self, make_scanner):
        logs = []
        make_scanner(on_log=logs.append)._log_loop_summary()
        assert not any(m.startswith("Thống kê:") for m in logs)


class TestOcrResultCompatibility:
    def test_ocr_result_still_unpacks_and_compares_like_the_old_tuple(self, make_scanner, monkeypatch):
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "Vex")
        s = make_scanner()
        result = s._ocr_slot(np.zeros((40, 40, 3), np.uint8))
        match, empty = result
        assert result == (("Vex", 1.0), False) and match == ("Vex", 1.0) and empty is False
        assert result.text == "Vex"


@pytest.mark.parametrize("flag", [True, False])
def test_verbose_log_flag_is_stored(make_scanner, flag):
    assert make_scanner(verbose_log=flag).verbose_log is flag


class TestGameProcessRecognition:
    def test_scanner_recognises_the_new_tft_client_by_default(self, make_scanner):
        s = make_scanner()
        assert "tftclient-win64-shipping.exe" in s.game_process_names and "league of legends.exe" in s.game_process_names

    def test_scanner_keeps_user_added_names(self, make_scanner):
        s = make_scanner(game_process_names=["League of Legends.exe", "Custom.exe"])
        assert "custom.exe" in s.game_process_names and "tftclient-win64-shipping.exe" in s.game_process_names

    def test_block_log_suggests_an_unlisted_game_like_process(self, make_scanner, clicks, foreground, monkeypatch):
        monkeypatch.setattr(sc, "suspect_game_process", lambda names: "tftclient-win64-shipping2.exe")
        logs = []
        s = running(make_scanner, on_log=logs.append)
        foreground["value"] = False
        buy(s, make_shop(s, [1, 2, 3, 4, 5]), score=1.0)
        hint = next(m for m in logs if m.startswith("Gợi ý:"))
        assert "tftclient-win64-shipping2.exe" in hint and "game_process_names" in hint


class TestDxgiGapLog:
    class Dxgi:
        def __init__(self):
            self.none_frames = 0
            self.closed = False

        def grab(self):
            return np.full((200, 1000, 3), 50, np.uint8)

        def close(self):
            self.closed = True

    def test_first_transient_loss_is_logged_once_and_counted_in_the_summary(self, make_scanner):
        logs = []
        s = running(make_scanner, on_log=logs.append)
        s._dxgi = self.Dxgi()
        s._grab_shop()
        assert logs == []  # chưa mất khung nào
        s._dxgi.none_frames = 3
        s._grab_shop()
        s._grab_shop()
        assert sum("DXGI tạm mất khung" in m and "dùng mss" in m for m in logs) == 1
        s._log_loop_summary()
        assert any("DXGI tạm mất khung 3 lần" in m for m in logs)

    def test_scanner_without_dxgi_logs_nothing_about_it(self, make_scanner):
        logs = []
        s = make_scanner(on_log=logs.append)
        s._log_loop_summary()
        assert logs == []
