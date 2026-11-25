"""Tự kiểm tra bản đang chạy (đặc biệt là exe đóng gói): `TFT_Auto_Buy.exe --selftest`.

Exe không có console nên kết quả ghi ra file. Dùng để kiểm tra việc đóng gói (thiếu module ẩn, thiếu DLL của winrt/OpenCV),
không cần mở giao diện, và build.bat chạy nó ngay sau khi đóng gói. Không tạo thư mục data/ nếu chưa có."""

import importlib
import os
import sys
import tempfile
import uuid
from pathlib import Path

from core import build_info
from core import config as _config

# Phải khớp các file trong core/ (tests/test_build_files.py kiểm tra) và hiddenimports của TFT_Auto_Buy.spec.
CORE_MODULES = (
    "core.build_info", "core.buyer", "core.capture", "core.cards", "core.champion_details", "core.champions", "core.config", "core.controller", "core.diagnostics", "core.dpi", "core.game_window", "core.hotkey",
    "core.license", "core.logging_setup", "core.monitors", "core.name_matcher", "core.ocr_check", "core.ocr_pool", "core.portraits", "core.preview", "core.profiles", "core.scanner",
    "core.selftest", "core.single_instance"
)
UI_MODULES = ("ui.app", "ui.champion_dialog", "ui.champion_view", "ui.license_dialog", "ui.main_window", "ui.overlay", "ui.selected_panel", "ui.theme", "ui.widgets")
THIRD_PARTY = (
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PIL.Image", "cv2", "numpy", "mss", "keyboard", "requests",
    "winocr", "winrt.windows.media.ocr", "dxcam", "comtypes", "nacl.signing",
)

DEFAULT_REPORT = Path(tempfile.gettempdir()) / "TFT_Auto_Buy_selftest.txt"


def _import_check(names) -> str:
    missing = []
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as e:  # ImportError, hoặc lỗi nạp DLL
            missing.append(f"{name} ({type(e).__name__}: {str(e)[:80]})")
    if missing:
        raise RuntimeError("không nạp được: " + "; ".join(missing))
    return f"{len(names)} module"


def _capture_check() -> str:
    import mss

    with mss.MSS() as sct:
        shot = sct.grab({"left": 0, "top": 0, "width": 8, "height": 8})
    return f"chụp được {shot.size.width}x{shot.size.height}"


def _dxgi_check() -> str:
    """DXGI là tùy chọn (phụ thuộc máy/game): không dùng được thì app dùng mss, nên đây chỉ là thông tin, không phải lỗi."""
    import time

    import mss
    import numpy as np

    from core.capture import open_dxgi

    region = {"left": 0, "top": 0, "width": 64, "height": 32}
    with mss.MSS() as sct:
        source, why = open_dxgi(region, lambda: np.asarray(sct.grab(region), dtype=np.uint8)[:, :, :3])
        if source is None:
            return f"không dùng được ({why}) — app sẽ chụp bằng mss"
        try:
            t0 = time.perf_counter()
            for _ in range(20):
                source.grab()
            return f"dùng được, {(time.perf_counter() - t0) / 20 * 1000:.1f} ms mỗi khung"
        finally:
            source.close()


def _license_check() -> str:
    """Không cần máy đã kích hoạt: chỉ chứng minh mã ký số (libsodium), mã máy và DPAPI chạy được trong bản đóng gói."""
    from nacl.signing import SigningKey

    from core import license as lic

    machine = lic.machine_hash()
    key = SigningKey.generate()
    text = lic.issue_key(key, lic.format_machine_code(machine))
    lic.verify_key(text, machine, bytes(key.verify_key))
    if lic._dpapi(lic._dpapi(b"selftest", protect=True), protect=False) != b"selftest":
        raise RuntimeError("DPAPI trả dữ liệu sai")
    lic.public_key_bytes()
    return "chữ ký Ed25519, mã máy và DPAPI hoạt động"


def _ocr_check() -> str:
    from core.ocr_check import check_ocr

    status = check_ocr()
    if not status.ok:
        raise RuntimeError(status.detail)
    return status.summary


def _mutex_check() -> str:
    from core import single_instance as si

    lock = si.acquire_instance_lock(f"Local\\TFTAutoBuy.SelfTest.{uuid.uuid4().hex}")
    if lock is None:
        raise RuntimeError("không tạo được mutex")
    lock.release()
    return "ok"


def _data_dir_check() -> str:
    """Thư mục data/ (cạnh exe) ghi được không? Không tạo mới: nếu chưa có thì kiểm tra thư mục cha."""
    data = _config.DATA_DIR
    target = data if data.exists() else data.parent
    if not os.access(target, os.W_OK):
        raise RuntimeError(f"không ghi được vào {target}")
    return f"{data} ({'đã có' if data.exists() else 'sẽ được tạo khi chạy'})"


def collect_checks() -> list[tuple[bool, str, str]]:
    """[(đạt?, tên kiểm tra, chi tiết)]. Lỗi của từng kiểm tra được ghi lại, không làm dừng các kiểm tra khác."""
    checks = [
        ("phiên bản", lambda: f"{build_info.describe()} | Python {sys.version.split()[0]} | "
                              f"{'đóng gói' if getattr(sys, 'frozen', False) else 'mã nguồn'}"),
        ("module của app", lambda: _import_check(CORE_MODULES)),
        ("module giao diện", lambda: _import_check(UI_MODULES)),
        ("thư viện ngoài", lambda: _import_check(THIRD_PARTY)),
        ("chụp màn hình (mss)", _capture_check),
        ("chụp DXGI (tùy chọn)", _dxgi_check),
        ("OCR (Windows)", _ocr_check),
        ("giấy phép (mã ký số)", _license_check),
        ("khóa một-bản-chạy", _mutex_check),
        ("thư mục data", _data_dir_check),
    ]
    results = []
    for name, fn in checks:
        try:
            results.append((True, name, str(fn())))
        except Exception as e:
            results.append((False, name, f"{type(e).__name__}: {e}"))
    return results


def run_selftest(report_path: Path | None = None) -> int:
    """Chạy các kiểm tra, ghi báo cáo ra file (và stdout nếu có). Mã thoát 0 nếu đạt hết, 1 nếu có lỗi."""
    results = collect_checks()
    failed = sum(1 for ok, _, _ in results if not ok)
    lines = [f"[{'OK ' if ok else 'LỖI'}] {name}: {detail}" for ok, name, detail in results]
    lines.append(f"Kết quả: {'ĐẠT' if not failed else f'{failed} kiểm tra LỖI'}")
    text = "\n".join(lines) + "\n"
    path = Path(report_path) if report_path else DEFAULT_REPORT
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass  # không ghi được báo cáo cũng không làm đổi mã thoát
    if sys.stdout:  # exe không có console thì stdout là None
        try:
            print(text, end="")
        except (OSError, UnicodeError):
            pass
    return 1 if failed else 0
