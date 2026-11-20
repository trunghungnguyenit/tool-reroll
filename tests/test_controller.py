"""Điều phối không giao diện: mọi hành vi quan trọng của luồng chọn tướng → kiểm tra điều kiện → chuẩn bị nền → scanner,
cộng bộ lọc danh sách, preview, phím tắt, đóng. Sự kiện gửi lên giao diện được ghi lại để kiểm tra."""

import json
import queue
import threading
import time
import types
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

import core.config as config
import core.controller as ctl
import core.champions as champions
from core.preview import PreviewResult
from tests.fakes import BAD_OCR, ENTRIES, OK_OCR, FakeScanner, champ, plan


class Events:
    def __init__(self):
        self.items: list[tuple[str, dict]] = []

    def __call__(self, event, **data):
        self.items.append((event, data))

    def of(self, name):
        return [d for e, d in self.items if e == name]

    def last(self, name):
        found = self.of(name)
        return found[-1] if found else None

    def logs(self):
        return "\n".join(d["text"] for d in self.of("log"))

    def dialogs(self, level):
        return [d for d in self.of("dialog") if d["level"] == level]


@pytest.fixture
def ev():
    return Events()


@pytest.fixture
def hotkeys():
    return types.SimpleNamespace(added=[], unhooked=False)


@pytest.fixture
def make(data_dir, monkeypatch, ev, hotkeys):
    FakeScanner.instances = []
    monkeypatch.setattr(ctl, "fetch_champion_list", lambda locale=None: ENTRIES)
    kb = types.SimpleNamespace(add_hotkey=lambda *a, **k: hotkeys.added.append(a),
                               unhook_all=lambda: setattr(hotkeys, "unhooked", True))

    def factory(saved_config=None, post=None):
        if saved_config is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
            raw = saved_config if isinstance(saved_config, str) else json.dumps(saved_config)
            (data_dir / "config.json").write_text(raw, encoding="utf-8")
        while not _Q.empty():
            _Q.get_nowait()
        kw = {"post": post or _Q.put}
        return ctl.AppController(ev, keyboard=kb, scanner_factory=FakeScanner, **kw)

    return factory


_Q: "queue.Queue" = queue.Queue()  # việc thread nền đưa về "luồng giao diện": chỉ chạy khi test gọi drain()


def drain():
    while True:
        try:
            fn = _Q.get_nowait()
        except queue.Empty:
            return
        fn()


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        drain()
        if cond():
            return True
        time.sleep(0.01)
    drain()
    return cond()


def ready(c, names="Vex", image=False, name=True, interval="5"):
    c.config["shop_region"] = {"left": 0, "top": 0, "width": 1000, "height": 200}
    c.config["slot_centers"] = [[40 + i * 190, 150] for i in range(5)]
    c.manual_names = names
    c.detect_image, c.detect_name, c.interval_text = image, name, interval
    return c


@pytest.fixture
def c(make):
    return make()


@pytest.fixture
def loaded(make):
    k = make()
    k.populate_champions(ENTRIES)
    return k


# ----------------------------------------------------------------------------- điều kiện chạy
class TestRequirements:
    def by_key(self, c):
        return {r.key: r for r in c.requirements()}

    def test_empty_app_is_missing_everything_in_order(self, c):
        r = self.by_key(c)
        assert not r["champions"].ok and r["champions"].step == ctl.STEP_CHAMPIONS
        assert not r["region"].ok and r["region"].step == ctl.STEP_REGION
        assert not r["clicks"].ok and r["clicks"].text == "Mới đặt 0/5 điểm click"
        assert c.first_missing().key == "champions" and not c.ready()

    def test_ready_when_everything_set(self, c):
        assert ready(c).ready()
        assert [r.ok for r in c.requirements()].count(False) == 0

    def test_both_modes_off(self, c):
        ready(c, image=False, name=False)
        assert c.first_missing().key == "mode" and "ít nhất 1 chế độ" in c.first_missing().text

    def test_bad_interval_names_the_value(self, c):
        ready(c, interval="abc")
        m = c.first_missing()
        assert m.key == "interval" and m.step == ctl.STEP_SETTINGS and "'abc'" in m.text and "0 đến 100" in m.text

    @pytest.mark.parametrize("text", ["", "1.5", "-1", "101", " "])
    def test_interval_rejects_blank_float_and_out_of_range(self, c, text):
        ready(c, interval=text)
        assert c.interval_value() is None

    def test_click_point_outside_region_names_the_slot(self, c):
        ready(c)
        c.config["slot_centers"][2] = [5000, 5000]
        m = c.first_missing()
        assert m.key == "clicks" and "ô 3 nằm ngoài vùng Shop" in m.text

    def test_fewer_than_five_points(self, c):
        ready(c)
        c.config["slot_centers"] = [[10, 10]] * 3
        assert c.first_missing().text == "Mới đặt 3/5 điểm click"

    def test_unchecked_ocr_is_only_a_note_not_a_blocker(self, c):
        ready(c)
        o = self.by_key(c)["ocr"]
        assert o.ok and not o.blocking and c.ready()

    def test_failed_ocr_blocks_name_only_mode(self, c):
        ready(c)
        c.ocr_status = BAD_OCR
        assert c.first_missing().key == "ocr" and "Thiếu pack ngôn ngữ" in c.first_missing().text

    def test_failed_ocr_does_not_block_when_image_mode_is_also_on(self, c):
        ready(c, image=True)
        c.ocr_status = BAD_OCR
        assert c.ready()
        assert not self.by_key(c)["ocr"].ok

    def test_no_ocr_row_when_name_mode_off(self, c):
        ready(c, image=True, name=False)
        assert "ocr" not in self.by_key(c)

    def test_selected_champions_are_counted(self, loaded):
        loaded.set_selected("Vex", True)
        loaded.manual_names = "Vex, Tahm Kench"
        assert loaded.requirements()[0].text == "2 tướng đang chọn"

    def test_changed_notifies_readiness(self, c, ev):
        c.changed()
        assert ev.of("readiness_changed")


# ----------------------------------------------------------------------------- validate/start
class TestStart:
    def test_blocked_start_reports_first_missing_and_starts_nothing(self, c, ev):
        c.start()
        blocked = ev.last("blocked")["requirement"]
        assert blocked.key == "champions" and not FakeScanner.instances and not c.preparing

    def test_toggle_when_not_ready_is_blocked_too(self, c, ev):
        c.toggle()
        assert ev.of("blocked")

    def test_valid_plan_snapshots_settings(self, c):
        ready(c, names="Vex, Zed\nVex")
        c.name_threshold = 0.85
        p = c._validate_start()
        assert p["names"] == ["Vex", "Zed"] and p["interval_ms"] == 5 and p["name_threshold"] == 0.85
        assert p["manual_names"] == "Vex, Zed\nVex" and all(isinstance(x, tuple) for x in p["centers"])

    def test_plan_is_unaffected_by_later_edits(self, c):
        ready(c)
        p = c._validate_start()
        c.manual_names += ", Zed"
        c.interval_text = "99"
        assert p["names"] == ["Vex"] and p["interval_ms"] == 5

    def test_warnings_in_journal(self, c, ev):
        ready(c, image=True)
        c.name_threshold, c.threshold = 0.6, 0.9
        c._validate_start()
        text = ev.logs()
        assert "Độ khớp tên < 75%" in text and "Độ khớp ảnh > 75%" in text
        assert "chưa có danh sách tên tướng đầy đủ" in text

    def test_name_only_hint(self, c, ev):
        ready(c)
        c._validate_start()
        assert "Bật thêm 'Bắt theo ảnh'" in ev.logs()

    def test_reference_from_loaded_entries_and_from_cache(self, make, data_dir):
        k = make()
        champions.save_champion_cache(ENTRIES)
        assert "Zed" in k.reference()[0]  # offline: lấy từ cache
        k.populate_champions(ENTRIES)
        assert {"Vex", "Zed", "Graves", "Sivir"} <= set(k.reference()[0])

    def test_name_mode_checks_ocr_in_background_then_starts(self, c, ev, monkeypatch):
        calls = []
        monkeypatch.setattr(ctl, "check_ocr", lambda wanted_extra=(): calls.append(wanted_extra) or OK_OCR)
        c.config["champion_locale"] = "en_US"
        ready(c)
        c.start()
        assert c.preparing and ev.last("preparing")["on"] is True
        assert ev.last("status")["text"] == "Đang kiểm tra OCR..."
        assert wait_for(lambda: bool(FakeScanner.instances))
        assert c.running and not c.preparing and calls == [()]
        assert ev.last("preparing")["on"] is False and "OCR: Windows OCR (en-US)" in ev.logs()

    def test_second_toggle_while_preparing_is_ignored(self, c, monkeypatch):
        gate = threading.Event()
        monkeypatch.setattr(ctl, "check_ocr", lambda wanted_extra=(): (gate.wait(5), OK_OCR)[1])
        ready(c)
        c.toggle()
        assert c.preparing
        c.toggle()
        gate.set()
        assert wait_for(lambda: bool(FakeScanner.instances))
        time.sleep(0.2)
        assert len(FakeScanner.instances) == 1

    def test_vietnamese_locale_asks_for_vi_pack(self, c, monkeypatch):
        calls = []
        monkeypatch.setattr(ctl, "check_ocr", lambda wanted_extra=(): calls.append(wanted_extra) or OK_OCR)
        c.config["champion_locale"] = "vi_VN"
        ready(c)
        c.start()
        assert wait_for(lambda: bool(calls)) and calls == [("vi-VN",)]

    def test_ocr_check_crash_is_reported_and_recovers(self, c, ev, monkeypatch):
        def boom(wanted_extra=()):
            raise RuntimeError("winrt chết")

        monkeypatch.setattr(ctl, "check_ocr", boom)
        ready(c)
        c.start()
        assert wait_for(lambda: not c.preparing)
        assert c.scanner is None and not FakeScanner.instances
        assert "Không kiểm tra được OCR: RuntimeError: winrt chết" in ev.dialogs("error")[-1]["text"]

    def test_download_failure_logged_other_images_used(self, loaded, ev, monkeypatch):
        ok_path = config.TEMPLATES_DIR / "Vex.png"

        def fake_download(name, url):
            if name == "Zed":
                raise OSError("đĩa đầy")
            ok_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(ok_path), np.full((80, 80, 3), 90, np.uint8))
            return ok_path

        monkeypatch.setattr(ctl, "download_template", fake_download)
        ready(loaded, names="Vex, Zed", image=True, name=False)
        loaded.start()
        assert wait_for(lambda: bool(FakeScanner.instances))
        assert "Lỗi khi tải ảnh tướng: OSError: đĩa đầy" in ev.logs()
        assert set(FakeScanner.instances[-1].kw["templates"]) == {"Vex"}

    def test_closing_during_download_starts_nothing(self, loaded, monkeypatch):
        def slow(name, url):
            loaded.closing = True

        monkeypatch.setattr(ctl, "download_template", slow)
        ready(loaded, image=True, name=False)
        loaded.start()
        time.sleep(0.4)
        assert not FakeScanner.instances

    def test_download_progress_status(self, loaded, ev, monkeypatch):
        monkeypatch.setattr(ctl, "download_template", lambda n, u: None)
        ready(loaded, image=True, name=False)
        loaded.start()
        assert ev.last("status")["text"] in ("Đang tải ảnh tướng (0/1)...", "Đang tải ảnh tướng (1/1)...")
        wait_for(lambda: not loaded.preparing)

    def test_image_only_with_custom_image_starts_immediately(self, c, ev):
        img = config.TEMPLATES_DIR / "vex_custom.png"
        img.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(img), np.full((80, 80, 3), 100, np.uint8))
        c.config["custom_templates"] = {"Vex": "templates/vex_custom.png"}
        ready(c, image=True, name=False)
        c.start()
        assert FakeScanner.instances and not c.preparing
        assert ev.last("ocr")["text"].startswith("OCR: không dùng")


# ----------------------------------------------------------------------------- _finish_start
class TestFinishStart:
    def test_saves_settings_and_passes_config_to_scanner(self, c, data_dir):
        c.config.update(card_same_corr=0.7, require_game_foreground=False, game_process_names=["x.exe"],
                        buy_cooldown_ms=120, buy_delay_ms=5, name_scan_interval_ms=40)
        c._finish_start(plan(selected=["Vex"], manual_names="", names=["Vex"]), {}, OK_OCR)
        kw = FakeScanner.instances[-1].kw
        assert kw["card_same_corr"] == 0.7 and kw["require_game_foreground"] is False
        assert kw["game_process_names"] == ["x.exe"] and kw["buy_cooldown_ms"] == 120
        assert kw["buy_delay_ms"] == 5 and kw["name_scan_interval_ms"] == 40 and kw["detect_by_name"] is True
        saved = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
        assert saved["selected_champions"] == ["Vex"] and saved["scan_interval_ms"] == 5
        assert saved["detect_by_name"] is True and saved["match_threshold"] == 0.72

    def test_running_event_and_journal(self, c, ev):
        c._finish_start(plan(), {}, OK_OCR)
        assert ev.last("running_changed") == {"running": True} and c.running
        assert "Sẵn sàng bắt 1 tướng [tên]: Vex" in ev.logs() and "Bắt đầu quét" in ev.logs()
        assert ev.last("speed")["text"] == "Thực tế: đang đo..."

    def test_ocr_broken_with_images_runs_image_only_and_keeps_user_choice(self, c, ev, data_dir):
        img = config.TEMPLATES_DIR / "Vex.png"
        img.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(img), np.full((80, 80, 3), 120, np.uint8))
        c._finish_start(plan(detect_image=True, detect_name=True), {"Vex": img}, BAD_OCR)
        kw = FakeScanner.instances[-1].kw
        assert kw["detect_by_name"] is False and kw["detect_by_image"] is True
        assert "chỉ bắt theo ảnh" in ev.dialogs("warning")[-1]["text"]
        assert json.loads((data_dir / "config.json").read_text(encoding="utf-8"))["detect_by_name"] is True
        assert "Gợi ý OCR: Add-WindowsCapability demo" in ev.logs()
        assert c.ocr_status is BAD_OCR  # điều kiện chạy phản ánh OCR hỏng

    def test_ocr_broken_and_nothing_else_blocks_start(self, c, ev, data_dir):
        c._finish_start(plan(), {}, BAD_OCR)
        assert c.scanner is None and not FakeScanner.instances
        assert "Thiếu pack ngôn ngữ" in ev.dialogs("error")[-1]["text"]
        assert ev.last("status")["text"] == "OCR không hoạt động — chưa bắt đầu"
        assert ev.last("ocr")["tone"] == ctl.TONE_FAIL
        assert not (data_dir / "config.json").exists() or "Vex" not in (data_dir / "config.json").read_text(encoding="utf-8")

    def test_image_mode_without_any_image_and_no_name_mode_errors(self, c, ev):
        c._finish_start(plan(detect_image=True, detect_name=False), {}, None)
        assert c.scanner is None and "Không tải được ảnh tướng" in ev.dialogs("error")[-1]["text"]
        assert ev.last("status")["text"] == "Sẵn sàng"

    def test_image_mode_without_image_falls_back_to_name(self, c, ev):
        c._finish_start(plan(detect_image=True, detect_name=True), {}, OK_OCR)
        assert FakeScanner.instances[-1].kw["detect_by_name"] is True
        assert "Không có ảnh — chỉ dùng bắt theo tên" in ev.logs()

    def test_scanner_refusing_to_start_is_closed(self, make, monkeypatch):
        closed = []

        class Refusing(FakeScanner):
            def start(self):
                self.is_running = False

            def close(self):
                closed.append(True)

        k = make()
        k._scanner_factory = Refusing
        k._finish_start(plan(), {}, OK_OCR)
        assert k.scanner is None and closed == [True]

    def test_ocr_none_skips_the_ocr_gate(self, c):
        c._finish_start(plan(detect_name=True), {}, None)
        assert FakeScanner.instances[-1].kw["detect_by_name"] is True

    def test_scanner_callbacks_are_wired_to_events(self, c, ev):
        c._finish_start(plan(), {}, OK_OCR)
        kw = FakeScanner.instances[-1].kw
        for name in ("on_match", "on_status", "on_error", "on_log", "on_ocr_health", "on_stats"):
            assert callable(kw[name]), name
        kw["on_status"]("Đang quét shop (tên)...")
        kw["on_match"]("Vex", 3, 1.0, "tên")
        drain()
        kw["on_log"]("Quét: 504 vòng")
        drain()
        assert ev.last("status")["text"] == "Đang quét shop (tên)..."
        assert "Mua Vex ở ô 3 (tên 100%)" in ev.logs() and "Quét: 504 vòng" in ev.logs()

    def test_ocr_health_changes_label_tone(self, c, ev):
        c._finish_start(plan(), {}, OK_OCR)
        kw = FakeScanner.instances[-1].kw
        kw["on_ocr_health"](False)
        drain()
        assert ev.last("ocr")["tone"] == ctl.TONE_WARN and "có vấn đề" in ev.last("ocr")["text"]
        kw["on_ocr_health"](True)
        drain()
        assert ev.last("ocr")["tone"] == ctl.TONE_OK and ev.last("ocr")["text"].endswith("✓")

    def test_speed_updates_and_late_stats_are_ignored_after_stop(self, c, ev):
        c._finish_start(plan(), {}, OK_OCR)
        kw = FakeScanner.instances[-1].kw
        kw["on_stats"]({"avg_ms": 12.0, "max_ms": 40.0, "count": 50})
        drain()
        assert ev.last("speed")["text"].startswith("Thực tế: 12.0 ms/vòng")
        c.toggle()
        assert ev.last("speed")["text"].startswith("Lần quét trước: 12.0 ms/vòng")
        kw["on_stats"]({"avg_ms": 99.0, "max_ms": 99.0, "count": 1})
        drain()
        assert ev.last("speed")["text"].startswith("Lần quét trước: 12.0")

    def test_stop_without_measurement_shows_idle_text(self, c, ev):
        c._finish_start(plan(), {}, OK_OCR)
        c.toggle()
        assert ev.last("speed")["text"] == ctl.SPEED_IDLE_TEXT


class TestToggleAndErrors:
    def test_toggle_stops_running_scanner(self, c, ev):
        c._finish_start(plan(), {}, OK_OCR)
        scanner = c.scanner
        c.toggle()
        assert not scanner.is_running and c.scanner is None and not c.running
        assert ev.last("status")["text"] == "Đã dừng" and ev.last("running_changed") == {"running": False}

    def test_fatal_error_resets_state(self, c, ev):
        c._finish_start(plan(), {}, OK_OCR)
        c.scanner.is_running = False
        c._scanner_error("Chụp màn hình hỏng", True)
        assert c.scanner is None and ev.last("status")["text"] == "Chụp màn hình hỏng"
        assert ev.last("running_changed") == {"running": False} and "⚠ Chụp màn hình hỏng" in ev.logs()

    def test_nonfatal_error_only_logs(self, c, ev):
        c._finish_start(plan(), {}, OK_OCR)
        c._scanner_error("Lỗi OCR: x", False)
        assert c.running and "⚠ Lỗi OCR: x" in ev.logs()

    def test_fatal_error_keeps_a_newer_running_scanner(self, c):
        c._finish_start(plan(), {}, OK_OCR)
        c._scanner_error("lỗi muộn", True)
        assert c.scanner is not None and c.scanner.is_running

    def test_close_stops_scanner_and_unhooks(self, c, hotkeys):
        c._finish_start(plan(), {}, OK_OCR)
        scanner = c.scanner
        c.close()
        assert c.closing and not scanner.is_running and hotkeys.unhooked

    def test_close_survives_failing_unhook(self, make):
        k = make()
        k._keyboard = types.SimpleNamespace(unhook_all=lambda: (_ for _ in ()).throw(RuntimeError("x")))
        k.close()
        assert k.closing

    def test_events_after_close_are_dropped(self, c, ev):
        c.closing = True
        called = []
        c._post_safe(lambda: called.append(1))
        drain()
        assert not called
        c.closing = False
        c._post_safe(lambda: called.append(1))
        drain()
        assert called == [1]  # ngược lại (chưa đóng) thì được chạy: test không "đạt" vì hàng đợi trống

    def test_notify_survives_a_failing_listener(self, make):
        def boom(event, **data):
            raise ValueError("giao diện hỏng")

        k = ctl.AppController(boom, keyboard=None)
        k.log("xin chào")  # không ném lỗi


# ----------------------------------------------------------------------------- mở app
class TestStartUp:
    def test_startup_logs_version_registers_hotkey_and_loads(self, make, ev, hotkeys):
        k = make()
        k.start_up()
        assert "Phiên bản:" in ev.logs() and hotkeys.added and hotkeys.added[0][0] == "f8"
        assert wait_for(lambda: bool(k.champions))

    def test_version_line_is_just_the_version_number(self, make, ev, monkeypatch):
        """Nhật ký chỉ ghi 'Phiên bản: 1.0.0.7', không kèm ngày giờ build hay mã commit."""
        monkeypatch.setattr(ctl, "app_version", lambda: "1.0.0.7")
        make().start_up()
        lines = [ln for ln in ev.logs().splitlines() if "Phiên bản:" in ln]
        assert len(lines) == 1 and lines[0].endswith("] Phiên bản: 1.0.0.7")
        assert "build" not in lines[0] and "commit" not in lines[0]

    def test_corrupt_config_announces_notes(self, make, ev):
        k = make(saved_config="{ đây không phải json")
        k.start_up()
        d = ev.dialogs("warning")[0]
        assert d["title"] == "Cấu hình đã được xử lý khi mở" and d["text"].splitlines()[0] in ev.logs()

    def test_clean_config_shows_no_dialog(self, make, ev):
        make(saved_config={"coords_version": config.COORDS_VERSION}).start_up()
        assert not ev.of("dialog")

    def test_old_coordinates_cleared_announced_and_saved(self, make, ev, data_dir):
        k = make(saved_config={"shop_region": {"left": 1, "top": 2, "width": 800, "height": 160},
                               "slot_centers": [[1, 1]] * 5, "selected_champions": ["Vex"]})
        k.start_up()
        assert k.config["shop_region"] is None and k.config["slot_centers"] == []
        d = ev.dialogs("info")[0]
        assert d["title"] == "Cấu hình lại vùng Shop" and "Chọn vùng Shop" in d["text"]
        saved = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
        assert saved["coords_version"] == config.COORDS_VERSION and saved["selected_champions"] == ["Vex"]
        assert k.region_text() == "Chưa cấu hình shop"

    def test_old_config_without_coordinates_migrates_silently(self, make, ev, data_dir):
        make(saved_config={"selected_champions": ["Zed"]}).start_up()
        assert not ev.dialogs("info")
        assert json.loads((data_dir / "config.json").read_text(encoding="utf-8"))["coords_version"] == config.COORDS_VERSION

    def test_current_version_coordinates_are_kept(self, make):
        region = {"left": 5, "top": 6, "width": 900, "height": 170}
        k = make(saved_config={"coords_version": config.COORDS_VERSION, "shop_region": region,
                               "slot_centers": [[50, 60]] * 5})
        assert k.config["shop_region"] == region and k.region_text().startswith("Shop: (5, 6) 900x170 | Click: 5/5")

    def test_invalid_hotkey_falls_back_and_is_logged(self, make, ev):
        k = make(saved_config={"hotkey_toggle": "khong-phai-phim"})
        calls = []

        def add(key, cb, suppress=False):
            calls.append(key)
            if key != "f8":
                raise ValueError("unknown key")

        k._keyboard = types.SimpleNamespace(add_hotkey=add, unhook_all=lambda: None)
        k.register_hotkey()
        assert calls == ["khong-phai-phim", "f8"] and k.hotkey == "f8" and ev.of("hotkey_changed")
        assert k.toggle_text(False) == "▶ BẮT ĐẦU (F8)" and k.toggle_text(True) == "⏹ DỪNG (F8)"

    def test_hotkey_press_toggles_through_post(self, make, hotkeys):
        queued = []
        k = make(post=queued.append)
        k.register_hotkey()
        hotkeys.added[0][1]()  # thread của thư viện keyboard bấm phím
        assert len(queued) == 1  # được chuyển sang luồng giao diện, không chạy trực tiếp


# ----------------------------------------------------------------------------- danh sách tướng
class TestChampionList:
    def test_populate_ticks_saved_selection_matching_normalised_names(self, make, ev):
        k = make(saved_config={"selected_champions": ["Vex", " zed "]})
        k.populate_champions(ENTRIES)
        assert k.is_selected("Vex") and k.is_selected("Zed") and not k.is_selected("Graves")
        assert ev.last("status")["text"] == "Đã tải 5 tướng (mùa 18)"
        assert k.selected_names() == ["Vex", "Graves", "Zed", "Ahri", "Jinx"][:0] + [
            c["name"] for c in k.champions if c["name"] in {"Vex", "Zed"}]
        assert ev.of("selection_changed") and ev.of("champions_changed")

    def test_old_set_selection_announced(self, make, ev):
        k = make(saved_config={"selected_champions": ["Sivir"]})
        k.populate_champions(ENTRIES)
        assert "1 tướng đã chọn thuộc mùa cũ đang ẩn (Sivir)" in ev.logs()

    def test_show_old_toggle_adds_old_set_and_is_saved(self, loaded, data_dir):
        assert "Sivir" not in [x["name"] for x in loaded.filtered()]
        loaded.set_show_old(True)
        assert "Sivir" in [x["name"] for x in loaded.filtered()]
        assert json.loads((data_dir / "config.json").read_text(encoding="utf-8"))["show_old_sets"] is True

    def test_search_matches_name_and_other_language_name(self, loaded):
        loaded.set_query("ze")
        assert [x["name"] for x in loaded.filtered()] == ["Zed"]
        loaded.set_query("  ZED  ")
        assert [x["name"] for x in loaded.filtered()] == ["Zed"]
        loaded.set_query("không-có-tướng-này")
        assert loaded.filtered() == []

    def test_search_uses_alt_name(self, make):
        k = make()
        k.populate_champions([champ("Ngộ Không", alt="Wukong"), champ("Zed")])
        k.set_query("wukong")
        assert [x["name"] for x in k.filtered()] == ["Ngộ Không"]

    def test_cost_filter_and_available_costs(self, loaded):
        assert loaded.costs_available() == [1, 2, 4, 5]
        loaded.toggle_cost(1, True)
        assert {x["name"] for x in loaded.filtered()} == {"Vex", "Graves"}
        loaded.toggle_cost(5, True)
        assert {x["name"] for x in loaded.filtered()} == {"Vex", "Graves", "Jinx"}
        loaded.toggle_cost(1, False)
        loaded.toggle_cost(5, False)
        assert len(loaded.filtered()) == 5

    def test_only_selected_filter_and_combination(self, loaded):
        loaded.set_selected("Zed", True)
        loaded.set_selected("Jinx", True)
        loaded.set_only_selected(True)
        assert {x["name"] for x in loaded.filtered()} == {"Zed", "Jinx"}
        loaded.toggle_cost(5, True)
        loaded.set_query("ji")
        assert [x["name"] for x in loaded.filtered()] == ["Jinx"]

    def test_filter_changes_notify(self, loaded, ev):
        before = len(ev.of("filter_changed"))
        loaded.set_query("a")
        loaded.toggle_cost(1, True)
        loaded.set_only_selected(True)
        loaded.set_show_old(True)
        assert len(ev.of("filter_changed")) == before + 4

    def test_select_all_respects_current_filter_and_hidden_old_set(self, loaded):
        loaded.toggle_cost(1, True)
        loaded.select_all_visible()
        assert {x for x in ("Vex", "Graves") if loaded.is_selected(x)} == {"Vex", "Graves"}
        assert not loaded.is_selected("Zed") and not loaded.is_selected("Sivir")
        loaded.deselect_all_visible()
        assert not any(loaded.is_selected(n) for n in ("Vex", "Graves"))

    def test_selection_is_not_lost_when_filtered_out(self, loaded):
        loaded.set_selected("Jinx", True)
        loaded.set_query("zed")
        assert loaded.is_selected("Jinx") and "Jinx" in loaded.selected_names()

    def test_manual_and_checked_names_deduplicate(self, loaded):
        loaded.set_selected("Vex", True)
        loaded.manual_names = "Vex,\nTahm Kench"
        assert loaded.target_names() == ["Vex", "Tahm Kench"]

    def test_offline_uses_saved_selection(self, make):
        assert make(saved_config={"selected_champions": ["Zed"]}).selected_names() == ["Zed"]

    def test_fetch_success_populates_and_writes_cache(self, make, data_dir):
        k = make()
        k.load_champions_async()
        assert wait_for(lambda: bool(k.champions))
        assert (data_dir / "champions_cache.json").exists() and not k.loading_champions

    def test_fetch_failure_reports_and_reload_retries(self, make, ev, monkeypatch):
        attempts = []

        def fetch(locale=None):
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("mất mạng")
            return ENTRIES

        monkeypatch.setattr(ctl, "fetch_champion_list", fetch)
        k = make()
        k.load_champions_async()
        assert wait_for(lambda: "Lỗi tải tướng: mất mạng" in ev.last("status")["text"])
        assert "bấm 'Tải lại danh sách'" in ev.logs() and not k.loading_champions
        k.reload_champions()
        assert wait_for(lambda: bool(k.champions))
        k.reload_champions()
        assert len(attempts) == 2 and "Danh sách tướng đã tải rồi" in ev.logs()

    def test_reload_ignored_while_loading(self, c, ev):
        c.loading_champions = True
        c.reload_champions()
        assert "Đang thử tải lại" not in ev.logs()

    def test_cache_write_failure_does_not_break_loading(self, make, monkeypatch):
        monkeypatch.setattr(ctl, "save_champion_cache", lambda e: (_ for _ in ()).throw(OSError("chỉ đọc")))
        k = make()
        k.load_champions_async()
        assert wait_for(lambda: bool(k.champions))

    @pytest.mark.parametrize("ok", [True, False])
    def test_fetch_finishing_when_ui_is_gone_does_not_crash_the_thread(self, make, ok, monkeypatch):
        def fetch(locale=None):
            if ok:
                return ENTRIES
            raise ConnectionError("x")

        monkeypatch.setattr(ctl, "fetch_champion_list", fetch)
        k = make(post=lambda fn: (_ for _ in ()).throw(RuntimeError("main thread is not in main loop")))
        errors = []

        def work():
            try:
                k._fetch_champions()
            except BaseException as e:
                errors.append(e)

        t = threading.Thread(target=work)
        t.start()
        t.join(5)
        assert errors == []


# ----------------------------------------------------------------------------- upload
class TestUpload:
    def test_valid_image_saved_and_remembered(self, loaded, tmp_path, data_dir, ev):
        src = tmp_path / "vex.jpg"
        cv2.imwrite(str(src), np.full((90, 120, 3), 200, np.uint8))
        loaded.upload_template("Vex", str(src))
        stored = loaded.config["custom_templates"]["Vex"]
        assert stored == "templates/custom_Vex.png" and (data_dir / stored).exists()
        assert json.loads((data_dir / "config.json").read_text(encoding="utf-8"))["custom_templates"]["Vex"] == stored
        assert "Đã upload ảnh cho Vex" in ev.logs()

    def test_unreadable_file_raises_and_saves_nothing(self, loaded, tmp_path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"khong phai anh")
        with pytest.raises(ValueError):
            loaded.upload_template("Vex", str(bad))
        assert not loaded.config.get("custom_templates")


# ----------------------------------------------------------------------------- vùng / điểm click / preview
class TestRegionAndPreview:
    @pytest.fixture(autouse=True)
    def no_real_preview(self, monkeypatch):
        self.calls = []

        def fake(region, centers, capture_live=True):
            self.calls.append((region, centers, capture_live))
            return PreviewResult(None, False, "")

        monkeypatch.setattr(ctl, "build_shop_preview", fake)

    def test_set_region_saves_notifies_and_refreshes(self, c, ev, data_dir):
        c.set_region({"left": 300, "top": 700, "width": 1200, "height": 200})
        assert json.loads((data_dir / "config.json").read_text(encoding="utf-8"))["shop_region"]["width"] == 1200
        assert c.region_text().startswith("Shop: (300, 700) 1200x200") and ev.of("config_changed")
        assert wait_for(lambda: bool(self.calls)) and self.calls[0][2] is True

    def test_set_click_points_saves_five_points(self, c, data_dir):
        c.config["shop_region"] = {"left": 0, "top": 0, "width": 1000, "height": 200}
        c.set_click_points([(40 + i * 190, 150) for i in range(5)])
        assert len(json.loads((data_dir / "config.json").read_text(encoding="utf-8"))["slot_centers"]) == 5
        assert c.region_text().endswith("Click: 5/5 ô")

    def test_point_inside_region(self, c):
        assert not c.point_inside_region(5, 5)  # chưa có vùng
        c.config["shop_region"] = {"left": 100, "top": 100, "width": 1000, "height": 200}
        assert c.point_inside_region(150, 200) and not c.point_inside_region(5, 5)

    def test_refresh_without_region_returns_false(self, c):
        assert c.refresh_preview() is False and not self.calls

    def test_preview_event_carries_note_and_tone(self, c, ev, monkeypatch):
        from datetime import datetime
        from PIL import Image

        img = Image.new("RGB", (10, 10))
        monkeypatch.setattr(ctl, "build_shop_preview",
                            lambda *a, **k: PreviewResult(img, True, "ok", datetime(2026, 1, 2, 3, 4, 5)))
        c.config["shop_region"] = {"left": 0, "top": 0, "width": 100, "height": 50}
        assert c.refresh_preview() is True
        assert wait_for(lambda: bool(ev.of("preview")))
        p = ev.last("preview")
        assert p["image"] is img and p["note"] == "Chụp lúc 03:04:05. ok" and p["tone"] == ctl.TONE_MUTED
        assert ev.last("preview_busy") == {"busy": False}

    def test_failed_preview_is_red_and_logged(self, c, ev, monkeypatch):
        monkeypatch.setattr(ctl, "build_shop_preview", lambda *a, **k: PreviewResult(None, False, "Chụp lỗi"))
        c.config["shop_region"] = {"left": 0, "top": 0, "width": 100, "height": 50}
        c.request_preview()
        assert wait_for(lambda: bool(ev.of("preview")))
        assert ev.last("preview")["tone"] == ctl.TONE_FAIL and "Preview: Chụp lỗi" in ev.logs()

    def test_stale_preview_results_are_dropped(self, c, ev):
        c._preview_seq = 5
        c._preview_inflight = 2
        c._preview_ready(4, PreviewResult(None, False, "cũ"))
        assert not ev.of("preview") and ev.last("preview_busy") is None  # còn yêu cầu đang chạy
        c._preview_ready(5, PreviewResult(None, False, "mới"))
        assert ev.last("preview")["note"] == "mới" and ev.last("preview_busy") == {"busy": False}

    def test_unexpected_exception_becomes_a_note(self, c, ev, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("hỏng")

        monkeypatch.setattr(ctl, "build_shop_preview", boom)
        c.config["shop_region"] = {"left": 0, "top": 0, "width": 100, "height": 50}
        c.request_preview()
        assert wait_for(lambda: bool(ev.of("preview")))
        assert "Lỗi tạo preview: RuntimeError: hỏng" in ev.last("preview")["note"]


# ----------------------------------------------------------------------------- ảnh chân dung
class TestPortraits:
    def test_portrait_path_none_until_downloaded(self, loaded):
        c0 = loaded.champions[0]
        assert loaded.portrait_path(c0) is None
        p = champions.template_path(c0["name"], c0["image_url"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        assert loaded.portrait_path(c0) == p

    def test_fetch_downloads_only_missing_visible_ones_and_notifies(self, make, ev, monkeypatch):
        got = []

        def fake(name, url):
            got.append(name)
            p = champions.template_path(name, url)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
            return p

        monkeypatch.setattr(ctl, "download_template", fake)
        k = make()
        k.populate_champions(ENTRIES)
        assert wait_for(lambda: len(ev.of("portrait_ready")) == 5)
        assert sorted(got) == ["Ahri", "Graves", "Jinx", "Vex", "Zed"] and "Sivir" not in got  # mùa cũ đang ẩn
        got.clear()
        k.fetch_portraits_async()  # đã có hết: không tải lại
        time.sleep(0.1)
        assert got == []

    def test_failed_download_does_not_notify_or_crash(self, make, ev, monkeypatch):
        monkeypatch.setattr(ctl, "download_template", lambda n, u: None)
        k = make()
        k.populate_champions(ENTRIES)
        time.sleep(0.3)
        drain()
        assert not ev.of("portrait_ready") and not k._portraits_running

    def test_closing_stops_fetching(self, make, ev, monkeypatch):
        monkeypatch.setattr(ctl, "download_template", lambda n, u: None)
        k = make()
        k.closing = True
        k.populate_champions(ENTRIES)
        time.sleep(0.2)
        assert not k._portraits_running


# ----------------------------------------------------------------------------- phím roll
class TestRollKey:
    @pytest.fixture
    def kb(self):
        calls = types.SimpleNamespace(added=[], removed=[])

        def add(key, cb, suppress=False):
            calls.added.append((key, cb, suppress))
            return f"handle-{len(calls.added)}"

        return types.SimpleNamespace(add_hotkey=add, remove_hotkey=lambda h: calls.removed.append(h),
                                     unhook_all=lambda: None, calls=calls)

    def controller(self, make, kb, saved=None):
        k = make(saved_config=saved)
        k._keyboard = kb
        return k

    def test_default_roll_key_is_d_and_registered_on_startup(self, make, kb, ev):
        k = self.controller(make, kb)
        k.start_up()
        assert k.roll_key == "d"
        assert [a[0] for a in kb.calls.added] == ["f8", "d"] and all(a[2] is False for a in kb.calls.added)
        assert "Đồng bộ phím roll: D" in ev.logs()

    def test_pressing_roll_key_wakes_the_running_scanner_directly(self, make, kb):
        k = self.controller(make, kb)
        k.register_roll_key()
        k._finish_start(plan(), {}, OK_OCR)
        kb.calls.added[-1][1]()  # luồng của thư viện phím gọi, KHÔNG qua hàng đợi giao diện
        assert k.scanner.rolls == 1

    def test_pressing_roll_key_without_scanner_is_harmless(self, make, kb):
        k = self.controller(make, kb)
        k.register_roll_key()
        kb.calls.added[-1][1]()

    def test_empty_roll_key_disables_the_feature(self, make, kb):
        k = self.controller(make, kb, saved={"roll_key": ""})
        k.register_roll_key()
        assert kb.calls.added == []

    def test_set_roll_key_saves_and_replaces_old_hook(self, make, kb, data_dir):
        k = self.controller(make, kb)
        k.register_roll_key()
        k.set_roll_key(" r ")
        assert k.roll_key == "r" and kb.calls.removed == ["handle-1"] and kb.calls.added[-1][0] == "r"
        assert json.loads((data_dir / "config.json").read_text(encoding="utf-8"))["roll_key"] == "r"

    def test_clearing_the_key_removes_the_hook_and_says_so(self, make, kb, ev):
        k = self.controller(make, kb)
        k.register_roll_key()
        k.set_roll_key("")
        assert kb.calls.removed == ["handle-1"] and "Đã tắt đồng bộ phím roll." in ev.logs() and len(kb.calls.added) == 1

    def test_roll_key_equal_to_toggle_key_is_refused(self, make, kb, ev):
        k = self.controller(make, kb, saved={"roll_key": "f8"})
        k.register_roll_key()
        assert kb.calls.added == [] and "trùng phím bật/tắt" in ev.logs()

    def test_failure_removing_old_hook_does_not_break_registration(self, make, kb):
        k = self.controller(make, kb)
        k.register_roll_key()
        kb.remove_hotkey = lambda h: (_ for _ in ()).throw(KeyError(h))
        k.set_roll_key("e")
        assert kb.calls.added[-1][0] == "e"

    def test_without_keyboard_module_nothing_happens(self, make):
        k = make()
        k._keyboard = None
        k.register_roll_key()
        k.set_roll_key("x")


# ----------------------------------------------------------------------------- chẩn đoán và giấy phép
class TestDiagnostics:
    def test_export_runs_in_background_then_reports_path(self, make, ev, monkeypatch, tmp_path):
        k = make()
        seen = {}
        zip_path = tmp_path / "TFT_Auto_Buy_chan_doan_x.zip"

        def fake_write(cfg, running=False, **kw):
            seen.update(cfg=cfg, running=running, thread=threading.current_thread().name)
            return zip_path

        monkeypatch.setattr(ctl.diagnostics, "write_report", fake_write)
        k.export_diagnostics()
        assert ev.last("diagnostics_busy") == {"busy": True}
        assert wait_for(lambda: ev.last("diagnostics_saved") is not None)
        assert ev.last("diagnostics_saved") == {"path": str(zip_path)}
        assert ev.last("diagnostics_busy") == {"busy": False}
        assert seen["thread"] != threading.main_thread().name  # selftest mất vài giây: không được chặn luồng giao diện
        assert seen["running"] is False and seen["cfg"] is not k.config  # truyền bản sao, luồng nền không đọc config đang sửa
        assert any(str(zip_path) in d["text"] for d in ev.of("log"))

    def test_running_flag_is_passed_when_scanning(self, make, ev, monkeypatch):
        k = make()
        k._finish_start(plan(), {}, OK_OCR)  # cách các test khác đưa controller vào trạng thái đang quét
        assert k.running
        got = {}
        monkeypatch.setattr(ctl.diagnostics, "write_report", lambda cfg, running=False, **kw: got.setdefault("r", running) and Path("x.zip"))
        k.export_diagnostics()
        assert wait_for(lambda: "r" in got) and got["r"] is True

    def test_second_click_while_busy_is_ignored(self, make, ev, monkeypatch):
        k = make()
        gate = threading.Event()
        calls = []

        def slow(cfg, running=False, **kw):
            calls.append(1)
            gate.wait(2)
            return Path("x.zip")

        monkeypatch.setattr(ctl.diagnostics, "write_report", slow)
        k.export_diagnostics()
        k.export_diagnostics()
        k.export_diagnostics()
        gate.set()
        assert wait_for(lambda: ev.last("diagnostics_saved") is not None)
        assert calls == [1] and len(ev.of("diagnostics_busy")) == 2  # bật một lần, tắt một lần

    def test_can_export_again_after_finishing(self, make, ev, monkeypatch):
        k = make()
        monkeypatch.setattr(ctl.diagnostics, "write_report", lambda cfg, running=False, **kw: Path("x.zip"))
        k.export_diagnostics()
        assert wait_for(lambda: len(ev.of("diagnostics_saved")) == 1)
        k.export_diagnostics()
        assert wait_for(lambda: len(ev.of("diagnostics_saved")) == 2)

    def test_failure_is_logged_and_shown_and_unlocks_button(self, make, ev, monkeypatch):
        k = make()

        def boom(cfg, running=False, **kw):
            raise PermissionError("Desktop bị khóa")

        monkeypatch.setattr(ctl.diagnostics, "write_report", boom)
        k.export_diagnostics()
        assert wait_for(lambda: bool(ev.dialogs("error")))
        assert "PermissionError: Desktop bị khóa" in ev.dialogs("error")[0]["text"]
        assert ev.last("diagnostics_busy") == {"busy": False} and ev.last("diagnostics_saved") is None
        assert "Không tạo được báo cáo chẩn đoán" in ev.logs()

    def test_closing_app_while_building_does_not_notify(self, make, ev, monkeypatch):
        k = make()
        gate = threading.Event()
        monkeypatch.setattr(ctl.diagnostics, "write_report", lambda cfg, running=False, **kw: gate.wait(2) and Path("x.zip"))
        k.export_diagnostics()
        k.closing = True
        gate.set()
        time.sleep(0.2)
        drain()
        assert ev.last("diagnostics_saved") is None


class TestLicenseSummary:
    def test_valid_license(self, make, monkeypatch):
        from core import license as lic

        info = lic.KeyInfo(machine=b"\0" * 16, issued_at=1, expires_at=2, key_id="4ca1b490fca75c29")
        monkeypatch.setattr(ctl.license_check, "check_installed", lambda *a: lic.Status(True, info=info, activated_at=1_800_000_000))
        monkeypatch.setattr(ctl.license_check, "machine_code", lambda: "AAAA-BBBB")
        s = make().license_summary()
        assert s["ok"] and s["key_id"] == "4ca1b490fca75c29" and s["machine_code"] == "AAAA-BBBB"
        assert s["activated"] == datetime.fromtimestamp(1_800_000_000).strftime("%Y-%m-%d %H:%M") and s["reason"] == ""

    def test_missing_activation_time_is_blank(self, make, monkeypatch):
        from core import license as lic

        info = lic.KeyInfo(machine=b"\0" * 16, issued_at=1, expires_at=2, key_id="abc")
        monkeypatch.setattr(ctl.license_check, "check_installed", lambda *a: lic.Status(True, info=info))
        monkeypatch.setattr(ctl.license_check, "machine_code", lambda: "AAAA")
        assert make().license_summary()["activated"] == ""

    def test_invalid_license_gives_reason(self, make, monkeypatch):
        from core import license as lic

        monkeypatch.setattr(ctl.license_check, "check_installed", lambda *a: lic.Status(False, "Giấy phép bị hỏng"))
        monkeypatch.setattr(ctl.license_check, "machine_code", lambda: "AAAA")
        s = make().license_summary()
        assert not s["ok"] and s["reason"] == "Giấy phép bị hỏng" and s["key_id"] == "" and s["machine_code"] == "AAAA"

    def test_machine_code_error_does_not_crash(self, make, monkeypatch):
        from core import license as lic

        def boom():
            raise lic.LicenseError("không đọc được định danh")

        monkeypatch.setattr(ctl.license_check, "check_installed", lambda *a: lic.Status(False, ""))
        monkeypatch.setattr(ctl.license_check, "machine_code", boom)
        s = make().license_summary()
        assert s["machine_code"] == "" and "không đọc được định danh" in s["reason"]
