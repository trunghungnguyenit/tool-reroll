"""Giao diện Qt trên nền offscreen (pytest-qt): thao tác thật bằng chuột/bàn phím lên widget, kiểm tra phản hồi tức thì,
bố cục thích ứng, tràn ngang, chủ đề sáng/tối và chụp ảnh giao diện để soát bằng mắt. Scanner, mạng, hộp thoại và overlay
được thay bằng bản giả; không có thao tác nào chạm vào chuột/màn hình thật."""

import json
import types

import cv2
import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea, QWidget

import core.champions as champions
import core.config as config
import core.controller as ctl
from core.preview import PreviewResult
from tests.fakes import BAD_OCR, ENTRIES, OK_OCR, FakeScanner
from ui import main_window as mw
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
    monkeypatch.setattr(ctl, "fetch_champion_list", lambda locale=None: ENTRIES)
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
        assert window.status_label.text().startswith("Đã tải 5 tướng")
        assert window.count_label.text() == "5/5 tướng"


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

    def test_shows_latest_set_only_by_default(self, window):
        assert sorted(self.names(window)) == ["Ahri", "Graves", "Jinx", "Vex", "Zed"]

    def test_search_filters_instantly_without_creating_widgets(self, window, qtbot):
        qtbot.keyClick(window.search, "g")  # lần gõ đầu Qt tạo nút xóa nội bộ của ô tìm kiếm
        before = len(window.findChildren(QWidget))
        for ch in "ra":
            qtbot.keyClick(window.search, ch)
        assert self.names(window) == ["Graves"] and window.count_label.text() == "1/5 tướng"
        after = len(window.findChildren(QWidget))
        assert after == before  # gõ tìm kiếm không dựng/hủy widget nào (khác bản Tk dựng lại cả lưới)

    def test_search_works_on_other_language_name_and_clears(self, window, qtbot):
        window.search.setText("  ZED ")
        assert self.names(window) == ["Zed"]
        window.search.clear()
        assert len(self.names(window)) == 5

    def test_empty_search_result_is_empty_list(self, window):
        window.search.setText("không có tướng này")
        assert self.names(window) == [] and window.count_label.text() == "0/5 tướng"

    def test_cost_chips_filter_and_unavailable_cost_is_disabled(self, window):
        assert not window.cost_buttons[3].isEnabled() and window.cost_buttons[1].isEnabled()
        window.cost_buttons[1].setChecked(True)
        assert sorted(self.names(window)) == ["Graves", "Vex"]
        window.cost_buttons[5].setChecked(True)
        assert sorted(self.names(window)) == ["Graves", "Jinx", "Vex"]

    def test_only_selected_filter(self, window):
        window.only_sel_btn.setChecked(True)
        assert self.names(window) == ["Vex"]
        click_card_names = window.view.champion_model.items()
        assert len(click_card_names) == 1

    def test_show_old_adds_the_old_season_card(self, window):
        window.old_btn.setChecked(True)
        assert "Sivir" in self.names(window)

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
        assert len(window.c.selected_names()) == 5 and window.chip_selected.text() == "5 tướng đang chọn"
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
        def boom(locale=None):
            raise ConnectionError("offline")

        monkeypatch.setattr(ctl, "fetch_champion_list", boom)
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

    def test_log_is_always_visible(self, make_window):
        for size in ((1100, 700), (420, 600)):
            w = make_window(ready_config(), size=size)
            assert w.log_view.isVisible() and w.log_view.height() >= 60


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


# --------------------------------------------------------------------------- overlay chọn vùng / điểm click
def fake_background(w=800, h=400):
    from PySide6.QtGui import QPixmap

    pix = QPixmap(w, h)
    pix.fill(Qt.GlobalColor.darkGray)
    return pix, QRect(0, 0, w, h)


class Cursor:
    """Con trỏ vật lý giả: bằng tọa độ logic nhân hệ số (mô phỏng scale 150%)."""

    def __init__(self, scale=1.5):
        self.scale = scale
        self.pos = (0, 0)

    def __call__(self):
        return self.pos


def drag(qtbot, overlay, cursor, a, b):
    cursor.pos = (int(a.x() * cursor.scale), int(a.y() * cursor.scale))
    qtbot.mousePress(overlay, Qt.MouseButton.LeftButton, pos=a)
    mid = QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2)
    cursor.pos = (int(mid.x() * cursor.scale), int(mid.y() * cursor.scale))
    QTest.mouseMove(overlay, mid)
    cursor.pos = (int(b.x() * cursor.scale), int(b.y() * cursor.scale))
    qtbot.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=b)


class TestRegionOverlay:
    def make(self, qtbot, cursor):
        bg, virtual = fake_background()
        o = ov.RegionOverlay(bg, virtual, phys=cursor)
        qtbot.addWidget(o)
        o.show()
        return o

    def test_drag_emits_physical_pixel_region(self, qtbot):
        cur = Cursor(1.5)
        o = self.make(qtbot, cur)
        got = []
        o.finished.connect(got.append)
        drag(qtbot, o, cur, QPoint(100, 120), QPoint(500, 200))
        assert got == [{"left": 150, "top": 180, "width": 600, "height": 120}]  # lưu theo pixel vật lý, không phải pixel Qt

    def test_drag_any_direction_normalises(self, qtbot):
        cur = Cursor(1.0)
        o = self.make(qtbot, cur)
        got = []
        o.finished.connect(got.append)
        drag(qtbot, o, cur, QPoint(500, 300), QPoint(100, 120))
        assert got == [{"left": 100, "top": 120, "width": 400, "height": 180}]

    def test_tiny_drag_is_rejected_and_overlay_stays_open(self, qtbot):
        cur = Cursor(1.0)
        o = self.make(qtbot, cur)
        got = []
        o.finished.connect(got.append)
        drag(qtbot, o, cur, QPoint(100, 100), QPoint(120, 110))
        assert got == [] and o.last_rejected and o.isVisible()
        o.grab()  # vẽ lại với gợi ý "quá nhỏ"
        drag(qtbot, o, cur, QPoint(100, 100), QPoint(400, 200))
        assert len(got) == 1

    def test_escape_cancels(self, qtbot):
        o = self.make(qtbot, Cursor())
        with qtbot.waitSignal(o.cancelled, timeout=1000):
            qtbot.keyClick(o, Qt.Key.Key_Escape)

    def test_right_click_is_ignored(self, qtbot):
        cur = Cursor(1.0)
        o = self.make(qtbot, cur)
        got = []
        o.finished.connect(got.append)
        qtbot.mousePress(o, Qt.MouseButton.RightButton, pos=QPoint(10, 10))
        qtbot.mouseRelease(o, Qt.MouseButton.RightButton, pos=QPoint(300, 300))
        assert got == []

    def test_paints_selection_magnifier_and_hint_without_error(self, qtbot):
        cur = Cursor(1.0)
        o = self.make(qtbot, cur)
        cur.pos = (100, 100)
        qtbot.mousePress(o, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        cur.pos = (400, 250)
        QTest.mouseMove(o, QPoint(400, 250))
        assert not o.grab().isNull()

    def test_falls_back_to_scaled_logical_position_when_cursor_api_fails(self, qtbot):
        o = self.make(qtbot, lambda: None)
        x, y = o._physical(QPoint(50, 60))
        assert isinstance(x, int) and isinstance(y, int)


class TestClickOverlay:
    def make(self, qtbot, cursor, region=None):
        bg, virtual = fake_background()
        region = region or {"left": 100, "top": 100, "width": 600, "height": 150}
        o = ov.ClickOverlay(region, lambda x, y: 100 <= x <= 700 and 100 <= y <= 250, bg, virtual, phys=cursor)
        qtbot.addWidget(o)
        o.show()
        return o

    def click(self, qtbot, o, cur, x, y):
        cur.pos = (x, y)
        qtbot.mouseClick(o, Qt.MouseButton.LeftButton, pos=QPoint(x, y))

    def test_five_clicks_finish_with_physical_points(self, qtbot):
        cur = Cursor()
        o = self.make(qtbot, cur)
        got = []
        o.finished.connect(got.append)
        pts = [(150 + i * 110, 170) for i in range(5)]
        for x, y in pts:
            self.click(qtbot, o, cur, x, y)
        assert got == [pts]

    def test_outside_click_is_rejected_with_a_message(self, qtbot):
        cur = Cursor()
        o = self.make(qtbot, cur)
        self.click(qtbot, o, cur, 10, 10)
        assert o.points == [] and "NGOÀI vùng Shop" in o.warning and "ô 1/5" in o.warning
        self.click(qtbot, o, cur, 200, 150)
        assert len(o.points) == 1 and o.warning == ""

    def test_backspace_removes_last_point(self, qtbot):
        cur = Cursor()
        o = self.make(qtbot, cur)
        self.click(qtbot, o, cur, 150, 150)
        self.click(qtbot, o, cur, 250, 150)
        qtbot.keyClick(o, Qt.Key.Key_Backspace)
        assert o.points == [(150, 150)] and "ô 2/5" in o._hint()
        qtbot.keyClick(o, Qt.Key.Key_Backspace)
        qtbot.keyClick(o, Qt.Key.Key_Backspace)  # hết điểm: không lỗi
        assert o.points == []

    def test_escape_cancels_and_paint_with_points_works(self, qtbot):
        cur = Cursor()
        o = self.make(qtbot, cur)
        self.click(qtbot, o, cur, 150, 150)
        assert not o.grab().isNull()
        with qtbot.waitSignal(o.cancelled, timeout=1000):
            qtbot.keyClick(o, Qt.Key.Key_Escape)


class TestWindowCalibrationFlow:
    def make(self, make_window, qtbot, kind):
        holder = {}

        def factory(which):
            cur = Cursor(1.0)
            bg, virtual = fake_background()
            if which == "region":
                o = ov.RegionOverlay(bg, virtual, phys=cur)
            else:
                o = ov.ClickOverlay(holder["w"].c.config["shop_region"], holder["w"].c.point_inside_region, bg, virtual,
                                    phys=cur)
            o.cursor_ = cur
            holder["overlay"] = o
            return o

        w = make_window(ready_config(shop_region=None, slot_centers=[]) if kind == "region" else ready_config(),
                        overlay_factory=factory)
        holder["w"] = w
        return w, holder

    def test_region_flow_minimises_then_saves_region_and_restores_window(self, make_window, qtbot, data_dir):
        w, holder = self.make(make_window, qtbot, "region")
        w.region_btn.click()
        assert w.isMinimized()
        qtbot.waitUntil(lambda: "overlay" in holder, timeout=2000)
        o = holder["overlay"]
        drag(qtbot, o, o.cursor_, QPoint(100, 100), QPoint(600, 250))
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
            qtbot.mouseClick(o, Qt.MouseButton.LeftButton, pos=QPoint(40 + i * 190, 150))
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


# ----------------------------------------------------------------------------- xuất chẩn đoán và mục Giấy phép
class TestDiagnosticsButton:
    def test_button_lives_in_the_journal_header_and_is_visible_in_both_layouts(self, make_window):
        for size in ((1100, 820), (460, 780)):
            w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, size=size, autoload=False)
            assert w.diag_btn.isVisible() and w.diag_btn.text() == "Xuất chẩn đoán"
            assert w.log_wrap.isAncestorOf(w.diag_btn) and w.diag_btn.toolTip()

    def test_click_builds_report_then_reveals_it_and_unlocks(self, make_window, qtbot, monkeypatch, tmp_path):
        from pathlib import Path

        zip_path = tmp_path / "r.zip"
        monkeypatch.setattr(ctl.diagnostics, "write_report", lambda cfg, running=False, **kw: zip_path)
        revealed = []
        monkeypatch.setattr(mw.diagnostics, "reveal_in_explorer", lambda p: revealed.append(p))
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, autoload=False)
        w.diag_btn.click()
        assert not w.diag_btn.isEnabled() and w.diag_btn.text() == "Đang tạo..."  # phản hồi ngay, không treo giao diện
        qtbot.waitUntil(lambda: revealed == [Path(zip_path)], timeout=3000)
        assert w.diag_btn.isEnabled() and w.diag_btn.text() == "Xuất chẩn đoán"
        assert f"Đã lưu báo cáo chẩn đoán: {zip_path}" in w.log_view.toPlainText()

    def test_failure_shows_error_box_and_unlocks(self, make_window, qtbot, monkeypatch, boxes):
        def boom(cfg, running=False, **kw):
            raise OSError("đĩa đầy")

        monkeypatch.setattr(ctl.diagnostics, "write_report", boom)
        monkeypatch.setattr(mw.diagnostics, "reveal_in_explorer", lambda p: pytest.fail("không được mở thư mục khi lỗi"))
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, autoload=False)
        w.diag_btn.click()
        qtbot.waitUntil(lambda: bool(boxes.items), timeout=3000)
        kind, title, text = boxes.items[-1]
        assert kind == "critical" and title == "Báo cáo chẩn đoán" and "đĩa đầy" in text
        assert w.diag_btn.isEnabled()


class TestLicenseSection:
    @pytest.fixture
    def patch_license(self, monkeypatch):
        from core import license as lic

        state = {"status": lic.Status(True, info=lic.KeyInfo(b"\0" * 16, 1, 2, "4ca1b490fca75c29"), activated_at=1_800_000_000),
                 "code": "5ZEN-JAHY-CSCA-HQ3D-ZV7E-KW6U-TPIM-2OHY"}
        monkeypatch.setattr(ctl.license_check, "check_installed", lambda *a: state["status"])
        monkeypatch.setattr(ctl.license_check, "machine_code", lambda: state["code"])
        return state

    def open_advanced(self, w):
        if w._compact:
            w.tabbar.setCurrentIndex(mw.PAGE_RUN)
        w.adv_toggle.setChecked(True)
        QApplication.processEvents()

    def test_shows_state_key_id_activation_time_and_machine_code(self, make_window, patch_license):
        from datetime import datetime

        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, autoload=False)
        self.open_advanced(w)
        text = w.license_state.text()
        assert text.startswith("✓ Đã kích hoạt cho máy này") and "4ca1b490fca75c29" in text
        assert datetime.fromtimestamp(1_800_000_000).strftime("%Y-%m-%d %H:%M") in text
        assert w.machine_edit.text() == patch_license["code"] and w.machine_edit.isReadOnly()
        assert theme.LIGHT.ok in w.license_state.styleSheet()
        assert "Key" in text and len(text) < 200  # chỉ key_id, không phải chuỗi Key

    def test_copy_button_copies_the_machine_code(self, make_window, patch_license):
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, autoload=False)
        self.open_advanced(w)
        QApplication.clipboard().setText("")
        w.machine_copy.click()
        assert QApplication.clipboard().text() == patch_license["code"]

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
        patch_license["code"] = "MOI-MOI-MOI"
        w.adv_toggle.setChecked(True)
        assert "Giấy phép đã bị xóa" in w.license_state.text() and w.machine_edit.text() == "MOI-MOI-MOI"

    def test_follows_theme_color_when_theme_changes(self, make_window, patch_license):
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, autoload=False)
        self.open_advanced(w)
        w.theme_box.setCurrentIndex(w.theme_box.findData("dark"))
        assert theme.DARK.ok in w.license_state.styleSheet()

    def test_fits_in_compact_layout_without_clipping(self, make_window, patch_license):
        w = make_window({"coords_version": config.COORDS_VERSION, "theme": "light"}, size=(460, 780), autoload=False)
        self.open_advanced(w)
        assert w._compact and w.machine_edit.isVisible() and w.machine_copy.isVisible()
        assert w.machine_edit.width() >= 120
        assert w.machine_edit.fontMetrics().horizontalAdvance(w.machine_edit.text()) <= w.machine_edit.width() + 40
