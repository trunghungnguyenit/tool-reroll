"""Đọc/ghi cấu hình tool (shop, tướng, ngưỡng nhận diện...) vào file JSON."""

import json
import sys
from pathlib import Path


def app_base_dir() -> Path:
    """Thư mục gốc app — cạnh file .exe khi đóng gói PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = app_base_dir()
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = DATA_DIR / "templates"
CONFIG_PATH = DATA_DIR / "config.json"
SHOP_PREVIEW_PATH = DATA_DIR / "shop_preview.png"

DEFAULT_CONFIG = {
    "shop_region": None,
    "slot_centers": [],
    "match_threshold": 0.72,
    "scan_interval_ms": 3,
    "buy_delay_ms": 0,
    "buy_cooldown_ms": 90,
    "hotkey_toggle": "f8",
    "selected_champions": [],
    "custom_templates": {},
    "manual_names": "",
    "detect_by_image": True,
    "detect_by_name": True,
    "name_match_threshold": 0.65,
    "name_scan_interval_ms": 50,
}


def ensure_dirs():
    """Tạo thư mục data/ và data/templates/ nếu chưa có."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Đọc config.json, gộp với giá trị mặc định nếu thiếu key."""
    ensure_dirs()
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        merged = {**DEFAULT_CONFIG, **data}
        return merged
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    """Lưu toàn bộ cấu hình ra config.json."""
    ensure_dirs()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
