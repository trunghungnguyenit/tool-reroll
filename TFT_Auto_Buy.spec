# PyInstaller spec — chay: pyinstaller TFT_Auto_Buy.spec  hoac  build.bat

import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH)

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
        "core.champions",
        "core.name_matcher",
        "core.preview",
        "keyboard",
        "keyboard._winkeyboard",
        "mss",
        "cv2",
        "PIL",
        "PIL.Image",
        "PIL.ImageTk",
        "numpy",
        "requests",
        "winocr",
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
    excludes=[],
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
    upx=True,
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
