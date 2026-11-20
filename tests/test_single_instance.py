import itertools
import time
import tkinter as tk

import pytest

import ui.app as app_mod
from core import single_instance as si

_counter = itertools.count()


@pytest.fixture
def mutex_name():
    """Tên mutex riêng cho từng test để không đụng bản app thật đang chạy trên máy."""
    return f"Local\\TFTAutoBuy.Test.{time.time_ns()}.{next(_counter)}"


class TestMutex:
    def test_second_acquire_is_refused(self, mutex_name):
        first = si.acquire_instance_lock(mutex_name)
        try:
            assert first is not None
            assert si.acquire_instance_lock(mutex_name) is None
            assert si.acquire_instance_lock(mutex_name) is None  # không "mòn" sau nhiều lần thử
        finally:
            first.release()

    def test_can_acquire_again_after_release(self, mutex_name):
        first = si.acquire_instance_lock(mutex_name)
        first.release()
        again = si.acquire_instance_lock(mutex_name)
        assert again is not None
        again.release()

    def test_failed_attempt_does_not_release_the_holder(self, mutex_name):
        """Lần thử bị từ chối đóng tay cầm của CHÍNH nó, không được làm nhả khóa của bản đầu."""
        first = si.acquire_instance_lock(mutex_name)
        try:
            assert si.acquire_instance_lock(mutex_name) is None
            assert si.acquire_instance_lock(mutex_name) is None
        finally:
            first.release()

    def test_refused_attempts_leave_no_handle_behind(self, mutex_name):
        """Lần thử bị từ chối phải đóng tay cầm thừa; nếu rò, mutex vẫn 'sống' sau khi bản đầu thoát và chặn mãi."""
        first = si.acquire_instance_lock(mutex_name)
        for _ in range(5):
            assert si.acquire_instance_lock(mutex_name) is None
        first.release()
        again = si.acquire_instance_lock(mutex_name)
        assert again is not None
        again.release()

    def test_fails_closed_when_mutex_cannot_be_created(self, monkeypatch, mutex_name):
        """Không tạo được mutex (bị chặn quyền...) thì coi như đã có bản khác: thà không chạy còn hơn chạy đôi."""
        import types

        fake = types.SimpleNamespace(CreateMutexW=lambda *a: None, CloseHandle=lambda h: True)
        monkeypatch.setattr(si, "_kernel32", fake)
        assert si.acquire_instance_lock(mutex_name) is None

    def test_different_names_do_not_block_each_other(self, mutex_name):
        a = si.acquire_instance_lock(mutex_name + ".a")
        b = si.acquire_instance_lock(mutex_name + ".b")
        try:
            assert a is not None and b is not None
        finally:
            a.release()
            b.release()

    def test_release_is_idempotent(self, mutex_name):
        lock = si.acquire_instance_lock(mutex_name)
        lock.release()
        lock.release()

    def test_name_is_per_session_and_independent_of_install_folder(self):
        """'Local\\' = một bản mỗi phiên đăng nhập; tên cố định nên hai thư mục cài khác nhau cũng chặn nhau."""
        assert si.MUTEX_NAME.startswith("Local\\")
        assert "\\" not in si.MUTEX_NAME[len("Local\\"):] and ":" not in si.MUTEX_NAME

    def test_uses_distinct_default_name_from_tests(self, mutex_name):
        assert mutex_name != si.MUTEX_NAME


def make_root(title):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("không có màn hình để dựng cửa sổ Tk")
    root.title(title)
    root.update()
    return root


class TestActivateExistingWindow:
    def test_returns_false_quickly_when_no_window(self, mutex_name):
        t0 = time.monotonic()
        assert si.activate_existing_window(title=mutex_name, wait_s=0.3) is False
        assert time.monotonic() - t0 < 2.0

    def test_finds_window_and_restores_if_minimized(self, mutex_name):
        root = make_root(mutex_name)
        try:
            root.iconify()
            root.update()
            assert root.state() == "iconic"
            assert si.activate_existing_window(title=mutex_name, wait_s=1.0) is True
            root.update()
            assert root.state() == "normal"
        finally:
            root.destroy()

    def test_waits_for_window_that_appears_late(self, mutex_name):
        """Bản đầu giữ khóa nhưng chưa dựng xong cửa sổ (exe khởi động chậm): bản hai phải chờ chứ không bỏ cuộc ngay."""
        root = make_root("tạm thời")
        try:
            root.after(300, lambda: root.title(mutex_name))
            result = {}
            import threading

            t = threading.Thread(target=lambda: result.setdefault("ok", si.activate_existing_window(mutex_name, 3.0)))
            t.start()
            deadline = time.monotonic() + 4
            while t.is_alive() and time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            t.join(1)
            assert result.get("ok") is True
        finally:
            root.destroy()


class Calls(list):
    state: dict


@pytest.fixture
def entry(monkeypatch):
    """Giả lập các phụ thuộc của run_app, ghi lại thứ tự gọi."""
    calls = Calls()
    state = {"raises": False}

    def gui():
        calls.append("gui")
        if state["raises"]:
            raise RuntimeError("hỏng khi chạy")
        return 0

    monkeypatch.setattr(app_mod, "_run_gui", gui)
    monkeypatch.setattr(app_mod, "setup_logging", lambda: calls.append("logging"))
    monkeypatch.setattr(app_mod, "_show_already_running_notice", lambda: calls.append("notice"))
    monkeypatch.setattr(app_mod, "_show_error", lambda err: calls.append(("error", err)))
    monkeypatch.setattr(app_mod.logger, "critical", lambda *a, **k: calls.append("critical"))
    calls.state = state
    return calls


class TestRunApp:
    def test_first_instance_takes_lock_then_logging_then_runs(self, monkeypatch, entry):
        monkeypatch.setattr(app_mod, "acquire_instance_lock", lambda: entry.append("lock") or object())
        monkeypatch.setattr(app_mod, "activate_existing_window", lambda: entry.append("activate") or True)
        assert app_mod.run_app() == 0
        assert entry == ["lock", "logging", "gui"]

    def test_second_instance_activates_old_window_and_exits_without_starting(self, monkeypatch, entry):
        monkeypatch.setattr(app_mod, "acquire_instance_lock", lambda: None)
        monkeypatch.setattr(app_mod, "activate_existing_window", lambda: entry.append("activate") or True)
        assert app_mod.run_app() == 0
        assert entry == ["activate"]  # không bật logging (không đụng app.log), không tạo app, không hộp thoại

    def test_second_instance_explains_when_old_window_not_found(self, monkeypatch, entry):
        monkeypatch.setattr(app_mod, "acquire_instance_lock", lambda: None)
        monkeypatch.setattr(app_mod, "activate_existing_window", lambda: entry.append("activate") or False)
        assert app_mod.run_app() == 0
        assert entry == ["activate", "notice"]

    def test_crash_is_logged_and_returns_error_code(self, monkeypatch, entry):
        monkeypatch.setattr(app_mod, "acquire_instance_lock", lambda: object())
        entry.state["raises"] = True
        assert app_mod.run_app() == 1
        assert "critical" in entry
        shown = [c for c in entry if isinstance(c, tuple)]
        assert len(shown) == 1 and "hỏng khi chạy" in shown[0][1]

    def test_crash_that_cannot_even_be_shown_is_reraised(self, monkeypatch, entry):
        monkeypatch.setattr(app_mod, "acquire_instance_lock", lambda: object())
        entry.state["raises"] = True

        def cannot(err):
            raise OSError("không hiện được hộp thoại")

        monkeypatch.setattr(app_mod, "_show_error", cannot)
        with pytest.raises(OSError):
            app_mod.run_app()


def test_window_title_is_shared_between_app_and_lookup():
    """Cửa sổ chính phải dùng đúng APP_TITLE, vì bản thứ hai tìm cửa sổ cũ bằng tiêu đề này."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "self.setWindowTitle(APP_TITLE)" in source
    assert "from core.single_instance import APP_TITLE" in source
