import os
import threading
import time

import numpy as np
import pytest

from core import config
from core import preview as pv
from tests.helpers import make_card

REGION = {"left": 100, "top": 50, "width": 400, "height": 120}
C1 = [(140 + i * 70, 110) for i in range(5)]  # điểm click kiểu 1 (trong vùng)
C2 = [(140 + i * 70, 150) for i in range(5)]  # người dùng đặt lại sang hàng khác


def clean_frame(seed=1):
    """Ảnh chụp giả 120x400 BGR không có đỏ/xanh lá thuần (để dễ kiểm tra chấm và viền)."""
    base = make_card(seed, size=(REGION["width"], REGION["height"]))
    return np.clip(base.astype(np.int16) * 0.5 + 60, 60, 160).astype(np.uint8)


def is_red_dot(img, center):
    """Có chấm đỏ #ef4444 tại điểm click `center` (tọa độ màn hình) không?"""
    rx, ry = center[0] - REGION["left"], center[1] - REGION["top"]
    r, g, b = img.convert("RGB").getpixel((rx, ry))
    return abs(r - 239) + abs(g - 68) + abs(b - 68) < 40


@pytest.fixture
def capture(monkeypatch):
    """Điều khiển ảnh mà 'màn hình' trả về: capture.frame = ndarray hoặc None (chụp lỗi)."""
    state = types_ns(frame=clean_frame(), calls=0)

    def fake(region):
        state.calls += 1
        return None if state.frame is None else state.frame.copy()

    monkeypatch.setattr(pv, "capture_shop_region", fake)
    return state


def types_ns(**kw):
    import types

    return types.SimpleNamespace(**kw)


class TestAnnotate:
    def test_dots_at_every_click_point_and_a_border(self):
        img = pv.annotate_preview(clean_frame(), REGION, C1)
        assert all(is_red_dot(img, c) for c in C1)
        assert img.getpixel((0, 60)) == (34, 197, 94)  # viền xanh #22c55e

    def test_no_dots_elsewhere(self):
        img = pv.annotate_preview(clean_frame(), REGION, C1)
        assert not any(is_red_dot(img, c) for c in C2)

    def test_does_not_modify_the_input_frame(self):
        frame = clean_frame()
        before = frame.copy()
        pv.annotate_preview(frame, REGION, C1)
        assert np.array_equal(frame, before)

    def test_without_click_points_only_the_border_is_drawn(self):
        img = pv.annotate_preview(clean_frame(), REGION, None)
        assert not any(is_red_dot(img, c) for c in C1 + C2)
        assert img.getpixel((0, 60)) == (34, 197, 94)

    def test_without_region_no_dots(self):
        img = pv.annotate_preview(clean_frame(), None, C1)
        assert not any(is_red_dot(img, c) for c in C1)

    def test_points_outside_the_image_are_skipped_not_crashing(self):
        pts = [(0, 0), (9999, 9999), (-50, 70), (140, 110), (210, 10**6)]
        img = pv.annotate_preview(clean_frame(), REGION, pts)
        assert is_red_dot(img, (140, 110))

    def test_a_point_just_outside_the_image_draws_nothing_not_even_a_partial_dot(self):
        """Điểm cách biên 2 px (nhỏ hơn bán kính chấm) vẫn phải bị bỏ, không vẽ nửa chấm sát mép ảnh."""
        just_outside = [(REGION["left"] - 2, REGION["top"] + 60)]
        img = pv.annotate_preview(clean_frame(), REGION, just_outside)
        assert img.getpixel((0, 60)) == (34, 197, 94)  # vẫn là viền xanh, không bị chấm đỏ đè lên

    def test_stale_dots_cannot_appear_because_marks_always_start_from_a_clean_frame(self):
        """Lỗi cũ: vẽ chấm kiểu 1, lưu, rồi vẽ kiểu 2 lên chính ảnh đó → có cả hai bộ chấm."""
        frame = clean_frame()
        pv.annotate_preview(frame, REGION, C1)
        img2 = pv.annotate_preview(frame, REGION, C2)
        assert all(is_red_dot(img2, c) for c in C2) and not any(is_red_dot(img2, c) for c in C1)


class TestSaveAndLoad:
    def test_roundtrip_is_lossless(self, data_dir):
        frame = clean_frame()
        pv.save_capture(frame)
        loaded, stamp = pv.load_capture()
        assert np.array_equal(loaded, frame) and (time.time() - stamp.timestamp()) < 30

    def test_missing_file(self, data_dir):
        assert pv.load_capture() is None

    @pytest.mark.parametrize("content", [b"", b"khong phai anh", b"\x89PNG\r\n\x1a\n" + b"x" * 20])
    def test_corrupt_or_empty_file_is_none_not_an_exception(self, data_dir, content):
        config.ensure_dirs()
        config.SHOP_CAPTURE_PATH.write_bytes(content)
        assert pv.load_capture() is None

    def test_path_with_accents(self, tmp_path, monkeypatch):
        folder = tmp_path / "Nguyễn Văn Á" / "data"
        folder.mkdir(parents=True)
        monkeypatch.setattr(config, "DATA_DIR", folder)
        monkeypatch.setattr(config, "TEMPLATES_DIR", folder / "templates")
        monkeypatch.setattr(config, "SHOP_CAPTURE_PATH", folder / "shop_capture.png")
        monkeypatch.setattr(config, "LEGACY_SHOP_PREVIEW_PATH", folder / "shop_preview.png")
        frame = clean_frame()
        pv.save_capture(frame)
        assert np.array_equal(pv.load_capture()[0], frame)

    def test_replace_is_retried_while_a_reader_holds_the_file_open(self, data_dir, monkeypatch):
        """Windows: thay file đang bị luồng khác mở để đọc → PermissionError tạm thời. Phải thử lại, không bỏ cuộc."""
        pv.save_capture(clean_frame(1))
        real, fails = os.replace, {"n": 3}

        def flaky(src, dst):
            if fails["n"] > 0:
                fails["n"] -= 1
                raise PermissionError("[WinError 5] Access is denied")
            return real(src, dst)

        monkeypatch.setattr(pv.os, "replace", flaky)
        new = clean_frame(2)
        pv.save_capture(new)
        assert fails["n"] == 0 and np.array_equal(pv.load_capture()[0], new)

    def test_read_is_retried_when_the_file_is_momentarily_locked(self, data_dir, monkeypatch):
        """Đúng lúc file đang được thay, mở để đọc báo PermissionError thoáng qua (đo thật: 88 lần trong 240 lần ghi)."""
        frame = clean_frame(1)
        pv.save_capture(frame)
        real, fails = pv._read_file, {"n": 2}

        def flaky(path):
            if fails["n"] > 0:
                fails["n"] -= 1
                raise PermissionError("[Errno 13] Permission denied")
            return real(path)

        monkeypatch.setattr(pv, "_read_file", flaky)
        got = pv.load_capture()
        assert got is not None and np.array_equal(got[0], frame) and fails["n"] == 0

    def test_read_gives_up_with_none_if_the_lock_never_clears(self, data_dir, monkeypatch):
        pv.save_capture(clean_frame(1))
        monkeypatch.setattr(pv, "_REPLACE_WAIT_S", 0.0)

        def locked(path):
            raise PermissionError("khóa mãi")

        monkeypatch.setattr(pv, "_read_file", locked)
        assert pv.load_capture() is None

    def test_missing_file_is_not_retried(self, data_dir, monkeypatch):
        calls = []
        real = pv._read_file

        def counting(path):
            calls.append(1)
            return real(path)

        monkeypatch.setattr(pv, "_read_file", counting)
        assert pv.load_capture() is None and len(calls) == 1

    def test_permission_error_that_never_clears_is_finally_raised(self, data_dir, monkeypatch):
        monkeypatch.setattr(pv, "_REPLACE_WAIT_S", 0.0)
        calls = []

        def locked(src, dst):
            calls.append(1)
            raise PermissionError("khóa mãi")

        monkeypatch.setattr(pv.os, "replace", locked)
        with pytest.raises(PermissionError):
            pv.save_capture(clean_frame(1))
        assert len(calls) == pv._REPLACE_TRIES and not list(data_dir.glob("*.part"))

    def test_failed_replace_keeps_the_previous_capture_and_leaves_no_temp_file(self, data_dir, monkeypatch):
        old = clean_frame(1)
        pv.save_capture(old)

        def boom(src, dst):
            raise OSError("ngắt giữa chừng")

        monkeypatch.setattr(pv.os, "replace", boom)
        with pytest.raises(OSError):
            pv.save_capture(clean_frame(2))
        assert np.array_equal(pv.load_capture()[0], old)
        assert not list(data_dir.glob("*.part"))

    def test_each_thread_writes_its_own_temp_file(self, data_dir, monkeypatch):
        """Hai thread ghi cùng lúc mà dùng chung 1 file tạm thì ghi đè lẫn nhau → ảnh hỏng. Tên tạm phải riêng từng thread."""
        names = []
        real = pv._replace_with_retry

        def spy(src, dst):
            names.append(str(src))
            return real(src, dst)

        monkeypatch.setattr(pv, "_replace_with_retry", spy)
        pv.save_capture(clean_frame(1))
        t = threading.Thread(target=lambda: pv.save_capture(clean_frame(2)))
        t.start()
        t.join()
        assert len(names) == 2 and names[0] != names[1] and all(n.endswith(".part") for n in names)

    def test_no_temp_files_remain_after_saving(self, data_dir):
        for i in range(5):
            pv.save_capture(clean_frame(i))
        assert [p.name for p in data_dir.iterdir() if p.is_file()] == ["shop_capture.png"]

    def test_saving_removes_the_legacy_annotated_preview(self, data_dir):
        config.ensure_dirs()
        config.LEGACY_SHOP_PREVIEW_PATH.write_bytes(b"anh cu da ve cham")
        pv.save_capture(clean_frame())
        assert not config.LEGACY_SHOP_PREVIEW_PATH.exists()

    def test_concurrent_writers_never_expose_a_half_written_file(self, data_dir):
        """Tái hiện lỗi gốc: 2 thread ghi liên tục + 1 thread đọc liên tục. Trước đây ~13% lần đọc gặp ảnh ghi dở."""
        frames = [clean_frame(1), clean_frame(2)]
        pv.save_capture(frames[0])  # đã có file → mọi lần đọc sau đó đều phải thành công
        bad, reads, stop = [], [0], threading.Event()

        def reader():
            while not stop.is_set():
                reads[0] += 1
                got = pv.load_capture()
                if got is None or not any(np.array_equal(got[0], f) for f in frames):
                    bad.append(1)

        def writer(i):
            for _ in range(120):
                pv.save_capture(frames[i])

        rt = threading.Thread(target=reader)
        rt.start()
        ws = [threading.Thread(target=writer, args=(i,)) for i in (0, 1)]
        [w.start() for w in ws]
        [w.join() for w in ws]
        stop.set()
        rt.join()
        assert reads[0] > 50 and bad == []
        assert not list(data_dir.glob("*.part"))


class TestBuild:
    def test_live_capture_saves_the_clean_frame_and_returns_marked_image(self, data_dir, capture):
        r = pv.build_shop_preview(REGION, C1, capture_live=True)
        assert r.live and r.note == "" and r.captured_at is not None
        assert all(is_red_dot(r.image, c) for c in C1)
        assert np.array_equal(pv.load_capture()[0], capture.frame)  # file chỉ có ảnh sạch

    def test_saved_file_has_no_marks_even_after_many_refreshes_with_changing_points(self, data_dir, capture):
        pv.build_shop_preview(REGION, C1)
        pv.build_shop_preview(REGION, C2)
        assert np.array_equal(pv.load_capture()[0], capture.frame)

    def test_capture_failure_shows_last_clean_frame_with_CURRENT_points_only(self, data_dir, capture):
        pv.build_shop_preview(REGION, C1)  # lần trước chụp được, điểm click kiểu 1
        capture.frame = None  # màn hình bị khóa / UAC
        r = pv.build_shop_preview(REGION, C2, capture_live=True)
        assert not r.live and "ảnh lần trước" in r.note and r.captured_at is not None
        assert all(is_red_dot(r.image, c) for c in C2)
        assert not any(is_red_dot(r.image, c) for c in C1), "chấm cũ không được còn lại"

    def test_repeated_failures_do_not_rewrite_the_saved_file(self, data_dir, capture):
        pv.build_shop_preview(REGION, C1)
        before = config.SHOP_CAPTURE_PATH.read_bytes()
        mtime = config.SHOP_CAPTURE_PATH.stat().st_mtime_ns
        capture.frame = None
        for pts in (C1, C2, C1):
            pv.build_shop_preview(REGION, pts)
        assert config.SHOP_CAPTURE_PATH.read_bytes() == before and config.SHOP_CAPTURE_PATH.stat().st_mtime_ns == mtime

    def test_failure_with_nothing_saved_returns_no_image_and_says_why(self, data_dir, capture):
        capture.frame = None
        r = pv.build_shop_preview(REGION, C1)
        assert r.image is None and "chưa có ảnh nào được lưu" in r.note

    def test_startup_load_shows_the_saved_frame_with_a_note(self, data_dir, capture):
        pv.build_shop_preview(REGION, C1)
        capture.calls = 0
        r = pv.build_shop_preview(REGION, C2, capture_live=False)
        assert r.image is not None and not r.live and r.note == "Ảnh chụp lần trước."
        assert capture.calls == 0  # lúc mở app không chụp màn hình
        assert all(is_red_dot(r.image, c) for c in C2)

    def test_startup_with_nothing_saved_is_silent(self, data_dir, capture):
        r = pv.build_shop_preview(REGION, C1, capture_live=False)
        assert r.image is None and r.note == ""

    def test_saved_frame_of_another_region_is_not_shown(self, data_dir, capture):
        pv.build_shop_preview(REGION, C1)
        other = {**REGION, "width": 500}
        startup = pv.build_shop_preview(other, None, capture_live=False)
        assert startup.image is None and startup.note == ""
        capture.frame = None
        failed = pv.build_shop_preview(other, None, capture_live=True)
        assert failed.image is None and "vùng Shop khác" in failed.note

    def test_disk_error_while_saving_still_shows_the_fresh_capture(self, data_dir, capture, monkeypatch):
        def boom(src, dst):
            raise PermissionError("bị khóa")

        monkeypatch.setattr(pv.os, "replace", boom)
        r = pv.build_shop_preview(REGION, C1)
        assert r.live and r.image is not None and "Không lưu được ảnh" in r.note

    def test_legacy_annotated_file_is_never_used_as_a_fallback(self, data_dir, capture):
        """File cũ đã vẽ chấm (tên shop_preview.png) không được dùng làm ảnh dự phòng nữa."""
        config.ensure_dirs()
        pv.annotate_preview(clean_frame(), REGION, C1).save(config.LEGACY_SHOP_PREVIEW_PATH)
        capture.frame = None
        r = pv.build_shop_preview(REGION, C2)
        assert r.image is None


def test_real_screen_capture_feeds_the_whole_pipeline(data_dir):
    """Chụp màn hình THẬT (bỏ qua nếu không có display): chụp → lưu sạch → đọc lại → vẽ chấm."""
    region = {"left": 0, "top": 0, "width": 320, "height": 100}
    if pv.capture_shop_region(region) is None:
        pytest.skip("không chụp được màn hình")
    centers = [(30 + i * 60, 60) for i in range(5)]
    r = pv.build_shop_preview(region, centers, capture_live=True)
    assert r.live and r.image.size == (320, 100)
    saved, _ = pv.load_capture()
    assert saved.shape == (100, 320, 3) and not os.path.exists(config.LEGACY_SHOP_PREVIEW_PATH)
