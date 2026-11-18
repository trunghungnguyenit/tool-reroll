"""Chụp màn hình vùng shop và tạo ảnh xem trước có đánh dấu điểm click."""

import cv2
import mss
import numpy as np
from PIL import Image, ImageDraw

from core.config import SHOP_PREVIEW_PATH, ensure_dirs


def capture_shop_region(region: dict) -> np.ndarray | None:
    """Chụp ảnh màn hình đúng vùng shop đã cấu hình (left, top, width, height)."""
    try:
        with mss.mss() as sct:
            shot = sct.grab(
                {
                    "left": region["left"],
                    "top": region["top"],
                    "width": region["width"],
                    "height": region["height"],
                }
            )
            return np.array(shot)[:, :, :3]
    except Exception:
        return None


def build_shop_preview(
    region: dict,
    slot_centers: list | None = None,
    capture_live: bool = True,
) -> Image.Image | None:
    """
    Tạo ảnh preview shop: viền xanh + chấm đỏ đánh dấu 5 điểm click.
    capture_live=True thì chụp màn hình mới; False thì dùng ảnh đã lưu.
    """
    ensure_dirs()
    frame = capture_shop_region(region) if capture_live else None

    if frame is None and SHOP_PREVIEW_PATH.exists():
        frame = cv2.imread(str(SHOP_PREVIEW_PATH))

    if frame is None:
        return None

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil)

    w, h = pil.size
    draw.rectangle([0, 0, w - 1, h - 1], outline="#22c55e", width=2)

    if slot_centers and region:
        left, top = region["left"], region["top"]
        for i, center in enumerate(slot_centers):
            cx, cy = center[0], center[1]
            rx, ry = cx - left, cy - top
            r = max(4, min(w, h) // 25)
            draw.ellipse([rx - r, ry - r, rx + r, ry + r], fill="#ef4444", outline="#ffffff", width=1)
            draw.text((rx + r + 2, ry - r - 2), str(i + 1), fill="#fbbf24")

    pil.save(SHOP_PREVIEW_PATH)
    return pil
