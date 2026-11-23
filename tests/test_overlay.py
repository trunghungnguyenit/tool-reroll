"""Overlay chọn vùng Shop / đặt 5 điểm click / xem trên màn hình thật: một cửa sổ cho mỗi màn hình, đúng trên nhiều màn hình có
DPI và vị trí khác nhau (kể cả màn hình nằm bên trái màn hình chính nên tọa độ âm). Màn hình thật được thay bằng màn hình giả."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from core.monitors import Monitor
from tests.overlay_fakes import Cursor, drag, one_screen, screen, two_screens
from ui import overlay as ov

GREEN, RED = ov.GREEN.name().lower(), ov.RED.name().lower()


def pixel(surface, x, y):
    """Màu (hex) tại điểm (x, y) của cửa sổ sau khi vẽ."""
    return surface.grab().toImage().pixelColor(int(x), int(y)).name().lower()


def colors(surface, step=20):
    """Tập màu (hex) lấy mẫu trên cả cửa sổ (chụp một lần): để kiểm tra "không có màu này ở màn hình này"."""
    img = surface.grab().toImage()
    return {img.pixelColor(x, y).name().lower() for x in range(0, img.width(), step) for y in range(0, img.height(), step)}


def dot(surface, point):
    """Màu tại điểm trong chấm đỏ đánh số của `point` (lệch sang phải để tránh chữ số ở giữa chấm)."""
    p = surface.to_local(*point)
    return pixel(surface, p.x() + 7, p.y())


def make(qtbot, cls, screens, *args, cursor=None):
    o = cls(*args, screens, phys=cursor or Cursor())
    for s in o.surfaces:
        qtbot.addWidget(s)
    o.show()
    return o


# ------------------------------------------------------------------------------------------ cửa sổ theo màn hình
class TestSurfaces:
    def test_one_window_per_screen_sized_by_the_screen_ratio(self, qtbot):
        o = make(qtbot, ov.RegionOverlay, two_screens())
        assert len(o.surfaces) == 2
        assert [(s.width(), s.height()) for s in o.surfaces] == [(1536, 864), (1707, 960)]  # vật lý / hệ số DPI từng màn hình

    def test_each_surface_maps_its_own_physical_origin(self, qtbot):
        a, b = make(qtbot, ov.RegionOverlay, two_screens()).surfaces
        assert a.to_phys(QPoint(0, 0)) == (0, 0) and a.to_phys(QPoint(768, 432)) == (960, 540)
        assert b.to_phys(QPoint(0, 0)) == (1920, 0) and b.to_phys(QPoint(100, 100)) == (2070, 150)

    def test_to_local_is_the_inverse_of_to_phys(self, qtbot):
        for s in make(qtbot, ov.RegionOverlay, two_screens()).surfaces:
            x, y = s.to_phys(QPoint(321, 123))
            p = s.to_local(x, y)
            assert abs(p.x() - 321) <= 1.5 and abs(p.y() - 123) <= 1.5

    def test_screen_left_of_the_primary_uses_negative_physical_coordinates(self, qtbot):
        o = make(qtbot, ov.RegionOverlay, [screen("D2", -1920, 0, 1920, 1080, 1.0), screen("D1", 0, 0, 1920, 1080, 1.0)])
        left = o.surfaces[0]
        assert left.to_phys(QPoint(100, 50)) == (-1820, 50)
        assert round(left.to_local(-1820, 50).x()) == 100

    def test_hide_and_delete_close_every_window(self, qtbot):
        o = make(qtbot, ov.RegionOverlay, two_screens())
        o.hide()
        assert not any(s.isVisible() for s in o.surfaces)
        o.deleteLater()


class TestCollectScreens:
    def test_describes_every_qt_screen_with_a_screenshot(self, qtbot):
        infos = ov.collect_screens([])
        assert len(infos) == len(QGuiApplication.screens()) >= 1
        for info in infos:
            assert info.ratio > 0 and not info.pixmap.isNull() and info.phys[2] > 0 and info.phys[3] > 0 and info.qscreen

    def test_matching_win32_monitor_gives_the_physical_rectangle(self, qtbot):
        name = QGuiApplication.screens()[0].name()
        mon = Monitor(name, -1920, 0, 2560, 1440, 150, True)
        assert ov.collect_screens([mon])[0].phys == (-1920, 0, 2560, 1440)

    def test_overlays_can_be_built_from_real_screens(self, qtbot):
        o = ov.RegionOverlay(phys=Cursor())
        qtbot.addWidget(o.surfaces[0])
        o.show()
        assert not o.surfaces[0].grab().isNull()
        o.hide()


# ------------------------------------------------------------------------------------------ chọn vùng
class TestRegionOverlay:
    def test_drag_emits_physical_pixel_region(self, qtbot):
        cur = Cursor()
        o = make(qtbot, ov.RegionOverlay, one_screen(1200, 600, 1.5), cursor=cur)
        got = []
        o.finished.connect(got.append)
        drag(qtbot, o, cur, o.surfaces[0], QPoint(100, 120), QPoint(500, 200))
        assert got == [{"left": 150, "top": 180, "width": 600, "height": 120}]  # pixel vật lý, không phải pixel Qt

    def test_drag_any_direction_normalises(self, qtbot):
        cur = Cursor()
        o = make(qtbot, ov.RegionOverlay, one_screen(), cursor=cur)
        got = []
        o.finished.connect(got.append)
        drag(qtbot, o, cur, o.surfaces[0], QPoint(500, 300), QPoint(100, 120))
        assert got == [{"left": 100, "top": 120, "width": 400, "height": 180}]

    def test_tiny_drag_is_rejected_and_overlay_stays_open(self, qtbot):
        cur = Cursor()
        o = make(qtbot, ov.RegionOverlay, one_screen(), cursor=cur)
        got = []
        o.finished.connect(got.append)
        drag(qtbot, o, cur, o.surfaces[0], QPoint(100, 100), QPoint(120, 110))
        assert got == [] and o.last_rejected and o.surfaces[0].isVisible()
        o.surfaces[0].grab()  # vẽ lại với gợi ý "quá nhỏ"
        drag(qtbot, o, cur, o.surfaces[0], QPoint(100, 100), QPoint(400, 200))
        assert len(got) == 1

    @pytest.mark.parametrize("which", [0, 1])
    def test_escape_cancels_from_any_screen(self, qtbot, which):
        o = make(qtbot, ov.RegionOverlay, two_screens())
        with qtbot.waitSignal(o.cancelled, timeout=1000):
            qtbot.keyClick(o.surfaces[which], Qt.Key.Key_Escape)

    def test_right_click_is_ignored(self, qtbot):
        cur = Cursor()
        o = make(qtbot, ov.RegionOverlay, one_screen(), cursor=cur)
        got = []
        o.finished.connect(got.append)
        qtbot.mousePress(o.surfaces[0], Qt.MouseButton.RightButton, pos=QPoint(10, 10))
        qtbot.mouseRelease(o.surfaces[0], Qt.MouseButton.RightButton, pos=QPoint(300, 300))
        assert got == []

    def test_paints_selection_magnifier_and_hint_without_error(self, qtbot):
        cur = Cursor()
        o = make(qtbot, ov.RegionOverlay, two_screens(), cursor=cur)
        s = o.surfaces[1]
        qtbot.mousePress(s, Qt.MouseButton.LeftButton, pos=cur.put(s, QPoint(100, 100)))
        QTest.mouseMove(s, cur.put(s, QPoint(400, 250)))
        assert not s.grab().isNull() and not o.surfaces[0].grab().isNull()

    def test_falls_back_to_scaled_logical_position_when_cursor_api_fails(self, qtbot):
        o = make(qtbot, ov.RegionOverlay, one_screen(1200, 600, 1.5), cursor=lambda: None)
        assert o.physical(o.surfaces[0], QPoint(100, 100)) == (150, 150)

    def test_fallback_drag_still_produces_a_region(self, qtbot):
        o = make(qtbot, ov.RegionOverlay, one_screen(1200, 600, 1.5), cursor=lambda: None)
        s, got = o.surfaces[0], []
        o.finished.connect(got.append)
        qtbot.mousePress(s, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        qtbot.mouseRelease(s, Qt.MouseButton.LeftButton, pos=QPoint(500, 300))
        assert got == [{"left": 150, "top": 150, "width": 600, "height": 300}]


class TestRegionOnSecondMonitor:
    """Yêu cầu chính: chọn vùng trên màn hình PHỤ có DPI khác màn hình chính vẫn ra đúng pixel vật lý."""

    def test_drag_on_the_second_screen_uses_that_screens_origin_and_ratio(self, qtbot):
        cur = Cursor()
        o = make(qtbot, ov.RegionOverlay, two_screens(), cursor=cur)
        got = []
        o.finished.connect(got.append)
        drag(qtbot, o, cur, o.surfaces[1], QPoint(100, 100), QPoint(700, 300))
        assert got == [{"left": 2070, "top": 150, "width": 900, "height": 300}]

    def test_drag_on_the_first_screen_still_uses_its_own_ratio(self, qtbot):
        cur = Cursor()
        o = make(qtbot, ov.RegionOverlay, two_screens(), cursor=cur)
        got = []
        o.finished.connect(got.append)
        drag(qtbot, o, cur, o.surfaces[0], QPoint(80, 80), QPoint(480, 180))
        assert got == [{"left": 100, "top": 100, "width": 500, "height": 125}]

    def test_region_on_a_screen_left_of_the_primary_has_negative_left(self, qtbot):
        cur = Cursor()
        o = make(qtbot, ov.RegionOverlay, [screen("D2", -1920, 0, 1920, 1080, 1.0), screen("D1", 0, 0, 1920, 1080, 1.0)],
                 cursor=cur)
        got = []
        o.finished.connect(got.append)
        drag(qtbot, o, cur, o.surfaces[0], QPoint(300, 600), QPoint(900, 700))
        assert got == [{"left": -1620, "top": 600, "width": 600, "height": 100}]

    def test_drag_that_leaves_the_screen_is_clamped_to_the_start_screen(self, qtbot):
        """Kéo từ màn hình chính sang màn hình phụ: vùng Shop không được trải qua hai màn hình (DXGI và bộ cấu hình cần một màn hình)."""
        cur = Cursor()
        o = make(qtbot, ov.RegionOverlay, two_screens(), cursor=cur)
        a, got = o.surfaces[0], []
        o.finished.connect(got.append)
        qtbot.mousePress(a, Qt.MouseButton.LeftButton, pos=cur.put(a, QPoint(1000, 600)))
        cur.pos = (2600, 700)  # con trỏ đã sang màn hình phụ
        QTest.mouseMove(a, QPoint(1900, 700))
        qtbot.mouseRelease(a, Qt.MouseButton.LeftButton, pos=QPoint(1900, 700))
        assert got == [{"left": 1250, "top": 700, "width": 669, "height": 50}]  # dừng ở mép phải (1919) của màn hình chính

    def test_drag_below_the_screen_is_clamped_to_its_bottom_edge(self, qtbot):
        cur = Cursor()
        o = make(qtbot, ov.RegionOverlay, two_screens(), cursor=cur)
        s, got = o.surfaces[1], []
        o.finished.connect(got.append)
        qtbot.mousePress(s, Qt.MouseButton.LeftButton, pos=cur.put(s, QPoint(100, 800)))
        cur.pos = (2300, 5000)
        QTest.mouseMove(s, QPoint(300, 2000))
        qtbot.mouseRelease(s, Qt.MouseButton.LeftButton, pos=QPoint(300, 2000))
        (region,) = got
        assert region["top"] + region["height"] == 1439 and region["left"] == 2070

    def test_magnifier_is_drawn_only_on_the_screen_with_the_cursor(self, qtbot):
        cur = Cursor()
        o = make(qtbot, ov.RegionOverlay, two_screens(), cursor=cur)
        b = o.surfaces[1]
        QTest.mouseMove(b, cur.put(b, QPoint(500, 400)))
        assert o._mouse_surface is b and o._mouse_phys == (2670, 600)
        tag_x, tag_y = 500 + 24 + 3, 400 + 24 + 136 + 8  # trong nhãn tọa độ đen dưới kính lúp
        assert pixel(b, tag_x, tag_y) != pixel(o.surfaces[0], tag_x, tag_y)  # màn hình kia không có kính lúp


# ------------------------------------------------------------------------------------------ đặt 5 điểm click
class TestClickOverlay:
    REGION = {"left": 100, "top": 100, "width": 600, "height": 150}

    def make(self, qtbot, screens=None, region=None, cursor=None):
        region = region or self.REGION
        inside = lambda x, y: (region["left"] <= x < region["left"] + region["width"]  # noqa: E731
                               and region["top"] <= y < region["top"] + region["height"])
        return make(qtbot, ov.ClickOverlay, screens or one_screen(), region, inside, cursor=cursor)

    def click(self, qtbot, o, cur, x, y, which=0):
        s = o.surfaces[which]
        cur.pos = (x, y)
        qtbot.mouseClick(s, Qt.MouseButton.LeftButton, pos=s.to_local(x, y).toPoint())

    def test_five_clicks_finish_with_physical_points(self, qtbot):
        cur = Cursor()
        o = self.make(qtbot, cursor=cur)
        got = []
        o.finished.connect(got.append)
        pts = [(150 + i * 110, 170) for i in range(5)]
        for x, y in pts:
            self.click(qtbot, o, cur, x, y)
        assert got == [pts]

    def test_outside_click_is_rejected_with_a_message(self, qtbot):
        cur = Cursor()
        o = self.make(qtbot, cursor=cur)
        self.click(qtbot, o, cur, 10, 10)
        assert o.points == [] and "NGOÀI vùng Shop" in o.warning and "ô 1/5" in o.warning
        self.click(qtbot, o, cur, 200, 150)
        assert len(o.points) == 1 and o.warning == ""

    def test_backspace_removes_last_point(self, qtbot):
        cur = Cursor()
        o = self.make(qtbot, cursor=cur)
        self.click(qtbot, o, cur, 150, 150)
        self.click(qtbot, o, cur, 250, 150)
        qtbot.keyClick(o.surfaces[0], Qt.Key.Key_Backspace)
        assert o.points == [(150, 150)] and "ô 2/5" in o._hint()
        qtbot.keyClick(o.surfaces[0], Qt.Key.Key_Backspace)
        qtbot.keyClick(o.surfaces[0], Qt.Key.Key_Backspace)  # hết điểm: không lỗi
        assert o.points == []

    def test_escape_cancels_and_paint_with_points_works(self, qtbot):
        cur = Cursor()
        o = self.make(qtbot, cursor=cur)
        self.click(qtbot, o, cur, 150, 150)
        assert not o.surfaces[0].grab().isNull()
        with qtbot.waitSignal(o.cancelled, timeout=1000):
            qtbot.keyClick(o.surfaces[0], Qt.Key.Key_Escape)

    def test_points_on_the_second_screen_are_collected_and_drawn_only_there(self, qtbot):
        region = {"left": 2000, "top": 200, "width": 1200, "height": 300}
        cur = Cursor()
        o = self.make(qtbot, two_screens(), region, cur)
        got = []
        o.finished.connect(got.append)
        pts = [(2100 + i * 200, 350) for i in range(5)]
        for x, y in pts[:2]:
            self.click(qtbot, o, cur, x, y, which=1)
        a, b = o.surfaces
        assert dot(b, pts[0]) == RED and dot(b, pts[1]) == RED  # chấm đỏ nằm đúng chỗ trên màn hình phụ
        assert RED not in colors(a)
        for x, y in pts[2:]:
            self.click(qtbot, o, cur, x, y, which=1)
        assert got == [pts]

    def test_region_frame_is_drawn_in_the_right_place_on_each_screen(self, qtbot):
        region = {"left": 2000, "top": 200, "width": 1200, "height": 300}
        o = self.make(qtbot, two_screens(), region)
        a, b = o.surfaces
        rect = o.region_rect_local(b, region)
        assert pixel(b, rect.left(), rect.center().y()) == GREEN
        assert GREEN not in colors(a)


# ------------------------------------------------------------------------------------------ xem trên màn hình thật
class TestViewOverlay:
    REGION = {"left": 2000, "top": 200, "width": 1200, "height": 300}
    CENTERS = [(2100 + i * 220, 350) for i in range(5)]

    def make(self, qtbot, confirm=False, centers=None, screens=None):
        return make(qtbot, ov.ViewOverlay, screens or two_screens(), self.REGION,
                    self.CENTERS if centers is None else centers, "Màn hình 2", confirm)

    def test_click_anywhere_closes(self, qtbot):
        o = self.make(qtbot)
        with qtbot.waitSignal(o.cancelled, timeout=1000):
            qtbot.mouseClick(o.surfaces[0], Qt.MouseButton.LeftButton, pos=QPoint(50, 50))

    def test_click_on_the_other_screen_also_closes(self, qtbot):
        o = self.make(qtbot)
        with qtbot.waitSignal(o.cancelled, timeout=1000):
            qtbot.mouseClick(o.surfaces[1], Qt.MouseButton.RightButton, pos=QPoint(900, 500))

    def test_escape_closes(self, qtbot):
        o = self.make(qtbot)
        with qtbot.waitSignal(o.cancelled, timeout=1000):
            qtbot.keyClick(o.surfaces[1], Qt.Key.Key_Escape)

    def test_enter_does_nothing_when_not_asking_for_confirmation(self, qtbot):
        o = self.make(qtbot)
        got = []
        o.finished.connect(got.append)
        qtbot.keyClick(o.surfaces[0], Qt.Key.Key_Return)
        assert got == []

    @pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
    def test_confirm_mode_accepts_with_enter_or_space(self, qtbot, key):
        o = self.make(qtbot, confirm=True)
        with qtbot.waitSignal(o.finished, timeout=1000) as sig:
            qtbot.keyClick(o.surfaces[1], key)
        assert sig.args == [True]

    def test_confirm_mode_click_declines(self, qtbot):
        o = self.make(qtbot, confirm=True)
        got = []
        o.finished.connect(got.append)
        with qtbot.waitSignal(o.cancelled, timeout=1000):
            qtbot.mouseClick(o.surfaces[1], Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        assert got == []

    def test_hint_tells_what_the_keys_do(self, qtbot):
        assert "Enter" in self.make(qtbot, confirm=True)._hint()
        assert "Esc" in self.make(qtbot)._hint() and "Enter" not in self.make(qtbot)._hint()

    def test_draws_frame_and_five_numbered_dots_on_the_screen_that_holds_them(self, qtbot):
        o = self.make(qtbot)
        a, b = o.surfaces
        rect = o.region_rect_local(b, self.REGION)
        assert pixel(b, rect.left(), rect.center().y()) == GREEN
        assert [dot(b, c) for c in self.CENTERS] == [RED] * 5
        assert GREEN not in colors(a) and RED not in colors(a)

    def test_dots_follow_the_screen_ratio(self, qtbot):
        """Cùng một điểm vật lý nhưng màn hình có DPI khác → vị trí cửa sổ khác, vẫn đúng chỗ trên ảnh chụp của màn hình đó."""
        for ratio in (1.0, 1.5, 2.0):
            screens = [screen("D", 0, 0, 1200, 600, ratio)]
            o = make(qtbot, ov.ViewOverlay, screens, {"left": 200, "top": 100, "width": 800, "height": 200},
                     [(300, 200)] * 5, "", False)
            s = o.surfaces[0]
            p = s.to_local(300, 200)
            assert (round(p.x()), round(p.y())) == (round(300 / ratio), round(200 / ratio))
            assert dot(s, (300, 200)) == RED

    def test_without_click_points_it_says_so_and_draws_no_dots(self, qtbot):
        o = self.make(qtbot, centers=[])
        b = o.surfaces[1]
        assert not b.grab().isNull()
        assert RED not in colors(b, 10)

    def test_region_on_a_screen_with_negative_coordinates(self, qtbot):
        screens = [screen("L", -1920, 0, 1920, 1080, 1.0), screen("R", 0, 0, 1920, 1080, 1.0)]
        o = make(qtbot, ov.ViewOverlay, screens, {"left": -1500, "top": 700, "width": 1000, "height": 200},
                 [(-1400 + i * 150, 800) for i in range(5)], "", False)
        left = o.surfaces[0]
        rect = o.region_rect_local(left, {"left": -1500, "top": 700, "width": 1000, "height": 200})
        assert (rect.left(), rect.top()) == (420, 700) and pixel(left, rect.left(), rect.center().y()) == GREEN
        assert dot(left, (-1400, 800)) == RED
