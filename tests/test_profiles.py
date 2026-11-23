"""Bộ cấu hình theo màn hình: tạo/kiểm tra, dịch chỗ khi sắp xếp lại màn hình, quy đổi khi đổi độ phân giải, chọn bộ gần nhất."""

import pytest

import core.profiles as pr
from core.monitors import Monitor

FHD = Monitor(r"\\.\DISPLAY1", 0, 0, 1920, 1080, 100, True)
QHD = Monitor(r"\\.\DISPLAY2", 1920, 0, 2560, 1440, 150)
ULTRA = Monitor(r"\\.\DISPLAY3", 0, 0, 3440, 1440, 100)
REGION = {"left": 360, "top": 900, "width": 1200, "height": 160}  # hàng shop giữa-đáy màn hình 1080p
CENTERS = [(450 + i * 230, 1000) for i in range(5)]


def inside(region, point):
    return (region["left"] <= point[0] < region["left"] + region["width"]
            and region["top"] <= point[1] < region["top"] + region["height"])


class TestProfile:
    def test_make_profile_keeps_everything_needed_to_restore_it(self):
        p = pr.make_profile(FHD, REGION, CENTERS)
        assert p["monitor"] == FHD.rect and p["shop_region"] == REGION and p["name"] == FHD.label()
        assert p["slot_centers"] == [list(c) for c in CENTERS] and pr.valid_profile(p)

    def test_make_profile_accepts_no_points_yet(self):
        assert pr.valid_profile(pr.make_profile(FHD, REGION, []))

    @pytest.mark.parametrize("break_it", [
        lambda p: p.pop("monitor"),
        lambda p: p.pop("shop_region"),
        lambda p: p.pop("slot_centers"),
        lambda p: p["monitor"].update(width=0),
        lambda p: p["shop_region"].update(height=-5),
        lambda p: p["shop_region"].update(left="1"),
        lambda p: p["slot_centers"].pop(),  # 4 điểm
        lambda p: p["slot_centers"].__setitem__(0, [1]),
        lambda p: p["slot_centers"].__setitem__(0, [1.5, 2]),
        lambda p: p["monitor"].update(left=True),
    ])
    def test_invalid_profiles_are_rejected(self, break_it):
        p = pr.make_profile(FHD, REGION, CENTERS)
        break_it(p)
        assert not pr.valid_profile(p)

    @pytest.mark.parametrize("junk", [None, 5, "x", [], {}, {"monitor": 1}])
    def test_non_profiles_are_rejected(self, junk):
        assert not pr.valid_profile(junk)


class TestTranslate:
    def test_moves_region_and_points_together(self):
        region, pts = pr.translate(REGION, [list(c) for c in CENTERS], 1920, -40)
        assert region == {"left": 2280, "top": 860, "width": 1200, "height": 160}
        assert pts[0] == [2370, 960] and len(pts) == 5

    def test_input_is_not_mutated(self):
        original = dict(REGION)
        pr.translate(REGION, [list(c) for c in CENTERS], 5, 5)
        assert REGION == original


class TestRescale:
    def test_same_aspect_ratio_scales_every_coordinate_exactly(self):
        old, new = FHD.rect, {"left": 0, "top": 0, "width": 2560, "height": 1440}
        region, pts = pr.rescale(old, new, REGION, [list(c) for c in CENTERS])
        s = 1440 / 1080
        # cùng tỉ lệ khung hình nên đây cũng chính là nhân đều mọi tọa độ (lề trái/phải bằng nhau nên quanh điểm giữa vẫn khớp)
        assert region == {"left": round(360 * s), "top": round(900 * s), "width": round(1560 * s) - round(360 * s),
                          "height": round(1060 * s) - round(900 * s)}
        assert pts[0] == [round(450 * s), round(1000 * s)] and pts[4] == [round(1370 * s), round(1000 * s)]

    def test_points_stay_inside_the_scaled_region(self):
        for target in (QHD, ULTRA, Monitor("d", 0, 0, 1280, 720), Monitor("d", 0, 0, 3840, 2160)):
            region, pts = pr.rescale(FHD.rect, target.rect, REGION, [list(c) for c in CENTERS])
            assert all(inside(region, p) for p in pts), (target, region, pts)

    def test_result_never_leaves_the_new_monitor(self):
        for target in (QHD, ULTRA, Monitor("d", -1280, 100, 1280, 1024), Monitor("d", 0, 0, 1366, 768)):
            region, pts = pr.rescale(FHD.rect, target.rect, REGION, [list(c) for c in CENTERS])
            r = target.rect
            assert r["left"] <= region["left"] and r["top"] <= region["top"]
            assert region["left"] + region["width"] <= r["left"] + r["width"]
            assert region["top"] + region["height"] <= r["top"] + r["height"]
            assert region["width"] >= 1 and region["height"] >= 1

    def test_ultrawide_keeps_the_shop_centred_and_at_the_bottom(self):
        """Giao diện game co theo chiều CAO và neo giữa-đáy: màn hình 21:9 cùng chiều cao thì hàng shop vẫn ở giữa, không bị kéo giãn."""
        full_hd_wide = Monitor("d", 0, 0, 3440, 1080)
        region, pts = pr.rescale(FHD.rect, full_hd_wide.rect, REGION, [list(c) for c in CENTERS])
        assert region["width"] == REGION["width"] and region["height"] == REGION["height"]  # cùng chiều cao → không đổi cỡ
        assert region["left"] + region["width"] / 2 == pytest.approx(3440 / 2, abs=1)  # vẫn ở giữa
        assert region["top"] + region["height"] == REGION["top"] + REGION["height"]  # cùng khoảng cách tới đáy

    def test_shop_stays_centred_when_resolution_changes(self):
        region, _ = pr.rescale(FHD.rect, QHD.rect, REGION, [list(c) for c in CENTERS])
        assert region["left"] + region["width"] / 2 - QHD.left == pytest.approx(QHD.width / 2, abs=2)

    def test_offset_monitor_origin_is_respected(self):
        a, _ = pr.rescale(FHD.rect, {"left": 0, "top": 0, "width": 2560, "height": 1440}, REGION, [list(c) for c in CENTERS])
        b, _ = pr.rescale(FHD.rect, QHD.rect, REGION, [list(c) for c in CENTERS])
        assert b["left"] - a["left"] == QHD.left and b["top"] == a["top"]

    def test_downscale(self):
        region, pts = pr.rescale(FHD.rect, {"left": 0, "top": 0, "width": 1280, "height": 720}, REGION, [list(c) for c in CENTERS])
        assert region["width"] < REGION["width"] and all(inside(region, p) for p in pts)

    def test_no_points_gives_no_points(self):
        assert pr.rescale(FHD.rect, QHD.rect, REGION, [])[1] == []


class TestAdapt:
    PROFILE = pr.make_profile(FHD, REGION, CENTERS)

    def test_same_monitor_is_returned_unchanged(self):
        region, pts, how = pr.adapt(self.PROFILE, FHD)
        assert how == "same" and region == REGION and pts == [list(c) for c in CENTERS]

    def test_scale_percent_change_alone_changes_nothing(self):
        """Đổi % scale của Windows không đổi pixel vật lý, nên tọa độ vẫn đúng."""
        assert pr.adapt(self.PROFILE, Monitor(FHD.device, 0, 0, 1920, 1080, 150))[2] == "same"

    def test_monitor_moved_on_the_desktop_translates_exactly(self):
        moved = Monitor(FHD.device, 1920, 200, 1920, 1080)
        region, pts, how = pr.adapt(self.PROFILE, moved)
        assert how == "moved" and region["left"] == 360 + 1920 and region["top"] == 900 + 200
        assert pts[0] == [450 + 1920, 1000 + 200]

    def test_different_resolution_is_only_an_estimate(self):
        region, pts, how = pr.adapt(self.PROFILE, QHD)
        assert how == "scaled" and all(inside(region, p) for p in pts)

    def test_profile_is_not_mutated(self):
        before = pr.make_profile(FHD, REGION, CENTERS)
        pr.adapt(before, QHD)
        assert before == pr.make_profile(FHD, REGION, CENTERS)


class TestNearest:
    def profiles(self):
        return {
            FHD.key: pr.make_profile(FHD, REGION, CENTERS),
            QHD.key: pr.make_profile(QHD, REGION, CENTERS),
        }

    def test_none_when_nothing_saved(self):
        assert pr.nearest({}, FHD) is None

    def test_same_size_wins_even_on_another_device(self):
        other = Monitor(r"\\.\DISPLAY9", 0, 0, 1920, 1080)
        key, _ = pr.nearest(self.profiles(), other)
        assert key == FHD.key

    def test_prefers_same_aspect_ratio(self):
        target = Monitor(r"\\.\DISPLAY5", 0, 0, 3840, 2160)  # 16:9, như cả hai bộ; chọn bộ gần diện tích hơn
        key, _ = pr.nearest(self.profiles(), target)
        assert key == QHD.key

    def test_ultrawide_gets_the_closest_ratio_then_area(self):
        profiles = {**self.profiles(), ULTRA.key: pr.make_profile(ULTRA, REGION, CENTERS)}
        key, _ = pr.nearest(profiles, Monitor(r"\\.\DISPLAY7", 0, 0, 2560, 1080))  # 21:9
        assert key == ULTRA.key

    def test_prefers_same_device_when_otherwise_equal(self):
        a = Monitor(r"\\.\DISPLAY1", 0, 0, 1600, 900)
        b = Monitor(r"\\.\DISPLAY2", 0, 0, 1600, 900)
        profiles = {a.key: pr.make_profile(a, REGION, []), b.key: pr.make_profile(b, REGION, [])}
        assert pr.nearest(profiles, Monitor(r"\\.\DISPLAY2", 0, 0, 1280, 720))[0] == b.key

    def test_ignores_invalid_profiles(self):
        profiles = {"junk": {"monitor": 1}, FHD.key: pr.make_profile(FHD, REGION, CENTERS)}
        assert pr.nearest(profiles, QHD)[0] == FHD.key

    def test_returns_a_copy(self):
        profiles = self.profiles()
        _, p = pr.nearest(profiles, QHD)
        p["shop_region"]["left"] = -1
        assert profiles[FHD.key]["shop_region"]["left"] == 360
