"""Các file đóng gói/repo phải nhất quán: thêm module mới mà quên khai báo thì exe thiếu module và chỉ lộ ra khi chạy."""

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import selftest

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _core_modules() -> set[str]:
    return {f"core.{p.stem}" for p in (ROOT / "core").glob("*.py") if p.stem != "__init__" and not p.stem.startswith("_")}


def _spec_hiddenimports() -> set[str]:
    tree = ast.parse(_read("TFT_Auto_Buy.spec"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "hiddenimports":
            return {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    raise AssertionError("không thấy hiddenimports trong spec")


def test_every_core_module_is_in_spec_hiddenimports():
    missing = _core_modules() - _spec_hiddenimports()
    assert not missing, f"module chưa có trong hiddenimports của spec: {sorted(missing)}"


def test_every_ui_module_is_in_spec_and_selftest():
    ui = {f"ui.{p.stem}" for p in (ROOT / "ui").glob("*.py") if p.stem != "__init__"}
    assert ui <= _spec_hiddenimports(), sorted(ui - _spec_hiddenimports())
    assert set(selftest.UI_MODULES) == ui


def test_spec_excludes_tk_and_unused_qt_modules():
    tree = ast.parse(_read("TFT_Auto_Buy.spec"))
    excludes = next(
        {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
        for node in ast.walk(tree) if isinstance(node, ast.keyword) and node.arg == "excludes"
    )
    assert {"tkinter", "PySide6.QtNetwork", "PySide6.QtQml"} <= excludes
    assert not excludes & {"PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"}


def test_requirements_pin_qt():
    assert any(ln.startswith("PySide6-Essentials==") for ln in _read("requirements.txt").splitlines())


def test_spec_declares_signature_library_and_its_cffi_backend():
    """Key ký số cần PyNaCl, và PyNaCl cần _cffi_backend: thiếu thì exe đóng gói không nạp được core.license (selftest bắt)."""
    assert {"nacl.signing", "_cffi_backend"} <= _spec_hiddenimports()
    assert any(ln.startswith("PyNaCl==") for ln in _read("requirements.txt").splitlines())


def test_spec_declares_build_stamp_module():
    assert "core._build_stamp" in _spec_hiddenimports()  # file sinh lúc build, không có trong git


def test_every_core_module_is_checked_by_selftest():
    assert set(selftest.CORE_MODULES) == _core_modules()


def test_spec_writes_build_stamp_before_analysis():
    spec = _read("TFT_Auto_Buy.spec")
    assert "write_build_stamp(" in spec
    assert spec.index("write_build_stamp(") < spec.index("Analysis(")


def test_spec_bumps_version_before_writing_stamp_and_passes_it_on():
    spec = _read("TFT_Auto_Buy.spec")
    assert spec.index("prepare_version(") < spec.index("write_build_stamp(") < spec.index("Analysis(")
    start = spec.index("write_build_stamp(")
    stamp_call = spec[start:spec.index(chr(10), start)]
    assert "version" in stamp_call  # phiên bản vừa tính phải vào stamp, nếu không exe không biết số của mình


def test_version_files_are_tracked_not_ignored():
    """VERSION và .version_hash phải vào git: máy khác build tiếp đúng số, không bị đếm lại từ đầu."""
    if shutil.which("git") is None:
        pytest.skip("không có git")
    for name in ("VERSION", ".version_hash"):
        r = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT)
        assert r.returncode == 1, f"{name} đang bị .gitignore bỏ qua"


def test_build_bat_runs_tests_before_packaging():
    bat = _read("build.bat")
    assert "-m pytest" in bat
    assert bat.index("-m pytest") < bat.index("-m PyInstaller")
    after_pytest = bat[bat.index("-m pytest"):bat.index("-m PyInstaller")]
    assert "errorlevel" in after_pytest and "exit /b 1" in after_pytest  # test hỏng thì dừng, không đóng gói


def test_build_bat_installs_pinned_build_requirements_and_runs_selftest():
    bat = _read("build.bat")
    assert "requirements-build.txt" in bat
    assert "--selftest" in bat
    assert bat.index("-m PyInstaller") < bat.index("--selftest")


def test_build_bat_is_ascii_only_for_cmd():
    # cmd.exe đọc theo code page của máy: chữ có dấu trong echo sẽ vỡ thành ký tự lạ.
    _read("build.bat").encode("ascii")


def test_requirements_build_pins_pyinstaller_and_includes_dev():
    lines = [ln.strip() for ln in _read("requirements-build.txt").splitlines() if ln.strip() and not ln.startswith("#")]
    assert "-r requirements-dev.txt" in lines
    assert any(re.fullmatch(r"pyinstaller==\d+(\.\d+)+", ln) for ln in lines)


def test_gitignore_covers_user_data_and_generated_files():
    entries = {ln.strip() for ln in _read(".gitignore").splitlines()}
    for must in ("data/", "dist/", "build/", "core/_build_stamp.py"):
        assert must in entries, must


def test_main_handles_selftest_flag_before_starting_the_app():
    tree = ast.parse(_read("main.py"))
    guard = next(n for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test))
    src = ast.unparse(guard)
    assert "--selftest" in src
    assert src.index("run_selftest") < src.index("run_app")


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="không có git")
def test_personal_files_are_not_tracked_by_git():
    out = subprocess.run(["git", "ls-files", "data", "lenh_claude_new.md"], cwd=ROOT, capture_output=True, text=True).stdout
    assert out.strip() == "", f"file cá nhân vẫn bị git theo dõi:\n{out}"


def test_flow_doc_lists_every_config_key():
    from core.config import DEFAULT_CONFIG

    doc = _read("LUONG_CHAY.md")
    missing = [k for k in [*DEFAULT_CONFIG, "coords_version"] if f"`{k}`" not in doc]
    assert not missing, f"LUONG_CHAY.md chưa mô tả key config: {missing}"
