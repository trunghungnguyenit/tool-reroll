import sys
from pathlib import Path

import pytest

from core import config, selftest


@pytest.fixture(autouse=True)
def _fast_checks(monkeypatch, tmp_path):
    """Chạy thật nhưng không phụ thuộc OCR/màn hình của máy: các kiểm tra nặng được thay bằng bản giả."""
    monkeypatch.setattr(selftest, "_capture_check", lambda: "chụp được 8x8")
    monkeypatch.setattr(selftest, "_dxgi_check", lambda: "dùng được, 1.0 ms mỗi khung")
    monkeypatch.setattr(selftest, "_ocr_check", lambda: "OCR ok")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")


def _by_name(results):
    return {name: (ok, detail) for ok, name, detail in results}


def test_all_checks_present_and_pass():
    results = selftest.collect_checks()
    names = [n for _, n, _ in results]
    assert names == ["phiên bản", "module của app", "module giao diện", "thư viện ngoài", "chụp màn hình (mss)", "chụp DXGI (tùy chọn)", "OCR (Windows)",
                     "giấy phép (mã ký số)", "khóa một-bản-chạy", "thư mục data"]
    assert all(ok for ok, _, _ in results), results


def test_license_check_runs_without_activation_and_needs_no_private_key(tmp_path, monkeypatch):
    """Selftest của exe chưa kích hoạt vẫn phải đạt: nó chỉ kiểm tra thư viện ký số/DPAPI, không đọc giấy phép."""
    from core import license as lic

    monkeypatch.setattr(lic, "LICENSE_PATH", tmp_path / "none.dat")
    ok, detail = _by_name(selftest.collect_checks())["giấy phép (mã ký số)"]
    assert ok and "Ed25519" in detail
    assert not (tmp_path / "none.dat").exists()


def test_version_check_reports_python_and_mode(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    ok, detail = _by_name(selftest.collect_checks())["phiên bản"]
    assert ok and "Python " in detail and "mã nguồn" in detail
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert "đóng gói" in _by_name(selftest.collect_checks())["phiên bản"][1]


def test_missing_module_is_reported_with_its_name(monkeypatch):
    monkeypatch.setattr(selftest, "THIRD_PARTY", ("json", "module_khong_ton_tai_xyz"))
    ok, detail = _by_name(selftest.collect_checks())["thư viện ngoài"]
    assert not ok and "module_khong_ton_tai_xyz" in detail and "json (" not in detail


def test_one_failing_check_does_not_stop_the_others(monkeypatch):
    def boom():
        raise RuntimeError("không có màn hình")

    monkeypatch.setattr(selftest, "_capture_check", boom)
    res = _by_name(selftest.collect_checks())
    assert res["chụp màn hình (mss)"][0] is False and "không có màn hình" in res["chụp màn hình (mss)"][1]
    assert res["OCR (Windows)"][0] and res["thư mục data"][0]


def test_does_not_create_data_dir(tmp_path):
    selftest.collect_checks()
    assert not (tmp_path / "data").exists()


def test_data_dir_check_existing_and_unwritable(monkeypatch, tmp_path):
    (tmp_path / "data").mkdir()
    assert "đã có" in selftest._data_dir_check()
    monkeypatch.setattr(selftest.os, "access", lambda p, mode: False)
    with pytest.raises(RuntimeError, match="không ghi được"):
        selftest._data_dir_check()


def test_mutex_check_does_not_hold_the_real_instance_lock():
    selftest._mutex_check()
    from core import single_instance as si

    lock = si.acquire_instance_lock()  # khóa thật vẫn lấy được sau khi tự kiểm tra
    assert lock is not None
    lock.release()


def test_run_selftest_ok_writes_report_and_returns_0(tmp_path, capsys):
    report = tmp_path / "r.txt"
    assert selftest.run_selftest(report) == 0
    text = report.read_text(encoding="utf-8")
    assert "Kết quả: ĐẠT" in text and text.count("[OK ]") == 10
    assert "Kết quả: ĐẠT" in capsys.readouterr().out


def test_run_selftest_failure_returns_1_and_lists_it(tmp_path, monkeypatch):
    monkeypatch.setattr(selftest, "CORE_MODULES", ("core.khong_co",))
    report = tmp_path / "r.txt"
    assert selftest.run_selftest(report) == 1
    text = report.read_text(encoding="utf-8")
    assert "[LỖI] module của app" in text and "core.khong_co" in text and "1 kiểm tra LỖI" in text


def test_run_selftest_without_console_and_unwritable_report(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)  # exe windowed: không có stdout
    assert selftest.run_selftest(tmp_path) == 0  # đường dẫn là thư mục -> ghi lỗi nhưng không đổi mã thoát


def test_default_report_is_in_temp_dir():
    assert isinstance(selftest.DEFAULT_REPORT, Path)
    assert selftest.DEFAULT_REPORT.parent == Path(__import__("tempfile").gettempdir())


class TestDxgiCheck:
    def test_unavailable_dxgi_is_information_not_a_failure(self, monkeypatch):
        monkeypatch.undo()  # dùng hàm thật, chỉ thay open_dxgi
        import core.capture as cap

        monkeypatch.setattr(cap, "open_dxgi", lambda region, ref: (None, "DXGI trả khung đen"))
        detail = selftest._dxgi_check()
        assert "không dùng được (DXGI trả khung đen)" in detail and "mss" in detail

    def test_available_dxgi_reports_speed(self, monkeypatch):
        monkeypatch.undo()
        import core.capture as cap

        class Src:
            n = 0

            def grab(self):
                Src.n += 1

            def close(self):
                Src.closed = True

        monkeypatch.setattr(cap, "open_dxgi", lambda region, ref: (Src(), "DXGI"))
        detail = selftest._dxgi_check()
        assert detail.startswith("dùng được,") and "ms mỗi khung" in detail and Src.n == 20 and Src.closed
