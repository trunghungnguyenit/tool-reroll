"""Giao diện Qt trên nền offscreen (pytest-qt): thao tác thật bằng chuột/bàn phím lên widget, kiểm tra phản hồi tức thì,
bố cục thích ứng, tràn ngang, chủ đề sáng/tối và chụp ảnh giao diện để soát bằng mắt. Scanner, mạng, hộp thoại và overlay
được thay bằng bản giả; không có thao tác nào chạm vào chuột/màn hình thật."""

import json
import types

import cv2
import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QScrollArea, QWidget

import core.champions as champions
import core.config as config
import core.controller as ctl
import core.monitors as monitors_mod
from core.monitors import Monitor
from core.preview import PreviewResult
from tests.fakes import BAD_OCR, ENTRIES, OK_OCR, FakeScanner, champ, fake_loader
from ui import main_window as mw
from tests.overlay_fakes import Cursor, drag, one_screen
from ui import overlay as ov
from ui import theme
from ui.champion_view import MODE_CARDS, MODE_TEXT
from ui.widgets import ElidedButton, FlowLayout, Switch


class Boxes:
    def __init__(self):
        self.items = []


@pytest.fixture
def boxes(monkeypatch):
    b = Boxes()
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda parent, title, text, _k=kind: b.items.append((_k, title, text))))
    return b


@pytest.fixture
def make_window(qtbot, data_dir, monkeypatch, boxes):
    FakeScanner.instances = []
    monkeypatch.setattr(ctl, "load_all_champions", fake_loader(ENTRIES))
    monkeypatch.setattr(ctl, "download_template", lambda n, u: None)
    monkeypatch.setattr(ctl, "build_shop_preview", lambda *a, **k: PreviewResult(None, False, ""))
    kb = types.SimpleNamespace(add_hotkey=lambda *a, **k: None, unhook_all=lambda: None)
    created = []

    def factory(saved_config=None, size=(1100, 820), overlay_factory=None, autoload=True):
        if saved_config is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "config.json").write_text(json.dumps(saved_config), encoding="utf-8")
        if not autoload:
            monkeypatch.setattr(ctl.AppController, "load_champions_async", lambda self: None)

        def make(notify, post):
            return ctl.AppController(notify, post=post, keyboard=kb, scanner_factory=FakeScanner)

        w = mw.MainWindow(make, overlay_factory=overlay_factory)
        qtbot.addWidget(w)
        w.resize(*size)
        w.show()
        QApplication.processEvents()
        created.append(w)
        return w

    yield factory
    for w in created:
        w.c.closing = True


def ready_config(**extra):
    base = {"coords_version": config.COORDS_VERSION, "theme": "light",
            "shop_region": {"left": 0, "top": 0, "width": 1000, "height": 200},
            "slot_centers": [[40 + i * 190, 150] for i in range(5)], "detect_by_image": False, "detect_by_name": True,
            "selected_champions": ["Vex"], "scan_interval_ms": 5}
    base.update(extra)
    return base


@pytest.fixture
def window(make_window, qtbot):
    w = make_window(ready_config())
    qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
    return w


def card_center(view, name):
    for row, c in enumerate(view.champion_model.items()):
        if c["name"] == name:
            return view.visualRect(view.champion_model.index(row)).center()
    raise AssertionError(f"{name} không có trong danh sách đang hiện")


def click_card(qtbot, window, name):
    qtbot.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, pos=card_center(window.view, name))


# --------------------------------------------------------------------------- khởi động và thanh điều khiển
class TestTopBar:
    def test_window_title_matches_single_instance_lookup(self, window):
        from core.single_instance import APP_TITLE

        assert window.windowTitle() == APP_TITLE

    def test_ready_state_shows_primary_button_and_green_chip(self, window):
        assert window.start_btn.text() == "▶ BẮT ĐẦU (F8)" and window.start_btn.isEnabled()
        assert window.chip_ready.text() == "✓ Sẵn sàng" and window.chip_ready.property("tone") == "ok"
        assert window.start_btn.property("blocked") is False
        assert window.chip_selected.text() == "1 tướng đang chọn"
        assert window.hotkey_label.text() == "Phím bật/tắt: F8"

    def test_not_ready_state_names_what_is_missing_and_marks_button(self, make_window):
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"})
        assert w.chip_ready.text() == "✗ Chưa chọn tướng nào" and w.chip_ready.property("tone") == "fail"
        assert w.start_btn.property("blocked") is True and "bấm để được dẫn" in w.start_btn.toolTip()
        assert w.start_btn.isEnabled()  # vẫn bấm được: nút dẫn tới bước còn thiếu

    def test_version_line_in_journal(self, window):
        from core.build_info import app_version

        text = window.log_view.toPlainText()
        assert f"] Phiên bản: {app_version()}" in text and "build 20" not in text

    def test_status_and_selected_chip_follow_loading(self, window):
        assert window.status_label.text().startswith("Đã tải 6 tướng")
        assert window.count_label.text() == "6/6 tướng"


class TestImmediateFeedback:
    def test_switching_modes_updates_readiness_at_once(self, window):
        window.sw_image.setChecked(False)
        window.sw_name.setChecked(False)
        assert window.chip_ready.text() == "✗ Bật ít nhất 1 chế độ: ảnh hoặc tên"
        assert window.ready_rows["mode"].property("state") == "fail"
        window.sw_name.setChecked(True)
        assert window.chip_ready.text() == "✓ Sẵn sàng"

    def test_manual_names_make_the_app_ready_while_typing(self, make_window):
        w = make_window(ready_config(selected_champions=[]), autoload=False)
        assert not w.c.ready()
        w.manual.setPlainText("Vex")
        assert w.c.ready() and w.chip_selected.text() == "1 tướng đang chọn"

    def test_interval_spinbox_updates_controller_and_row(self, window):
        window.interval.setValue(42)
        assert window.c.interval_text == "42" and window.c.interval_value() == 42

    def test_thresholds_show_percent_and_reach_controller(self, window):
        window.sl_image.setValue(66)
        window.sl_name.setValue(91)
        assert window.lb_image.text() == "66%" and window.lb_name.text() == "91%"
        assert window.c.threshold == 0.66 and window.c.name_threshold == 0.91

    def test_settings_loaded_from_config_are_shown(self, make_window):
        w = make_window(ready_config(match_threshold=0.6, name_match_threshold=0.9, scan_interval_ms=7,
                                     manual_names="Zed", detect_by_image=True, detect_by_name=False))
        assert w.sw_image.isChecked() and not w.sw_name.isChecked()
        assert w.sl_image.value() == 60 and w.lb_name.text() == "90%" and w.interval.value() == 7
        assert w.manual.toPlainText() == "Zed"


# --------------------------------------------------------------------------- bắt đầu / dừng
class TestStartStop:
    def test_start_then_stop_through_the_button(self, window, qtbot, monkeypatch):
        monkeypatch.setattr(ctl, "check_ocr", lambda wanted_extra=(): OK_OCR)
        window.start_btn.click()
        assert window.start_btn.text() == "Đang chuẩn bị…" and not window.start_btn.isEnabled()
        qtbot.waitUntil(lambda: window.c.running, timeout=3000)
        assert window.start_btn.text() == "⏹ DỪNG (F8)" and window.start_btn.property("running") is True
        assert "OCR: Windows OCR (en-US) ✓" in window.chip_ocr.text() and window.chip_ocr.property("tone") == "ok"
        assert window.chip_speed.text() == "Thực tế: đang đo..."
        window.start_btn.click()
        assert not window.c.running and window.start_btn.text() == "▶ BẮT ĐẦU (F8)"
        assert window.status_label.text() == "Đã dừng"

    def test_live_speed_and_ocr_health_reach_the_chips(self, window, qtbot, monkeypatch):
        monkeypatch.setattr(ctl, "check_ocr", lambda wanted_extra=(): OK_OCR)
        window.start_btn.click()
        qtbot.waitUntil(lambda: window.c.running, timeout=3000)
        kw = FakeScanner.instances[-1].kw
        kw["on_stats"]({"avg_ms": 9.0, "max_ms": 25.0, "count": 111})
        kw["on_ocr_health"](False)
        qtbot.waitUntil(lambda: "chậm nhất 25 ms" in window.chip_speed.text(), timeout=2000)
        assert window.chip_ocr.property("tone") == "warn" and "có vấn đề" in window.chip_ocr.text()
        assert window.speed_label.text().startswith("Thực tế: 9.0 ms/vòng")

    def test_broken_ocr_shows_error_dialog_and_red_chip(self, window, qtbot, monkeypatch, boxes):
        monkeypatch.setattr(ctl, "check_ocr", lambda wanted_extra=(): BAD_OCR)
        window.start_btn.click()
        qtbot.waitUntil(lambda: any(k == "critical" for k, *_ in boxes.items), timeout=3000)
        assert "Thiếu pack ngôn ngữ" in boxes.items[-1][2]
        assert window.chip_ocr.property("tone") == "fail" and not window.c.running
        assert window.start_btn.isEnabled()

    def test_scanner_log_lines_land_in_the_journal(self, window, qtbot, monkeypatch):
        monkeypatch.setattr(ctl, "check_ocr", lambda wanted_extra=(): OK_OCR)
        window.start_btn.click()
        qtbot.waitUntil(lambda: window.c.running, timeout=3000)
        FakeScanner.instances[-1].kw["on_match"]("Vex", 3, 1.0, "tên")
        qtbot.waitUntil(lambda: "Mua Vex ở ô 3" in window.log_view.toPlainText(), timeout=2000)

    def test_hotkey_callback_toggles_from_another_thread(self, make_window, qtbot, monkeypatch):
        added = []
        kb = types.SimpleNamespace(add_hotkey=lambda *a, **k: added.append(a), unhook_all=lambda: None)
        monkeypatch.setattr(ctl, "check_ocr", lambda wanted_extra=(): OK_OCR)

        def make(notify, post):
            return ctl.AppController(notify, post=post, keyboard=kb, scanner_factory=FakeScanner)

        w = mw.MainWindow(make)
        qtbot.addWidget(w)
        w.show()
        qtbot.waitUntil(lambda: bool(added), timeout=2000)
        w.c.config.update(ready_config())
        w.c.manual_names = "Vex"
        import threading

        threading.Thread(target=added[0][1]).start()  # thread của thư viện keyboard
        qtbot.waitUntil(lambda: w.c.running, timeout=3000)
        w.c.closing = True


class TestBlockedStart:
    def test_wide_layout_flashes_the_card_and_explains(self, make_window, qtbot):
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light", "selected_champions": ["Vex"]})
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        w.start_btn.click()
        assert w.status_label.text() == "Chưa chạy được: Chưa chọn vùng Shop"
        assert w.shop_card.property("attention") is True
        qtbot.waitUntil(lambda: w.shop_card.property("attention") is False, timeout=3000)

    def test_compact_layout_jumps_to_the_right_tab(self, make_window, qtbot):
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light", "selected_champions": ["Vex"]},
                        size=(460, 780))
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        assert w._compact and w.tabbar.currentIndex() == mw.PAGE_CHAMPIONS
        w.start_btn.click()
        assert w.tabbar.currentIndex() == mw.PAGE_SHOP and w.stack.currentIndex() == mw.PAGE_SHOP

    def test_bad_interval_opens_advanced_and_focuses_it(self, window):
        window.interval.setValue(0)
        window.c.interval_text = "abc"
        window.c.changed()
        window.start_btn.click()
        assert window.adv_toggle.isChecked() and window.adv_body.isVisible()
        assert "Chu kỳ quét phải là số nguyên" in window.status_label.text()

    def test_clicking_a_missing_row_navigates(self, make_window, qtbot):
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, size=(460, 780))
        w.ready_rows["region"].click()
        assert w.tabbar.currentIndex() == mw.PAGE_SHOP


# --------------------------------------------------------------------------- danh sách tướng
class TestChampionList:
    def names(self, w):
        return [c["name"] for c in w.view.champion_model.items()]

    def test_shows_every_season_by_default(self, window):
        assert sorted(self.names(window)) == ["Ahri", "Graves", "Jinx", "Sivir", "Vex", "Zed"]

    def test_search_filters_instantly_without_creating_widgets(self, window, qtbot):
        qtbot.keyClick(window.search, "g")  # lần gõ đầu Qt tạo nút xóa nội bộ của ô tìm kiếm
        before = len(window.findChildren(QWidget))
        for ch in "ra":
            qtbot.keyClick(window.search, ch)
        assert self.names(window) == ["Graves"] and window.count_label.text() == "1 kết quả (tìm trong mọi mùa)"
        after = len(window.findChildren(QWidget))
        assert after == before  # gõ tìm kiếm không dựng/hủy widget nào (khác bản Tk dựng lại cả lưới)

    def test_search_works_on_other_language_name_and_clears(self, window, qtbot):
        window.search.setText("  ZED ")
        assert self.names(window) == ["Zed"]
        window.search.clear()
        assert len(self.names(window)) == 6

    def test_empty_search_result_is_empty_list(self, window):
        window.search.setText("không có tướng này")
        assert self.names(window) == [] and window.count_label.text() == "0 kết quả (tìm trong mọi mùa)"

    def test_cost_chips_filter_and_unavailable_cost_is_disabled(self, window):
        assert not window.cost_buttons[3].isEnabled() and window.cost_buttons[1].isEnabled()
        window.cost_buttons[1].setChecked(True)
        assert sorted(self.names(window)) == ["Graves", "Sivir", "Vex"]
        window.cost_buttons[5].setChecked(True)
        assert sorted(self.names(window)) == ["Graves", "Jinx", "Sivir", "Vex"]

    def test_only_selected_filter(self, window):
        window.only_sel_btn.setChecked(True)
        assert self.names(window) == ["Vex"]
        click_card_names = window.view.champion_model.items()
        assert len(click_card_names) == 1


    def test_click_toggles_selection_immediately_and_updates_chips(self, window, qtbot):
        assert not window.c.is_selected("Zed")
        click_card(qtbot, window, "Zed")
        assert window.c.is_selected("Zed") and window.chip_selected.text() == "2 tướng đang chọn"
        click_card(qtbot, window, "Zed")
        assert not window.c.is_selected("Zed") and window.chip_selected.text() == "1 tướng đang chọn"

    def test_selecting_while_only_selected_active_refreshes_the_list(self, window, qtbot):
        window.only_sel_btn.setChecked(True)
        click_card(qtbot, window, "Vex")  # bỏ chọn → biến mất khỏi danh sách đang lọc
        assert self.names(window) == []

    def test_keyboard_space_toggles_current_card(self, window, qtbot):
        window.view.setFocus()
        window.view.setCurrentIndex(window.view.champion_model.index(0))
        first = window.view.champion_model.items()[0]["name"]
        before = window.c.is_selected(first)
        qtbot.keyClick(window.view, Qt.Key.Key_Space)
        assert window.c.is_selected(first) != before

    def test_select_all_and_deselect_all_buttons(self, window, qtbot):
        buttons = {b.text(): b for b in window.champ_panel.findChildren(type(window.mode_btn))}
        buttons["Chọn tất cả"].click()
        assert len(window.c.selected_names()) == 6 and window.chip_selected.text() == "6 tướng đang chọn"
        buttons["Bỏ chọn"].click()
        assert window.c.selected_names() == [] and window.chip_ready.property("tone") == "fail"

    def test_view_mode_toggle_switches_between_cards_and_text(self, window):
        assert window.view.mode == MODE_CARDS and window.mode_btn.text() == "Dạng chữ"
        window.mode_btn.click()
        assert window.view.mode == MODE_TEXT and window.mode_btn.text() == "Dạng thẻ ảnh"
        assert window.view.sizeHintForRow(0) == 34
        window.mode_btn.click()
        assert window.view.mode == MODE_CARDS

    def test_portrait_loaded_after_download_is_used(self, window, qtbot):
        champ = next(c for c in window.c.champions if c["name"] == "Vex")
        assert window.view.champion_model.portrait(champ) is None
        path = champions.template_path(champ["name"], champ["image_url"])
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), np.full((70, 70, 3), 120, np.uint8))
        window.c.notify("portrait_ready", name="Vex")
        assert window.view.champion_model.portrait(champ) is not None

    def test_replaced_portrait_file_is_reloaded_on_portrait_ready(self, window):
        champ = next(c for c in window.c.champions if c["name"] == "Vex")
        path = champions.template_path(champ["name"], champ["image_url"])
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), np.full((40, 40, 3), 100, np.uint8))
        assert window.view.champion_model.portrait(champ).width() == 40
        cv2.imwrite(str(path), np.full((90, 90, 3), 100, np.uint8))
        assert window.view.champion_model.portrait(champ).width() == 40  # còn cache
        window.c.notify("portrait_ready", name="Vex")
        assert window.view.champion_model.portrait(champ).width() == 90

    def test_accessible_text_announces_state(self, window):
        idx = window.view.champion_model.index([c["name"] for c in window.view.champion_model.items()].index("Vex"))
        assert "đã chọn" in idx.data(Qt.ItemDataRole.AccessibleTextRole)

    def test_failed_load_keeps_saved_selection_counted(self, make_window, monkeypatch):
        monkeypatch.setattr(ctl, "load_all_champions", fake_loader([], fail=ConnectionError("offline")))
        w = make_window(ready_config(selected_champions=["Vex", "Zed"]))
        QTest.qWait(300)
        assert w.chip_selected.text() == "2 tướng đang chọn" and "Lỗi tải tướng" in w.status_label.text()

    def test_upload_requires_exactly_one_selected(self, window, boxes, monkeypatch):
        window.c.set_selected("Zed", True)
        for b in window.champ_panel.findChildren(type(window.mode_btn)):
            if b.text() == "Upload ảnh":
                b.click()
        assert boxes.items[-1][1] == "Upload ảnh" and "đúng 1 tướng" in boxes.items[-1][2]

    def test_upload_saves_image(self, window, boxes, monkeypatch, tmp_path, data_dir):
        src = tmp_path / "v.jpg"
        cv2.imwrite(str(src), np.full((90, 120, 3), 200, np.uint8))
        monkeypatch.setattr(mw.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(src), "")))
        window._upload()
        assert window.c.config["custom_templates"]["Vex"].endswith("custom_Vex.png")
        assert boxes.items[-1][2] == "Đã lưu ảnh tướng Vex"

    def test_upload_unreadable_image_reports_error(self, window, boxes, monkeypatch, tmp_path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"khong phai anh")
        monkeypatch.setattr(mw.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad), "")))
        window._upload()
        assert boxes.items[-1][0] == "critical" and "Không dùng được file này" in boxes.items[-1][2]


class TestRollKeyField:
    def test_field_shows_saved_key_and_saves_on_edit(self, make_window, data_dir):
        w = make_window(ready_config(roll_key="e"))
        assert w.roll_edit.text() == "e"
        w.roll_edit.setText("r")
        w.roll_edit.editingFinished.emit()
        assert w.c.roll_key == "r"
        assert json.loads((data_dir / "config.json").read_text(encoding="utf-8"))["roll_key"] == "r"

    def test_clearing_the_field_disables_the_feature(self, window):
        window.roll_edit.setText("")
        window.roll_edit.editingFinished.emit()
        assert window.c.roll_key == "" and "Đã tắt đồng bộ phím roll." in window.log_view.toPlainText()


# --------------------------------------------------------------------------- preview và nhật ký
class TestPreviewAndLog:
    def test_preview_image_and_note_are_shown_with_tone(self, window):
        img = Image.new("RGB", (600, 90), (30, 90, 160))
        window.c.notify("preview", image=img, note="Chụp lúc 12:00:00.", tone="warn")
        assert window.preview.pixmap() is not None and not window.preview.pixmap().isNull()
        assert window.preview_note.text() == "Chụp lúc 12:00:00."
        assert theme.LIGHT.warn in window.preview_note.styleSheet()

    def test_failed_preview_keeps_previous_picture(self, window):
        window.c.notify("preview", image=Image.new("RGB", (300, 60)), note="", tone="muted")
        window.c.notify("preview", image=None, note="Chụp lỗi", tone="fail")
        assert window.preview.pixmap() is not None and window.preview_note.text() == "Chụp lỗi"

    def test_refresh_button_disabled_while_capturing(self, window):
        window.c.notify("preview_busy", busy=True)
        assert not window.refresh_btn.isEnabled()
        window.c.notify("preview_busy", busy=False)
        assert window.refresh_btn.isEnabled()

    def test_refresh_without_region_guides_to_region_step(self, make_window, boxes):
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, size=(460, 780))
        w.refresh_btn.click()
        assert boxes.items[-1][2] == "Chọn vùng Shop trước." and w.tabbar.currentIndex() == mw.PAGE_SHOP

    def test_journal_is_bounded(self, window):
        for i in range(mw.MAX_LOG_LINES + 200):
            window.c.log(f"dòng {i}")
        assert window.log_view.document().blockCount() <= mw.MAX_LOG_LINES + 1
        assert "dòng 699" in window.log_view.toPlainText() and "dòng 0\n" not in window.log_view.toPlainText()

    def test_dialog_events_use_the_right_message_box(self, window, boxes):
        for level, kind in (("info", "information"), ("warning", "warning"), ("error", "critical")):
            window.c.notify("dialog", level=level, title="T", text=level)
            assert boxes.items[-1][0] == kind


# --------------------------------------------------------------------------- bố cục thích ứng, chủ đề, tràn ngang
class TestAdaptiveLayout:
    def test_wide_uses_splitter_and_narrow_uses_tabs(self, make_window):
        w = make_window(ready_config(), size=(1100, 800))
        assert not w._compact and w.body.currentWidget() is w.splitter
        assert w.champ_panel.parent() is w.splitter
        w.resize(460, 780)
        QApplication.processEvents()
        assert w._compact and w.body.currentWidget() is w.compact_page
        assert w.stack.indexOf(w.stack.widget(0)) == 0 and w.champ_panel.isAncestorOf(w.view)
        assert w.tabbar.count() == 3 and w.tabbar.tabText(0) == "1 · Tướng"

    def test_hysteresis_prevents_flicker_near_the_threshold(self, make_window):
        w = make_window(ready_config(), size=(1100, 800))
        assert not w._compact
        for width, expect in ((mw.COMPACT_BELOW - 10, False), (mw.COMPACT_BELOW - mw.HYSTERESIS - 10, True),
                              (mw.COMPACT_BELOW + 10, True), (mw.COMPACT_BELOW + mw.HYSTERESIS + 10, False)):
            w.resize(width, 800)
            QApplication.processEvents()
            assert w._compact is expect, width

    def test_state_survives_layout_switch(self, make_window, qtbot):
        w = make_window(ready_config())
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        w.search.setText("ze")
        w.c.set_selected("Zed", True)
        w.resize(460, 780)
        QApplication.processEvents()
        w.resize(1200, 800)
        QApplication.processEvents()
        assert w.search.text() == "ze" and w.c.is_selected("Zed") and not w._compact
        assert w.ready_card.parent() is not None and w.shop_card.isAncestorOf(w.region_btn)

    @pytest.mark.parametrize("width", [420, 460, 600, 800])
    def test_compact_pages_never_scroll_horizontally(self, make_window, qtbot, width):
        w = make_window(ready_config(), size=(width, 800))
        for page in range(3):
            w.tabbar.setCurrentIndex(page)
            QApplication.processEvents()
            scroll = w.stack.widget(page)
            assert isinstance(scroll, QScrollArea)
            assert not scroll.horizontalScrollBar().isVisible(), f"tab {page} tràn ngang ở {width}px"
            assert scroll.widget().width() <= scroll.viewport().width() + 1

    def test_top_chips_wrap_instead_of_overflowing(self, make_window):
        w = make_window(ready_config(), size=(420, 800))
        for chip in (w.chip_ready, w.chip_selected, w.chip_ocr, w.chip_speed):
            assert chip.geometry().right() <= w.centralWidget().width()

    def test_start_button_always_visible_at_top(self, make_window):
        for size in ((1100, 700), (420, 600)):
            w = make_window(ready_config(), size=size)
            top = w.start_btn.mapTo(w, QPoint(0, 0))
            assert 0 <= top.y() < 80 and w.start_btn.isVisible()

    def test_log_bar_is_always_visible_but_closed(self, make_window):
        for size in ((1100, 700), (420, 600)):
            w = make_window(ready_config(), size=size)
            assert w.log_toggle.isVisible() and not w.log_view.isVisible()


class TestTheme:
    def test_dark_and_light_stylesheets_differ_and_apply(self, make_window):
        w = make_window(ready_config(theme="dark"))
        assert w.palette_.name == "dark" and theme.DARK.bg in QApplication.instance().styleSheet()
        w.theme_box.setCurrentIndex(w.theme_box.findData("light"))
        assert w.palette_.name == "light" and theme.LIGHT.bg in QApplication.instance().styleSheet()
        assert w.c.config["theme"] == "light"

    def test_theme_choice_is_saved(self, make_window, data_dir):
        w = make_window(ready_config())
        w.theme_box.setCurrentIndex(w.theme_box.findData("dark"))
        assert json.loads((data_dir / "config.json").read_text(encoding="utf-8"))["theme"] == "dark"

    def test_invalid_theme_falls_back_to_auto(self, make_window):
        w = make_window(ready_config(theme="hồng"))
        assert w._mode_pref == "auto"

    def test_auto_follows_system_scheme(self, monkeypatch):
        monkeypatch.setattr(theme, "is_dark_system", lambda: True)
        assert theme.pick("auto") is theme.DARK
        monkeypatch.setattr(theme, "is_dark_system", lambda: False)
        assert theme.pick("auto") is theme.LIGHT and theme.pick("dark") is theme.DARK

    @pytest.mark.parametrize("p", [theme.LIGHT, theme.DARK], ids=lambda p: p.name)
    def test_text_and_status_colors_are_readable_on_surfaces(self, p):
        def lum(h):
            c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

        def ratio(a, b):
            la, lb = sorted((lum(a), lum(b)), reverse=True)
            return (la + 0.05) / (lb + 0.05)

        assert ratio(p.text, p.bg) >= 7 and ratio(p.text, p.surface) >= 7
        assert ratio(p.muted, p.surface) >= 4.5
        for tone in (p.ok, p.warn, p.fail):
            assert ratio(tone, p.surface) >= 4.5, (p.name, tone)
        assert ratio(p.accent_text, p.accent) >= 4.5

    @pytest.mark.parametrize("mode", ["light", "dark"])
    @pytest.mark.parametrize("size", [(1100, 800), (460, 780)], ids=["wide", "compact"])
    def test_renders_real_content(self, make_window, qtbot, mode, size, tmp_path):
        w = make_window(ready_config(theme=mode), size=size)
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        img = w.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
        assert img.width() >= size[0] - 2
        arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, : img.width() * 3]
        assert arr.std() > 20 and len(np.unique(arr)) > 10  # không phải ảnh trống/một màu
        out = tmp_path / f"{mode}_{size[0]}.png"
        assert w.grab().save(str(out)) and out.stat().st_size > 5000


class TestDialogsFollowTheme:
    """Hộp thoại (QMessageBox, hộp nhập Key) từng nền đen ở cả hai giao diện vì `QWidget { background: transparent }` áp cả cho
    cửa sổ cấp cao: chữ theo giao diện còn nền thì không, nên giao diện Sáng cho chữ tối trên nền đen (tương phản 1,2)."""

    @staticmethod
    def _lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def _ratio(self, a, b):
        la, lb = sorted((self._lum(a), self._lum(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)

    @staticmethod
    def _background(dialog):
        """Màu (hex, alpha) tại một điểm trống sát góc của hộp thoại sau khi vẽ."""
        dialog.show()
        QApplication.processEvents()
        c = dialog.grab().toImage().pixelColor(3, 3)
        return c.name().lower(), c.alpha()

    def _boxes(self, parent=None):
        from ui import license_dialog as ld

        info = QMessageBox(QMessageBox.Icon.Information, "Upload ảnh", "Chọn đúng 1 tướng (tick) rồi upload ảnh chân dung.", parent=parent)
        warn = QMessageBox(QMessageBox.Icon.Warning, "Cấu hình", "Cấu hình đã được xử lý khi mở.", parent=parent)
        crit = QMessageBox(QMessageBox.Icon.Critical, "Lỗi", "Không chụp được màn hình.", parent=parent)
        lic = ld.LicenseDialog("AAAA-BBBB-CCCC-DDDD", lambda text: None, parent=parent)
        return {"thông tin": info, "cảnh báo": warn, "lỗi": crit, "nhập Key": lic}

    @pytest.mark.parametrize("p", [theme.LIGHT, theme.DARK], ids=lambda p: p.name)
    def test_dialog_background_is_opaque_and_uses_the_theme_color(self, qtbot, p):
        QApplication.instance().setStyleSheet(theme.stylesheet(p))
        for name, dialog in self._boxes().items():
            qtbot.addWidget(dialog)
            color, alpha = self._background(dialog)
            assert alpha == 255, f"{name}: nền trong suốt (hiện đen trên Windows)"
            assert color == p.bg.lower(), f"{name}: nền {color}, cần {p.bg}"
            assert self._ratio(p.text, color) >= 7, f"{name}: chữ khó đọc trên nền"

    @pytest.mark.parametrize("p", [theme.LIGHT, theme.DARK], ids=lambda p: p.name)
    def test_message_box_with_a_parent_window_gets_the_same_background(self, make_window, qtbot, p):
        """Ứng dụng luôn mở hộp thoại với cửa sổ chính làm cha: nền phải vẫn đúng (không thừa kế kiểu trong suốt)."""
        w = make_window(ready_config(theme=p.name))
        for name, dialog in self._boxes(parent=w).items():
            qtbot.addWidget(dialog)
            color, alpha = self._background(dialog)
            assert alpha == 255 and color == p.bg.lower(), (name, color, alpha)

    def test_switching_theme_updates_dialogs_opened_afterwards(self, make_window, qtbot):
        w = make_window(ready_config(theme="light"))
        w.theme_box.setCurrentIndex(w.theme_box.findData("dark"))
        box = QMessageBox(QMessageBox.Icon.Information, "x", "y", parent=w)
        qtbot.addWidget(box)
        assert self._background(box)[0] == theme.DARK.bg.lower()
        w.theme_box.setCurrentIndex(w.theme_box.findData("light"))
        box2 = QMessageBox(QMessageBox.Icon.Information, "x", "y", parent=w)
        qtbot.addWidget(box2)
        assert self._background(box2)[0] == theme.LIGHT.bg.lower()

    @pytest.mark.parametrize("p", [theme.LIGHT, theme.DARK], ids=lambda p: p.name)
    def test_dialog_rule_does_not_change_other_widgets(self, qtbot, p):
        """Chỉ hộp thoại đổi: widget thường vẫn trong suốt để thấy nền thẻ/khung phía sau."""
        QApplication.instance().setStyleSheet(theme.stylesheet(p))
        holder = QWidget()
        holder.setObjectName("root")
        qtbot.addWidget(holder)
        label = QLabel("x", holder)
        holder.resize(80, 40)
        holder.show()
        QApplication.processEvents()
        c = holder.grab().toImage().pixelColor(70, 30)  # chỗ không có label: nền của root, không phải của QLabel
        assert c.name().lower() == p.bg.lower() and label.isVisible()


# --------------------------------------------------------------------------- widget dùng chung
class TestWidgets:
    def test_flow_layout_wraps_and_grows_taller_when_narrow(self, qtbot):
        from PySide6.QtWidgets import QPushButton, QWidget

        host = QWidget()
        qtbot.addWidget(host)
        lay = FlowLayout(host)
        for i in range(6):
            lay.addWidget(QPushButton(f"nút số {i}"))
        wide, narrow = lay.heightForWidth(1000), lay.heightForWidth(180)
        assert narrow > wide and lay.count() == 6
        host.resize(180, narrow)
        host.show()
        QApplication.processEvents()
        assert all(lay.itemAt(i).geometry().right() <= 181 for i in range(6))

    def test_switch_toggles_with_click_and_space_and_emits_signal(self, qtbot):
        sw = Switch("Bật")
        qtbot.addWidget(sw)
        sw.show()
        seen = []
        sw.toggled.connect(seen.append)
        qtbot.mouseClick(sw, Qt.MouseButton.LeftButton, pos=QPoint(10, sw.height() // 2))
        assert sw.isChecked()
        sw.setFocus()
        qtbot.keyClick(sw, Qt.Key.Key_Space)
        assert not sw.isChecked() and seen == [True, False]
        assert not sw.grab().isNull() and sw.sizeHint().width() > Switch.W

    def test_elided_button_never_widens_and_keeps_full_text(self, qtbot):
        b = ElidedButton()
        qtbot.addWidget(b)
        b.setFullText("✗  " + "rất dài " * 30)
        b.resize(200, 30)
        b.show()
        QApplication.processEvents()
        assert b.text().endswith("…") and b.toolTip().startswith("✗") and b.minimumSizeHint().width() <= 40
        assert b.fontMetrics().horizontalAdvance(b.text()) <= 200


# --------------------------------------------------------------------------- luồng chọn vùng / điểm click / xem (overlay thay bằng giả)
class TestWindowCalibrationFlow:
    def make(self, make_window, qtbot, kind, config_extra=None):
        holder = {}

        def factory(which, plan=None):
            cur = Cursor()
            screens = one_screen()
            if which == "region":
                o = ov.RegionOverlay(screens, phys=cur)
            elif which == "clicks":
                o = ov.ClickOverlay(holder["w"].c.config["shop_region"], holder["w"].c.point_inside_region, screens, phys=cur)
            else:
                o = ov.ViewOverlay(plan["region"], plan["centers"], "", plan["confirm"], screens, phys=cur)
            o.cursor_ = cur
            holder["overlay"] = o
            holder["which"] = which
            holder["plan"] = plan
            for s in o.surfaces:
                qtbot.addWidget(s)
            return o

        base = ready_config(shop_region=None, slot_centers=[]) if kind == "region" else ready_config()
        base.update(config_extra or {})
        w = make_window(base, overlay_factory=factory)
        holder["w"] = w
        return w, holder

    def test_region_flow_minimises_then_saves_region_and_restores_window(self, make_window, qtbot, data_dir):
        w, holder = self.make(make_window, qtbot, "region")
        w.region_btn.click()
        assert w.isMinimized()
        qtbot.waitUntil(lambda: "overlay" in holder, timeout=2000)
        o = holder["overlay"]
        drag(qtbot, o, o.cursor_, o.surfaces[0], QPoint(100, 100), QPoint(600, 250))
        assert w.c.config["shop_region"] == {"left": 100, "top": 100, "width": 500, "height": 150}
        assert not w.isMinimized() and w._overlay is None
        assert json.loads((data_dir / "config.json").read_text(encoding="utf-8"))["shop_region"]["width"] == 500
        assert w.region_label.text().startswith("Shop: (100, 100) 500x150")
        assert w.region_btn.text().startswith("✓")

    def test_clicks_flow_saves_five_points(self, make_window, qtbot):
        w, holder = self.make(make_window, qtbot, "clicks")
        w.c.config["slot_centers"] = []
        w.c.changed()
        w.clicks_btn.click()
        qtbot.waitUntil(lambda: "overlay" in holder, timeout=2000)
        o = holder["overlay"]
        for i in range(5):
            o.cursor_.pos = (40 + i * 190, 150)
            qtbot.mouseClick(o.surfaces[0], Qt.MouseButton.LeftButton, pos=QPoint(40 + i * 190, 150))
        assert [tuple(p) for p in w.c.config["slot_centers"]] == [(40 + i * 190, 150) for i in range(5)]
        assert w.clicks_btn.text().startswith("✓") and not w.isMinimized()

    def test_cancel_restores_window_and_changes_nothing(self, make_window, qtbot):
        w, holder = self.make(make_window, qtbot, "region")
        w.region_btn.click()
        qtbot.waitUntil(lambda: "overlay" in holder, timeout=2000)
        holder["overlay"].cancelled.emit()
        assert not w.isMinimized() and w.c.config["shop_region"] is None

    def test_clicks_without_region_warns_and_goes_to_region(self, make_window, boxes):
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, size=(460, 780))
        w.clicks_btn.click()
        assert boxes.items[-1][2] == "Hãy chọn vùng Shop trước." and w.tabbar.currentIndex() == mw.PAGE_SHOP

    # --- xem trên màn hình thật
    def test_view_button_shows_the_saved_region_and_points_then_closes_on_click(self, make_window, qtbot):
        w, holder = self.make(make_window, qtbot, "view")
        w.view_btn.click()
        assert w.isMinimized()
        qtbot.waitUntil(lambda: "overlay" in holder, timeout=2000)
        o = holder["overlay"]
        assert holder["which"] == "view" and holder["plan"]["confirm"] is False
        assert holder["plan"]["region"] == w.c.config["shop_region"] and len(holder["plan"]["centers"]) == 5
        qtbot.mouseClick(o.surfaces[0], Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        assert not w.isMinimized() and w._overlay is None
        assert w.c.config["shop_region"] == ready_config()["shop_region"]  # chỉ xem: không đổi gì

    def test_view_without_region_explains_and_goes_to_region_step(self, make_window, qtbot, boxes):
        w, holder = self.make(make_window, qtbot, "region")
        w.view_btn.click()
        assert "overlay" not in holder and not w.isMinimized()
        assert boxes.items[-1][1] == "Xem trên màn hình" and "chọn vùng Shop" in boxes.items[-1][2]

    def test_view_with_region_but_no_points_still_opens(self, make_window, qtbot):
        w, holder = self.make(make_window, qtbot, "view", {"slot_centers": []})
        w.view_btn.click()
        qtbot.waitUntil(lambda: "overlay" in holder, timeout=2000)
        assert holder["plan"]["centers"] == []
        for s in holder["overlay"].surfaces:
            assert not s.grab().isNull()
        holder["overlay"].cancelled.emit()


class TestMonitorUi:
    """Thẻ 'Vùng Shop và điểm click': màn hình đang dùng, nút Xem trên màn hình, và luồng gợi ý quy đổi cần xác nhận."""

    M1 = Monitor(r"\\.\DISPLAY1", 0, 0, 1920, 1080, 100, True)
    M2 = Monitor(r"\\.\DISPLAY2", 1920, 0, 2560, 1440, 150)

    @pytest.fixture
    def two_monitors(self, monkeypatch):
        state = {"game": None}
        monkeypatch.setattr(monitors_mod, "list_monitors", lambda: [self.M1, self.M2])
        monkeypatch.setattr(monitors_mod, "game_monitor", lambda names, mons: state["game"])
        return state

    def window_with_overlay_log(self, make_window, qtbot, **extra):
        holder = {}

        def factory(which, plan=None):
            assert which == "view"
            o = ov.ViewOverlay(plan["region"], plan["centers"], "", plan["confirm"], one_screen(), phys=Cursor())
            for s in o.surfaces:
                qtbot.addWidget(s)
            holder["overlay"], holder["plan"] = o, plan
            return o

        w = make_window(ready_config(**extra), overlay_factory=factory)
        return w, holder

    def test_label_names_the_monitor_in_use_after_startup(self, make_window, qtbot, two_monitors):
        w = make_window(ready_config())
        qtbot.waitUntil(lambda: "Màn hình 1" in w.monitor_label.text(), timeout=3000)
        assert "1920×1080" in w.monitor_label.text() and w.view_btn.text() == "👁  Xem"

    def test_game_on_another_monitor_without_a_profile_shows_a_warning_and_asks_to_confirm(self, make_window, qtbot, two_monitors):
        w = make_window(ready_config())
        qtbot.waitUntil(lambda: "Màn hình 1" in w.monitor_label.text(), timeout=3000)
        two_monitors["game"] = self.M2
        w.c.refresh_monitor()
        text = w.monitor_label.text()
        assert "Màn hình 2" in text and "xác nhận" in text and "Gợi ý quy đổi" in text
        assert theme.LIGHT.warn in w.monitor_label.styleSheet()
        assert w.view_btn.text() == "👁  Xác nhận"
        assert w.region_btn.text().startswith("①") and w.clicks_btn.text().startswith("②")  # chưa tính là đã làm xong
        assert w.chip_ready.text().startswith("✗") and "xác nhận" in w.chip_ready.text()

    def test_confirming_the_suggestion_with_enter_uses_it(self, make_window, qtbot, two_monitors):
        w, holder = self.window_with_overlay_log(make_window, qtbot)
        qtbot.waitUntil(lambda: "Màn hình 1" in w.monitor_label.text(), timeout=3000)
        two_monitors["game"] = self.M2
        w.view_btn.click()
        qtbot.waitUntil(lambda: "overlay" in holder, timeout=2000)
        assert holder["plan"]["confirm"] is True and holder["plan"]["monitor"] == self.M2
        suggestion = w.c.monitor_status.suggestion["shop_region"]
        qtbot.keyClick(holder["overlay"].surfaces[0], Qt.Key.Key_Return)
        assert w.c.config["shop_region"] == suggestion and not w.c.monitor_pending
        assert not w.isMinimized() and w._overlay is None
        assert w.view_btn.text() == "👁  Xem" and w.region_btn.text().startswith("✓")
        assert theme.LIGHT.warn not in w.monitor_label.styleSheet()

    def test_declining_the_suggestion_changes_nothing(self, make_window, qtbot, two_monitors):
        w, holder = self.window_with_overlay_log(make_window, qtbot)
        qtbot.waitUntil(lambda: "Màn hình 1" in w.monitor_label.text(), timeout=3000)
        before = dict(w.c.config["shop_region"])
        two_monitors["game"] = self.M2
        w.view_btn.click()
        qtbot.waitUntil(lambda: "overlay" in holder, timeout=2000)
        qtbot.mouseClick(holder["overlay"].surfaces[0], Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        assert w.c.monitor_pending and w.c.config["shop_region"] == before and not w.isMinimized()

    def test_start_is_blocked_while_the_suggestion_is_unconfirmed(self, make_window, qtbot, two_monitors):
        w = make_window(ready_config())
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        two_monitors["game"] = self.M2
        w.start_btn.click()
        assert not FakeScanner.instances
        assert "xác nhận" in w.status_label.text() and w.c.monitor_pending

    def test_compact_layout_fits_with_the_long_monitor_text(self, make_window, qtbot, two_monitors):
        w = make_window(ready_config(), size=(460, 780))
        qtbot.waitUntil(lambda: "Màn hình 1" in w.monitor_label.text(), timeout=3000)
        two_monitors["game"] = self.M2
        w.c.refresh_monitor()
        w.tabbar.setCurrentIndex(mw.PAGE_SHOP)
        QApplication.processEvents()
        assert w.monitor_label.wordWrap() and w.monitor_label.isVisible()
        assert w.monitor_label.height() >= w.monitor_label.heightForWidth(w.monitor_label.width())  # xuống dòng, không bị cắt
        for b in (w.view_btn, w.region_btn, w.clicks_btn):
            assert b.isVisible() and b.width() <= w.width()

    def test_view_button_exists_in_the_wide_layout_too(self, make_window, qtbot, two_monitors):
        w = make_window(ready_config(shop_region=None, slot_centers=[]), size=(1100, 820))
        assert w.view_btn.isVisible() and w.monitor_label.isVisible()

    def test_view_button_in_dark_theme_keeps_the_warning_readable(self, make_window, qtbot, two_monitors):
        w = make_window(ready_config(theme="dark"))
        qtbot.waitUntil(lambda: "Màn hình 1" in w.monitor_label.text(), timeout=3000)
        two_monitors["game"] = self.M2
        w.c.refresh_monitor()
        assert theme.DARK.warn in w.monitor_label.styleSheet()


# --------------------------------------------------------------------------- chip chọn mùa và nhãn mùa trên thẻ
MULTI_SEASONS = [
    champ("Vex", 18, tier=1), champ("Zed", 18, tier=2), champ("Zed", 16, tier=3), champ("Zed", 14, tier=3),
    champ("Sivir", 17, tier=1), champ("Garen", 7, tier=1), champ("Kha'Zix", 15, tier=3, alt="Khazix"),
    {**champ("Darius", 18, tier=2), "id": "Maps/Shipping/Map22/Sets/TFTSetTutorial/Shop/TFTTutorial_Darius", "set": None},
]


class TestSeasonChips:
    @pytest.fixture
    def w(self, make_window, qtbot, monkeypatch):
        monkeypatch.setattr(ctl, "load_all_champions", fake_loader(MULTI_SEASONS))
        w = make_window(ready_config())
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        return w

    @staticmethod
    def names(w):
        return sorted(c["name"] for c in w.view.champion_model.items())

    def test_old_season_button_is_gone_and_all_chip_is_on_by_default(self, w):
        assert not hasattr(w, "old_btn")
        assert w.season_all.text() == "Tất cả" and w.season_all.isChecked()
        assert list(w.season_buttons) == [18, 17, 16, 15, 14, 7]  # lấy tự động từ dữ liệu, mới nhất trước
        assert [b.text() for b in w.season_buttons.values()] == ["M18", "M17", "M16", "M15", "M14", "M7"]
        assert not any(b.isChecked() for b in w.season_buttons.values())

    def test_default_list_shows_every_champion(self, w):
        assert self.names(w) == ["Darius", "Garen", "Kha'Zix", "Sivir", "Vex", "Zed"] and w.count_label.text() == "6/6 tướng"

    def test_clicking_a_season_chip_filters_and_unchecks_all(self, w):
        w.season_buttons[7].click()
        assert self.names(w) == ["Garen"] and w.season_buttons[7].isChecked() and not w.season_all.isChecked()
        assert w.count_label.text() == "1/6 tướng"

    def test_several_season_chips_combine(self, w):
        w.season_buttons[7].click()
        w.season_buttons[17].click()
        assert self.names(w) == ["Garen", "Sivir"]

    def test_unchecking_the_last_season_chip_returns_to_all(self, w):
        w.season_buttons[7].click()
        w.season_buttons[7].click()
        assert w.season_all.isChecked() and len(self.names(w)) == 6

    def test_all_chip_clears_every_season_chip(self, w):
        w.season_buttons[7].click()
        w.season_buttons[17].click()
        w.season_all.click()
        assert w.season_all.isChecked() and not any(b.isChecked() for b in w.season_buttons.values()) and len(self.names(w)) == 6

    def test_clicking_the_checked_all_chip_keeps_it_checked(self, w):
        w.season_all.click()
        assert w.season_all.isChecked()

    def test_search_shows_every_season_whatever_the_chips(self, w):
        w.season_buttons[7].click()
        w.search.setText("zed")
        assert self.names(w) == ["Zed"] and w.count_label.text() == "1 kết quả (tìm trong mọi mùa)"
        w.search.clear()
        assert self.names(w) == ["Garen"]  # bộ lọc mùa áp dụng lại

    def test_search_ignores_accents_and_apostrophes(self, w):
        w.search.setText("khazix")
        assert self.names(w) == ["Kha'Zix"]
        w.search.setText("KHA ZIX")
        assert self.names(w) == ["Kha'Zix"]

    def test_chip_tooltip_explains_why_it_is_ignored_while_searching(self, w):
        w.search.setText("zed")
        assert "tìm kiếm" in w.season_buttons[7].toolTip()
        w.search.clear()
        assert "mùa 7" in w.season_buttons[7].toolTip()

    def test_chips_rebuild_when_a_new_season_appears(self, w):
        before = list(w.season_buttons)
        w.c.populate_champions(MULTI_SEASONS + [champ("Newbie", 19, tier=1)])
        assert list(w.season_buttons) == [19, *before] and w.season_buttons[19].text() == "M19"

    def test_chips_are_kept_when_the_season_list_does_not_change(self, w):
        chips = dict(w.season_buttons)
        w.c.populate_champions(MULTI_SEASONS)
        assert all(w.season_buttons[s] is b for s, b in chips.items())

    def test_saved_season_filter_is_applied_at_startup(self, make_window, qtbot, monkeypatch):
        monkeypatch.setattr(ctl, "load_all_champions", fake_loader(MULTI_SEASONS))
        w = make_window(ready_config(season_filter=[7]))
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        assert self.names(w) == ["Garen"] and w.season_buttons[7].isChecked() and not w.season_all.isChecked()

    def test_chips_wrap_in_the_narrow_layout_without_horizontal_overflow(self, make_window, qtbot, monkeypatch):
        many = [champ(f"C{s}", s, tier=1) for s in range(4, 19)]
        monkeypatch.setattr(ctl, "load_all_champions", fake_loader(many))
        w = make_window(ready_config(), size=(460, 780))
        qtbot.waitUntil(lambda: len(w.season_buttons) == 15, timeout=3000)
        QApplication.processEvents()
        assert all(b.isVisible() and b.x() + b.width() <= w.width() for b in w.season_buttons.values())

    def test_card_tooltip_and_accessible_text_list_the_seasons(self, w):
        idx = w.view.champion_model.index([c["name"] for c in w.view.champion_model.items()].index("Zed"))
        assert "mùa 18, 16, 14" in idx.data(Qt.ItemDataRole.ToolTipRole)
        assert "mùa 18, 16, 14" in idx.data(Qt.ItemDataRole.AccessibleTextRole)
        darius = w.view.champion_model.index([c["name"] for c in w.view.champion_model.items()].index("Darius"))
        assert "tutorial/sự kiện" in darius.data(Qt.ItemDataRole.ToolTipRole)

    @pytest.mark.parametrize("mode", [MODE_CARDS, MODE_TEXT])
    def test_cards_paint_with_season_labels_in_both_views(self, w, mode):
        w.view.set_mode(mode)
        w.resize(1100, 820)
        QApplication.processEvents()
        assert not w.view.viewport().grab().isNull()

    def test_text_mode_rows_fit_the_viewport_without_a_horizontal_scrollbar(self, make_window, qtbot, monkeypatch):
        """Nhiều tướng nên có thanh cuộn dọc: hàng chữ phải rộng đúng viewport (cột cost không bị thanh cuộn che, không có thanh cuộn ngang)."""
        many = [champ(f"T{i}", 18 - i % 12, tier=1 + i % 5) for i in range(237)]
        monkeypatch.setattr(ctl, "load_all_champions", fake_loader(many))
        w = make_window(ready_config(), size=(1100, 900))
        qtbot.waitUntil(lambda: len(w.c.champions) == 237, timeout=3000)
        w.mode_btn.click()
        QApplication.processEvents()
        assert w.view.verticalScrollBar().isVisible() and not w.view.horizontalScrollBar().isVisible()
        assert w.view.itemDelegate().sizeHint(None, w.view.champion_model.index(0)).width() <= w.view.viewport().width()

    def test_season_label_is_drawn_on_the_card(self, w, tmp_path):
        """Nhãn mùa được vẽ thật: thẻ Zed (3 mùa) khác thẻ không nhãn khi vẽ (kiểm tra bằng ảnh chụp danh sách)."""
        w.resize(1100, 820)
        QApplication.processEvents()
        out = tmp_path / "list.png"
        assert w.view.viewport().grab().save(str(out)) and out.stat().st_size > 3000


class TestClose:
    def test_close_event_stops_controller(self, make_window):
        w = make_window(ready_config())
        w.close()
        assert w.c.closing

    def test_events_with_unknown_names_are_ignored(self, window):
        window.on_event("sự-kiện-lạ", x=1)


class TestAppEntry:
    def test_app_entry_builds_controller_with_keyboard_module(self):
        import ui.app as app

        assert callable(app.make_controller) and callable(app.run_app)

    def test_main_module_only_dispatches(self):
        import ast
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
        assert "tk" not in names and "Tk" not in src.replace("TFT", "")


# ----------------------------------------------------------------------------- mục Giấy phép trong Nâng cao
class TestLicenseSection:
    @pytest.fixture
    def patch_license(self, monkeypatch):
        from core import license as lic

        state = {"status": lic.Status(True, info=lic.KeyInfo(b"\0" * 16, 1, 2, "4ca1b490fca75c29"), activated_at=1_800_000_000)}
        monkeypatch.setattr(ctl.license_check, "check_installed", lambda *a: state["status"])
        return state

    def open_advanced(self, w):
        if w._compact:
            w.tabbar.setCurrentIndex(mw.PAGE_RUN)
        w.adv_toggle.setChecked(True)
        QApplication.processEvents()

    def test_shows_state_key_id_and_activation_time(self, make_window, patch_license):
        from datetime import datetime

        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, autoload=False)
        self.open_advanced(w)
        text = w.license_state.text()
        assert text.startswith("✓ Đã kích hoạt cho máy này") and "4ca1b490fca75c29" in text
        assert datetime.fromtimestamp(1_800_000_000).strftime("%Y-%m-%d %H:%M") in text
        assert theme.LIGHT.ok in w.license_state.styleSheet()
        assert "Key" in text and len(text) < 200  # chỉ key_id, không phải chuỗi Key

    def test_invalid_license_is_shown_in_fail_color(self, make_window, patch_license):
        from core import license as lic

        patch_license["status"] = lic.Status(False, "Giấy phép không dùng được trên máy này")
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, autoload=False)
        self.open_advanced(w)
        assert w.license_state.text().startswith("✗ Giấy phép không hợp lệ: Giấy phép không dùng được")
        assert theme.LIGHT.fail in w.license_state.styleSheet()

    def test_refreshes_every_time_advanced_is_opened(self, make_window, patch_license):
        from core import license as lic

        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, autoload=False)
        self.open_advanced(w)
        assert "✓" in w.license_state.text()
        w.adv_toggle.setChecked(False)
        patch_license["status"] = lic.Status(False, "Giấy phép đã bị xóa")
        w.adv_toggle.setChecked(True)
        assert "Giấy phép đã bị xóa" in w.license_state.text()

    def test_follows_theme_color_when_theme_changes(self, make_window, patch_license):
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, autoload=False)
        self.open_advanced(w)
        w.theme_box.setCurrentIndex(w.theme_box.findData("dark"))
        assert theme.DARK.ok in w.license_state.styleSheet()

    def test_machine_code_and_copy_button_are_not_shown_in_advanced(self, make_window, patch_license, monkeypatch):
        """Mã máy chỉ hiện ở hộp thoại nhập Key lần đầu; mục Nâng cao không có ô mã và nút Sao chép."""
        from PySide6.QtWidgets import QLabel, QLineEdit, QToolButton

        code = "5ZEN-JAHY-CSCA-HQ3D-ZV7E-KW6U-TPIM-2OHY"
        monkeypatch.setattr(ctl.license_check, "machine_code", lambda: code)
        for size in ((1100, 820), (460, 780)):
            w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, size=size, autoload=False)
            self.open_advanced(w)
            assert not hasattr(w, "machine_edit") and not hasattr(w, "machine_copy")
            texts = [x.text() for x in w.adv_body.findChildren(QLabel)] + [x.text() for x in w.adv_body.findChildren(QToolButton)]
            texts += [x.text() for x in w.adv_body.findChildren(QLineEdit)]
            assert not [t for t in texts if "Sao chép" in t or "Mã máy" in t or code in t], texts

    def test_license_line_is_fully_visible_in_compact_layout(self, make_window, patch_license):
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, size=(460, 780), autoload=False)
        self.open_advanced(w)
        assert w._compact and w.license_state.isVisible() and w.license_state.wordWrap()
        assert w.license_state.height() >= w.license_state.heightForWidth(w.license_state.width())  # xuống dòng, không bị cắt
