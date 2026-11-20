import pytest

from core.hotkey import register_roll_hotkey, DEFAULT_HOTKEY, register_toggle_hotkey


class FakeKeyboard:
    """Giả keyboard.add_hotkey: ghi lại các lần gọi; `bad` là tập phím sẽ bị từ chối bằng ValueError."""

    def __init__(self, bad=(), error=None):
        self.calls, self.bad, self.error = [], set(bad), error

    def add_hotkey(self, key, callback, suppress=False):
        self.calls.append((key, suppress))
        if self.error:
            raise self.error
        if key in self.bad:
            raise ValueError((f"Key {key!r} is not mapped to any known key.", ValueError("x")))


CB = lambda: None  # noqa: E731


def test_valid_hotkey_is_registered_without_noise():
    kb = FakeKeyboard()
    assert register_toggle_hotkey(kb.add_hotkey, "ctrl+f9", CB) == ("ctrl+f9", [])
    assert kb.calls == [("ctrl+f9", False)]  # suppress=False: không nuốt phím của game


def test_invalid_hotkey_falls_back_to_default_and_says_so():
    kb = FakeKeyboard(bad={"f88"})
    key, lines = register_toggle_hotkey(kb.add_hotkey, "f88", CB)
    assert key == DEFAULT_HOTKEY and [c[0] for c in kb.calls] == ["f88", "f8"]
    assert any("'f88' không hợp lệ" in line for line in lines) and any("mặc định" in line for line in lines)
    assert not any("Admin" in line for line in lines)  # không báo nhầm thành lỗi quyền


def test_default_itself_invalid_gives_up_with_a_clear_message():
    kb = FakeKeyboard(bad={"f8"})
    key, lines = register_toggle_hotkey(kb.add_hotkey, "f8", CB)
    assert key is None and len(kb.calls) == 1  # requested == default: không thử lại cùng một phím
    assert any("không hợp lệ" in line for line in lines) and any("BẮT ĐẦU" in line for line in lines)


def test_both_invalid():
    kb = FakeKeyboard(bad={"f88", "f8"})
    key, lines = register_toggle_hotkey(kb.add_hotkey, "f88", CB)
    assert key is None and len(kb.calls) == 2 and sum("không hợp lệ" in line for line in lines) == 2


@pytest.mark.parametrize("error", [PermissionError("denied"), OSError("hook"), RuntimeError("x")])
def test_other_errors_mean_permissions_and_stop_immediately(error):
    """Đổi phím cũng không giúp được khi thiếu quyền, nên không thử phím khác."""
    kb = FakeKeyboard(error=error)
    key, lines = register_toggle_hotkey(kb.add_hotkey, "f9", CB)
    assert key is None and len(kb.calls) == 1
    assert len(lines) == 1 and "Admin" in lines[0] and type(error).__name__ in lines[0]


def test_empty_hotkey_value_is_just_an_invalid_hotkey():
    kb = FakeKeyboard(bad={""})
    assert register_toggle_hotkey(kb.add_hotkey, "", CB)[0] == DEFAULT_HOTKEY


def test_real_keyboard_library_rejects_bad_names_with_valueerror():
    """Giữ giả định mà cả mô-đun dựa vào: thư viện thật ném ValueError (không phải lỗi khác) cho phím sai."""
    keyboard = pytest.importorskip("keyboard")
    for bad in ("f88", "banana", "", "ctrl+", "  f8 "):
        with pytest.raises(ValueError):
            keyboard.add_hotkey(bad, lambda: None, suppress=False)
    keyboard.unhook_all()


def test_real_keyboard_library_end_to_end_fallback():
    keyboard = pytest.importorskip("keyboard")
    try:
        key, lines = register_toggle_hotkey(keyboard.add_hotkey, "f88", CB)
        assert key == "f8" and lines
    finally:
        keyboard.unhook_all()


class TestRollHotkey:
    def test_registers_without_suppressing_the_key(self):
        calls = []

        def add(key, cb, suppress=False):
            calls.append((key, suppress))
            return "handle"

        handle, lines = register_roll_hotkey(add, "d", lambda: None)
        assert handle == "handle" and calls == [("d", False)]  # phím vẫn tới game
        assert lines == ["Đồng bộ phím roll: D (quét dày ngay khi bạn roll)."]

    def test_empty_key_disables_silently(self):
        calls = []
        assert register_roll_hotkey(lambda *a, **k: calls.append(1), "  ", lambda: None) == (None, [])
        assert calls == []

    def test_same_as_toggle_key_is_rejected(self):
        calls = []
        handle, lines = register_roll_hotkey(lambda *a, **k: calls.append(1), "F8", lambda: None, toggle_key="f8")
        assert handle is None and calls == [] and "trùng phím bật/tắt" in lines[0]

    def test_invalid_key_is_reported_and_ignored(self):
        def add(key, cb, suppress=False):
            raise ValueError("Unrecognized key 'zzz'")

        handle, lines = register_roll_hotkey(add, "zzz", lambda: None)
        assert handle is None and "không hợp lệ" in lines[0] and "Unrecognized key" in lines[0]

    def test_permission_error_suggests_admin(self):
        def add(key, cb, suppress=False):
            raise OSError("denied")

        handle, lines = register_roll_hotkey(add, "d", lambda: None)
        assert handle is None and "quyền Admin" in lines[0] and "OSError" in lines[0]
