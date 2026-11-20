"""Chọn engine OCR (winocr → none) và cắt dải tên: các nhánh test_name_matcher chưa chạm tới."""

import sys
import types

import numpy as np
import pytest

import core.name_matcher as nm


@pytest.fixture(autouse=True)
def fresh_backend(monkeypatch):
    monkeypatch.setattr(nm, "_ocr_backend", None)
    yield
    nm.refresh_ocr_state()
    nm.drain_ocr_errors()


class TestDetectBackend:
    def test_winocr_preferred_when_importable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "winocr", types.ModuleType("winocr"))
        assert nm._detect_backend() == "winocr"

    def test_none_when_no_engine(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "winocr", None)  # None trong sys.modules => import ném ImportError
        assert nm._detect_backend() == "none"

    def test_result_is_cached(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "winocr", None)  # None trong sys.modules => import ném ImportError
        assert nm._detect_backend() == "none"
        monkeypatch.setitem(sys.modules, "winocr", types.ModuleType("winocr"))
        assert nm._detect_backend() == "none"  # đã nhớ; refresh_ocr_state() mới dò lại
        nm.refresh_ocr_state()
        assert nm._detect_backend() == "winocr"


class TestReadNameFromSlot:
    def test_engine_crash_is_recorded_not_raised(self, monkeypatch):
        monkeypatch.setattr(nm, "_ocr_backend", "winocr")

        def boom(region):
            raise ValueError("winrt hỏng")

        monkeypatch.setattr(nm, "_read_winocr", boom)
        assert nm.read_name_from_slot(np.zeros((60, 120, 3), np.uint8)) == ""
        assert nm.drain_ocr_errors() == {"ValueError: winrt hỏng": 1}

    def test_no_engine_is_reported_and_returns_empty(self, monkeypatch):
        monkeypatch.setattr(nm, "_ocr_backend", "none")
        monkeypatch.setattr(nm, "_read_winocr", lambda region: pytest.fail("không được gọi khi không có engine"))
        assert nm.read_name_from_slot(np.zeros((60, 120, 3), np.uint8)) == ""
        assert nm.drain_ocr_errors() == {"Không có engine OCR (cài winocr)": 1}

    def test_winocr_text_is_returned(self, monkeypatch):
        monkeypatch.setattr(nm, "_ocr_backend", "winocr")
        seen = []
        monkeypatch.setattr(nm, "_read_winocr", lambda region: seen.append(region.shape) or "Zed")
        assert nm.read_name_from_slot(np.zeros((60, 120, 3), np.uint8)) == "Zed"
        assert seen and seen[0][0] > 0


class TestExtractNameRegion:
    def test_crops_bottom_strip_and_triples_size(self):
        frame = np.zeros((100, 200, 3), np.uint8)
        roi = nm.extract_name_region(frame)
        assert roi.shape == ((int(100 * 0.96) - int(100 * 0.72)) * 3, (int(200 * 0.95) - int(200 * 0.05)) * 3, 3)

    def test_only_the_name_strip_is_used(self):
        frame = np.zeros((100, 200, 3), np.uint8)
        frame[75:90, 20:180] = 255  # dải tên
        frame[:50] = 128  # phần tranh tướng: không được lọt vào
        roi = nm.extract_name_region(frame)
        assert roi.max() == 255 and (roi == 128).sum() == 0

    def test_degenerate_slot_returns_frame_unchanged_instead_of_crashing(self):
        frame = np.zeros((1, 1, 3), np.uint8)
        assert nm.extract_name_region(frame) is frame
