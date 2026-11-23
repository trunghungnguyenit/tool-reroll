"""Bố cục desktop: khung chọn tướng chiếm tối đa chỗ, cột phải gọn có thu/mở, Nhật ký đóng/mở (mặc định đóng), chip mùa cỡ nhỏ,
thanh trên một hàng. Dữ liệu tướng giả (237 thẻ, 12 mùa) để lưới thật sự cần cuộn và các chip mùa thật sự cần xuống dòng."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

import core.controller as ctl
from tests.fakes import champ, fake_loader
from tests.test_ui import boxes, make_window, ready_config  # noqa: F401  (fixture dùng chung của test giao diện)
from ui import main_window as mw
from ui.champion_view import CARD_W


def many_champions():
    out = []
    for i in range(237):
        c = champ(f"Tướng {i}", 18 - i % 12, tier=1 + i % 5)
        c["sets"] = [18 - i % 12, 17 - i % 5][: 1 + i % 2]
        out.append(c)
    return out


@pytest.fixture
def big(make_window, qtbot, monkeypatch):
    """Cửa sổ có 237 thẻ, 12 mùa; trả hàm tạo cửa sổ theo kích thước."""
    monkeypatch.setattr(ctl, "load_all_champions", fake_loader(many_champions()))
    monkeypatch.setattr(ctl, "download_template", lambda n, u: None)

    def make(size=(1280, 720), **cfg):
        w = make_window(ready_config(**cfg), size=size)
        qtbot.waitUntil(lambda: len(w.c.champions) == 237, timeout=5000)
        QApplication.processEvents()
        return w

    return make


def fresh_log(w):
    """Đưa Nhật ký về trạng thái 'vừa xem xong, đang đóng' để đếm dòng mới từ 0."""
    w.log_toggle.setChecked(True)
    w.log_toggle.setChecked(False)


# --------------------------------------------------------------------------- Nhật ký đóng/mở
class TestLogBar:
    @pytest.mark.parametrize("size", [(1280, 720), (460, 780)])
    def test_log_is_closed_by_default_and_the_bar_stays_visible(self, make_window, size):
        w = make_window(ready_config(), size=size)
        assert not w.log_toggle.isChecked() and not w.log_view.isVisible()
        assert w.log_toggle.isVisible() and w.log_preview.isVisible() and not w.log_tools.isVisible()
        assert w.log_toggle.text() == "▸  Nhật ký"

    def test_closed_bar_is_one_line_high(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert w.log_wrap.height() <= 40

    def test_new_lines_show_a_count_and_the_latest_line_without_its_timestamp(self, make_window):
        w = make_window(ready_config())
        fresh_log(w)
        w.c.log("Chuyện thường thứ nhất")
        w.c.log("Dòng mới nhất")
        assert w.log_badge.isVisible() and w.log_badge.text() == "2"
        assert w.log_preview.fullText() == "Dòng mới nhất" and "Dòng mới nhất" in w.log_preview.text()

    def test_lines_are_still_recorded_while_closed(self, make_window):
        w = make_window(ready_config())
        w.c.log("ghi khi đóng")
        assert "ghi khi đóng" in w.log_view.toPlainText()

    def test_badge_is_hidden_when_nothing_is_new(self, make_window):
        w = make_window(ready_config())
        fresh_log(w)
        assert not w.log_badge.isVisible()

    def test_badge_colour_follows_the_worst_new_line(self, make_window):
        w = make_window(ready_config())
        fresh_log(w)
        w.c.log("Đã làm xong một việc")
        assert w.log_badge.property("tone") == "muted"
        w.c.log("Cảnh báo: Độ khớp tên < 75%")
        assert w.log_badge.property("tone") == "warn"
        w.c.log("Không bắt đầu được: thiếu Key")
        assert w.log_badge.property("tone") == "fail"
        w.c.log("Lại một dòng thường")  # lỗi đã có thì dòng thường không hạ mức
        assert w.log_badge.property("tone") == "fail"
        assert w.log_preview.property("tone") == "fail"  # dòng xem trước đổi màu theo cùng mức nặng nhất

    def test_warning_does_not_open_the_log_by_itself(self, make_window):
        w = make_window(ready_config())
        w.c.log("⚠ Chụp màn hình lỗi")
        assert not w.log_toggle.isChecked() and not w.log_view.isVisible()

    def test_opening_shows_the_log_tools_and_clears_the_badge(self, make_window):
        w = make_window(ready_config())
        fresh_log(w)
        w.c.log("Cảnh báo: gì đó")
        w.log_toggle.setChecked(True)
        assert w.log_view.isVisible() and w.log_tools.isVisible() and not w.log_preview.isVisible() and not w.log_badge.isVisible()
        assert w.log_toggle.text() == "▾  Nhật ký" and w.log_copy_btn.isVisible()

    def test_lines_logged_while_open_do_not_count_as_new(self, make_window):
        w = make_window(ready_config())
        w.log_toggle.setChecked(True)
        w.c.log("dòng khi đang mở")
        assert w._log_new == 0 and not w.log_badge.isVisible()
        w.log_toggle.setChecked(False)
        assert not w.log_badge.isVisible()
        w.c.log("dòng sau khi đóng")
        assert w.log_badge.text() == "1"

    def test_open_height_depends_on_the_layout(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        w.log_toggle.setChecked(True)
        assert w.log_view.height() == mw.LOG_OPEN_H
        w.resize(460, 780)
        QApplication.processEvents()
        assert w.log_view.height() == mw.LOG_OPEN_H_COMPACT

    def test_copy_takes_the_whole_log_even_when_closed(self, make_window):
        w = make_window(ready_config())
        w.c.log("để sao chép")
        QApplication.clipboard().setText("")
        w.log_copy_btn.click()
        assert "để sao chép" in QApplication.clipboard().text() and "Phiên bản" in QApplication.clipboard().text()

    def test_clear_empties_the_log_badge_and_preview(self, make_window):
        w = make_window(ready_config())
        w.c.log("xóa tôi")
        w.log_toggle.setChecked(True)
        w.log_clear_btn.click()
        assert w.log_view.toPlainText() == "" and w._log_new == 0 and w.log_preview.fullText() == ""

    def test_bottom_button_scrolls_to_the_newest_line(self, make_window):
        w = make_window(ready_config())
        for i in range(60):
            w.c.log(f"dòng {i}")
        w.log_toggle.setChecked(True)
        bar = w.log_view.verticalScrollBar()
        bar.setValue(0)
        w.log_bottom_btn.click()
        assert bar.value() == bar.maximum() > 0

    def test_long_preview_is_elided_not_widening_the_window(self, make_window):
        w = make_window(ready_config(), size=(460, 780))
        w.c.log("x" * 400)
        assert w.log_preview.fullText().startswith("xxx") and len(w.log_preview.text()) < 200
        assert w.log_preview.width() <= w.width()

    def test_badge_caps_at_99_plus(self, make_window):
        w = make_window(ready_config())
        fresh_log(w)
        for i in range(105):
            w.c.log(f"dòng {i}")
        assert w.log_badge.text() == "99+"

    def test_log_keeps_working_after_a_layout_switch(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        w.log_toggle.setChecked(True)
        w.resize(460, 780)
        QApplication.processEvents()
        w.resize(1280, 720)
        QApplication.processEvents()
        assert w.log_toggle.isChecked() and w.log_view.isVisible()


class TestClassifyLog:
    @pytest.mark.parametrize("text,level", [
        ("Không bắt đầu được: thiếu Key", "error"), ("⚠ Chụp lỗi", "error"), ("Lỗi tải tướng: mất mạng", "error"),
        ("[10:00:00] OCR bị kẹt quá hạn", "error"), ("Chụp DXGI gặp vấn đề (x) — chuyển sang mss.", "error"),
        ("⚠ OCR không hoạt động: thiếu gói", "error"),
        ("Cảnh báo: Độ khớp tên < 75%", "warn"), ("Không có mạng — dùng danh sách đã lưu", "warn"),
        ("Bỏ click ô 3: thẻ đã đổi", "warn"), ("2/94 bản patch lỗi mạng", "warn"),
        ("Đã lưu vùng shop", "info"), ("✓ Mua Vex ở ô 3", "info"), ("OCR đã hồi phục sau khi bị kẹt.", "info"),
        ("OCR đã đọc lại được chữ trong shop.", "info"), ("", "info"),
    ])
    def test_levels(self, text, level):
        assert ctl.classify_log(text) == level
        assert ctl.classify_log(f"[12:00:00] {text}") == level  # có dấu thời gian đầu dòng vẫn như vậy

    def test_log_event_carries_the_level(self, make_window):
        events = []
        w = make_window(ready_config())
        orig = w._ev_log
        w._ev_log = lambda text, level="info": (events.append(level), orig(text, level))
        w.c.log("Cảnh báo: x")
        assert events == ["warn"]


# --------------------------------------------------------------------------- khung chọn tướng chiếm tối đa
class TestChampionAreaFirst:
    @pytest.mark.parametrize("size", [(1920, 1040), (1280, 720), (1000, 700)])
    def test_grid_gets_most_of_the_window_height(self, big, size):
        w = big(size)
        assert w.view.height() >= 0.45 * w.height(), (size, w.view.height())

    @pytest.mark.parametrize("size", [(1920, 1040), (1280, 720), (1000, 700)])
    def test_champion_panel_is_wider_than_the_right_column(self, big, size):
        w = big(size)
        assert w.champ_panel.width() > w.right_scroll.width() * 1.5

    @pytest.mark.parametrize("size", [(1920, 1040), (1280, 720), (1000, 700)])
    def test_right_column_is_narrow_and_fixed_in_range(self, big, size):
        w = big(size)
        assert mw.RIGHT_W - 40 <= w.right_scroll.width() <= mw.RIGHT_W + 80

    def test_extra_width_goes_to_the_champion_panel_only(self, big):
        w = big((1100, 800))
        right, left = w.right_scroll.width(), w.champ_panel.width()
        w.resize(1500, 800)
        QApplication.processEvents()
        assert abs(w.right_scroll.width() - right) <= 10 and w.champ_panel.width() > left + 300

    def test_more_cards_are_visible_than_before(self, big):
        """Trước bố cục mới ở 1920x1040 chỉ thấy ~15 thẻ (1 hàng). Giờ nhiều hơn hẳn."""
        w = big((1920, 1040))
        rows = max(1, w.view.height() // w.view.cell_size().height())
        assert w.view.columns() * rows >= 60

    def test_bottom_of_the_panel_is_one_compact_row_with_manual_names_hidden(self, big):
        w = big((1280, 720))
        assert not w.manual.isVisible() and w.sw_image.isVisible() and w.sw_name.isVisible()
        ys = {w.sw_image.mapTo(w, QPoint(0, 0)).y() // 20, w.sw_name.mapTo(w, QPoint(0, 0)).y() // 20}
        assert len(ys) == 1  # hai công tắc cùng một hàng

    def test_search_shares_the_header_row_in_the_wide_layout(self, big):
        w = big((1280, 720))
        assert abs(w.search.mapTo(w, QPoint(0, 0)).y() - w.mode_btn.mapTo(w, QPoint(0, 0)).y()) < 12

    def test_search_gets_its_own_row_in_the_narrow_layout(self, big):
        w = big((460, 780))
        assert w.search.mapTo(w, QPoint(0, 0)).y() > w.mode_btn.mapTo(w, QPoint(0, 0)).y() + 15


class TestGridFill:
    def test_cards_stretch_to_fill_the_row(self, big):
        for size in ((1920, 1040), (1280, 720), (1000, 700), (460, 780)):
            w = big(size)
            v = w.view
            cols = v.columns()
            used = v.cell_size().width() * cols
            assert cols >= 2 and used <= v.viewport().width() and v.viewport().width() - used < cols, (size, cols, used)
            assert v.gridSize() == v.cell_size() and v.cell_size().width() >= CARD_W

    def test_wider_window_gives_more_columns_and_the_grid_follows_resizes(self, big):
        w = big((1000, 700))
        before = w.view.columns()
        w.resize(1700, 700)
        QApplication.processEvents()
        assert w.view.columns() > before and w.view.gridSize() == w.view.cell_size()

    def test_resizing_creates_no_widgets_and_keeps_the_model(self, big):
        w = big((1280, 720))
        model, count = w.view.champion_model, len(w.findChildren(QWidget))
        for width in (1300, 1500, 1100, 1700, 1280):
            w.resize(width, 720)
            QApplication.processEvents()
        assert w.view.champion_model is model and len(w.findChildren(QWidget)) == count

    def test_crossing_the_compact_threshold_creates_no_widgets_either(self, big):
        w = big((1280, 720))
        count = len(w.findChildren(QWidget))
        for width in (700, 1280, 700, 1280):
            w.resize(width, 720)
            QApplication.processEvents()
        assert len(w.findChildren(QWidget)) == count

    def test_filtering_does_not_change_the_grid(self, big):
        w = big((1280, 720))
        cell = w.view.gridSize()
        w.search.setText("Tướng 1")
        w.season_buttons[7].click()
        assert w.view.gridSize() == cell  # thanh cuộn luôn hiện nên bề rộng viewport không nhảy theo số kết quả

    def test_vertical_scrollbar_is_always_on_and_horizontal_never(self, big):
        w = big((1280, 720))
        assert w.view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        assert w.view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff

    def test_text_mode_is_unaffected(self, big):
        w = big((1280, 720))
        w.mode_btn.click()
        assert w.view.gridSize().isEmpty()


# --------------------------------------------------------------------------- chip chọn mùa nhỏ
class TestSmallSeasonChips:
    def test_chips_are_small_pills(self, big):
        w = big((1280, 720))
        for b in (w.season_all, *w.season_buttons.values(), *w.cost_buttons.values(), w.only_sel_btn):
            assert b.height() <= 26 and b.property("pill") is True, b.text()

    def test_seasons_and_costs_share_rows_and_take_at_most_two(self, big):
        w = big((1280, 720))
        rows = {b.mapTo(w, QPoint(0, 0)).y() // 10 for b in (*w.cost_buttons.values(), w.only_sel_btn, w.season_all, *w.season_buttons.values())}
        assert len(rows) <= 3  # (làm tròn theo 10px) chip cost và chip mùa chung hàng, tổng cộng tối đa 2 hàng

    def test_first_season_chip_is_on_the_same_row_as_the_cost_chips_when_wide(self, big):
        w = big((1920, 1040))
        assert abs(w.season_all.geometry().center().y() - w.cost_buttons[1].geometry().center().y()) < 4

    def test_all_season_chips_fit_one_row_on_a_very_wide_window(self, big):
        w = big((1920, 1040))
        ys = {b.geometry().center().y() for b in (w.season_all, *w.season_buttons.values())}
        assert len(ys) == 1

    def test_pills_are_much_smaller_than_the_old_chips(self, big):
        w = big((1280, 720))
        assert w.season_buttons[18].height() <= 24 and w.season_buttons[18].width() <= 56

    def test_narrow_layout_wraps_without_overflowing(self, big):
        w = big((460, 780))
        assert all(b.isVisible() and b.mapTo(w, QPoint(0, 0)).x() + b.width() <= w.width() for b in w.season_buttons.values())


# --------------------------------------------------------------------------- cột phải gọn, thu/mở
class TestRightColumn:
    def test_ready_block_is_a_single_line_when_everything_is_ready(self, make_window, qtbot):
        w = make_window(ready_config())
        qtbot.waitUntil(lambda: bool(w.c.champions), timeout=3000)
        assert w.c.ready() and not w.ready_toggle.isChecked() and not w.ready_body.isVisible()
        assert w.ready_toggle.text() == "▸  ✓ Sẵn sàng chạy" and w.ready_toggle.property("tone") == "ok"
        assert w.ready_card.height() <= 60

    def test_ready_block_opens_by_itself_and_lists_what_is_missing(self, make_window):
        w = make_window(ready_config(selected_champions=[]), autoload=False)
        assert not w.c.ready() and w.ready_toggle.isChecked() and w.ready_body.isVisible()
        assert w.ready_toggle.text().startswith("▾  ✗ Chưa sẵn sàng · còn 1 việc") and w.ready_toggle.property("tone") == "fail"
        assert w.ready_rows["champions"].isVisible()

    def test_ready_block_collapses_when_the_last_missing_item_is_fixed(self, make_window):
        w = make_window(ready_config(selected_champions=[]), autoload=False)
        w.c.manual_names = "Vex"
        w.c.changed()
        assert w.c.ready() and not w.ready_toggle.isChecked()

    def test_user_choice_is_kept_until_the_state_changes(self, make_window):
        w = make_window(ready_config(), autoload=False)
        w.ready_toggle.setChecked(True)  # người dùng tự mở dù đã sẵn sàng
        w.c.changed()
        w.c.changed()
        assert w.ready_toggle.isChecked() and w.ready_body.isVisible()
        w.c.manual_names = ""
        w.c.config["selected_champions"] = []
        w.c.detect_name = w.c.detect_image = False
        w.c.changed()  # không còn sẵn sàng → mở (đã mở)
        assert w.ready_toggle.isChecked()

    def test_shop_block_is_collapsed_when_already_configured(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert not w.shop_toggle.isChecked() and not w.shop_body.isVisible()
        assert w.shop_toggle.text() == "▸  Vùng Shop và điểm click  ·  ✓"

    def test_shop_block_is_open_when_not_configured(self, make_window):
        w = make_window(ready_config(shop_region=None, slot_centers=[]), size=(1280, 720))
        assert w.shop_toggle.isChecked() and w.shop_body.isVisible() and w.region_btn.isVisible()
        assert w.shop_toggle.text() == "▾  Vùng Shop và điểm click  ·  ✗"

    def test_shop_block_reopens_by_itself_when_the_config_breaks(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert not w.shop_toggle.isChecked()
        w.c.config["slot_centers"] = []
        w.c.changed()
        assert w.shop_toggle.isChecked() and w.shop_body.isVisible()

    def test_shop_block_does_not_close_itself_after_the_user_finishes_the_steps(self, make_window):
        w = make_window(ready_config(shop_region=None, slot_centers=[]), size=(1280, 720))
        w.c.set_region({"left": 0, "top": 0, "width": 1000, "height": 200})
        w.c.set_click_points([(40 + i * 190, 150) for i in range(5)])
        assert w.shop_toggle.isChecked()  # còn thấy ảnh xem trước vừa chụp

    def test_user_can_fold_and_unfold_every_block(self, make_window):
        w = make_window(ready_config(shop_region=None, slot_centers=[]), size=(1280, 720))
        for toggle, body in ((w.shop_toggle, w.shop_body), (w.ready_toggle, w.ready_body), (w.adv_toggle, w.adv_body)):
            toggle.setChecked(True)
            assert body.isVisible()
            toggle.setChecked(False)
            assert not body.isVisible()

    def test_go_to_step_opens_the_target_block(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert not w.shop_toggle.isChecked()
        w.go_to_step(ctl.STEP_REGION)
        assert w.shop_toggle.isChecked() and w.shop_body.isVisible()

    def test_blocked_start_dragging_the_user_to_the_shop_block_opens_it(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        w.c.config.update(shop_region=None, slot_centers=[], monitor_profiles={}, active_monitor="")  # cấu hình hỏng thật sự
        w.shop_toggle.setChecked(False)
        w.start_btn.click()
        assert w.shop_toggle.isChecked()

    def test_the_three_steps_share_one_row_with_short_labels(self, make_window):
        w = make_window(ready_config(shop_region=None, slot_centers=[]), size=(1280, 720))
        ys = {b.mapTo(w, QPoint(0, 0)).y() for b in (w.region_btn, w.clicks_btn, w.view_btn)}
        assert len(ys) == 1 and w.region_btn.text() == "①  Vùng Shop" and w.clicks_btn.text() == "②  5 điểm click"
        assert w.view_btn.text() == "👁  Xem"

    def test_done_steps_show_a_tick(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert w.region_btn.text() == "✓  Vùng Shop" and w.clicks_btn.text() == "✓  5 điểm click"

    def test_row_and_button_sizes_are_compact(self, make_window):
        w = make_window(ready_config(shop_region=None, slot_centers=[]), size=(1280, 720))
        w.shop_toggle.setChecked(True)
        assert w.region_btn.height() <= 30 and w.refresh_btn.height() <= 28 and w.mode_btn.height() <= 28
        w.ready_toggle.setChecked(True)
        assert all(r.height() <= 26 for r in w.ready_rows.values())

    def test_advanced_stays_closed_by_default(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert not w.adv_toggle.isChecked() and not w.adv_body.isVisible() and w.adv_toggle.text() == "▸  Nâng cao"

    def test_the_whole_header_row_is_clickable(self, make_window, qtbot):
        w = make_window(ready_config(shop_region=None, slot_centers=[]), size=(1280, 720))
        assert w.shop_toggle.width() >= w.shop_card.width() - 30  # bấm bất kỳ chỗ nào trên hàng tiêu đề
        qtbot.mouseClick(w.shop_toggle, Qt.MouseButton.LeftButton, pos=QPoint(w.shop_toggle.width() - 10, 8))
        assert not w.shop_toggle.isChecked()

    def test_nothing_in_the_right_column_scrolls_horizontally(self, make_window):
        w = make_window(ready_config(shop_region=None, slot_centers=[]), size=(1280, 720))
        w.adv_toggle.setChecked(True)
        QApplication.processEvents()
        assert not w.right_scroll.horizontalScrollBar().isVisible()


# --------------------------------------------------------------------------- tên gõ tay
class TestManualNames:
    def test_hidden_behind_a_button_by_default(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert not w.manual.isVisible() and w.manual_btn.text() == "Tên gõ tay ▸" and not w.manual_btn.isChecked()

    def test_button_shows_and_hides_the_box(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        w.manual_btn.click()
        assert w.manual.isVisible() and w.manual_btn.text() == "Tên gõ tay ▾"
        w.manual_btn.click()
        assert not w.manual.isVisible()

    def test_existing_manual_names_are_shown_at_startup(self, make_window):
        w = make_window(ready_config(manual_names="Aatrox, Yasuo"), size=(1280, 720))
        assert w.manual.isVisible() and w.manual.toPlainText() == "Aatrox, Yasuo" and w.manual_btn.isChecked()

    def test_hidden_box_still_counts_its_names(self, make_window):
        w = make_window(ready_config(selected_champions=[]), autoload=False)
        w.manual.setPlainText("Vex")
        assert w.c.target_names() == ["Vex"]


# --------------------------------------------------------------------------- thanh trên một hàng
class TestTopBar:
    def test_wide_layout_puts_chips_and_start_button_on_one_row(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        ys = [w.title_label.mapTo(w, QPoint(0, 0)).y(), w.chips_box.mapTo(w, QPoint(0, 0)).y(), w.start_btn.mapTo(w, QPoint(0, 0)).y()]
        assert max(ys) - min(ys) < 30

    def test_wide_topbar_is_shorter_than_before(self, make_window):
        w = make_window(ready_config(), size=(1920, 1040))
        assert w.centralWidget().layout().itemAt(0).widget().height() <= 56

    def test_narrow_layout_moves_chips_under_the_title(self, make_window):
        w = make_window(ready_config(), size=(460, 780))
        assert w.chips_box.mapTo(w, QPoint(0, 0)).y() > w.start_btn.mapTo(w, QPoint(0, 0)).y() + 20

    def test_start_button_stays_in_the_top_right(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        assert w.start_btn.mapTo(w, QPoint(0, 0)).x() > w.width() * 0.6 and w.start_btn.mapTo(w, QPoint(0, 0)).y() < 40

    def test_switching_layouts_back_and_forth_keeps_every_chip(self, make_window):
        w = make_window(ready_config(), size=(1280, 720))
        for width in (460, 1280, 460, 1280):
            w.resize(width, 720)
            QApplication.processEvents()
        assert all(c.isVisible() for c in (w.chip_ready, w.chip_selected, w.chip_ocr, w.chip_speed, w.start_btn))


# --------------------------------------------------------------------------- bố cục hẹp
class TestNarrowLayout:
    def test_three_tabs_kept_and_log_closed(self, make_window):
        w = make_window(ready_config(), size=(460, 780))
        assert w._compact and w.tabbar.count() == 3 and not w.log_view.isVisible()

    @pytest.mark.parametrize("width", [420, 460, 600, 800])
    def test_compact_pages_never_scroll_horizontally_with_the_new_blocks(self, big, width):
        w = big((width, 800))
        for page in range(3):
            w.tabbar.setCurrentIndex(page)
            w.shop_toggle.setChecked(True)
            w.ready_toggle.setChecked(True)
            w.adv_toggle.setChecked(True)
            QApplication.processEvents()
            scroll = w.stack.widget(page)
            assert isinstance(scroll, QScrollArea) and not scroll.horizontalScrollBar().isVisible(), (width, page)

    def test_champion_tab_grid_is_tall_enough_to_be_useful(self, big):
        w = big((460, 780))
        assert w.view.height() >= 220
