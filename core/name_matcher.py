"""Đọc tên tướng bằng OCR (Windows) và so khớp với danh sách tướng cần bắt."""

import asyncio
import re
import unicodedata
from difflib import SequenceMatcher

import cv2
import numpy as np
from PIL import Image

_ocr_backend = None
_ocr_langs = ("en-US", "vi-VN")


def _detect_backend() -> str:
    """Chọn engine OCR: winocr (Windows) hoặc rapidocr (dự phòng)."""
    global _ocr_backend
    if _ocr_backend is not None:
        return _ocr_backend
    try:
        import winocr  # noqa: F401

        _ocr_backend = "winocr"
        return _ocr_backend
    except ImportError:
        pass
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401

        _ocr_backend = "rapidocr"
        return _ocr_backend
    except ImportError:
        pass
    _ocr_backend = "none"
    return _ocr_backend


_rapidocr_engine = None


def _read_winocr(region: np.ndarray) -> str:
    """Đọc chữ từ ảnh bằng Windows OCR (en-US / vi-VN)."""
    import winocr

    rgb = cv2.cvtColor(region, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)

    async def run():
        for lang in _ocr_langs:
            try:
                result = await winocr.recognize_pil(pil, lang)
                text = (result.text or "").strip()
                if text:
                    return text
            except Exception:
                continue
        return ""

    try:
        return asyncio.run(run())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(run())
        finally:
            loop.close()


def _read_rapidocr(region: np.ndarray) -> str:
    """Đọc chữ từ ảnh bằng RapidOCR (khi không có winocr)."""
    global _rapidocr_engine
    from rapidocr_onnxruntime import RapidOCR

    if _rapidocr_engine is None:
        _rapidocr_engine = RapidOCR()
    result, _ = _rapidocr_engine(region)
    if not result:
        return ""
    return " ".join(str(line[1]) for line in result if len(line) > 1)


def normalize_name(text: str) -> str:
    """Chuẩn hóa tên: bỏ dấu, chữ thường, bỏ ký tự đặc biệt — để so sánh OCR dễ hơn."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_name_region(slot_frame: np.ndarray) -> np.ndarray:
    """Cắt dải tên tướng ở đáy thẻ (TFT hiển thị tên dưới cùng) và phóng to cho OCR."""
    h, w = slot_frame.shape[:2]
    y0 = int(h * 0.72)
    y1 = int(h * 0.96)
    roi = slot_frame[y0:y1, int(w * 0.05) : int(w * 0.95)]
    if roi.size == 0:
        return slot_frame

    return cv2.resize(roi, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)


def read_name_from_slot(slot_frame: np.ndarray) -> str:
    """OCR đọc tên tướng từ 1 ô shop, trả về chuỗi text."""
    backend = _detect_backend()
    if backend == "none":
        return ""

    region = extract_name_region(slot_frame)
    try:
        if backend == "winocr":
            return _read_winocr(region)
        return _read_rapidocr(region)
    except Exception:
        return ""


def match_name_in_text(
    ocr_text: str,
    targets: list[str],
    min_ratio: float = 0.65,
) -> tuple[str, float] | None:
    """
    So sánh text OCR với danh sách tướng cần bắt.
    Trả về (tên_tướng, độ_khớp) nếu >= min_ratio, ngược lại None.
    """
    ocr_norm = normalize_name(ocr_text)
    if not ocr_norm:
        return None

    best_name = None
    best_score = 0.0

    for name in targets:
        target_norm = normalize_name(name)
        if not target_norm:
            continue

        if target_norm in ocr_norm or ocr_norm in target_norm:
            return name, 1.0

        words = ocr_norm.split()
        for n in range(1, min(4, len(words) + 1)):
            tail = " ".join(words[-n:])
            if target_norm == tail or target_norm in tail or tail in target_norm:
                return name, 1.0
            for word in words[-n:]:
                if len(word) >= 3 and (word == target_norm or target_norm in word or word in target_norm):
                    return name, 1.0

        score = SequenceMatcher(None, ocr_norm, target_norm).ratio()
        for word in ocr_norm.split():
            if len(word) >= 3:
                score = max(score, SequenceMatcher(None, word, target_norm).ratio())

        if score > best_score:
            best_score = score
            best_name = name

    if best_name and best_score >= min_ratio:
        return best_name, best_score
    return None
