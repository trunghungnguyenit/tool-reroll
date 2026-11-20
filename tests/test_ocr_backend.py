"""Chọn engine OCR (winocr → rapidocr → none), nhánh RapidOCR và cắt dải tên: các nhánh test_name_matcher chưa chạm tới."""

import sys
import types

import numpy as np
import pytest

import core.name_matcher as nm


@pytest.fixture(autouse=True)
def fresh_backend(monkeypatch):
    monkeypatch.setattr(nm, "_ocr_backend", None)
    monkeypatch.setattr(nm, "_rapidocr_engine", None)
    yield
    nm.refresh_ocr_state()
    nm.drain_ocr_errors()


def fake_rapidocr(monkeypatch, result):
    calls = {"created": 0, "regions": []}

    class FakeEngine:
        def __init__(self):
            calls["created"] += 1

        def __call__(self, region):
            calls["regions"].append(region)
            return result, 0.01

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", types.SimpleNamespace(RapidOCR=FakeEngine))
    return calls


class TestDetectBackend:
    def test_winocr_preferred_when_importable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "winocr", types.ModuleType("winocr"))
        fake_rapidocr(monkeypatch, [])
        assert nm._detect_backend() == "winocr"

    def test_rapidocr_when_winocr_missing(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "winocr", None)  # None trong sys.modules => import ném ImportError
        fake_rapidocr(monkeypatch, [])
        assert nm._detect_backend() == "rapidocr"

    def test_none_when_no_engine(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "winocr", None)
        monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
        assert nm._detect_backend() == "none"

    def test_result_is_cached(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "winocr", None)
        monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
        assert nm._detect_backend() == "none"
        monkeypatch.setitem(sys.modules, "winocr", types.ModuleType("winocr"))
        assert nm._detect_backend() == "none"  # đã nhớ; refresh_ocr_state() mới dò lại
        nm.refresh_ocr_state()
        assert nm._detect_backend() == "winocr"


class TestRapidOcr:
    def test_joins_text_lines_and_reuses_engine(self, monkeypatch):
        calls = fake_rapidocr(monkeypatch, [[[0, 0], "Tahm", 0.9], [[0, 1], "Kench", 0.8]])
        region = np.zeros((10, 10, 3), np.uint8)
        assert nm._read_rapidocr(region) == "Tahm Kench"
        assert nm._read_rapidocr(region) == "Tahm Kench"
        assert calls["created"] == 1  # engine nặng: chỉ tạo một lần

    def test_no_result_is_empty_string(self, monkeypatch):
        fake_rapidocr(monkeypatch, None)
        assert nm._read_rapidocr(np.zeros((4, 4, 3), np.uint8)) == ""

    def test_lines_without_text_part_are_skipped(self, monkeypatch):
        fake_rapidocr(monkeypatch, [[[0, 0]], [[0, 1], "Vex", 0.9]])
        assert nm._read_rapidocr(np.zeros((4, 4, 3), np.uint8)) == "Vex"

    def test_read_name_from_slot_uses_rapidocr_branch(self, monkeypatch):
        monkeypatch.setattr(nm, "_ocr_backend", "rapidocr")
        calls = fake_rapidocr(monkeypatch, [[[0, 0], "Zed", 0.9]])
        assert nm.read_name_from_slot(np.zeros((60, 120, 3), np.uint8)) == "Zed"
        assert calls["regions"][0].shape[0] > 0

    def test_rapidocr_crash_is_recorded_not_raised(self, monkeypatch):
        monkeypatch.setattr(nm, "_ocr_backend", "rapidocr")

        class Boom:
            def __call__(self, region):
                raise ValueError("onnx hỏng")

        monkeypatch.setattr(nm, "_rapidocr_engine", Boom())
        monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", types.SimpleNamespace(RapidOCR=Boom))
        assert nm.read_name_from_slot(np.zeros((60, 120, 3), np.uint8)) == ""
        assert nm.drain_ocr_errors() == {"ValueError: onnx hỏng": 1}


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
