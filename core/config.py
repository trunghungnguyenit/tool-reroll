"""Đọc/ghi cấu hình tool (shop, tướng, ngưỡng nhận diện...) vào file JSON."""

import copy
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path, PureWindowsPath


def app_base_dir() -> Path:
    """Thư mục gốc app — cạnh file .exe khi đóng gói PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = app_base_dir()
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = DATA_DIR / "templates"
CONFIG_PATH = DATA_DIR / "config.json"
SHOP_CAPTURE_PATH = DATA_DIR / "shop_capture.png"  # ảnh chụp vùng shop SẠCH (không viền/chấm)
LEGACY_SHOP_PREVIEW_PATH = DATA_DIR / "shop_preview.png"  # kiểu cũ: ảnh đã vẽ chấm; được xóa khi lưu ảnh mới

DEFAULT_CONFIG = {
    "shop_region": None,
    "slot_centers": [],
    "match_threshold": 0.72,
    "scan_interval_ms": 3,
    "buy_delay_ms": 0,
    "buy_cooldown_ms": 90,
    "card_same_corr": 0.80,
    "require_game_foreground": True,
    "game_process_names": ["League of Legends.exe"],
    "hotkey_toggle": "f8",
    "capture_backend": "auto",  # cách chụp màn hình: auto (thử DXGI, tự quay về mss) hoặc mss
    "roll_key": "d",  # phím roll trong game: bấm thì app quét dày ~0,5 giây; "" = tắt
    "champion_locale": "vi_VN",  # ngôn ngữ danh sách tướng (vi_VN, en_US...); alias ngôn ngữ kia luôn được khớp
    "show_old_sets": False,
    "theme": "auto",  # giao diện: auto (theo Windows), light hoặc dark
    "selected_champions": [],
    "custom_templates": {},
    "manual_names": "",
    "detect_by_image": True,
    "detect_by_name": True,
    "name_match_threshold": 0.80,
    "name_scan_interval_ms": 50,
}


# Phiên bản hệ tọa độ của shop_region/slot_centers. 2 = pixel vật lý (tiến trình DPI-aware, xem core/dpi.py).
# Config cũ không có key này: tọa độ có thể đã lưu ở hệ tọa độ ảo (scale ≠ 100%) nên không dùng lại được.
# Không đưa key này vào DEFAULT_CONFIG, nếu không config cũ sẽ được gộp thành "đã đúng phiên bản".
COORDS_VERSION = 2


def migrate_coordinates(config: dict) -> bool:
    """
    Đảm bảo tọa độ trong config ở hệ COORDS_VERSION. Config cũ → xóa vùng shop và điểm click để cấu hình lại.
    Trả True nếu vừa xóa tọa độ đã lưu (UI nên báo người dùng chọn lại).
    """
    if config.get("coords_version") == COORDS_VERSION:
        return False
    had_coords = bool(config.get("shop_region")) or bool(config.get("slot_centers"))
    config["shop_region"] = None
    config["slot_centers"] = []
    config["coords_version"] = COORDS_VERSION
    return had_coords


def to_stored_template_path(path: Path) -> str:
    """Đường dẫn ảnh upload để lưu vào config: tương đối so với data/ (đổi máy/thư mục vẫn dùng được)."""
    try:
        return Path(path).resolve().relative_to(DATA_DIR.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_template_path(stored: str) -> Path | None:
    """
    Tìm file ảnh upload từ đường dẫn lưu trong config.
    Thứ tự: đường dẫn tương đối (so với data/) hoặc tuyệt đối → cùng tên file trong data/templates/ → None.
    """
    p = Path(stored)
    candidate = p if p.is_absolute() else DATA_DIR / p
    if candidate.exists():
        return candidate
    fallback = TEMPLATES_DIR / PureWindowsPath(stored).name  # config cũ: C:\Users\<máy khác>\...\file.png
    return fallback if fallback.exists() else None


def normalize_custom_templates(custom: dict[str, str]) -> dict[str, str]:
    """Đổi các đường dẫn ảnh upload tìm lại được sang dạng tương đối; không tìm được thì giữ nguyên."""
    result = {}
    for name, stored in custom.items():
        found = resolve_template_path(stored)
        result[name.strip()] = to_stored_template_path(found) if found else stored  # strip: tên Data Dragon từng có dấu cách thừa
    return result


def ensure_dirs():
    """Tạo thư mục data/ và data/templates/ nếu chưa có."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def _sibling(suffix: str) -> Path:
    """File cạnh config.json: .bak (bản lưu trước), .bad (bản hỏng), .tmp (đang ghi)."""
    return CONFIG_PATH.with_name(CONFIG_PATH.name + suffix)


def _read_config_file(path: Path) -> dict:
    """Đọc 1 file config; ném lỗi nếu không phải JSON object hợp lệ."""
    with open(path, encoding="utf-8-sig") as f:  # utf-8-sig: file lưu từ Notepad kiểu "UTF-8 with BOM" vẫn đọc được
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("config không phải JSON object")
    return data


def _with_defaults(data: dict | None) -> dict:
    return {**copy.deepcopy(DEFAULT_CONFIG), **(data or {})}


# ---------------------------------------------------------------------------------------------------------------
# Làm sạch config sửa tay. Giá trị sai kiểu/ngoài khoảng không được làm app hỏng im lặng (vd game_process_names là
# chuỗi → thành tập ký tự → không bao giờ click). Quy tắc: tự đổi khi rõ ý, không rõ thì dùng mặc định; số ngoài
# khoảng thì kẹp vào biên; mọi thay đổi đều có 1 dòng thông báo. Khóa lạ (không có trong DEFAULT_CONFIG) giữ nguyên.
# ---------------------------------------------------------------------------------------------------------------
DEFAULT_LOCALE = "vi_VN"
_LOCALE_RE = re.compile(r"^[a-z]{2}_[A-Z]{2}$")

# Khoảng hợp lệ của các số (min, max). Trùng với thanh trượt/ô số trên giao diện nếu có.
NUMERIC_LIMITS: dict[str, tuple[float, float]] = {
    "match_threshold": (0.5, 0.95),
    "name_match_threshold": (0.5, 0.95),
    "card_same_corr": (0.5, 0.99),
    "scan_interval_ms": (0, 100),
    "name_scan_interval_ms": (0, 2000),
    "buy_delay_ms": (0, 2000),
    "buy_cooldown_ms": (0, 5000),
}
_INT_KEYS = {"scan_interval_ms", "name_scan_interval_ms", "buy_delay_ms", "buy_cooldown_ms"}
_BOOL_KEYS = ("require_game_foreground", "show_old_sets", "detect_by_image", "detect_by_name")
_TRUE_WORDS = {"true", "yes", "on", "1", "có", "co"}
_FALSE_WORDS = {"false", "no", "off", "0", "không", "khong"}
_REGION_KEYS = ("left", "top", "width", "height")
_UNSET = object()


def normalize_locale(locale) -> str:
    """Locale hợp lệ dạng 'vi_VN'/'en_US'; sai định dạng thì dùng mặc định (tránh gọi URL lạ)."""
    return locale if isinstance(locale, str) and _LOCALE_RE.match(locale) else DEFAULT_LOCALE


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
    elif isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return _UNSET


def _to_number(value, integer: bool):
    """Số, hoặc chuỗi số (chấp nhận dấu phẩy thập phân kiểu Việt "0,8"). bool, NaN, vô cực → _UNSET."""
    if isinstance(value, bool):
        return _UNSET
    if isinstance(value, (int, float)):
        x = float(value)
    elif isinstance(value, str):
        try:
            x = float(value.strip().replace(",", "."))
        except ValueError:
            return _UNSET
    else:
        return _UNSET
    if math.isnan(x) or math.isinf(x):
        return _UNSET
    return int(round(x)) if integer else x


def _str_list(value, strip: bool):
    """(danh sách chuỗi, số phần tử bị bỏ) hoặc (_UNSET, 0) nếu không đoán được ý. Chuỗi đơn → danh sách 1 phần tử.
    strip=True: bỏ khoảng trắng hai đầu (cần cho tên process); False: giữ nguyên chuỗi (tên tướng đã được chuẩn hóa
    khi so khớp, và từng có dấu cách thừa như 'Mel ' do Data Dragon)."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return _UNSET, 0
    kept = [(v.strip() if strip else v) for v in value if isinstance(v, str) and v.strip()]
    return kept, len(value) - len(kept)


def sanitize_config(config: dict) -> list[str]:
    """Sửa config tại chỗ cho khớp kiểu/khoảng hợp lệ. Trả các dòng thông báo (rỗng nếu không phải sửa gì)."""
    notes: list[str] = []

    def default(key):
        return copy.deepcopy(DEFAULT_CONFIG[key])

    def use_default(key, why):
        old = config[key]
        config[key] = default(key)
        notes.append(f"Cấu hình '{key}': giá trị {old!r} {why}; đã dùng mặc định {config[key]!r}.")

    for key in _BOOL_KEYS:
        value = _to_bool(config[key])
        if value is _UNSET:
            use_default(key, "không phải true/false")
        elif value is not config[key]:
            notes.append(f"Cấu hình '{key}': {config[key]!r} sai kiểu, đã đổi thành {value!r}.")
            config[key] = value

    for key, (lo, hi) in NUMERIC_LIMITS.items():
        old = config[key]
        value = _to_number(old, key in _INT_KEYS)
        if value is _UNSET:
            use_default(key, "không phải số")
            continue
        clamped = min(max(value, lo), hi)
        if clamped != value:
            notes.append(f"Cấu hình '{key}': {old!r} ngoài khoảng {lo}–{hi}, đã kẹp thành {clamped!r}.")
        elif isinstance(old, str) or (key in _INT_KEYS and old != value):  # "5" → 5, 5.7 → 6 (5.0 → 5 thì lặng lẽ)
            notes.append(f"Cấu hình '{key}': {old!r} sai kiểu, đã đổi thành {value!r}.")
        config[key] = clamped

    for key in ("hotkey_toggle", "manual_names", "roll_key"):
        value = config[key]
        if not isinstance(value, str) or (key == "hotkey_toggle" and not value.strip()):
            use_default(key, "không phải chuỗi")
        elif key in ("hotkey_toggle", "roll_key") and value != value.strip():
            notes.append(f"Cấu hình '{key}': {value!r} thừa khoảng trắng (thư viện phím không nhận), đã bỏ.")
            config[key] = value.strip()

    if config["capture_backend"] not in ("auto", "mss"):
        use_default("capture_backend", "chỉ nhận 'auto' hoặc 'mss'")

    if normalize_locale(config["champion_locale"]) != config["champion_locale"]:
        use_default("champion_locale", "không đúng dạng ngôn_NGỮ (vd vi_VN, en_US)")

    for key in ("game_process_names", "selected_champions"):
        value, dropped = _str_list(config[key], strip=(key == "game_process_names"))
        if value is _UNSET or (key == "game_process_names" and not value):
            use_default(key, "không phải danh sách chuỗi" if value is _UNSET else "rỗng")
            continue
        if value != config[key]:
            if dropped:
                what = f"bỏ {dropped} phần tử không phải chuỗi/rỗng"
            elif isinstance(config[key], str):
                what = f"{config[key]!r} là chuỗi, đã đổi thành danh sách 1 phần tử"
            else:
                what = "bỏ khoảng trắng thừa"
            notes.append(f"Cấu hình '{key}': {what} → {value!r}.")
        config[key] = value

    custom = config["custom_templates"]
    if not isinstance(custom, dict):
        use_default("custom_templates", "không phải danh sách ánh xạ tên → đường dẫn")
    else:
        good = {k: v for k, v in custom.items() if isinstance(k, str) and isinstance(v, str)}
        if len(good) != len(custom):
            notes.append(f"Cấu hình 'custom_templates': bỏ {len(custom) - len(good)} mục không hợp lệ.")
        config["custom_templates"] = good

    region = config["shop_region"]
    if region is not None:
        nums = [_to_number(region.get(k), True) if isinstance(region, dict) else _UNSET for k in _REGION_KEYS]
        if _UNSET in nums or nums[2] <= 0 or nums[3] <= 0:
            notes.append(f"Cấu hình 'shop_region': {region!r} không hợp lệ, đã bỏ — hãy chọn lại vùng Shop.")
            config["shop_region"] = None
        else:
            config["shop_region"] = dict(zip(_REGION_KEYS, nums))

    points = config["slot_centers"]
    fixed = _sanitize_points(points)
    if fixed is None:
        notes.append(f"Cấu hình 'slot_centers': {points!r} không hợp lệ, đã bỏ — hãy đặt lại 5 điểm click.")
        config["slot_centers"] = []
    else:
        config["slot_centers"] = fixed
    return notes


def _sanitize_points(points):
    """Danh sách [x, y] nguyên, đúng 5 điểm (hoặc rỗng = chưa đặt); None nếu không dùng được."""
    if not isinstance(points, (list, tuple)) or len(points) not in (0, 5):
        return None
    result = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return None
        xy = [_to_number(v, True) for v in p]
        if _UNSET in xy:
            return None
        result.append(xy)
    return result


def parse_int_in_range(text, lo: int, hi: int) -> int | None:
    """Đọc số nguyên từ ô nhập: trống, chữ, số thập phân (5.5) hoặc ngoài [lo, hi] → None.
    Giao diện báo ô nào sai chứ không tự đoán giá trị."""
    if not isinstance(text, str) or not text.strip():
        return None
    value = _to_number(text, False)
    if value is _UNSET or value != int(value) or not lo <= value <= hi:
        return None
    return int(value)


def _finalize(data: dict | None, notes: list[str]) -> tuple[dict, list[str]]:
    config = _with_defaults(data)
    notes.extend(sanitize_config(config))
    return config, notes


def load_config_with_notes() -> tuple[dict, list[str]]:
    """
    Đọc config.json, gộp với mặc định và làm sạch giá trị sai. Trả (config, notes) — notes là các dòng cần báo
    người dùng (khôi phục file hỏng, giá trị đã sửa). File hỏng: đổi tên thành config.json.bad, thử khôi phục từ
    config.json.bak, không được thì dùng mặc định.
    """
    ensure_dirs()
    notes: list[str] = []
    if not CONFIG_PATH.exists():
        return _finalize(None, notes)

    try:
        return _finalize(_read_config_file(CONFIG_PATH), notes)
    except (OSError, ValueError) as e:  # ValueError gồm JSONDecodeError và UnicodeDecodeError
        bad = _sibling(".bad")
        try:
            os.replace(CONFIG_PATH, bad)
            notes.append(f"{CONFIG_PATH.name} bị hỏng ({type(e).__name__}) — đã đổi tên thành {bad.name}.")
        except OSError:
            notes.append(f"{CONFIG_PATH.name} bị hỏng ({type(e).__name__}) và không đổi tên được.")

    bak = _sibling(".bak")
    if bak.exists():
        try:
            data = _read_config_file(bak)
            shutil.copy2(bak, CONFIG_PATH)
            notes.append(f"Đã khôi phục cấu hình từ {bak.name} (lần lưu trước đó).")
            return _finalize(data, notes)
        except (OSError, ValueError):
            notes.append(f"{bak.name} cũng hỏng.")
    notes.append("Dùng cấu hình mặc định — hãy cấu hình lại vùng Shop và chọn tướng.")
    return _finalize(None, notes)


def save_config(config: dict):
    """
    Lưu cấu hình nguyên tử: ghi file tạm rồi thay thế, nên ngắt giữa chừng không làm cụt config.json.
    Bản hợp lệ của lần lưu trước được giữ ở config.json.bak.
    """
    ensure_dirs()
    text = json.dumps(config, indent=2, ensure_ascii=False)  # lỗi serialize thì chưa đụng tới file nào

    tmp = _sibling(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())

    if CONFIG_PATH.exists():
        try:
            _read_config_file(CONFIG_PATH)  # chỉ sao lưu bản còn đọc được, không để .bak bị đè bởi file hỏng
            shutil.copy2(CONFIG_PATH, _sibling(".bak"))
        except (OSError, ValueError):
            pass
    os.replace(tmp, CONFIG_PATH)
