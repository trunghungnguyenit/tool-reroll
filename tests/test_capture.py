"""Chụp DXGI với dự phòng mss: chọn đúng màn hình, tự kiểm tra, tự quay về mss, và tích hợp vào scanner."""

import threading
import types

import numpy as np
import pytest

import core.capture as cap
import core.scanner as sc

REGION = {"left": 2000, "top": 100, "width": 400, "height": 80}  # nằm trên màn hình thứ hai (x từ 1920)


def frame(value=100, h=80, w=400):
    return np.full((h, w, 3), value, np.uint8)


def rect(left, top, right, bottom):
    return types.SimpleNamespace(left=left, top=top, right=right, bottom=bottom)


class FakeCam:
    def __init__(self, coords, frames):
        self._output = types.SimpleNamespace(desc=types.SimpleNamespace(DesktopCoordinates=rect(*coords)))
        self.frames = list(frames)
        self.released = False
        self.grabs = []

    def grab(self, region=None, new_frame_only=True, copy=True):
        self.grabs.append((region, new_frame_only))
        if not self.frames:
            return None
        return self.frames[0] if len(self.frames) == 1 else self.frames.pop(0)

    def release(self):
        self.released = True


class FakeDx:
    """Hai adapter, mỗi adapter một màn hình 1920x1080: adapter 0 ở x 0..1920, adapter 1 ở x 1920..3840."""

    def __init__(self, frames=None, layout=((0, 0, 1920, 1080), (1920, 0, 3840, 1080))):
        self.layout = layout
        self.frames = frames if frames is not None else [frame(100)]
        self.cameras: list[FakeCam] = []
        self.create_calls = []

    def create(self, device_idx=0, output_idx=0, output_color="RGB", **kw):
        self.create_calls.append((device_idx, output_idx, output_color))
        if output_idx != 0 or device_idx >= len(self.layout):
            raise IndexError("không có output")
        cam = FakeCam(self.layout[device_idx], self.frames)
        self.cameras.append(cam)
        return cam


def no_sleep(_):
    pass


class TestMeanAbsDiff:
    def test_identical_and_different(self):
        assert cap.mean_abs_diff(frame(50), frame(50)) == 0.0
        assert cap.mean_abs_diff(frame(50), frame(80)) == 30.0

    def test_different_shapes_are_completely_different(self):
        assert cap.mean_abs_diff(frame(50), frame(50, h=40)) == 255.0
        assert cap.mean_abs_diff(np.zeros((0, 0, 3), np.uint8), np.zeros((0, 0, 3), np.uint8)) == 255.0

    def test_uint8_wraparound_is_not_an_issue(self):
        assert cap.mean_abs_diff(frame(10), frame(250)) == 240.0


class TestOpenDxgi:
    def test_picks_the_adapter_that_contains_the_region_and_translates_coordinates(self):
        dx = FakeDx()
        src, why = cap.open_dxgi(REGION, lambda: frame(100), dx, no_sleep)
        assert why == "DXGI" and isinstance(src, cap.DxgiSource)
        chosen = dx.cameras[-1]
        assert src._cam is chosen and chosen._output.desc.DesktopCoordinates.left == 1920
        assert src._region == (80, 100, 480, 180)  # tọa độ so với góc màn hình thứ hai
        assert dx.create_calls[0][2] == "BGR"

    def test_non_matching_outputs_are_released(self):
        dx = FakeDx()
        cap.open_dxgi(REGION, lambda: frame(100), dx, no_sleep)
        assert dx.cameras[0].released and not dx.cameras[1].released

    def test_region_on_first_screen_stops_after_first_adapter(self):
        dx = FakeDx()
        src, _ = cap.open_dxgi({"left": 10, "top": 10, "width": 400, "height": 80}, lambda: frame(100), dx, no_sleep)
        assert src is not None and len(dx.cameras) == 1

    def test_region_spanning_two_screens_is_refused(self):
        dx = FakeDx()
        src, why = cap.open_dxgi({"left": 1800, "top": 10, "width": 400, "height": 80}, lambda: frame(100), dx, no_sleep)
        assert src is None and "chứa trọn vùng Shop" in why and all(c.released for c in dx.cameras)

    def test_no_dxgi_outputs_at_all(self):
        dx = FakeDx(layout=())
        src, why = cap.open_dxgi(REGION, lambda: frame(100), dx, no_sleep)
        assert src is None and "chứa trọn vùng Shop" in why

    def test_black_frames_from_exclusive_fullscreen_are_rejected_with_advice(self):
        dx = FakeDx(frames=[frame(0)])
        src, why = cap.open_dxgi(REGION, lambda: frame(120), dx, no_sleep)
        assert src is None and "khung đen" in why and "borderless" in why and dx.cameras[-1].released

    def test_frames_that_do_not_match_mss_are_rejected(self):
        dx = FakeDx(frames=[frame(200)])
        src, why = cap.open_dxgi(REGION, lambda: frame(20), dx, no_sleep)
        assert src is None and "khác ảnh chụp mss" in why

    def test_verification_tolerates_a_moving_screen_by_retrying(self):
        dx = FakeDx(frames=[frame(250), frame(250), frame(101)])
        src, why = cap.open_dxgi(REGION, lambda: frame(100), dx, no_sleep)
        assert src is not None and why == "DXGI"

    def test_no_frame_from_camera_is_reported(self):
        dx = FakeDx(frames=[])
        src, why = cap.open_dxgi(REGION, lambda: frame(100), dx, no_sleep)
        assert src is None and "không trả về khung" in why

    def test_missing_library_is_reported(self, monkeypatch):
        def boom(name):
            raise ImportError(name)

        monkeypatch.setattr(cap.importlib, "import_module", boom)
        src, why = cap.open_dxgi(REGION, lambda: frame(100))
        assert src is None and "không nạp được thư viện dxcam" in why

    def test_unexpected_error_while_probing_is_reported(self):
        class Boom:
            def create(self, **kw):
                raise RuntimeError("driver")

        src, why = cap.open_dxgi(REGION, lambda: frame(100), Boom(), no_sleep)
        assert src is None and "chứa trọn vùng Shop" in why  # create lỗi = không có output

    def test_camera_without_readable_coordinates_is_skipped(self):
        class OddCam(FakeCam):
            def __init__(self):
                super().__init__((0, 0, 1, 1), [frame(100)])
                self._output = None

        class Dx:
            def create(self, device_idx=0, output_idx=0, **kw):
                if device_idx > 0 or output_idx > 0:
                    raise IndexError
                return OddCam()

        src, why = cap.open_dxgi(REGION, lambda: frame(100), Dx(), no_sleep)
        assert src is None


class TestDxgiSource:
    def make(self, frames, ref, clock):
        cam = FakeCam((0, 0, 1920, 1080), frames)
        return cap.DxgiSource(cam, (0, 0, 400, 80), lambda: ref(), clock), cam

    def test_requests_the_last_frame_instead_of_none_when_screen_is_static(self):
        src, cam = self.make([frame(90)], lambda: frame(90), lambda: 0.0)
        assert src.grab().shape == (80, 400, 3) and cam.grabs[0] == ((0, 0, 400, 80), False)

    def test_none_from_camera_raises_mismatch(self):
        src, _ = self.make([], lambda: frame(90), lambda: 0.0)
        with pytest.raises(cap.CaptureMismatch):
            src.grab()

    def test_periodic_check_passes_when_frames_agree(self):
        t = {"v": 0.0}
        src, _ = self.make([frame(90)], lambda: frame(92), lambda: t["v"])
        t["v"] = cap.CHECK_EVERY_S + 1
        for _ in range(5):
            src.grab()  # không ném lỗi

    def test_one_mismatch_is_tolerated_two_in_a_row_fail(self):
        t = {"v": 0.0}
        src, _ = self.make([frame(10)], lambda: frame(200), lambda: t["v"])
        t["v"] = cap.CHECK_EVERY_S + 0.1
        src.grab()  # lệch lần 1
        t["v"] += cap.CHECK_EVERY_S + 0.1
        with pytest.raises(cap.CaptureMismatch, match="lệch so với ảnh chụp mss"):
            src.grab()  # lệch lần 2 liên tiếp

    def test_a_good_check_resets_the_mismatch_count(self):
        t = {"v": 0.0}
        ref = {"v": frame(200)}
        src, _ = self.make([frame(10)], lambda: ref["v"], lambda: t["v"])
        t["v"] = cap.CHECK_EVERY_S + 0.1
        src.grab()  # lệch
        ref["v"] = frame(11)
        t["v"] += cap.CHECK_EVERY_S + 0.1
        src.grab()  # khớp → đếm về 0
        ref["v"] = frame(200)
        t["v"] += cap.CHECK_EVERY_S + 0.1
        src.grab()  # lệch lần 1 mới, chưa đủ để bỏ

    def test_check_does_not_run_every_frame(self):
        calls = []
        t = {"v": 0.0}
        src, _ = self.make([frame(10)], lambda: calls.append(1) or frame(10), lambda: t["v"])
        for _ in range(10):
            src.grab()
        assert calls == []
        t["v"] = cap.CHECK_EVERY_S + 0.1
        src.grab()
        src.grab()
        assert len(calls) == 1

    def test_black_dxgi_frame_while_screen_is_not_black_counts_as_mismatch(self):
        t = {"v": cap.CHECK_EVERY_S + 1}
        src, _ = self.make([frame(0)], lambda: frame(3), lambda: t["v"])
        src._next_check = 0
        src.grab()
        src._next_check = 0
        with pytest.raises(cap.CaptureMismatch):
            src.grab()

    def test_close_releases_camera_and_survives_errors(self):
        src, cam = self.make([frame(1)], lambda: frame(1), lambda: 0.0)
        src.close()
        assert cam.released
        cam.release = lambda: (_ for _ in ()).throw(RuntimeError("x"))
        src.close()


# ----------------------------------------------------------------------------- tích hợp scanner
class FakeSource:
    name = "DXGI"

    def __init__(self, frames=None, error=None):
        self.frames = frames or [frame(10, h=200, w=1000)]
        self.error = error
        self.closed = 0
        self.grabs = 0

    def grab(self):
        self.grabs += 1
        if self.error:
            raise self.error
        return self.frames[0]

    def close(self):
        self.closed += 1


class Log:
    def __init__(self):
        self.lines = []

    def __call__(self, m):
        self.lines.append(m)


class TestScannerIntegration:
    def test_default_backend_is_mss_and_never_touches_dxgi(self, make_scanner, monkeypatch):
        monkeypatch.setattr(sc, "open_dxgi", lambda *a, **k: pytest.fail("không được gọi"))
        s = make_scanner()
        assert s.capture_backend == "mss"
        s._open_capture()
        assert s._dxgi is None

    def test_auto_success_uses_dxgi_and_logs_it(self, make_scanner, monkeypatch):
        src = FakeSource()
        monkeypatch.setattr(sc, "open_dxgi", lambda region, ref: (src, "DXGI"))
        log = Log()
        s = make_scanner(capture_backend="auto", on_log=log)
        s._open_capture()
        assert s._dxgi is src and s._dxgi_thread == threading.get_ident()
        assert log.lines == ["Chụp màn hình: DXGI (~1 ms mỗi khung, nhanh hơn mss ~10 ms)."]

    def test_auto_failure_logs_reason_and_keeps_mss(self, make_scanner, monkeypatch):
        monkeypatch.setattr(sc, "open_dxgi", lambda region, ref: (None, "DXGI trả khung đen"))
        log = Log()
        s = make_scanner(capture_backend="auto", on_log=log)
        s._open_capture()
        assert s._dxgi is None and log.lines == ["Chụp màn hình: mss — không dùng được DXGI: DXGI trả khung đen."]

    def test_unexpected_exception_while_opening_falls_back(self, make_scanner, monkeypatch):
        def boom(region, ref):
            raise OSError("com lỗi")

        monkeypatch.setattr(sc, "open_dxgi", boom)
        log = Log()
        s = make_scanner(capture_backend="auto", on_log=log)
        s._open_capture()
        assert s._dxgi is None and "OSError: com lỗi" in log.lines[0]

    def test_grab_uses_dxgi_frame_without_calling_mss(self, make_scanner):
        s = make_scanner()
        src = FakeSource()
        s._dxgi = src
        s._sct = types.SimpleNamespace(grab=lambda m: pytest.fail("không được gọi mss"), close=lambda: None)
        out = s._grab_shop()
        assert out is src.frames[0] and src.grabs == 1

    def test_dxgi_failure_drops_to_mss_in_the_same_call_and_logs_once(self, make_scanner):
        log = Log()
        s = make_scanner(on_log=log)
        src = FakeSource(error=cap.CaptureMismatch("khung lệch"))
        s._dxgi = src
        s._sct = types.SimpleNamespace(grab=lambda m: np.full((200, 1000, 4), 7, np.uint8), close=lambda: None)
        out = s._grab_shop()
        assert out is not None and out.shape == (200, 1000, 3) and int(out[0, 0, 0]) == 7
        assert s._dxgi is None and src.closed == 1
        s._grab_shop()
        assert log.lines == ["Chụp DXGI gặp vấn đề (khung lệch) — chuyển sang mss."]

    def test_close_releases_dxgi_only_from_the_owning_thread(self, make_scanner):
        s = make_scanner()
        src = FakeSource()
        s._dxgi = src
        s._dxgi_thread = -1  # luồng khác
        s.close()
        assert src.closed == 0 and s._dxgi is src
        s._dxgi_thread = threading.get_ident()
        s.close()
        assert src.closed == 1 and s._dxgi is None

    def test_run_loop_opens_capture_first(self, make_scanner, monkeypatch):
        s = make_scanner(capture_backend="auto")
        order = []
        monkeypatch.setattr(s, "_open_capture", lambda: order.append("open"))
        s._running = False
        s._run_loop()
        assert order == ["open"]

    def test_verification_capture_uses_the_fast_source_too(self, make_scanner, clicks):
        """Chụp xác nhận trước click đi qua cùng nguồn chụp nên cũng nhanh (~1 ms thay vì ~12 ms)."""
        from tests.helpers import make_shop

        s = make_scanner(require_game_foreground=False)
        s._running = True
        shop = make_shop(s, [1, 2, 3, 4, 5])
        src = FakeSource(frames=[shop])
        s._dxgi = src
        slots = s._slice_slots(shop)
        s._buy_batch([(0, "Vex", 0.9, "ảnh", slots[0])], {}, 0.0)
        assert src.grabs == 1 and clicks == [s.slot_centers[0]]


# ----------------------------------------------------------------------------- DXGI thật trên máy này
class TestRealDxgi:
    def test_real_dxgi_matches_mss_and_is_much_faster(self):
        import time

        import mss

        try:
            import dxcam  # noqa: F401
        except Exception:
            pytest.skip("chưa cài dxcam")
        region = {"left": 100, "top": 100, "width": 400, "height": 80}
        sct = mss.MSS()

        def ref():
            return np.asarray(sct.grab(region), dtype=np.uint8)[:, :, :3]

        src, why = cap.open_dxgi(region, ref)
        if src is None:
            sct.close()
            pytest.skip(f"máy này không dùng được DXGI: {why}")
        try:
            frames = []
            t0 = time.perf_counter()
            for _ in range(40):
                frames.append(src.grab())
            per = (time.perf_counter() - t0) / 40 * 1000
            assert frames[0].shape == (80, 400, 3) and frames[0].dtype == np.uint8
            assert per < 8, f"DXGI mất {per:.1f} ms/khung, mong đợi nhanh hơn mss (~11 ms)"
            assert cap.mean_abs_diff(frames[-1], ref()) < 30
        finally:
            src.close()
            sct.close()
