"""Liệt kê màn hình và tìm màn hình chứa game: phần logic (chọn màn hình theo điểm/vùng) bằng dữ liệu giả; phần Win32 chạy thật."""

import pytest

import core.monitors as mon
from core.monitors import Monitor

D1 = Monitor(r"\\.\DISPLAY1", 0, 0, 1920, 1080, 125, True)
D2 = Monitor(r"\\.\DISPLAY2", 1920, 0, 2560, 1440, 150)
LEFT = Monitor(r"\\.\DISPLAY3", -1280, 100, 1280, 1024, 100)
ALL = [LEFT, D1, D2]


class TestMonitor:
    def test_key_changes_with_resolution_so_a_new_resolution_needs_its_own_profile(self):
        assert D1.key == r"\\.\DISPLAY1|1920x1080"
        assert Monitor(D1.device, 0, 0, 2560, 1440).key != D1.key

    def test_key_ignores_position_and_scale(self):
        moved = Monitor(D1.device, 500, 20, 1920, 1080, 150)
        assert moved.key == D1.key

    def test_rect_number_and_label(self):
        assert D2.rect == {"left": 1920, "top": 0, "width": 2560, "height": 1440} and D2.number == 2
        assert D1.label() == "Màn hình 1 · 1920×1080 · 125% · chính"
        assert D2.label() == "Màn hình 2 · 2560×1440 · 150%"
        assert Monitor("weird", 0, 0, 10, 10).label().startswith("Màn hình ·")

    def test_contains_is_half_open(self):
        assert D1.contains(0, 0) and D1.contains(1919, 1079)
        assert not D1.contains(1920, 0) and not D1.contains(0, 1080) and not D1.contains(-1, 0)


class TestLookup:
    def test_monitor_for_point(self):
        assert mon.monitor_for_point(ALL, 100, 100) is D1
        assert mon.monitor_for_point(ALL, 2000, 10) is D2
        assert mon.monitor_for_point(ALL, -500, 500) is LEFT  # tọa độ âm: màn hình bên trái màn hình chính
        assert mon.monitor_for_point(ALL, 9000, 9000) is None
        assert mon.monitor_for_point([], 1, 1) is None

    def test_monitor_for_region_picks_the_one_with_most_overlap(self):
        assert mon.monitor_for_region(ALL, {"left": 100, "top": 800, "width": 1000, "height": 200}) is D1
        assert mon.monitor_for_region(ALL, {"left": 2000, "top": 100, "width": 1000, "height": 200}) is D2
        straddling = {"left": 1800, "top": 100, "width": 400, "height": 100}  # 120 px ở D1, 280 px ở D2
        assert mon.monitor_for_region(ALL, straddling) is D2
        assert mon.monitor_for_region(ALL, {"left": -1000, "top": 300, "width": 500, "height": 100}) is LEFT

    def test_region_outside_every_monitor_has_none(self):
        assert mon.monitor_for_region(ALL, {"left": 9000, "top": 9000, "width": 100, "height": 100}) is None

    def test_find_by_device(self):
        assert mon.find_by_device(ALL, r"\\.\DISPLAY2") is D2 and mon.find_by_device(ALL, "x") is None


@pytest.mark.real_monitors
class TestGameMonitor:
    """game_monitor thật (conftest giả lập nó mặc định); chỉ vị trí cửa sổ game được giả."""

    def test_game_on_second_monitor(self, monkeypatch):
        monkeypatch.setattr(mon, "game_window_center", lambda names: (3000, 700))
        assert mon.game_monitor(frozenset({"league of legends.exe"}), ALL) is D2

    def test_game_not_running(self, monkeypatch):
        monkeypatch.setattr(mon, "game_window_center", lambda names: None)
        assert mon.game_monitor(frozenset({"league of legends.exe"}), ALL) is None

    def test_game_window_off_every_monitor(self, monkeypatch):
        monkeypatch.setattr(mon, "game_window_center", lambda names: (-9000, -9000))
        assert mon.game_monitor(frozenset({"league of legends.exe"}), ALL) is None


@pytest.mark.real_monitors
class TestWin32:
    """Chạy thật trên máy này (Windows): kiểm tra các lệnh gọi Win32 không lỗi và cho dữ liệu hợp lý."""

    def test_lists_at_least_one_monitor_with_sane_values(self):
        found = mon.list_monitors()
        if not found:
            pytest.skip("máy này không đọc được danh sách màn hình (không có màn hình/phiên không tương tác)")
        assert all(m.width > 0 and m.height > 0 and m.scale >= 100 and m.device for m in found)
        assert sum(m.primary for m in found) == 1
        assert found == sorted(found, key=lambda m: (m.left, m.top))
        assert len({m.device for m in found}) == len(found)

    def test_unknown_process_has_no_window(self):
        assert mon.game_window_center(frozenset({"khong-co-tien-trinh-nay.exe"})) is None

    def test_empty_name_set_has_no_window(self):
        assert mon.game_window_center(frozenset()) is None
