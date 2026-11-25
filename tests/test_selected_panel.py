"""Khung 'Tướng đã chọn' (hiện đúng danh sách tool sẽ bắt) và các khung kéo được: bề rộng cột phải, chiều cao khung chọn / cài đặt,
chiều cao Nhật ký; cỡ cửa sổ theo màn hình và được nhớ giữa các lần mở."""

from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

import core.config as config
from tests.test_layout import big  # noqa: F401  (237 tướng giả)
from tests.test_ui import boxes, make_window, ready_config  # noqa: F401
from ui import main_window as mw
from ui import selected_panel as sp
from ui import theme
from ui.selected_panel import SelectedPanel


def settle(n=3):
    for _ in range(n):
        QApplication.processEvents()


# --------------------------------------------------------------------------- khung chip
class TestPanelWidget:
    def make(self, qtbot, portrait=None):
        p = SelectedPanel(portrait)
        qtbot.addWidget(p)
        p.resize(320, 200)
        p.show()
        return p

    def test_empty_state_explains_how_to_choose_and_cannot_clear(self, qtbot):
        p = self.make(qtbot)
        assert p.empty_label.isVisible() and not p.scroll.isVisible() and not p.clear_btn.isEnabled()
        assert "Bấm vào thẻ tướng" in p.empty_label.text() and p.chip_names() == []

    def test_chips_count_and_summary(self, qtbot):
        p = self.make(qtbot)
        p.set_data([("Akali", 3), ("Yorick", 1)], ["Teemo"])
        assert p.chip_names() == ["Akali", "Yorick", "Teemo"]
        assert p.count_label.text() == "2 tướng + 1 tên gõ tay"
        assert p.summary.fullText() == "Akali, Yorick, Teemo"
        assert p.scroll.isVisible() and not p.empty_label.isVisible() and p.clear_btn.isEnabled()

    def test_only_manual_names(self, qtbot):
        p = self.make(qtbot)
        p.set_data([], ["Teemo"])
        assert p.chip_names() == ["Teemo"] and p.count_label.text() == "1 tên gõ tay"

    def test_chip_color_follows_the_cost_and_manual_chips_are_marked(self, qtbot):
        p = self.make(qtbot)
        p.set_data([("Akali", 3)], ["Teemo"])
        chips = [p.flow.itemAt(i).widget() for i in range(p.flow.count())]
        assert chips[0].property("tier") == "3" and chips[0].property("manual") is False
        assert chips[1].property("manual") is True and "✎" in chips[1].findChildren(QLabel)[-1].text()

    def test_x_buttons_emit_the_right_signals(self, qtbot):
        p = self.make(qtbot)
        p.set_data([("Akali", 3)], ["Teemo"])
        got = []
        p.unselect.connect(lambda n: got.append(("sel", n)))
        p.unselect_manual.connect(lambda n: got.append(("man", n)))
        buttons = p.findChildren(QToolButton)
        assert len(buttons) == 2
        buttons[0].click()
        buttons[1].click()
        assert got == [("sel", "Akali"), ("man", "Teemo")]

    def test_clear_all_signal(self, qtbot):
        p = self.make(qtbot)
        p.set_data([("Akali", 3)], [])
        got = []
        p.clear_all.connect(lambda: got.append(1))
        p.clear_btn.click()
        assert got == [1]

    def test_many_champions_are_capped_with_a_note(self, qtbot):
        p = self.make(qtbot)
        p.set_data([(f"Tướng {i}", 1) for i in range(sp.MAX_CHIPS + 25)], [])
        assert len(p.chip_names()) == sp.MAX_CHIPS
        labels = [w.text() for w in p.body.findChildren(QLabel)]
        assert any("và 25 tướng nữa" in t for t in labels)
        assert p.count_label.text() == f"{sp.MAX_CHIPS + 25} tướng"

    def test_same_data_does_not_rebuild_the_chips(self, qtbot):
        p = self.make(qtbot)
        p.set_data([("Akali", 3)], [])
        first = p.flow.itemAt(0).widget()
        p.set_data([("Akali", 3)], [])
        assert p.flow.itemAt(0).widget() is first
        p.set_data([("Akali", 3), ("Yorick", 1)], [])
        assert p.flow.itemAt(0).widget() is not first

    def test_portrait_is_shown_when_available_and_skipped_otherwise(self, qtbot):
        from PySide6.QtGui import QColor, QPixmap

        pix = QPixmap(64, 64)
        pix.fill(QColor("red"))
        p = self.make(qtbot, portrait=lambda name: pix if name == "Akali" else None)
        p.set_data([("Akali", 3), ("Yorick", 1)], [])
        icons = [p.flow.itemAt(i).widget().findChildren(QLabel)[0] for i in range(2)]
        assert not icons[0].pixmap().isNull() and not icons[0].isHidden()
        assert icons[1].isHidden()

    def test_compact_collapses_to_one_line_and_expands_on_click(self, qtbot):
        p = self.make(qtbot)
        p.set_data([("Akali", 3), ("Yorick", 1)], [])
        p.set_compact(True)
        settle()
        assert p.toggle_btn.isVisible() and p.summary.isVisible() and not p.title.isVisible()
        assert not p.scroll.isVisible() and not p.clear_btn.isVisible() and p.layout().sizeHint().height() < 50
        p.toggle_btn.click()
        settle()
        assert p.scroll.isVisible() and p.clear_btn.isVisible() and not p.summary.isVisible()
        assert p.toggle_btn.text().startswith("▾")
        p.set_compact(False)
        settle()
        assert p.title.isVisible() and not p.toggle_btn.isVisible() and p.scroll.isVisible()

    def test_compact_empty_shows_the_hint_only_when_open(self, qtbot):
        p = self.make(qtbot)
        p.set_compact(True)
        settle()
        assert not p.empty_label.isVisible() and p.summary.fullText() == "chưa chọn tướng nào"
        p.toggle_btn.click()
        settle()
        assert p.empty_label.isVisible()


# --------------------------------------------------------------------------- nối với cửa sổ chính
class TestSelectedInTheWindow:
    def test_shows_what_the_tool_will_catch_and_follows_ticking(self, make_window, qtbot):
        w = make_window(ready_config(selected_champions=["Vex", "Zed"]), size=(1280, 720))
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        settle()
        assert w.selected_card.chip_names() == ["Vex", "Zed"]
        w.c.set_selected("Ahri", True)
        settle()
        assert w.selected_card.chip_names() == ["Vex", "Zed", "Ahri"]
        w.c.set_selected("Vex", False)
        settle()
        assert w.selected_card.chip_names() == ["Zed", "Ahri"] and w.selected_card.count_label.text() == "2 tướng"

    def test_x_unselects_in_the_controller_and_the_card_grid(self, make_window, qtbot):
        w = make_window(ready_config(selected_champions=["Vex", "Zed"]), size=(1280, 720))
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        settle()
        w.selected_card.findChildren(QToolButton)[0].click()
        settle()
        assert not w.c.is_selected("Vex") and w.c.is_selected("Zed")
        assert w.chip_selected.text() == "1 tướng đang chọn"

    def test_manual_names_are_listed_and_removable(self, make_window, qtbot):
        w = make_window(ready_config(selected_champions=["Vex"], manual_names="Teemo, Karma"), size=(1280, 720))
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        settle()
        assert w.selected_card.chip_names() == ["Vex", "Teemo", "Karma"]
        manual_x = w.selected_card.findChildren(QToolButton)[1]
        manual_x.click()
        settle()
        assert w.c.parsed_manual_names() == ["Karma"] and w.manual.toPlainText() == "Karma"
        assert w.selected_card.chip_names() == ["Vex", "Karma"]

    def test_manual_name_that_is_also_ticked_is_not_listed_twice(self, make_window, qtbot):
        w = make_window(ready_config(selected_champions=["Vex"], manual_names="Vex, Teemo"), size=(1280, 720))
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        settle()
        assert w.selected_card.chip_names() == ["Vex", "Teemo"]

    def test_typing_a_manual_name_updates_the_card(self, make_window, qtbot):
        w = make_window(ready_config(selected_champions=["Vex"]), size=(1280, 720))
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        w.manual.setPlainText("Garen")
        settle()
        assert "Garen" in w.selected_card.chip_names()

    def test_clear_all_unselects_everything_but_keeps_manual_names(self, make_window, qtbot):
        w = make_window(ready_config(selected_champions=["Vex", "Zed"], manual_names="Teemo"), size=(1280, 720))
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        settle()
        w.selected_card.clear_btn.click()
        settle()
        assert w.c.selected_names() == [] and w.selected_card.chip_names() == ["Teemo"]

    def test_select_all_is_capped_but_counted(self, big):
        w = big((1280, 720))
        w.c.select_all_visible()
        settle()
        assert w.selected_card.count_label.text() == f"{len(w.c.champions)} tướng"
        assert len(w.selected_card.chip_names()) == sp.MAX_CHIPS

    def test_wide_layout_puts_the_card_above_the_settings_in_the_right_column(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert not w._compact and w.selected_card.parent() is w.right_split
        assert w.right_split.widget(0) is w.selected_card and w.right_split.widget(1) is w.right_scroll
        assert w.right_split.parent() is w.splitter

    def test_narrow_layout_puts_a_slim_collapsed_line_above_the_grid(self, big):
        w = big((460, 780))
        assert w._compact and w.selected_card.parent() is w.compact_pages[mw.PAGE_CHAMPIONS]
        assert w.selected_card.height() < 50 and not w.selected_card.scroll.isVisible()
        assert w.view.height() >= 220  # lưới tướng vẫn được ưu tiên diện tích

    def test_switching_layouts_keeps_the_card_working(self, make_window, qtbot):
        w = make_window(ready_config(selected_champions=["Vex"]), size=(1280, 720))
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        w.resize(460, 780)
        settle()
        assert w._compact and w.selected_card.chip_names() == ["Vex"] and w.selected_card.toggle_btn.isVisible()
        w.resize(1280, 720)
        settle()
        assert not w._compact and w.selected_card.title.isVisible() and w.selected_card.parent() is w.right_split

    def test_portrait_downloaded_later_refreshes_the_chip(self, make_window, qtbot):
        w = make_window(ready_config(selected_champions=["Vex"]), size=(1280, 720))
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        settle()
        first = w.selected_card.flow.itemAt(0).widget()
        w._ev_portrait_ready("Vex")
        assert w.selected_card.flow.itemAt(0).widget() is not first  # dựng lại để lấy ảnh vừa tải
        w._ev_portrait_ready("Zed")  # tướng không chọn: không đụng tới
        assert w.selected_card.flow.itemAt(0).widget() is not None


# --------------------------------------------------------------------------- controller
class TestControllerSelection:
    def test_clear_selected_notifies_once_and_empties_everything(self, make_window, qtbot):
        w = make_window(ready_config(selected_champions=["Vex", "Zed"]), size=(1280, 720))
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        events = []
        original = w.c.notify
        w.c.notify = lambda ev, **kw: (events.append(ev), original(ev, **kw))[1]
        w.c.clear_selected()
        assert w.c.selected_names() == [] and events.count("selection_changed") == 1

    def test_offline_unselecting_updates_the_saved_selection(self, make_window):
        w = make_window(ready_config(selected_champions=["Vex", "Zed"]), size=(1280, 720), autoload=False)
        assert w.c.champions == [] and w.c.selected_names() == ["Vex", "Zed"]
        w.c.set_selected("Vex", False)
        assert w.c.selected_names() == ["Zed"]
        w.c.set_selected("Ahri", True)
        assert w.c.selected_names() == ["Zed", "Ahri"]
        w.c.clear_selected()
        assert w.c.selected_names() == []


# --------------------------------------------------------------------------- khung kéo được
class TestDraggableFrames:
    def test_handles_are_wide_enough_to_grab(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert w.splitter.handleWidth() == mw.HANDLE_W and w.right_split.handleWidth() == mw.HANDLE_W
        assert mw.HANDLE_W >= 6

    def test_stylesheet_draws_and_highlights_the_handles(self):
        for palette in (theme.LIGHT, theme.DARK):
            css = theme.stylesheet(palette)
            assert "QSplitter::handle:horizontal" in css and "QSplitter::handle:vertical" in css
            assert "QSplitter::handle:horizontal:hover" in css and palette.accent_line in css

    def test_right_column_width_is_draggable_within_its_range(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert mw.RIGHT_W == w.right_split.width() or abs(w.right_split.width() - mw.RIGHT_W) <= 2
        w.splitter.moveSplitter(w.width() - 480, 1)  # kéo thanh sang trái: cột phải rộng ra
        settle()
        assert abs(w.right_split.width() - 480) <= 12
        w.splitter.moveSplitter(10, 1)  # kéo quá xa sang trái: dừng ở mức tối đa
        settle()
        assert w.right_split.width() <= mw.RIGHT_MAX + 2
        w.splitter.moveSplitter(w.width() - 20, 1)  # kéo sang phải hết cỡ: dừng ở mức tối thiểu
        settle()
        assert w.right_split.width() >= mw.RIGHT_MIN - 2

    def test_dragging_right_keeps_the_champion_panel_usable(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        w.splitter.moveSplitter(w.width() - mw.RIGHT_MAX, 1)
        settle()
        assert w.champ_panel.width() >= 300 and not w.right_scroll.horizontalScrollBar().isVisible()

    def test_card_height_is_draggable_and_has_a_floor(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        before = w.selected_card.height()
        w.right_split.moveSplitter(before + 120, 1)
        settle()
        assert w.selected_card.height() >= before + 100
        w.right_split.moveSplitter(5, 1)
        settle()
        assert w.selected_card.height() >= mw.SELECTED_MIN_H - 2

    def test_log_has_no_handle_when_closed_and_a_draggable_one_when_open(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert w.v_split.handleWidth() == 0 and w.log_wrap.height() <= 40
        w.log_toggle.setChecked(True)
        settle()
        assert w.v_split.handleWidth() == mw.HANDLE_W and w.log_view.height() == mw.LOG_OPEN_H
        w.log_toggle.setChecked(False)
        settle()
        assert w.v_split.handleWidth() == 0 and w.log_wrap.height() <= 40

    def test_log_height_can_be_dragged_and_is_remembered_for_the_session(self, make_window, qtbot):
        w = make_window(ready_config(), size=(1280, 760))
        w.log_toggle.setChecked(True)
        settle()
        top = w.v_split.sizes()[0]
        w.v_split.moveSplitter(top - 140, 1)  # kéo thanh lên: Nhật ký cao thêm ~140 px
        settle(5)
        tall = w.log_view.height()
        assert tall >= mw.LOG_OPEN_H + 100 and w._log_user_h == tall
        w.log_toggle.setChecked(False)
        w.log_toggle.setChecked(True)
        settle()
        assert abs(w.log_view.height() - tall) <= 2  # mở lại giữ chiều cao đã kéo
        w.resize(460, 780)  # đổi sang bố cục hẹp: không bị đặt lại về mặc định
        settle(5)
        assert w.log_view.height() >= mw.LOG_OPEN_H_COMPACT + 80

    def test_log_cannot_be_dragged_smaller_than_the_floor(self, make_window):
        w = make_window(ready_config(), size=(1280, 760))
        w.log_toggle.setChecked(True)
        settle()
        w.v_split.moveSplitter(w.v_split.height(), 1)
        settle(5)
        assert w.log_view.height() >= mw.LOG_MIN_H - 1

    def test_body_keeps_the_extra_height_when_the_window_grows(self, make_window):
        w = make_window(ready_config(), size=(1280, 700))
        w.log_toggle.setChecked(True)
        settle()
        log_h = w.log_view.height()
        w.resize(1280, 900)
        settle(5)
        assert w.log_view.height() == log_h and w.body.height() > 500


# --------------------------------------------------------------------------- cỡ cửa sổ theo màn hình + nhớ lại
class TestScreenAndMemory:
    def test_default_size_fits_the_screen(self, make_window):
        w = make_window(ready_config(), size=None)
        avail = w.screen().availableGeometry()
        assert w.width() <= avail.width() and w.height() <= avail.height()
        assert w.width() <= int(avail.width() * mw.SCREEN_FRACTION) + 1 and w.height() <= int(avail.height() * mw.SCREEN_FRACTION) + 1
        assert w.width() >= mw.MIN_WINDOW[0] and w.height() >= mw.MIN_WINDOW[1]

    def test_minimum_size_fits_a_small_laptop_screen(self):
        assert mw.MIN_WINDOW[1] <= 480 and mw.MIN_WINDOW[0] <= 480  # màn hình 1366x768 scale 150% chỉ còn ~910x512 px logic

    def test_window_never_exceeds_the_screen_after_restoring_a_big_saved_size(self, make_window, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        st = QSettings(str(data_dir / mw.UI_STATE_FILE), QSettings.Format.IniFormat)
        probe = make_window(ready_config(), size=(8000, 6000))  # cửa sổ rất lớn
        st.setValue("window/geometry", probe.saveGeometry())
        st.sync()
        w = make_window(ready_config(), size=None)
        avail = w.screen().availableGeometry()
        assert w.width() <= avail.width() and w.height() <= avail.height()

    def test_state_file_lives_in_the_data_folder(self, make_window, data_dir):
        w = make_window(ready_config(), size=(1280, 720))
        w._save_ui_state()
        assert (data_dir / mw.UI_STATE_FILE).exists()
        assert not (config.BASE_DIR / "data" / mw.UI_STATE_FILE).exists() or data_dir != config.BASE_DIR / "data"

    def test_frames_and_window_are_remembered_between_runs(self, make_window, data_dir, qtbot):
        w = make_window(ready_config(), size=(1280, 760))
        w.splitter.moveSplitter(w.width() - 460, 1)
        w.right_split.moveSplitter(w.selected_card.height() + 60, 1)
        w.log_toggle.setChecked(True)
        settle()
        w.v_split.moveSplitter(w.v_split.sizes()[0] - 90, 1)
        settle(5)
        right_w, sel_h, log_h = w.right_split.width(), w.selected_card.height(), w.log_view.height()
        w._save_ui_state()
        again = make_window(ready_config(), size=(1280, 760))  # lần mở sau (cùng thư mục data)
        settle()
        assert abs(again.right_split.width() - right_w) <= 14
        assert abs(again.selected_card.height() - sel_h) <= 14
        again.log_toggle.setChecked(True)
        settle()
        assert abs(again.log_view.height() - log_h) <= 3

    def test_corrupt_state_file_falls_back_to_defaults(self, make_window, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / mw.UI_STATE_FILE).write_text("[window]\ngeometry=@@@\n[split]\nright_w=abc\nselected_h=-5\n[log]\nheight=zzz\n", encoding="utf-8")
        w = make_window(ready_config(), size=None)
        settle()
        assert w.width() >= mw.MIN_WINDOW[0] and abs(w.right_split.width() - mw.RIGHT_W) <= 14 or w._compact

    def test_saved_values_outside_the_allowed_range_are_clamped(self, make_window, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        st = QSettings(str(data_dir / mw.UI_STATE_FILE), QSettings.Format.IniFormat)
        st.setValue("split/right_w", 9000)
        st.sync()
        w = make_window(ready_config(), size=(1300, 760))
        w.resize(1301, 760)
        settle()
        assert w.right_split.width() <= mw.RIGHT_MAX + 2

    def test_close_saves_the_state(self, make_window, data_dir):
        w = make_window(ready_config(), size=(1280, 720))
        w.splitter.moveSplitter(w.width() - 500, 1)
        settle()
        (data_dir / mw.UI_STATE_FILE).unlink(missing_ok=True)
        w.close()
        assert (data_dir / mw.UI_STATE_FILE).exists()
        assert int(QSettings(str(data_dir / mw.UI_STATE_FILE), QSettings.Format.IniFormat).value("split/right_w")) >= mw.RIGHT_MIN

    def test_compact_layout_does_not_overwrite_the_wide_layout_sizes(self, make_window, data_dir):
        w = make_window(ready_config(), size=(1280, 720))
        w.splitter.moveSplitter(w.width() - 500, 1)
        settle()
        w._save_ui_state()
        saved = int(QSettings(str(data_dir / mw.UI_STATE_FILE), QSettings.Format.IniFormat).value("split/right_w"))
        w.resize(460, 780)
        settle()
        w._save_ui_state()
        assert int(QSettings(str(data_dir / mw.UI_STATE_FILE), QSettings.Format.IniFormat).value("split/right_w")) == saved


def test_helper_as_int():
    assert mw._as_int("12") == 12 and mw._as_int(None) is None and mw._as_int("x") is None and mw._as_int(7.0) == 7


def test_qpoint_import_is_used_for_geometry_sanity(make_window):
    w = make_window(ready_config(), size=(1280, 720))
    assert w.selected_card.mapTo(w, QPoint(0, 0)).x() > w.champ_panel.mapTo(w, QPoint(0, 0)).x()  # khung chọn nằm bên phải khung tướng
