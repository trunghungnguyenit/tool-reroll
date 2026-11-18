"""Tải danh sách tướng TFT và ảnh mẫu từ Riot Data Dragon."""

import re
from pathlib import Path

import cv2
import numpy as np
import requests

from core.config import TEMPLATES_DIR, ensure_dirs

DDRAGON_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_TFT_CHAMP = "https://ddragon.leagueoflegends.com/cdn/{version}/data/vi_VN/tft-champion.json"
DDRAGON_IMG = "https://ddragon.leagueoflegends.com/cdn/{version}/img/tft-champion/{filename}"


def _latest_version() -> str:
    """Lấy phiên bản patch mới nhất từ Data Dragon."""
    resp = requests.get(DDRAGON_VERSIONS, timeout=15)
    resp.raise_for_status()
    versions = resp.json()
    for v in versions:
        if re.match(r"^\d+\.\d+\.\d+$", v):
            return v
    return versions[0]


def fetch_champion_list() -> list[dict]:
    """Tải danh sách tướng TFT (tên, cost, link ảnh), loại trùng tên."""
    version = _latest_version()
    url = DDRAGON_TFT_CHAMP.format(version=version)
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    data = resp.json()["data"]

    champions = []
    seen_names = set()
    for champ_id, info in data.items():
        name = info.get("name", "")
        if not name or name in seen_names:
            continue
        tier = info.get("tier")
        if tier is None:
            continue
        img_file = info["image"]["full"]
        img_url = DDRAGON_IMG.format(version=version, filename=img_file)
        seen_names.add(name)
        champions.append(
            {
                "id": champ_id,
                "name": name,
                "tier": tier,
                "image_url": img_url,
            }
        )
    champions.sort(key=lambda c: (c["tier"], c["name"]))
    return champions


def download_template(name: str, url: str) -> Path | None:
    """Tải ảnh portrait tướng về data/templates/, bỏ qua nếu đã có."""
    ensure_dirs()
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    path = TEMPLATES_DIR / f"{safe}.png"
    if path.exists():
        return path
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        path.write_bytes(resp.content)
        return path
    except requests.RequestException:
        return None


def load_template_image(path: Path) -> np.ndarray | None:
    """Đọc file ảnh tướng từ ổ đĩa thành mảng OpenCV."""
    if not path.exists():
        return None
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return img


def prepare_shop_template(full_img: np.ndarray, size: int = 64) -> np.ndarray:
    """Cắt vuông giữa ảnh tướng và resize về size×size để so khớp trong shop."""
    h, w = full_img.shape[:2]
    side = min(h, w)
    y0 = (h - side) // 2
    x0 = (w - side) // 2
    cropped = full_img[y0 : y0 + side, x0 : x0 + side]
    return cv2.resize(cropped, (size, size), interpolation=cv2.INTER_AREA)
