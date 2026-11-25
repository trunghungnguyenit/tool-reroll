"""Chẩn đoán môi trường (quyền Admin của tool/game, cửa sổ game, vùng Shop) và các hàm Win32 đứng sau nó."""

import os

import pytest

import core.diagnostics as dg
import core.game_window as gw

REGION = {"left": 366, "top": 870, "width": 1195, "height": 209}
FULLSCREEN = (0, 0, 1920, 1080)


def game(elevation=gw.ELEV_NO, process="league of legends.exe", rect=FULLSCREEN):
    return gw.GameWindow(hwnd=1, pid=2, process=process, cls="RiotWindowClass", title="League of Legends (TM) Client",
                         rect=rect, elevation=elevation)


def warnings(lines):
    return [m for m in lines if m.startswith("Cảnh báo")]


class TestEnvironmentLines:
    def test_game_not_running_says_so(self):
        lines = dg.environment_lines(None, gw.ELEV_NO, REGION)
        assert lines[0] == "Chẩn đoán: tool đang chạy quyền thường." and "chưa thấy cửa sổ game" in lines[1]
        assert len(lines) == 2

    def test_everything_fine_has_no_warning(self):
        lines = dg.environment_lines(game(), gw.ELEV_NO, REGION)
        assert warnings(lines) == []
        assert "league of legends.exe" in lines[1] and "1920×1080" in lines[1] and "quyền thường" in lines[1]

    @pytest.mark.parametrize("game_elevation", [gw.ELEV_YES, gw.ELEV_DENIED])
    def test_game_with_higher_rights_than_the_tool_is_a_warning(self, game_elevation):
        lines = dg.environment_lines(game(game_elevation), gw.ELEV_NO, REGION)
        assert len(warnings(lines)) == 1 and "Run as administrator" in warnings(lines)[0]

    def test_both_admin_is_fine(self):
        assert warnings(dg.environment_lines(game(gw.ELEV_YES), gw.ELEV_YES, REGION)) == []

    def test_unreadable_game_rights_are_noted_but_not_a_warning(self):
        lines = dg.environment_lines(game(gw.ELEV_UNKNOWN, process=None), gw.ELEV_NO, REGION)
        assert warnings(lines) == []
        assert any("Vanguard" in m for m in lines) and "không đọc được tên process" in lines[1]

    def test_shop_region_outside_the_game_window_is_a_warning(self):
        other_screen = game(rect=(-1920, 0, 0, 1080))
        warn = warnings(dg.environment_lines(other_screen, gw.ELEV_NO, REGION))
        assert len(warn) == 1 and "KHÔNG nằm trong cửa sổ game" in warn[0]

    def test_no_region_means_no_region_check(self):
        assert warnings(dg.environment_lines(game(rect=(-1920, 0, 0, 1080)), gw.ELEV_NO, None)) == []


# Số thật từ máy người dùng (data/config.json): vùng 1195 px gồm cả nút Buy XP/Reroll bên trái; thẻ thật rộng ~200 px từ x=185.
USER_REGION = {"left": 366, "top": 870, "width": 1195, "height": 209}
USER_CENTERS = [(642, 1021), (862, 1005), (1065, 1017), (1242, 1012), (1450, 1010)]
# Vùng đúng: chỉ 5 thẻ (mỗi thẻ ~200 px), tâm thẻ nằm giữa từng ô chia đều
GOOD_REGION = {"left": 541, "top": 870, "width": 1010, "height": 209}
GOOD_CENTERS = [(541 + 101 + 202 * i, 1010) for i in range(5)]


class TestSlotAlignment:
    def test_the_users_real_region_is_flagged_with_a_suggestion(self):
        lines = dg.slot_alignment_lines(USER_REGION, USER_CENTERS)
        assert lines[0].startswith("Cảnh báo: vùng Shop KHÔNG khớp 5 thẻ") and "ô 1 lệch +156 px" in lines[0]
        assert "ô lệch: 1, 2, 3" in lines[0] and "Buy XP/Reroll" in lines[0]
        assert "mép trái vùng ≈ 541" in lines[1] and "rộng ≈ 1010" in lines[1]  # đúng vùng thẻ thật (551..1546)

    def test_a_region_around_just_the_five_cards_is_fine(self):
        assert dg.slot_alignment_lines(GOOD_REGION, GOOD_CENTERS) == []

    def test_small_click_inaccuracy_is_tolerated(self):
        sloppy = [(x + dx, y) for (x, y), dx in zip(GOOD_CENTERS, (-30, 25, 0, -20, 30))]
        assert dg.slot_alignment_lines(GOOD_REGION, sloppy) == []

    @pytest.mark.parametrize("region,centers", [(None, USER_CENTERS), (USER_REGION, None), (USER_REGION, []),
                                                (USER_REGION, USER_CENTERS[:3]), ({"left": 0, "top": 0, "width": 0, "height": 5}, USER_CENTERS)])
    def test_missing_data_means_no_check(self, region, centers):
        assert dg.slot_alignment_lines(region, centers) == []

    def test_environment_reports_it_even_when_the_game_is_not_running(self):
        lines = dg.environment_lines(None, gw.ELEV_NO, USER_REGION, USER_CENTERS)
        assert len(warnings(lines)) == 1 and "chưa thấy cửa sổ game" in lines[-1]

    def test_no_centers_given_keeps_the_old_behaviour(self):
        assert warnings(dg.environment_lines(game(), gw.ELEV_NO, REGION)) == []


class TestRegionInsideWindow:
    def test_inside_and_outside(self):
        assert dg.region_inside_window(REGION, FULLSCREEN)
        assert not dg.region_inside_window(REGION, (0, 0, 1000, 1080))

    def test_small_overhang_is_tolerated_for_window_borders(self):
        edge = {"left": 0, "top": 0, "width": 1924, "height": 1080}
        assert dg.region_inside_window(edge, FULLSCREEN)
        assert not dg.region_inside_window({**edge, "width": 1940}, FULLSCREEN)


class TestRealWin32:
    def test_collect_environment_reads_the_real_system(self):
        lines = dg.collect_environment(frozenset({"khong-co-game-nay.exe"}), REGION)
        assert lines[0].startswith("Chẩn đoán: tool đang chạy quyền")

    def test_own_process_elevation_is_yes_or_no(self):
        assert gw.process_elevation(os.getpid()) in (gw.ELEV_YES, gw.ELEV_NO)
        assert gw.tool_elevation() == gw.process_elevation(os.getpid())

    def test_missing_process_is_unknown(self):
        assert gw.process_elevation(0x7FFFFFF0) == gw.ELEV_UNKNOWN

    def test_find_game_window_returns_none_or_a_riot_window(self):
        found = gw.find_game_window(frozenset({"khong-co-game-nay.exe"}))
        assert found is None or (found.cls or "").lower() in gw.GAME_WINDOW_CLASSES

    def test_find_game_window_by_process_name_of_a_visible_window(self):
        """Cửa sổ đang ở trước (nếu đọc được tên process và đủ lớn) tìm được theo tên process của nó."""
        name = gw.foreground_process_name()
        if name is None:
            pytest.skip("không có cửa sổ foreground đọc được")
        found = gw.find_game_window(frozenset({name}))
        if found is not None:  # cửa sổ foreground có thể nhỏ/ẩn nên không bắt buộc tìm thấy
            assert found.process == name and found.rect[2] > found.rect[0] and found.pid > 0
