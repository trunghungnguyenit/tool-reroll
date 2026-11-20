"""Báo cáo chẩn đoán: gom thông tin cần để xem lỗi của người dùng vào MỘT file zip (không cần hỏi từng thứ).

Gồm: phiên bản + máy (Windows, màn hình, quyền Admin, giấy phép), kết quả selftest, cấu hình đã lược tọa độ cá nhân, và các
file log. KHÔNG gồm: chuỗi Key, khóa, ảnh chụp màn hình, ảnh mẫu. File lưu ra Desktop (đúng thư mục Desktop của Windows, kể cả
khi được OneDrive chuyển hướng); không ghi được thì lưu vào data/."""

import ctypes
import json
import platform
import subprocess
import sys
import time
import zipfile
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from core import build_info
from core import config as _config
from core import license as lic
from core import selftest

REPORT_PREFIX = "TFT_Auto_Buy_chan_doan_"
LOG_FILES = ("app.log", "app.log.1", "app.log.2")  # khớp logging_setup (BACKUP_COUNT = 2)
SKIP_WHEN_RUNNING = ("chụp DXGI (tùy chọn)",)  # kiểm tra này mở thêm một phiên chụp màn hình: không làm khi đang quét


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _known_desktop() -> Path | None:
    """Thư mục Desktop thật của người dùng theo Windows (SHGetKnownFolderPath), None nếu không hỏi được."""
    folder_id = _GUID(0xB4BFCC3A, 0xDB2C, 0x424C, (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41))
    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ptr = ctypes.c_void_p()
    if shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(ptr)) != 0 or not ptr.value:
        return None
    try:
        return Path(ctypes.wstring_at(ptr.value))
    finally:
        ole32.CoTaskMemFree(ptr)


def desktop_dir() -> Path:
    """Nơi lưu báo cáo: Desktop của Windows, nếu không có thì ~/Desktop, cuối cùng là data/."""
    try:
        known = _known_desktop()
    except Exception:
        known = None
    for candidate in (known, Path.home() / "Desktop"):
        if candidate is not None and candidate.is_dir():
            return candidate
    return _config.DATA_DIR


def sanitize_config(cfg: dict) -> dict:
    """Cấu hình để gửi đi: giữ mọi cài đặt, lược tọa độ trên màn hình và đường dẫn ảnh cá nhân (chỉ giữ kích thước/số lượng)."""
    out = {k: v for k, v in cfg.items() if k not in ("shop_region", "slot_centers", "custom_templates")}
    region = cfg.get("shop_region")
    out["shop_region"] = f"{region.get('width')}x{region.get('height')} (vị trí đã lược)" if isinstance(region, dict) else "chưa chọn"
    out["slot_centers"] = f"{len(cfg.get('slot_centers') or [])} điểm (tọa độ đã lược)"
    out["custom_templates"] = f"{len(cfg.get('custom_templates') or {})} ảnh tự tải lên (đường dẫn đã lược)"
    return out


def _screen_info() -> str:
    u = ctypes.windll.user32
    return (f"{u.GetSystemMetrics(80)} màn hình; màn hình chính {u.GetSystemMetrics(0)}x{u.GetSystemMetrics(1)}; "
            f"toàn bộ vùng ảo {u.GetSystemMetrics(78)}x{u.GetSystemMetrics(79)}")


def _license_lines() -> list[str]:
    try:
        code = lic.machine_code()
    except lic.LicenseError as e:
        code = f"không đọc được ({e})"
    status = lic.check_installed()
    lines = [f"Mã máy: {code}"]
    if status.ok and status.info:
        when = datetime.fromtimestamp(status.activated_at).strftime("%Y-%m-%d %H:%M") if status.activated_at else "không rõ"
        lines += ["Giấy phép: hợp lệ", f"Key ID: {status.info.key_id}", f"Kích hoạt lúc: {when}"]
    else:
        lines.append(f"Giấy phép: không hợp lệ ({status.reason})")
    return lines


def system_info(running: bool, now: datetime) -> str:
    try:
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        admin = None
    lines = [
        f"Tạo lúc: {now:%Y-%m-%d %H:%M:%S}",
        f"Phiên bản: {build_info.describe()}",
        f"Windows: {platform.platform()}",
        f"Python: {sys.version.split()[0]} ({'đóng gói' if getattr(sys, 'frozen', False) else 'mã nguồn'})",
        f"Màn hình: {_screen_info()}",
        f"Quyền Admin: {'có' if admin else 'không' if admin is not None else 'không rõ'}",
        f"Đang quét khi tạo báo cáo: {'có' if running else 'không'}",
        *_license_lines(),
    ]
    return "\n".join(lines) + "\n"


def _entries(cfg: dict, running: bool, now: datetime) -> dict[str, bytes]:
    results = selftest.collect_checks(skip=SKIP_WHEN_RUNNING if running else ())
    selftest_text = selftest.format_results(results)
    if running:
        selftest_text += "(Đang quét: bỏ qua kiểm tra DXGI để không ảnh hưởng việc chụp màn hình.)\n"
    entries = {
        "thong-tin.txt": system_info(running, now).encode("utf-8"),
        "selftest.txt": selftest_text.encode("utf-8"),
        "config.json": json.dumps(sanitize_config(cfg), ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
    }
    for name in LOG_FILES:
        try:
            entries[f"logs/{name}"] = (_config.DATA_DIR / name).read_bytes()
        except OSError:
            continue  # chưa có (log xoay vòng chưa tới file đó) hoặc không đọc được
    return entries


def _write_zip(folder: Path, name: str, entries: dict[str, bytes], stamp: time.struct_time) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry, data in entries.items():
            info = zipfile.ZipInfo(entry, date_time=stamp[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return path


def write_report(cfg: dict, running: bool = False, dest_dir: Path | None = None, now: datetime | None = None) -> Path:
    """Tạo file zip báo cáo và trả đường dẫn. `dest_dir` mặc định là Desktop; không ghi được Desktop thì lưu vào data/."""
    now = now or datetime.now()
    entries = _entries(cfg, running, now)
    name = f"{REPORT_PREFIX}{now:%Y%m%d_%H%M%S}.zip"
    stamp = now.timetuple()
    if dest_dir is not None:
        return _write_zip(Path(dest_dir), name, entries, stamp)
    try:
        return _write_zip(desktop_dir(), name, entries, stamp)
    except OSError:
        return _write_zip(_config.DATA_DIR, name, entries, stamp)


def reveal_in_explorer(path: Path) -> None:
    """Mở thư mục chứa file và chọn sẵn file đó. Không mở được cũng không sao (đường dẫn đã có trong Nhật ký)."""
    try:
        subprocess.Popen(f'explorer /select,"{path}"')
    except OSError:
        pass
