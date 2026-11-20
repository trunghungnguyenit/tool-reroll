"""Hộp thoại nhập Key và cổng kiểm tra giấy phép lúc khởi động / bắt đầu quét."""

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from core import license as lic
from ui import app as app_mod
from ui import license_dialog as ld

CODE = "AAAA-BBBB-CCCC-DDDD"


@pytest.fixture
def dialog(qtbot):
    calls = []

    def activate(text):
        calls.append(text)
        if text == "BAD":
            raise lic.LicenseError("Key không hợp lệ (sai chữ ký).")

    dlg = ld.LicenseDialog(CODE, activate)
    qtbot.addWidget(dlg)
    dlg.calls = calls
    return dlg


def test_shows_machine_code_read_only_and_copies_it(dialog):
    assert dialog.code_edit.text() == CODE and dialog.code_edit.isReadOnly()
    dialog.copy_btn.click()
    assert QApplication.clipboard().text() == CODE


def test_title_matches_main_window_title_so_second_instance_can_find_it(dialog):
    from core.single_instance import APP_TITLE

    assert dialog.windowTitle() == APP_TITLE


def test_empty_key_asks_to_paste_and_does_not_call_activate(dialog):
    dialog.activate_btn.click()
    assert dialog.calls == [] and "dán Key" in dialog.status.text() and not dialog.status.isHidden()
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_rejected_key_shows_reason_and_stays_open(dialog):
    dialog.key_edit.setPlainText("BAD")
    dialog.activate_btn.click()
    assert "sai chữ ký" in dialog.status.text() and not dialog.status.isHidden()
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_accepted_key_closes_with_accept_and_strips_whitespace(dialog):
    dialog.key_edit.setPlainText("  AAAA-BBBB\n  ")
    dialog.activate_btn.click()
    assert dialog.calls == ["AAAA-BBBB"] and dialog.result() == QDialog.DialogCode.Accepted


def test_quit_rejects(dialog):
    dialog.quit_btn.click()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_notice_is_shown_up_front(qtbot):
    dlg = ld.LicenseDialog(CODE, lambda t: None, notice="Giấy phép không dùng được trên máy này")
    qtbot.addWidget(dlg)
    assert not dlg.status.isHidden() and "không dùng được" in dlg.status.text()


class TestEnsureLicense:
    def test_valid_license_skips_dialog(self, monkeypatch):
        monkeypatch.setattr(lic, "check_installed", lambda *a: lic.Status(True))
        monkeypatch.setattr(ld, "LicenseDialog", lambda *a, **k: pytest.fail("không được hiện hộp thoại"))
        assert ld.ensure_license() is True

    def _patch_missing(self, monkeypatch, result, status=None):
        shown = {}

        class Fake:
            def __init__(self, code, activate, notice=""):
                shown.update(code=code, activate=activate, notice=notice)

            def exec(self):
                return result

        monkeypatch.setattr(lic, "check_installed", lambda *a: status or lic.Status(False, "Chưa kích hoạt.", missing=True))
        monkeypatch.setattr(lic, "machine_code", lambda: CODE)
        monkeypatch.setattr(ld, "LicenseDialog", Fake)
        return shown

    def test_missing_license_shows_dialog_and_accept_means_run(self, qtbot, monkeypatch):
        shown = self._patch_missing(monkeypatch, QDialog.DialogCode.Accepted)
        assert ld.ensure_license() is True
        assert shown["code"] == CODE and shown["activate"] is lic.activate and shown["notice"] == ""  # lần đầu: không báo lỗi

    def test_closing_dialog_means_exit(self, qtbot, monkeypatch):
        self._patch_missing(monkeypatch, QDialog.DialogCode.Rejected)
        assert ld.ensure_license() is False

    def test_invalid_license_explains_why(self, qtbot, monkeypatch):
        shown = self._patch_missing(monkeypatch, QDialog.DialogCode.Rejected,
                                    status=lic.Status(False, "Giấy phép không dùng được trên máy này"))
        ld.ensure_license()
        assert "không dùng được trên máy này" in shown["notice"]

    def test_unreadable_machine_id_blocks_with_message(self, qtbot, monkeypatch):
        monkeypatch.setattr(lic, "check_installed", lambda *a: lic.Status(False, "x", missing=True))

        def boom():
            raise lic.LicenseError("Không đọc được định danh của máy này")

        monkeypatch.setattr(lic, "machine_code", boom)
        shown = []
        monkeypatch.setattr(ld.QMessageBox, "critical", lambda *a: shown.append(a[2]))
        assert ld.ensure_license() is False and "định danh" in shown[0]


class TestStartupGate:
    def test_run_gui_does_not_build_main_window_without_license(self, qtbot, monkeypatch):
        import ui.main_window as mw

        monkeypatch.setattr(ld, "ensure_license", lambda: False)
        monkeypatch.setattr(mw, "MainWindow", lambda *a, **k: pytest.fail("không được dựng cửa sổ chính khi chưa có Key"))
        assert app_mod._run_gui() == 0

    def test_run_gui_builds_window_when_licensed(self, qtbot, monkeypatch):
        import ui.main_window as mw

        built = []

        class Win:
            def __init__(self, *a, **k):
                built.append(1)

            def show(self):
                pass

        monkeypatch.setattr(ld, "ensure_license", lambda: True)
        monkeypatch.setattr(mw, "MainWindow", Win)
        monkeypatch.setattr(QApplication, "exec", lambda self=None: 0)
        assert app_mod._run_gui() == 0 and built == [1]


@pytest.mark.real_license
class TestScatteredChecks:
    """Cổng không chỉ ở lúc mở app: bấm Bắt đầu và bật quét cũng kiểm tra lại giấy phép."""

    def test_controller_start_is_blocked_without_license(self, data_dir, monkeypatch):
        from core.controller import AppController

        events = []
        monkeypatch.setattr(lic, "check_installed", lambda *a: lic.Status(False, "Chưa kích hoạt.", missing=True))
        c = AppController(lambda ev, **kw: events.append((ev, kw)), post=lambda fn: fn(), keyboard=None)
        assert c._validate_start() is None
        dialogs = [kw for ev, kw in events if ev == "dialog"]
        assert dialogs and dialogs[0]["level"] == "error" and "Chưa kích hoạt" in dialogs[0]["text"]

    def test_scanner_start_is_blocked_without_license(self, make_scanner, monkeypatch):
        statuses = []
        monkeypatch.setattr(lic, "check_installed", lambda *a: lic.Status(False, "Chưa kích hoạt.", missing=True))
        scanner = make_scanner(on_status=statuses.append)
        scanner.start()
        assert not scanner.is_running and any("Cần Key xác thực" in s for s in statuses)

    def test_scanner_starts_with_license(self, make_scanner, monkeypatch):
        monkeypatch.setattr(lic, "check_installed", lambda *a: lic.Status(True))
        scanner = make_scanner(on_status=lambda s: None)
        scanner.start()
        try:
            assert scanner.is_running
        finally:
            scanner.stop()
