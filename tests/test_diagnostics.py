"""Báo cáo chẩn đoán (zip): nội dung, lược dữ liệu cá nhân, không lộ Key, nơi lưu và dự phòng."""

import base64
import json
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from nacl.signing import SigningKey

from core import diagnostics as dg
from core import license as lic
from core import selftest

NOW = datetime(2026, 11, 20, 8, 54, 43)
CFG = {
    "theme": "dark", "roll_key": "d", "selected_champions": ["Vex", "Zoe"], "manual_names": "Ahri",
    "shop_region": {"left": 12345, "top": 6789, "width": 1200, "height": 200},
    "slot_centers": [[1111 + i, 2222] for i in range(5)],
    "custom_templates": {"Vex": r"C:\Users\ten-rieng\anh\vex.png"},
}


@pytest.fixture(autouse=True)
def _fast_checks(monkeypatch, tmp_path):
    """Không chạy các kiểm tra nặng thật (chụp màn hình, OCR): thay bằng kết quả cố định, ghi lại tham số skip."""
    calls = []

    def fake_collect(skip=()):
        calls.append(skip)
        return [(True, "phiên bản", "1.0.0.1"), (False, "chụp DXGI (tùy chọn)", "lỗi giả")] if not skip else [(True, "phiên bản", "1.0.0.1")]

    monkeypatch.setattr(selftest, "collect_checks", fake_collect)
    monkeypatch.setattr(dg.lic, "check_installed", lambda *a: lic.Status(False, "Chưa kích hoạt.", missing=True))
    monkeypatch.setattr(dg.lic, "machine_code", lambda: "AAAA-BBBB-CCCC-DDDD")
    return calls


@pytest.fixture
def skip_calls(_fast_checks):
    return _fast_checks


def read_zip(path):
    with zipfile.ZipFile(path) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


class TestSanitizeConfig:
    def test_hides_coordinates_and_personal_paths_but_keeps_sizes_and_settings(self):
        out = dg.sanitize_config(CFG)
        text = json.dumps(out, ensure_ascii=False)
        for secret in ("12345", "6789", "1111", "2222", "ten-rieng", "vex.png"):
            assert secret not in text
        assert out["shop_region"].startswith("1200x200") and "5 điểm" in out["slot_centers"]
        assert out["custom_templates"].startswith("1 ảnh")
        assert out["theme"] == "dark" and out["selected_champions"] == ["Vex", "Zoe"] and out["manual_names"] == "Ahri"

    def test_missing_or_broken_values_do_not_crash(self):
        out = dg.sanitize_config({"shop_region": None, "slot_centers": None, "custom_templates": None})
        assert out["shop_region"] == "chưa chọn" and out["slot_centers"].startswith("0 điểm") and out["custom_templates"].startswith("0 ảnh")
        assert dg.sanitize_config({"shop_region": "hỏng"})["shop_region"] == "chưa chọn"

    def test_does_not_modify_the_original(self):
        before = json.dumps(CFG, sort_keys=True)
        dg.sanitize_config(CFG)
        assert json.dumps(CFG, sort_keys=True) == before


class TestWriteReport:
    def test_zip_has_expected_files_and_name(self, tmp_path, data_dir):
        data_dir.mkdir()
        (data_dir / "app.log").write_bytes("dòng log 1\n".encode("utf-8"))  # bytes: write_text đổi \n thành \r\n trên Windows
        (data_dir / "app.log.1").write_bytes("log cũ\n".encode("utf-8"))
        path = dg.write_report(CFG, dest_dir=tmp_path / "out", now=NOW)
        assert path.name == "TFT_Auto_Buy_chan_doan_20261120_085443.zip" and path.parent == tmp_path / "out"
        files = read_zip(path)
        assert set(files) == {"thong-tin.txt", "selftest.txt", "config.json", "logs/app.log", "logs/app.log.1"}
        assert files["logs/app.log"].decode("utf-8") == "dòng log 1\n" and files["logs/app.log.1"].decode("utf-8") == "log cũ\n"

    def test_info_has_version_machine_and_license_state(self, tmp_path):
        info = read_zip(dg.write_report(CFG, dest_dir=tmp_path, now=NOW))["thong-tin.txt"].decode("utf-8")
        for needle in ("Tạo lúc: 2026-11-20 08:54:43", "Phiên bản:", "Windows:", "Python:", "Màn hình:", "Quyền Admin:",
                       "Đang quét khi tạo báo cáo: không", "Mã máy: AAAA-BBBB-CCCC-DDDD", "Giấy phép: không hợp lệ (Chưa kích hoạt.)"):
            assert needle in info, needle

    def test_info_contains_the_real_version_description(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dg.build_info, "describe", lambda: "9.8.7.6, build 2026-01-02 03:04 (abc1234)")
        info = read_zip(dg.write_report(CFG, dest_dir=tmp_path, now=NOW))["thong-tin.txt"].decode("utf-8")
        assert "Phiên bản: 9.8.7.6, build 2026-01-02 03:04 (abc1234)" in info

    def test_valid_license_shows_key_id_but_never_the_key_string(self, tmp_path, monkeypatch):
        seller = SigningKey.generate()
        machine = bytes(range(16))
        monkeypatch.undo()  # bỏ bản giả check_installed của fixture: dùng giấy phép thật trong thư mục tạm
        monkeypatch.setattr(selftest, "collect_checks", lambda skip=(): [(True, "x", "y")])
        monkeypatch.setattr(lic, "LICENSE_PATH", tmp_path / "license.dat")
        monkeypatch.setattr(lic, "USED_PATH", tmp_path / "used.dat")
        monkeypatch.setattr(lic, "PUBLIC_KEY_B64", base64.b64encode(bytes(seller.verify_key)).decode())
        monkeypatch.setattr(lic, "machine_hash", lambda: machine)
        monkeypatch.setattr(lic.build_info, "build_time", lambda: None)
        key = lic.issue_key(seller, lic.format_machine_code(machine))
        info = lic.activate(key)
        files = read_zip(dg.write_report(CFG, dest_dir=tmp_path / "out", now=NOW))
        text = files["thong-tin.txt"].decode("utf-8")
        assert "Giấy phép: hợp lệ" in text and f"Key ID: {info.key_id}" in text and "Kích hoạt lúc:" in text
        canonical = lic._canonical(key).encode("ascii")
        for name, data in files.items():  # chuỗi Key (kể cả dạng đã bỏ dấu gạch) không được xuất hiện ở bất kỳ file nào
            assert canonical not in data.replace(b"-", b""), name
            assert key.encode("ascii") not in data, name

    def test_config_in_zip_is_sanitized(self, tmp_path):
        text = read_zip(dg.write_report(CFG, dest_dir=tmp_path, now=NOW))["config.json"].decode("utf-8")
        assert "12345" not in text and "ten-rieng" not in text and '"theme": "dark"' in text
        json.loads(text)  # hợp lệ

    def test_no_screenshots_or_templates_included(self, tmp_path, data_dir):
        data_dir.mkdir()
        (data_dir / "shop_capture.png").write_bytes(b"\x89PNG")
        (data_dir / "config.json").write_text("{}", encoding="utf-8")
        files = read_zip(dg.write_report(CFG, dest_dir=tmp_path, now=NOW))
        assert not [n for n in files if n.endswith(".png") or n.startswith("templates")]
        assert "logs/app.log" not in files  # chưa có log thì không có mục log, không lỗi

    def test_running_skips_dxgi_check_and_says_so(self, tmp_path, skip_calls):
        files = read_zip(dg.write_report(CFG, running=True, dest_dir=tmp_path, now=NOW))
        assert skip_calls[-1] == dg.SKIP_WHEN_RUNNING
        assert "bỏ qua kiểm tra DXGI" in files["selftest.txt"].decode("utf-8")
        assert "Đang quét khi tạo báo cáo: có" in files["thong-tin.txt"].decode("utf-8")

    def test_not_running_runs_every_check(self, tmp_path, skip_calls):
        text = read_zip(dg.write_report(CFG, dest_dir=tmp_path, now=NOW))["selftest.txt"].decode("utf-8")
        assert skip_calls[-1] == () and "bỏ qua" not in text and "[LỖI] chụp DXGI" in text and "1 kiểm tra LỖI" in text

    def test_machine_code_error_is_reported_not_raised(self, tmp_path, monkeypatch):
        def boom():
            raise lic.LicenseError("không đọc được định danh")

        monkeypatch.setattr(dg.lic, "machine_code", boom)
        info = read_zip(dg.write_report(CFG, dest_dir=tmp_path, now=NOW))["thong-tin.txt"].decode("utf-8")
        assert "Mã máy: không đọc được (không đọc được định danh)" in info

    def test_unreadable_log_is_skipped(self, tmp_path, data_dir, monkeypatch):
        data_dir.mkdir()
        (data_dir / "app.log").write_text("x", encoding="utf-8")
        real = Path.read_bytes

        def deny(self):
            if self.name == "app.log":
                raise PermissionError(13, "bị khóa")
            return real(self)

        monkeypatch.setattr(Path, "read_bytes", deny)
        assert "logs/app.log" not in read_zip(dg.write_report(CFG, dest_dir=tmp_path, now=NOW))


class TestWhereItIsSaved:
    def test_default_destination_is_the_desktop(self, tmp_path, monkeypatch):
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        monkeypatch.setattr(dg, "desktop_dir", lambda: desktop)
        assert dg.write_report(CFG, now=NOW).parent == desktop

    def test_falls_back_to_data_dir_when_desktop_is_not_writable(self, tmp_path, monkeypatch, data_dir):
        blocker = tmp_path / "la-mot-file"
        blocker.write_text("x")  # mkdir trên đường dẫn là file → OSError
        monkeypatch.setattr(dg, "desktop_dir", lambda: blocker / "Desktop")
        path = dg.write_report(CFG, now=NOW)
        assert path.parent == data_dir and path.exists()

    def test_explicit_destination_errors_are_not_hidden(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        with pytest.raises(OSError):
            dg.write_report(CFG, dest_dir=blocker / "sub", now=NOW)

    def test_desktop_dir_prefers_windows_known_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dg, "_known_desktop", lambda: tmp_path)
        assert dg.desktop_dir() == tmp_path

    def test_desktop_dir_falls_back_to_home_then_data(self, tmp_path, monkeypatch, data_dir):
        (tmp_path / "Desktop").mkdir()
        monkeypatch.setattr(dg, "_known_desktop", lambda: None)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        assert dg.desktop_dir() == tmp_path / "Desktop"
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "khong-co"))
        assert dg.desktop_dir() == data_dir

    def test_known_folder_failure_is_swallowed(self, tmp_path, monkeypatch, data_dir):
        def boom():
            raise OSError("shell32 hỏng")

        monkeypatch.setattr(dg, "_known_desktop", boom)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "khong-co"))
        assert dg.desktop_dir() == data_dir

    def test_real_known_folder_is_an_existing_directory(self):
        folder = dg._known_desktop()
        assert folder is None or folder.is_dir()  # máy thật: Desktop (kể cả khi OneDrive chuyển hướng)


class TestReveal:
    def test_opens_explorer_with_file_selected(self, monkeypatch):
        seen = []
        monkeypatch.setattr(subprocess, "Popen", lambda cmd, *a, **k: seen.append(cmd))
        dg.reveal_in_explorer(Path(r"C:\Users\A B\Desktop\x.zip"))
        assert seen == [r'explorer /select,"C:\Users\A B\Desktop\x.zip"']

    def test_failure_to_open_is_ignored(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("không có explorer")

        monkeypatch.setattr(subprocess, "Popen", boom)
        dg.reveal_in_explorer(Path("x.zip"))  # không ném
