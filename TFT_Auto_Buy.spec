# PyInstaller spec — chay: pyinstaller TFT_Auto_Buy.spec  hoac  build.bat

import sys
from datetime import datetime
from pathlib import Path

block_cipher = None
root = Path(SPECPATH)

# Tăng phiên bản (1.0.0.N) nếu mã nguồn đã đổi so với lần build trước, rồi ghi phiên bản + ngày giờ build + mã commit vào
# core/_build_stamp.py TRƯỚC khi phân tích mã (app in phiên bản ở dòng đầu Nhật ký).
sys.path.insert(0, str(root))
from core.build_info import git_commit, prepare_version, write_build_stamp  # noqa: E402

version = prepare_version(root)
write_build_stamp(root / "core" / "_build_stamp.py", datetime.now(), git_commit(root), version)

a = Analysis(
    ["main.py"],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "core",
        "core.config",
        "core.scanner",
        "core.buyer",
        "core.game_window",
        "core.dpi",
        "core.logging_setup",
        "core.single_instance",
        "core.ocr_check",
        "core.hotkey",
        "core.ocr_pool",
        "core.build_info",
        "core.license",
        "core.capture",
        "core.controller",
        "core._build_stamp",
        "core.selftest",
        "core.champions",
        "core.name_matcher",
        "core.preview",
        "ui",
        "ui.app",
        "ui.champion_view",
        "ui.license_dialog",
        "ui.main_window",
        "ui.overlay",
        "ui.theme",
        "ui.widgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "keyboard",
        "keyboard._winkeyboard",
        "mss",
        "cv2",
        "PIL",
        "PIL.Image",
        "numpy",
        "requests",
        "winocr",
        "dxcam",
        "dxcam.core",
        "dxcam.core.backend",
        "dxcam.core.capture_loop",
        "dxcam.core.capture_runtime",
        "dxcam.core.device",
        "dxcam.core.display_recovery",
        "dxcam.core.duplicator",
        "dxcam.core.dxgi_duplicator",
        "dxcam.core.dxgi_errors",
        "dxcam.core.output",
        "dxcam.core.output_recovery",
        "dxcam.core.stagesurf",
        "dxcam.core.winrt_duplicator",
        "dxcam.dxcam",
        "dxcam.processor",
        "dxcam.processor.base",
        "dxcam.processor.cv2_processor",
        "dxcam.processor.numpy_processor",
        "dxcam.processor._numpy_kernels",
        "dxcam.types",
        "dxcam.util",
        "dxcam.util.io",
        "dxcam.util.timer",
        "dxcam._libs",
        "dxcam._libs.d3d11",
        "dxcam._libs.dxgi",
        "dxcam._libs.user32",
        "comtypes",
        "comtypes.client",
        "_cffi_backend",  # PyNaCl nạp libsodium qua cffi; thiếu thì exe báo No module named _cffi_backend
        "nacl",
        "nacl.signing",
        "nacl.exceptions",
        "winrt",
        "winrt.windows.foundation",
        "winrt.windows.foundation.collections",
        "winrt.windows.graphics.imaging",
        "winrt.windows.media.ocr",
        "winrt.windows.storage",
        "winrt.windows.storage.streams",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Chỉ dùng QtCore/QtGui/QtWidgets: loại phần còn lại của Qt (và Tk, không còn dùng) để exe không phình.
    excludes=[
        "tkinter", "_tkinter",
        "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets", "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtDBus", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtConcurrent", "PySide6.QtXml",
        "PySide6.QtPrintSupport", "PySide6.QtHelp", "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtWebEngineCore",
        "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtBluetooth", "PySide6.QtCharts",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="TFT_Auto_Buy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX hay bị antivirus báo nhầm, nhất là exe có hook bàn phím
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
