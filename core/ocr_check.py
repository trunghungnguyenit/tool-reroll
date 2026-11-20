"""Tự kiểm tra OCR trước khi quét: có engine không, có pack ngôn ngữ không, đọc thử được chữ mẫu không.
Trước đây OCR hỏng (thiếu pack, không có engine, lỗi giữa chừng) chỉ cho ra chuỗi rỗng — người dùng không phân biệt được
"OCR chết" với "shop chưa có tướng mục tiêu"."""

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core import name_matcher as nm

SAMPLE_TEXT = "Tryndamere"  # tên dài nên đọc ổn định (chữ 3 ký tự như "Vex" có lúc bị Windows OCR bỏ sót khi chữ nhỏ)
_SAMPLE_SIZES = (20, 24, 28)
_FONTS = ("segoeui.ttf", "arial.ttf", "tahoma.ttf")
_SELFTEST_MIN_RATIO = 0.8


def capability_command(lang_tag: str) -> str:
    """Lệnh PowerShell (chạy bằng quyền Admin) cài pack OCR của Windows cho một ngôn ngữ."""
    return f'Add-WindowsCapability -Online -Name "Language.OCR~~~{lang_tag}~0.0.1.0"'


@dataclass
class OcrStatus:
    ok: bool
    backend: str  # "winocr" | "rapidocr" | "none"
    languages: list[str] = field(default_factory=list)  # ngôn ngữ đang dùng
    detail: str = ""  # lý do khi không ok
    hints: list[str] = field(default_factory=list)  # cách sửa (lệnh cài đặt...), cả khi ok (vd thiếu pack tùy chọn)

    @property
    def summary(self) -> str:
        """Một dòng cho nhãn trên giao diện và Nhật ký."""
        if not self.ok:
            return f"lỗi — {self.detail}"
        names = {"winocr": "Windows OCR", "rapidocr": "RapidOCR"}
        engine = names.get(self.backend, self.backend)
        return f"{engine} ({', '.join(self.languages)})" if self.languages else engine

    def problem_text(self) -> str:
        """Nội dung hộp thoại khi OCR không hoạt động: nguyên nhân + cách sửa."""
        lines = [self.detail] + [f"• {h}" for h in self.hints]
        return "\n".join(lines)


OCR_RUN = "run"  # chạy bình thường
OCR_IMAGE_ONLY = "image_only"  # OCR hỏng nhưng bắt theo ảnh dùng được → tắt bắt theo tên trong lần chạy này
OCR_BLOCK = "block"  # OCR hỏng và không còn cách nào khác → không bắt đầu


def start_decision(ocr: "OcrStatus | None", detect_name: bool, image_ready: bool) -> str:
    """
    Có cho bắt đầu quét không, dựa vào kết quả tự kiểm tra OCR. Chỉ bắt theo tên mà OCR hỏng thì chạy cũng vô ích
    (scanner im lặng không bao giờ thấy tướng) nên chặn; còn bắt theo ảnh được thì chạy bằng ảnh.
    """
    if not detect_name or ocr is None or ocr.ok:
        return OCR_RUN
    return OCR_IMAGE_ONLY if image_ready else OCR_BLOCK


def _load_font(size: int):
    for name in _FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # Pillow cũ không nhận tham số size
        return ImageFont.load_default()


CARD_SIZE = (190, 164)  # (rộng, cao) một ô shop giả
# Dải cắt tên của OCR (xem nm.extract_name_region): từ 72% đến 96% chiều cao ô.
_BAND = (0.72, 0.96)


def render_sample(text: str = SAMPLE_TEXT, size: int = 22) -> np.ndarray:
    """
    Vẽ 1 'thẻ shop' giả: tên + số vàng nằm GIỮA dải mà OCR cắt ra (nếu lệch ra ngoài dải thì OCR đọc rỗng,
    làm phép thử báo hỏng oan).
    """
    w, h = CARD_SIZE
    img = Image.new("RGB", CARD_SIZE, (30, 30, 40))
    draw = ImageDraw.Draw(img)
    font = _load_font(size)
    label = f"{text}  3"
    left, top, _, bottom = draw.textbbox((0, 0), label, font=font)
    band_mid = (_BAND[0] + _BAND[1]) / 2 * h
    draw.text((10 - left, band_mid - (bottom - top) / 2 - top), label, fill=(240, 240, 240), font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _selftest(sample: str) -> tuple[bool, str]:
    """Đọc thử chữ mẫu ở vài cỡ chữ; đạt nếu một lần đọc ra đúng tên mẫu."""
    matcher = nm.NameMatcher([sample], None, _SELFTEST_MIN_RATIO)
    last = ""
    for size in _SAMPLE_SIZES:
        last = nm.read_name_from_slot(render_sample(sample, size))
        if matcher.match(last):
            return True, ""
    return False, f"đọc thử chữ mẫu '{sample}' ra {last!r}"


def check_ocr(sample: str = SAMPLE_TEXT, wanted_extra: tuple[str, ...] = ()) -> OcrStatus:
    """
    Kiểm tra OCR từ đầu (đọc lại danh sách pack vừa cài). wanted_extra: ngôn ngữ mong muốn có thêm nhưng không bắt buộc
    (vd 'vi-VN'); thiếu thì chỉ thêm gợi ý cài, không làm OCR bị coi là hỏng.
    """
    nm.refresh_ocr_state()
    nm.drain_ocr_errors()  # lỗi cũ không còn liên quan tới kết quả lần kiểm tra này
    backend = nm._detect_backend()

    if backend == "none":
        return OcrStatus(
            False,
            backend,
            detail="Không có engine OCR.",
            hints=["Chạy: pip install winocr   (hoặc rapidocr-onnxruntime)"],
        )

    hints: list[str] = []
    languages: list[str] = []
    if backend == "winocr":
        languages = nm.ocr_languages_in_use()
        if not languages:
            return OcrStatus(
                False,
                backend,
                detail="Windows chưa cài pack ngôn ngữ OCR nào.",
                hints=[f"Cài pack tiếng Anh (PowerShell, quyền Admin): {capability_command('en-US')}"],
            )
        installed = set(nm.installed_ocr_languages())
        for lang in dict.fromkeys((*nm._ocr_langs[:1], *wanted_extra)):  # en-US luôn nên có; thêm ngôn ngữ mong muốn
            if lang not in installed:
                hints.append(f"Chưa cài pack OCR {lang}. Cài (PowerShell, quyền Admin): {capability_command(lang)}")

    ok, why = _selftest(sample)
    errors = nm.drain_ocr_errors()
    if not ok:
        detail = f"OCR không đọc được chữ mẫu ({why})."
        if errors:
            detail += " Lỗi OCR: " + "; ".join(errors)
        return OcrStatus(False, backend, languages, detail, hints + ["Xem data/app.log để biết thêm chi tiết."])
    return OcrStatus(True, backend, languages, "", hints)
