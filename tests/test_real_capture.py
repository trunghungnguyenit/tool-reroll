"""Chụp màn hình THẬT bằng mss (không giả lập) qua đúng đường của scanner và preview, với cảnh báo deprecated của mss
bị coi là lỗi. Bộ test còn lại giả lập mss nên không bao giờ chạm tới thư viện thật. Bỏ qua khi không có màn hình.

Chỉ giữ ảnh trong bộ nhớ, không lưu ra đĩa."""

import threading
import time
import warnings

import mss
import numpy as np
import pytest

from core import preview
from core import scanner as sc

REGION = {"left": 0, "top": 0, "width": 320, "height": 100}
CENTERS = [(30 + i * 60, 60) for i in range(5)]


@pytest.fixture(scope="module")
def display():
    try:
        with mss.MSS() as sct:
            sct.grab({"left": 0, "top": 0, "width": REGION["width"], "height": REGION["height"]})
    except Exception as e:  # máy chủ CI không có display
        pytest.skip(f"không chụp được màn hình: {type(e).__name__}: {e}")


@pytest.fixture(autouse=True)
def mss_deprecations_are_errors(display):
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message=r".*\bmss\b.*", category=DeprecationWarning)
        yield


def real_scanner(**kw):
    return sc.ShopScanner(REGION, CENTERS, {}, ["Vex"], detect_by_image=False, detect_by_name=True, **kw)


class TestScannerRealGrab:
    def test_grab_returns_bgr_frame_that_survives_the_cv2_pipeline(self):
        s = real_scanner()
        try:
            frame = s._grab_shop()
            assert frame is not None, s._last_grab_error
            assert frame.shape == (REGION["height"], REGION["width"], 3) and frame.dtype == np.uint8
            slots = s._slice_slots(frame)
            assert len(slots) == 5
            sigs = [sc._slot_signature(x) for x in slots]  # cv2.cvtColor/resize trên mảng không liên tục của mss
            assert all(sig.shape == (20, 40) for sig in sigs)
        finally:
            s.close()

    def test_close_is_clean_and_grab_after_close_is_reported_not_raised(self):
        s = real_scanner()
        s.close()
        s.close()
        assert s._grab_shop() is None and s._last_grab_error

    def test_grab_works_on_another_thread_than_the_one_that_created_mss(self):
        """Scanner tạo mss ở thread giao diện nhưng chụp ở thread quét."""
        s = real_scanner()
        out = {}
        try:
            t = threading.Thread(target=lambda: out.setdefault("frame", s._grab_shop()))
            t.start()
            t.join(5)
            assert out.get("frame") is not None, s._last_grab_error
        finally:
            s.close()

    def test_real_scan_loop_runs_clean_then_releases_mss(self, clicks, foreground):
        """Vòng quét thật trên màn hình thật (nhận diện bằng ảnh, ngưỡng không thể đạt nên không click)."""
        errors = []
        template = np.random.default_rng(0).integers(0, 255, (64, 64, 3), dtype=np.uint8)
        s = sc.ShopScanner(
            REGION, CENTERS, {"Vex": template}, ["Vex"], threshold=1.01, detect_by_image=True, detect_by_name=False,
            scan_interval_ms=5, on_error=lambda m, f: errors.append(m),
        )
        sct = s._sct
        s.start()
        time.sleep(0.4)
        s.stop()
        s._thread.join(3)
        assert not s._thread.is_alive()
        assert errors == [] and clicks == []
        assert s._sct is None and sct is not None  # mss do thread quét tự đóng khi thoát


class TestPreviewRealCapture:
    def test_capture_shop_region_uses_non_deprecated_api(self):
        frame = preview.capture_shop_region(REGION)
        assert frame is not None and frame.shape == (REGION["height"], REGION["width"], 3)
        assert frame.dtype == np.uint8

    def test_capture_failure_is_reported_as_none_not_raised(self):
        assert preview.capture_shop_region({"left": 0, "top": 0, "width": 0, "height": 0}) is None
