"""Hàm dựng dữ liệu giả cho test (ảnh thẻ tướng, ảnh vùng shop)."""

import cv2
import numpy as np

REGION = {"left": 100, "top": 50, "width": 1000, "height": 200}
CENTERS = [(200 + i * 200, 150) for i in range(5)]  # đều nằm trong REGION


def make_card(seed: int, size=(200, 164)) -> np.ndarray:
    """Thẻ giả: ảnh nhiễu mượt theo seed (cùng seed → cùng thẻ)."""
    small = np.random.default_rng(seed).integers(0, 255, (8, 5, 3), dtype=np.uint8)
    return cv2.resize(small, size, interpolation=cv2.INTER_CUBIC)


def make_shop(scanner, seeds, empty=()) -> np.ndarray:
    """Ảnh cả vùng shop: ô i chứa thẻ seeds[i]; ô trong `empty` để đen (đã mua)."""
    h, w = scanner.shop_region["height"], scanner.shop_region["width"]
    shop = np.zeros((h, w, 3), dtype=np.uint8)
    y0 = int(h * scanner._card_top_ratio)
    for i, seed in enumerate(seeds):
        if i in empty:
            continue
        x0, x1 = i * w // 5, (i + 1) * w // 5
        card = make_card(seed)
        rows = min(card.shape[0], h - y0)
        shop[y0 : y0 + rows, x0:x1] = card[:rows, : x1 - x0]
    return shop
